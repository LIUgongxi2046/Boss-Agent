import asyncio
import hashlib
import json
import os
import secrets
import socket
import sys
from pathlib import Path
from uuid import uuid4

import aiohttp
import pytest
from aiohttp import web
from nanobot.agent.loop import AgentLoop
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.bus.queue import MessageBus
from nanobot.channels.websocket.runtime import WebSocketChannel, WebSocketConfig
from nanobot.config.loader import save_config
from nanobot.config.schema import Config
from nanobot.webui.gateway_services import build_gateway_services
from websockets.asyncio.server import serve

from agent_chat_budget import AgentChatBudget
from agent_artifact_workspace import ArtifactWorkspace
from agent_run_api import product_application
from agent_run_broker import RunBroker, RunIdentity
from agent_run_concurrency import RunConcurrencyBudget
from agent_run_dispatcher import AgentRunDispatcher
from agent_run_launch_transaction import RunLaunchTransaction
from agent_run_method_selection import AgentRunMethodSelection
from agent_run_recovery_routes import install_run_recovery_routes
from agent_run_scope import RunScopeService
from agent_run_store import RunStore
from boss_memory_sessions import MemorySessionManager
from boss_page_api import BossPageAPI
from boss_simulation_api import _context
from business import OPERATIONS, checksum
from controls import ControlStore
from hermes_bridge import EngineEventSink, HermesBridge
from hermes_bi_authority import HermesBIQueryAuthority
from hermes_cpu_budget import HermesCPUBudget
from hermes_product import HermesProductServices
from hermes_run_recovery import HermesRunRecovery
from hermes_runtime_binding import HermesDeploymentConfig, HermesExecutionFactory
from hermes_vm_manager import HermesVMManager
from model_probe import BusinessTool
from product_bi import FeatureProvider, ProductBI
from product_fc01 import ProductFc01
from product_read_tools import product_read_tools
from product_runtime import ProductRuntime
from product_skills import ProductSkills
from role_channel import RoleChannel


ROOT = Path.cwd().resolve()
RESULTS = Path(sys.argv[1]).resolve(strict=True)
PREPARE_RECOVERY = len(sys.argv) == 3 and sys.argv[2] == '--prepare-recover'
PREPARE_FAILURE = len(sys.argv) == 3 and sys.argv[2] in {'--prepare-failure', '--prepare-recover'}
CANCEL_CHECK = len(sys.argv) == 3 and sys.argv[2] == '--tools-cancel'
LOGOUT_CHECK = len(sys.argv) == 3 and sys.argv[2] == '--tools-logout'
WITHDRAW_CHECK = len(sys.argv) == 3 and sys.argv[2] == '--tools-withdraw'
EXPIRE_CHECK = len(sys.argv) == 3 and sys.argv[2] == '--tools-expire'
INODE_CHECK = len(sys.argv) == 3 and sys.argv[2] == '--tools-inodes'
BYTES_CHECK = len(sys.argv) == 3 and sys.argv[2] == '--tools-bytes'
RESELECT_MULTIPLE = len(sys.argv) == 3 and sys.argv[2] == '--reselect-multiple'
RESELECT_CHECK = len(sys.argv) == 3 and sys.argv[2] in {'--reselect-only', '--reselect-multiple'}
TOOLS_CHECK = len(sys.argv) == 3 and sys.argv[2] in {'--tools-check', '--tools-cancel', '--tools-logout', '--tools-withdraw', '--tools-expire', '--tools-inodes', '--tools-bytes'}
if len(sys.argv) not in (2, 3) or len(sys.argv) == 3 and not (PREPARE_FAILURE or TOOLS_CHECK or RESELECT_CHECK):
    raise ValueError('检查参数无效')
VM = ROOT / '.work/upgrade2/managed-linux-001'
CHECK = ROOT / '.work/upgrade2/u2-03'
ENGINE = CHECK / 'clean-hermes'
DEPENDENCIES = ROOT / '.work/upgrade2/dependency-resolution-001/linux-target'
EXECUTABLE = CHECK / 'vsock-workspace-relay-004'
EXECUTABLE_SHA256 = 'cd25e0e17465579277d35d317b299d1a109ce8b58893b4909ed53ca865da11b5'
CREDENTIALS = CHECK / 'lifecycle-check-001/credentials'
RUNTIME_PORT, CONTROL_PORT = 27861, 27862


async def main():
    inputs = (Path(__file__).resolve(), RESULTS / 'business.sqlite',
              ROOT / 'validation/hermes_bi_authority.py', ROOT / 'validation/hermes_runtime_binding.py',
              ROOT / 'validation/hermes_bridge.py', ROOT / 'validation/hermes_budget_gateway.py',
              ROOT / 'validation/hermes_runtime_transport.py', ROOT / 'validation/hermes_transport.py',
              ROOT / 'validation/hermes_vm_host.py', ROOT / 'validation/agent_run_method_selection.py',
              ROOT / 'validation/conversation_agent/queries.py',
              CHECK / 'guest-dist-048/boss_agent_guest_runtime-0.2.48-py3-none-any.whl',
              CHECK / 'bi-adapter-008/boss_agent_hermes_adapter-0.1.9-py3-none-any.whl',
              CHECK / 'install-runtime-052.log')
    for path in inputs:
        with path.open('rb') as source:
            print('INPUT_SHA256', hashlib.file_digest(source, 'sha256').hexdigest(), path, flush=True)
    business = ControlStore(RESULTS / 'business.sqlite')
    store = RunStore(business.path, allow_migration=False)
    config = Config()
    config.agents.defaults.workspace = str(RESULTS / 'workspace')
    config.agents.defaults.provider = 'deepseek'
    config.agents.defaults.model = 'deepseek-flash'
    config.agents.defaults.dream.enabled = False
    config.providers.deepseek.api_key = ''
    config.providers.deepseek.api_base = 'https://api.deepseek.com'
    config_path = RESULTS / 'config.json'
    save_config(config, config_path)
    sessions = MemorySessionManager(config.workspace_path, business_store=business, sessions_root=RESULTS / 'sessions')
    bus = MessageBus()
    registry = ToolRegistry()
    envelope = {'request_id': 'ui-check', 'owner_id': 'boss-1', 'execution_namespace': 'ui-check',
                'dataset_id': 'selection', 'dataset_version': '1', 'session_id': 'ui-check'}
    tools = [BusinessTool(name, business, envelope, {}, []) for name in OPERATIONS]
    pages = BossPageAPI(business)
    tools.extend(product_read_tools(business, pages))
    provider = FeatureProvider(ProductFc01(business), ProductBI(business))
    loop = AgentLoop.from_config(config, bus, provider=provider, tool_registry=registry, session_manager=sessions)
    runtime = ProductRuntime(business, config_path, loop, registry, tools, provider, workspace_api=pages)
    skills = ProductSkills(runtime)
    role_secrets = {role: secrets.token_urlsafe(32) for role in ('BOSS', 'MAINTAINER')}
    ws_config = WebSocketConfig(host='127.0.0.1', port=0, token_issue_secret=role_secrets['BOSS'], token_ttl_s=180)
    gateway = build_gateway_services(config=ws_config, bus=bus, session_manager=sessions, static_dist_path=None,
        workspace_path=RESULTS, default_restrict_to_workspace=True, config_path=config_path,
        runtime_model_name=None, runtime_surface='webui', runtime_capabilities_overrides=None)
    channel = RoleChannel(WebSocketChannel(ws_config, bus, gateway=gateway), role_secrets, RESULTS / 'audit.jsonl',
                          business, runtime, skills)
    scope = RunScopeService(business, sessions, 'ui-check')
    selection = AgentRunMethodSelection(store, scope, skills.catalog, skills.drafts)
    broker = RunBroker(store, scope_service=scope, method_selection=selection)
    chat_budget = AgentChatBudget(store, channel, scope)
    services = HermesProductServices(store, scope, broker, HermesBridge(business), HermesRunRecovery(channel, scope, store), chat_budget)
    dispatcher = AgentRunDispatcher(services)
    manager = None
    technical = {}
    try:
        workspace_root = RESULTS / 'vm-workspaces'
        workspace_root.mkdir(mode=0o700)
        budget = {'model_requests': 2, 'rounds': 2, 'tools': 4 if TOOLS_CHECK else 2, 'seconds': 60, 'concurrency': 1,
                  'context_tokens': 128, 'files': 1 if PREPARE_FAILURE else 16 if INODE_CHECK else 128 if TOOLS_CHECK else 16,
                  'file_bytes': 1048576 if BYTES_CHECK or not TOOLS_CHECK else 16777216, 'open_files': 64, 'cpu_seconds': 20}
        async with serve(channel._connection_loop, '127.0.0.1', 0, process_request=channel._dispatch_http) as upstream:
            listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            listener.bind(('127.0.0.1', 0))
            listener.listen()
            listener.setblocking(False)
            public_port = listener.getsockname()[1]
            origin = 'http://127.0.0.1:' + str(public_port)
            app = product_application(channel, broker, public_port=public_port, upstream_port=upstream.sockets[0].getsockname()[1])

            async def configure(request):
                key = 'factory-budget-reselect' if RESELECT_CHECK else 'factory-budget-recovery' if PREPARE_RECOVERY else 'factory-budget-tools' if TOOLS_CHECK else 'factory-budget'
                return web.json_response(chat_budget.configure(request, key, 1 if TOOLS_CHECK or PREPARE_RECOVERY or RESELECT_CHECK else 0, budget))

            async def create(request):
                chat_id = (await request.json())['conversation_id']
                channel.require_run_subscription(request, chat_id)
                session = sessions.get_or_create('websocket:' + chat_id)
                sessions.save(session, fsync=True)
                with business.connect() as db:
                    db.execute('BEGIN IMMEDIATE')
                    context = _context(db)
                    document = business.get(db, 'ui-check', 'document', 'finance-note')
                    initial = business.get(db, 'ui-check', 'initial', 'snapshot')
                    selected = {'source_id': 'finance-note', 'version': document['version']}
                    binding = {key: context[key] for key in ('namespace', 'owner_id', 'dataset_id', 'dataset_version')}
                    binding.update({'chat_id': chat_id, 'session_id': session.key, 'native_session_created_at': session.created_at.isoformat(),
                                    'binding_id': 'factory-binding', 'context_version': '1', 'source_refs': [selected],
                                    'source_pins': [{**selected, 'content_sha256': checksum(document)}]})
                    business.put(db, 'ui-check', 'conversation_source_binding', session.key, binding)
                proof = scope.prove(chat_id, ['finance-note'])
                identity = RunIdentity(proof.owner_id, proof.namespace, 'BOSS', frozenset({chat_id}), frozenset({'finance-note'}),
                                       verify=lambda: channel.require_run_subscription(request, chat_id))
                _, references = skills.catalog.context('BOSS', ['SOP03'])
                method = {key: references[0][key] for key in ('sop_id', 'version', 'content_sha256')}
                goal = ('查询 region-1 的全部当前产品的毛利率，查询期间' + '至'.join(initial['periods']['CURRENT'])
                        + '，对比期间' + '至'.join(initial['periods']['BASE']) + '，使用当前获准口径')
                body = {'conversation_id': chat_id, 'goal': goal, 'selected_refs': ['finance-note'],
                        'request_key': str(uuid4()), 'method_selection': method, 'required_outputs': ['TEXT']}
                binding = HermesBIQueryAuthority(scope).prepare(request, identity, body)
                if binding['binding']['parameters']['question'] != goal or binding['binding_sha256'] != checksum(binding['binding']):
                    raise ValueError('经营查询授权结果不可核查')
                technical.update(query=binding['binding']['parameters'], path='technical-check.txt', content='受限工作区检查',
                                 hold_seconds=20 if CANCEL_CHECK or LOGOUT_CHECK or WITHDRAW_CHECK or EXPIRE_CHECK else 0)
                print('FACTORY_BI_AUTHORIZATION_PREPARED', flush=True)
                return web.json_response(broker.create(identity, body, request=request, chat_budget=chat_budget))

            async def execute(request):
                nonlocal manager
                run_id = (await request.json())['run_id']
                ArtifactWorkspace(workspace_root).create(run_id)
                manager = await asyncio.to_thread(HermesVMManager.start, EXECUTABLE, VM, CREDENTIALS, EXECUTABLE_SHA256,
                    RUNTIME_PORT, CONTROL_PORT, {'memory_bytes': 1073741824, 'processes': 64, 'cpu_percent': 100},
                    dependencies_directory=DEPENDENCIES, engine_directory=ENGINE)
                print('FACTORY_VM_STARTED', flush=True)
                await asyncio.sleep(25)
                await asyncio.to_thread(manager.control.identity)
                deployment = HermesDeploymentConfig(ENGINE, ROOT / '.work/upgrade2/u2-01/hermes.tar.gz',
                    ROOT / '.work/upgrade2/u2-03/dependency-audit-001/environment',
                    ROOT / '.work/upgrade2/u2-03/dependency-audit-001/environment/bin/python', workspace_root,
                    ROOT / 'validation/hermes_process_isolation.sb', RUNTIME_PORT, None, True, manager)
                factory = HermesExecutionFactory(services, deployment)
                process_config = factory.prepare(request, run_id, 1)
                print('FACTORY_PROCESS_CONFIG_READY', flush=True)
                owner = str(uuid4())
                with store.connect() as db:
                    db.execute('BEGIN IMMEDIATE')
                    lease = store.acquire_queued_in_transaction(db, run_id, 0, owner, 15 if EXPIRE_CHECK or PREPARE_RECOVERY else budget['seconds'])
                    dispatcher.bind_budget_in_transaction(db, run_id, owner, lease['epoch'])
                    plan, saved_budget = dispatcher.approved_budget_in_transaction(db, run_id)
                    digest = checksum({'run_id': run_id, 'lease_epoch': lease['epoch'], 'plan_digest': checksum(plan), 'budget': saved_budget})
                    key = 'dispatch:' + run_id + ':' + str(lease['epoch'])
                    RunConcurrencyBudget(store).reserve_in_transaction(db, run_id, owner, lease['epoch'], key, digest)
                    dispatcher.record_dispatch_in_transaction(db, run_id, 'factory-dispatch', 0, owner, lease['epoch'])
                print('FACTORY_LEASE_AND_BUDGET_READY', flush=True)
                sink = EngineEventSink(store, process_config.run, owner)
                assembly = factory.assemble(request, sink, saved_budget, checksum(plan))
                print('FACTORY_ASSEMBLED', flush=True)
                if (assembly.request_key, assembly.request_digest) != (key, digest):
                    raise ValueError('工厂运行身份不可核查')
                access = assembly.lifecycle.host.access
                with RunLaunchTransaction(store).hold(run_id, owner, lease['epoch']) as db:
                    assembly.lifecycle.transport.authority.require_in_transaction(db)
                    assembly.lifecycle.evidence.record_vm_start_in_transaction(db, access.bindings, run_id, key, digest,
                        owner, lease['epoch'], plan['owner_id'], scope.namespace, access.vm_id, access.boot_id, access.workspace)
                    cpu_budget = HermesCPUBudget(store)
                    cpu_budget.configure_in_transaction(db, run_id, owner, lease['epoch'], saved_budget['cpu_seconds'] * 1000000000)
                    cpu_budget.reserve_in_transaction(db, access, saved_budget['cpu_seconds'] * 1000000000)
                print('FACTORY_ASSEMBLY_READY', flush=True)
                bootstrap = {**assembly.bootstrap, 'technical_check': technical} if TOOLS_CHECK else assembly.bootstrap
                with assembly.listener:
                    with pytest.raises((ValueError, web.HTTPException)) as stopped:
                        await assembly.lifecycle.run_vm(assembly.listener, process_config, bootstrap=bootstrap,
                                                        technical_check=technical if TOOLS_CHECK else None)
                    expected_errors = {'客体控制响应不可核查'} if PREPARE_FAILURE else {'客体控制响应不可核查', '客体进程退出范围尚未核查'}
                    if CANCEL_CHECK:
                        expected_errors.add('运行或父运行已经取消或不可执行')
                    if LOGOUT_CHECK:
                        expected_errors.add('Unauthorized')
                    if WITHDRAW_CHECK:
                        expected_errors.update({'来源已经撤销', '来源清理尚未完成'})
                    if EXPIRE_CHECK:
                        expected_errors.add('租约无效')
                    if str(stopped.value) not in expected_errors and not str(stopped.value).startswith('客体控制响应不可核查：HTTP '):
                        raise ValueError('工厂运行退出原因不可核查')
                if EXPIRE_CHECK:
                    recovered = await asyncio.to_thread(services.recovery.recover_vm_expired, request, run_id, manager, workspace_root)
                    if recovered != {'run_id': run_id, 'status': 'INTERRUPTED', 'unknown_reservations': 0}:
                        raise ValueError('本人恢复回执不可核查')
                    with store.connect() as db:
                        db.execute('BEGIN')
                        dispatch = dispatcher.inspect_dispatch_recovery_in_transaction(db, run_id, 'factory-dispatch')
                        if dispatch['receipt_state'] != 'UNKNOWN' or dispatch['reservation_state'] != 'RELEASED' or dispatch['automatic_retry'] is not False:
                            raise ValueError('原派发恢复状态不可核查')
                    print('FACTORY_EXPIRED_RECOVERY_CONFIRMED', flush=True)
                with pytest.raises(ValueError):
                    await asyncio.to_thread(assembly.lifecycle.host.workspace_status, budget, assembly.bootstrap)
                with store.connect() as db:
                    events = db.execute('SELECT type FROM agent_run_events WHERE run_id=? ORDER BY seq', (run_id,)).fetchall()
                    tool_events = db.execute("SELECT json_extract(payload,'$.tool_id') FROM agent_run_events WHERE run_id=? AND type='TOOL_FINISHED' ORDER BY seq", (run_id,)).fetchall()
                    reservations = db.execute('SELECT count(*) FROM agent_tool_reservations WHERE run_id=?', (run_id,)).fetchone()
                    unknown = db.execute('SELECT state,cpu_ns FROM hermes_cpu_unknown_exits WHERE run_id=? AND request_key=?', (run_id, key)).fetchone()
                    final = db.execute('SELECT cpu_ns,source FROM hermes_cpu_final_exits WHERE run_id=? AND request_key=?', (run_id, key)).fetchone()
                    reservation = db.execute('SELECT state FROM agent_concurrency_reservations WHERE run_id=? AND request_key=?', (run_id, key)).fetchone()
                    model_requests = db.execute('SELECT count(*) FROM hermes_model_requests WHERE root_run_id=?', (run_id,)).fetchone()
                if unknown != ('UNKNOWN', None) or model_requests != (0,):
                    raise ValueError('工厂运行退出及预算状态不可核查')
                if CANCEL_CHECK and store.read_run(run_id)['status'] != 'RECONCILING':
                    raise ValueError('本人取消后的运行状态不可核查')
                if (LOGOUT_CHECK or WITHDRAW_CHECK) and store.read_run(run_id)['status'] != 'INTERRUPTED':
                    raise ValueError('授权失效后的运行状态不可核查')
                if EXPIRE_CHECK and store.read_run(run_id)['status'] != 'INTERRUPTED':
                    raise ValueError('租约到期后的运行状态不可核查')
                if PREPARE_FAILURE:
                    inspection = await asyncio.to_thread(assembly.lifecycle.host.inspect)
                    if ('RUN_STARTED',) in events or final is not None or reservation != ('ACTIVE',) or inspection['process_exited'] is not None:
                        raise ValueError('工作区准备失败后的运行状态不可核查')
                    print('FACTORY_PREPARE_FAILURE_UNKNOWN_RETAINED', flush=True)
                else:
                    if ('RUN_STARTED',) not in events or not TOOLS_CHECK and ('RUN_FAILED',) not in events or final is None or final[0] <= 0 or final[1] != 'SLICE_CPU_NSEC_V1' or reservation != ('RELEASED',):
                        raise ValueError('工厂运行最终结算不可核查')
                    if (INODE_CHECK or BYTES_CHECK) and tool_events == [('query_metrics',), ('read_evidence',), ('workspace_write_file',)] and reservations == (3,):
                        with store.connect() as db:
                            failed = db.execute("SELECT json_extract(payload,'$.error_code') FROM agent_run_events WHERE run_id=? AND type='RUN_FAILED' ORDER BY seq DESC LIMIT 1", (run_id,)).fetchone()
                        if failed != ('TECHNICAL_FILE_FAILED_WRITE_QUOTA_FILE',):
                            raise ValueError('工作区额度检查失败原因不可核查')
                        print('FACTORY_QUOTA_WRITE_REJECTED', budget['files'], budget['file_bytes'], flush=True)
                    elif TOOLS_CHECK and (tool_events != [('query_metrics',), ('read_evidence',), ('workspace_write_file',), ('workspace_read_file',)] or reservations != (4,)):
                        print('FACTORY_TOOL_EVENTS', tool_events, 'RESERVATIONS', reservations, flush=True)
                        raise ValueError('受限 worker 工具检查未完成')
                    elif INODE_CHECK or BYTES_CHECK:
                        print('FACTORY_QUOTA_WRITE_RETURNED', budget['files'], budget['file_bytes'], flush=True)
                    print('FACTORY_WORKER_EXIT_AND_CPU_SETTLED', final[0], flush=True)
                return web.json_response({'run_id': run_id})

            app.router.add_post('/technical/configure', configure)
            app.router.add_post('/technical/create', create)
            app.router.add_post('/technical/execute', execute)
            runner = web.AppRunner(app)
            await runner.setup()
            await web.SockSite(runner, listener).start()
            try:
                async with aiohttp.ClientSession() as client:
                    async with client.get(origin + '/webui/bootstrap', headers={'Authorization': 'Bearer ' + role_secrets['MAINTAINER']}) as response:
                        response.raise_for_status()
                        maintainer = await response.json()
                    async with client.post(origin + '/technical/configure', headers={'Authorization': 'Bearer ' + maintainer['api_token'], 'Origin': origin}) as response:
                        response.raise_for_status()
                    async with client.get(origin + '/webui/bootstrap', headers={'Authorization': 'Bearer ' + role_secrets['BOSS']}) as response:
                        response.raise_for_status()
                        authentication = await response.json()
                    headers = {'Authorization': 'Bearer ' + authentication['api_token'], 'Origin': origin}
                    async with client.ws_connect(authentication['ws_url'], params={'token': authentication['token']}) as websocket:
                        while json.loads((await websocket.receive()).data).get('event') != 'ready':
                            pass
                        await websocket.send_json({'type': 'new_chat'})
                        while True:
                            event = json.loads((await websocket.receive()).data)
                            if event.get('event') == 'attached':
                                chat_id = event['chat_id']
                                break
                        async with client.post(origin + '/technical/create', json={'conversation_id': chat_id}, headers=headers) as response:
                            if response.status != 200:
                                raise ValueError('产品运行创建失败：' + await response.text())
                            data = await response.json()
                            run_id = data['run_id']
                        if RESELECT_CHECK:
                            input_url = origin + '/api/v2/runs/' + run_id + '/inputs'
                            async with client.post(input_url, json={'input': '指标改为销售收入', 'expected_goal_revision': 1,
                                                                  'request_key': 'factory-reselection-input'}, headers=headers) as response:
                                if response.status != 200:
                                    raise ValueError('目标补充失败：' + await response.text())
                            revision = 2
                            if RESELECT_MULTIPLE:
                                async with client.post(input_url, json={'input': '只看 region-1', 'expected_goal_revision': 2,
                                                                      'request_key': 'factory-reselection-second-input'}, headers=headers) as response:
                                    if response.status != 200:
                                        raise ValueError('连续目标补充失败：' + await response.text())
                                revision = 3
                            _, references = skills.catalog.context('BOSS', ['SOP03'])
                            method = {key: references[0][key] for key in ('sop_id', 'version', 'content_sha256')}
                            method_url = origin + '/api/v2/runs/' + run_id + '/method-selection'
                            payload = {'expected_goal_revision': revision, 'request_key': 'factory-reselection', 'method_selection': method}
                            async with client.post(method_url, json=payload, headers={'Authorization': 'Bearer invalid', 'Origin': origin}) as response:
                                if response.status != 401:
                                    raise ValueError('未认证方法选择未被拒绝')
                            stale = {**payload, 'expected_goal_revision': revision + 1, 'request_key': 'factory-reselection-stale'}
                            async with client.post(method_url, json=stale, headers=headers) as response:
                                if response.status != 409:
                                    raise ValueError('过期目标版本未被拒绝')
                            for _ in range(2):
                                async with client.post(method_url, json=payload, headers=headers) as response:
                                    if response.status != 200:
                                        raise ValueError('本人方法选择失败：' + str(response.status) + ' ' + await response.text())
                                    if (await response.json())['goal_revision'] != revision:
                                        raise ValueError('方法选择版本不可核查')
                            with store.connect() as db:
                                records = db.execute("SELECT id,body FROM objects WHERE namespace='ui-check' AND kind='hermes_bi_query_authorization' AND id IN (?,?) ORDER BY id", (run_id, run_id + ':' + str(revision))).fetchall()
                                if len(records) != 2:
                                    raise ValueError('经营查询授权版本不可核查')
                                second = json.loads(records[-1][1])
                                if second['goal_revision'] != revision or second['binding']['parameters']['metric_ids'] != ['revenue']:
                                    raise ValueError('经营查询目标更新不可核查')
                                first = json.loads(records[0][1])
                                if first['goal_revision'] != 1 or first['binding_sha256'] == second['binding_sha256']:
                                    raise ValueError('经营查询原目标版本不可核查')
                            print('FACTORY_BI_RESELECTION_AUTHORIZED', flush=True)
                            return
                        execution = asyncio.create_task(client.post(origin + '/technical/execute', json={'run_id': run_id}, headers=headers))
                        if CANCEL_CHECK or LOGOUT_CHECK or WITHDRAW_CHECK:
                            async def wait_tools():
                                while True:
                                    if execution.done():
                                        response = await execution
                                        raise ValueError('取消前受限运行已经结束：' + str(response.status) + ' ' + await response.text())
                                    with store.connect() as db:
                                        count = db.execute("SELECT count(*) FROM agent_run_events WHERE run_id=? AND type='TOOL_FINISHED'", (run_id,)).fetchone()[0]
                                    if count == 4:
                                        return
                                    await asyncio.sleep(0.1)
                            await asyncio.wait_for(wait_tools(), 90)
                            if CANCEL_CHECK:
                                revision = store.read_run(run_id)['revision']
                                async with client.post(origin + '/api/v2/runs/' + run_id + '/cancel',
                                        json={'expected_revision': revision, 'request_key': 'factory-cancel'}, headers=headers) as response:
                                    if response.status != 200:
                                        raise ValueError('本人取消请求未通过：' + await response.text())
                                print('FACTORY_OWNER_CANCELLED', flush=True)
                            elif LOGOUT_CHECK:
                                await websocket.send_json({'type': 'webui_request', 'action': 'boss.auth.logout',
                                                           'request_id': 'factory-logout', 'payload': {}})
                                while True:
                                    event = json.loads((await websocket.receive()).data)
                                    if event.get('request_id') == 'factory-logout':
                                        if event.get('ok') is not True:
                                            raise ValueError('本人退出请求未通过')
                                        break
                                print('FACTORY_OWNER_LOGGED_OUT', flush=True)
                            else:
                                business.control('ui-check', 'withdraw', {'source_id': 'finance-note', 'version': '1'})
                                print('FACTORY_SOURCE_WITHDRAWN', flush=True)
                        async with await execution as response:
                            text = await response.text()
                            print('FACTORY_EXECUTION_HTTP', response.status, text, flush=True)
                            if response.status != 200:
                                raise ValueError('产品工厂运行没有完成')
                            print('FACTORY_LIFECYCLE_CHECK_OK', flush=True)
                        if PREPARE_RECOVERY:
                            await asyncio.sleep(16)
                            recovery_listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                            recovery_listener.bind(('127.0.0.1', 0))
                            recovery_listener.listen()
                            recovery_listener.setblocking(False)
                            recovery_port = recovery_listener.getsockname()[1]
                            recovery_origin = 'http://127.0.0.1:' + str(recovery_port)
                            recovery_app = product_application(channel, broker, public_port=recovery_port, upstream_port=upstream.sockets[0].getsockname()[1])
                            install_run_recovery_routes(recovery_app, channel, services.recovery, public_port=recovery_port,
                                                        vm_manager=manager, workspace_root=workspace_root)
                            recovery_runner = web.AppRunner(recovery_app)
                            await recovery_runner.setup()
                            await web.SockSite(recovery_runner, recovery_listener).start()
                            try:
                                url = recovery_origin + '/api/v2/runs/' + run_id + '/recover-expired'
                                async with client.post(url, json={}, headers={'Authorization': 'Bearer invalid', 'Origin': recovery_origin}) as response:
                                    if response.status != 401:
                                        raise ValueError('未认证恢复请求未被拒绝')
                                async with client.get(recovery_origin + '/webui/bootstrap', headers={'Authorization': 'Bearer ' + role_secrets['BOSS']}) as response:
                                    response.raise_for_status()
                                    unattached = await response.json()
                                async with client.post(url, json={}, headers={'Authorization': 'Bearer ' + unattached['api_token'], 'Origin': recovery_origin}) as response:
                                    if response.status != 403:
                                        raise ValueError('未订阅会话的恢复请求未被拒绝')
                                recovery_headers = {'Authorization': 'Bearer ' + authentication['api_token'], 'Origin': recovery_origin}
                                for _ in range(2):
                                    async with client.post(url, json={}, headers=recovery_headers) as response:
                                        if response.status != 200:
                                            raise ValueError('准备失败恢复请求未通过：' + str(response.status) + ' ' + await response.text())
                                        result = await response.json()
                                        if result != {'run_id': run_id, 'status': 'INTERRUPTED', 'unknown_reservations': 1}:
                                            raise ValueError('准备失败恢复回执不可核查：' + str(result))
                                with store.connect() as db:
                                    state = db.execute('SELECT state FROM agent_concurrency_reservations WHERE run_id=?', (run_id,)).fetchone()
                                    final = db.execute('SELECT count(*) FROM hermes_cpu_final_exits WHERE run_id=?', (run_id,)).fetchone()
                                    cpu = db.execute('SELECT reserved_ns,observed_ns FROM hermes_cpu_reservations WHERE run_id=?', (run_id,)).fetchone()
                                    if state != ('UNKNOWN',) or final != (0,) or cpu != (budget['cpu_seconds'] * 1000000000, 0):
                                        raise ValueError('准备失败恢复预留不可核查')
                                    db.execute('BEGIN')
                                    dispatch = dispatcher.inspect_dispatch_recovery_in_transaction(db, run_id, 'factory-dispatch')
                                    if dispatch['receipt_state'] != 'UNKNOWN' or dispatch['reservation_state'] != 'UNKNOWN' or dispatch['automatic_retry'] is not False:
                                        raise ValueError('准备失败派发恢复不可核查')
                                print('FACTORY_PREPARE_UNKNOWN_RECOVERY_CONFIRMED', flush=True)
                            finally:
                                await recovery_runner.cleanup()
            finally:
                await runner.cleanup()
    finally:
        if manager is not None:
            await asyncio.to_thread(manager.stop)
            print('FACTORY_VM_STOPPED', flush=True)


asyncio.run(main())
