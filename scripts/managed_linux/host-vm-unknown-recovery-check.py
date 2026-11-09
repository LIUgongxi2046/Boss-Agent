import asyncio
import json
import secrets
import socket
import sys
from pathlib import Path

import aiohttp
from aiohttp import web
from nanobot.bus.queue import MessageBus
from nanobot.channels.websocket.runtime import WebSocketChannel, WebSocketConfig
from nanobot.webui.gateway_services import build_gateway_services
from websockets.asyncio.server import serve

from agent_run_api import product_application
from agent_run_broker import RunBroker
from agent_run_dispatcher import AgentRunDispatcher
from agent_run_recovery_routes import install_run_recovery_routes
from agent_run_scope import RunScopeService
from agent_run_store import RunStore
from boss_memory_sessions import MemorySessionManager
from controls import ControlStore
from hermes_bridge import HermesBridge
from hermes_product import HermesProductServices
from hermes_run_recovery import HermesRunRecovery
from hermes_vm_manager import HermesVMManager
from role_channel import RoleChannel


ROOT = Path.cwd().resolve()
RESULTS = Path(sys.argv[1]).resolve(strict=True)
ORIGINAL = ROOT / '.work/upgrade2/u2-03/lifecycle-check-001/factory-results-019'
WORKSPACE_ROOT = (ORIGINAL / 'vm-workspaces').resolve(strict=True)
RUN_ID = '97b1a2be-d7f5-45f8-a7e8-33581567f093'
VM = ROOT / '.work/upgrade2/managed-linux-001'
CHECK = ROOT / '.work/upgrade2/u2-03'
EXECUTABLE = CHECK / 'vsock-workspace-relay-004'
EXECUTABLE_SHA256 = 'cd25e0e17465579277d35d317b299d1a109ce8b58893b4909ed53ca865da11b5'
CREDENTIALS = CHECK / 'lifecycle-check-001/credentials'
DEPENDENCIES = ROOT / '.work/upgrade2/dependency-resolution-001/linux-target'
ENGINE = CHECK / 'clean-hermes'
RUNTIME_PORT, CONTROL_PORT = 27861, 27862


async def main():
    business = ControlStore(RESULTS / 'business.sqlite')
    store = RunStore(business.path, allow_migration=False)
    saved = store.read_run(RUN_ID)
    if saved['status'] != 'RUNNING' or saved['conversation_id'] != 'e82eb217-1d92-4367-871f-ade4cd53b07a':
        raise ValueError('待恢复运行身份不可核查')
    sessions = MemorySessionManager(RESULTS / 'workspace', business_store=business, sessions_root=RESULTS / 'sessions')
    scope = RunScopeService(business, sessions, 'ui-check')
    broker = RunBroker(store, scope_service=scope)
    role_secrets = {role: secrets.token_urlsafe(32) for role in ('BOSS', 'MAINTAINER')}
    config = WebSocketConfig(host='127.0.0.1', port=0, token_issue_secret=role_secrets['BOSS'], token_ttl_s=180)
    bus = MessageBus()
    gateway = build_gateway_services(config=config, bus=bus, session_manager=sessions, static_dist_path=None,
        workspace_path=RESULTS, default_restrict_to_workspace=True, config_path=RESULTS / 'config.json',
        runtime_model_name=None, runtime_surface='webui', runtime_capabilities_overrides=None)
    channel = RoleChannel(WebSocketChannel(config, bus, gateway=gateway), role_secrets, RESULTS / 'audit.jsonl', business)
    recovery = HermesRunRecovery(channel, scope, store)
    services = HermesProductServices(store, scope, broker, HermesBridge(business), recovery)
    dispatcher = AgentRunDispatcher(services)
    manager = await asyncio.to_thread(HermesVMManager.start, EXECUTABLE, VM, CREDENTIALS, EXECUTABLE_SHA256,
        RUNTIME_PORT, CONTROL_PORT, {'memory_bytes': 1073741824, 'processes': 64, 'cpu_percent': 100},
        dependencies_directory=DEPENDENCIES, engine_directory=ENGINE)
    try:
        await asyncio.sleep(25)
        await asyncio.to_thread(manager.control.identity)
        async with serve(channel._connection_loop, '127.0.0.1', 0, process_request=channel._dispatch_http) as upstream:
            listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            listener.bind(('127.0.0.1', 0))
            listener.listen()
            listener.setblocking(False)
            port = listener.getsockname()[1]
            origin = 'http://127.0.0.1:' + str(port)
            app = product_application(channel, broker, public_port=port, upstream_port=upstream.sockets[0].getsockname()[1])
            install_run_recovery_routes(app, channel, recovery, public_port=port, vm_manager=manager, workspace_root=WORKSPACE_ROOT)
            runner = web.AppRunner(app)
            await runner.setup()
            await web.SockSite(runner, listener).start()
            try:
                async with aiohttp.ClientSession() as client:
                    async with client.get(origin + '/webui/bootstrap', headers={'Authorization': 'Bearer ' + role_secrets['BOSS']}) as response:
                        response.raise_for_status()
                        authentication = await response.json()
                    headers = {'Authorization': 'Bearer ' + authentication['api_token'], 'Origin': origin}
                    async with client.ws_connect(authentication['ws_url'], params={'token': authentication['token']}) as websocket:
                        while json.loads((await websocket.receive()).data).get('event') != 'ready':
                            pass
                        await websocket.send_json({'type': 'attach', 'chat_id': saved['conversation_id']})
                        while True:
                            event = json.loads((await websocket.receive()).data)
                            if event.get('event') == 'attached' and event.get('chat_id') == saved['conversation_id']:
                                break
                        url = origin + '/api/v2/runs/' + RUN_ID + '/recover-expired'
                        async with client.post(url, json={}, headers={'Authorization': 'Bearer invalid', 'Origin': origin}) as response:
                            if response.status != 401:
                                raise ValueError('未认证恢复请求未被拒绝')
                        for _ in range(2):
                            async with client.post(url, json={}, headers=headers) as response:
                                if response.status != 200:
                                    raise ValueError('未知退出恢复请求未通过：' + str(response.status) + ' ' + await response.text())
                                body = await response.json()
                                if body != {'run_id': RUN_ID, 'status': 'INTERRUPTED', 'unknown_reservations': 1}:
                                    raise ValueError('未知退出恢复状态不可核查：' + str(response.status) + ' ' + str(body))
                        with store.connect() as db:
                            state = db.execute('SELECT state FROM agent_concurrency_reservations WHERE run_id=?', (RUN_ID,)).fetchone()
                            final = db.execute('SELECT count(*) FROM hermes_cpu_final_exits WHERE run_id=?', (RUN_ID,)).fetchone()
                            if state != ('UNKNOWN',) or final != (0,):
                                raise ValueError('未知退出预留或最终回执不可核查')
                            db.execute('BEGIN')
                            dispatch = dispatcher.inspect_dispatch_recovery_in_transaction(db, RUN_ID, 'factory-dispatch')
                            if dispatch['receipt_state'] != 'UNKNOWN' or dispatch['automatic_retry'] is not False:
                                raise ValueError('未知派发状态不可核查')
                        print('AUTHENTICATED_UNKNOWN_RECOVERY_CONFIRMED', flush=True)
            finally:
                await runner.cleanup()
    finally:
        await asyncio.to_thread(manager.stop)
        print('UNKNOWN_RECOVERY_VM_STOPPED', flush=True)


asyncio.run(main())
