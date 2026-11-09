import argparse
import asyncio
import json
import secrets
import socket
import sys
from pathlib import Path
from uuid import uuid4

import aiohttp
import pytest
from aiohttp import web
from nanobot.bus.queue import MessageBus
from nanobot.channels.websocket.runtime import WebSocketChannel, WebSocketConfig
from nanobot.webui.gateway_services import build_gateway_services
from websockets.asyncio.server import serve

from agent_run_api import product_application
from agent_run_broker import RunBroker, RunIdentity
from agent_run_concurrency import RunConcurrencyBudget
from agent_run_dispatcher import AgentRunDispatcher
from agent_run_recovery_routes import install_run_recovery_routes
from agent_run_scope import RunScopeService
from agent_run_store import RunStore
from agent_simulation_migration_install import install_simulation_migrations
from boss_memory_sessions import MemorySessionManager
from controls import ControlStore
from hermes_cpu_budget import HermesCPUBudget
from hermes_bridge import HermesBridge
from hermes_process_evidence import HermesProcessEvidence
from hermes_product import HermesProductServices
from hermes_run_recovery import HermesRunRecovery
from hermes_vm_host import HermesVMHostClient
from hermes_vm_identity import HermesVMRunAccess, HermesVMRunBindings
from hermes_vm_manager import HermesVMManager
from role_channel import RoleChannel


parser = argparse.ArgumentParser()
parser.add_argument("--executable", type=Path, required=True)
parser.add_argument("--executable-sha256", required=True)
parser.add_argument("--directory", type=Path, required=True)
parser.add_argument("--credentials", type=Path, required=True)
parser.add_argument("--dependencies", type=Path, required=True)
parser.add_argument("--engine", type=Path, required=True)
parser.add_argument("--results", type=Path, required=True)
parser.add_argument("--runtime-port", type=int, required=True)
parser.add_argument("--control-port", type=int, required=True)
parser.add_argument("--reboot-before-recovery", action="store_true")
parser.add_argument("--expire-while-running", action="store_true")
parser.add_argument("--expect-unknown", action="store_true")
arguments = parser.parse_args()
results = arguments.results.resolve(strict=True)
business = ControlStore(results / "business.sqlite")
business.initialize("ui-check")
store = RunStore(business.path)
install_simulation_migrations(store.path)
sessions = MemorySessionManager(results / "sessions-workspace", business_store=business, sessions_root=results / "sessions")
scope = RunScopeService(business, sessions, "ui-check")
broker = RunBroker(store, scope_service=scope)
concurrency = RunConcurrencyBudget(store)
evidence = HermesProcessEvidence(store)
bindings = HermesVMRunBindings(store)
cpu_budget = HermesCPUBudget(store)
workspace_root = results / "vm-workspaces"
workspace_root.mkdir(mode=0o700)
role_secrets = {role: secrets.token_urlsafe(32) for role in ("BOSS", "MAINTAINER")}
config = WebSocketConfig(host="127.0.0.1", port=0, token_issue_secret=role_secrets["BOSS"], token_ttl_s=180)
bus = MessageBus()
gateway = build_gateway_services(config=config, bus=bus, session_manager=sessions, static_dist_path=None,
    workspace_path=results, default_restrict_to_workspace=True, config_path=results / "config.json",
    runtime_model_name=None, runtime_surface="webui", runtime_capabilities_overrides=None)
channel = RoleChannel(WebSocketChannel(config, bus, gateway=gateway), role_secrets, results / "audit.jsonl", business)
recovery = HermesRunRecovery(channel, scope, store)
dispatcher = AgentRunDispatcher(HermesProductServices(store, scope, broker, HermesBridge(business), recovery))
manager = HermesVMManager.start(arguments.executable, arguments.directory, arguments.credentials, arguments.executable_sha256,
    arguments.runtime_port, arguments.control_port, {"memory_bytes": 1073741824, "processes": 64, "cpu_percent": 100},
    dependencies_directory=arguments.dependencies, engine_directory=arguments.engine)


async def main():
    global manager
    async with serve(channel._connection_loop, "127.0.0.1", 0, process_request=channel._dispatch_http) as upstream:
        upstream_port = upstream.sockets[0].getsockname()[1]
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        listener.setblocking(False)
        public_port = listener.getsockname()[1]
        origin = "http://127.0.0.1:" + str(public_port)
        app = product_application(channel, broker, public_port=public_port, upstream_port=upstream_port)
        install_run_recovery_routes(app, channel, recovery, public_port=public_port, vm_manager=manager, workspace_root=workspace_root)

        async def technical_create(request):
            channel.require_run_api_role(request)
            body = await request.json()
            chat_id = body["conversation_id"]
            channel.require_run_subscription(request, chat_id)
            session = sessions.get_or_create("websocket:" + chat_id)
            sessions.save(session, fsync=True)
            proof = scope.prove(chat_id, [])
            identity = RunIdentity(proof.owner_id, proof.namespace, "BOSS", frozenset({chat_id}), frozenset(),
                verify=lambda: channel.require_run_subscription(request, chat_id))
            return web.json_response(broker.create(identity, {"conversation_id": chat_id, "goal": "核查运行恢复", "selected_refs": [], "request_key": str(uuid4())}, request=request))

        app.router.add_post("/technical/create", technical_create)
        runner = web.AppRunner(app)
        await runner.setup()
        await web.SockSite(runner, listener).start()
        restarted_runner = None
        try:
            async with aiohttp.ClientSession() as client:
                async with client.get(origin + "/webui/bootstrap", headers={"Authorization": "Bearer " + role_secrets["BOSS"]}) as response:
                    response.raise_for_status()
                    authentication = await response.json()
                headers = {"Authorization": "Bearer " + authentication["api_token"], "Origin": origin}
                async with client.ws_connect(authentication["ws_url"], params={"token": authentication["token"]}) as websocket:
                    while json.loads((await websocket.receive()).data).get("event") != "ready":
                        pass
                    await websocket.send_json({"type": "new_chat"})
                    while True:
                        event = json.loads((await websocket.receive()).data)
                        if event.get("event") == "attached":
                            chat_id = event["chat_id"]
                            break
                    async with client.post(origin + "/technical/create", json={"conversation_id": chat_id}, headers=headers) as response:
                        response.raise_for_status()
                        run_id = (await response.json())["run_id"]
                    lease = store.acquire_lease(run_id, 0, "worker", 15)
                    epoch = lease["epoch"]
                    process_key = "dispatch:" + run_id + ":" + str(epoch)
                    store.transition(run_id, lease["revision"], "RUNNING", "worker", epoch)
                    concurrency.configure(run_id, "worker", epoch, 1)
                    workspace = workspace_root / run_id
                    workspace.mkdir(mode=0o700)
                    boot_id = await asyncio.to_thread(manager.control.identity)
                    with store.connect() as db:
                        db.execute("BEGIN IMMEDIATE")
                        concurrency.reserve_in_transaction(db, run_id, "worker", epoch, process_key, "digest")
                        dispatcher.record_dispatch_in_transaction(db, run_id, "dispatch-check", 0, "worker", epoch)
                        evidence.record_vm_start_in_transaction(db, bindings, run_id, process_key, "digest", "worker", epoch,
                            "boss-1", "ui-check", manager.vm_id, boot_id, workspace)
                        cpu_budget.configure_in_transaction(db, run_id, "worker", epoch, 20_000_000_000)
                    access = HermesVMRunAccess(bindings, run_id, process_key, "worker", epoch, manager.vm_id, boot_id, workspace)
                    with store.connect() as db:
                        db.execute("BEGIN IMMEDIATE")
                        cpu_budget.reserve_in_transaction(db, access, 20_000_000_000)
                    host = HermesVMHostClient(access, manager.control.context, manager.control.guest_name,
                                              manager.control.guest_certificate_sha256, arguments.control_port)
                    budget = {"rounds": 1, "seconds": 45, "memory_bytes": 1073741824, "processes": 64,
                              "cpu_percent": 100, "open_files": 64, "files": 16, "file_bytes": 1048576, "cpu_seconds": 20}
                    bootstrap = {"endpoint": "http://127.0.0.1:" + str(arguments.runtime_port), "capability": secrets.token_urlsafe(32),
                        "provider_capability": secrets.token_urlsafe(32), "run_id": run_id,
                        "engine_commit": "903230b1e23e0c496b28e5d2e8c4f2639cd506b6"}
                    await asyncio.to_thread(host.start, budget, bootstrap)
                    await asyncio.sleep(1)
                    sampled = await asyncio.to_thread(cpu_budget.record_sample, host, "sample-1")
                    if arguments.expect_unknown != (arguments.reboot_before_recovery and arguments.expire_while_running):
                        raise ValueError("恢复检查选项无效")
                    if not arguments.expire_while_running:
                        await asyncio.to_thread(host.stop)
                    if arguments.reboot_before_recovery:
                        await asyncio.to_thread(manager.stop)
                        manager = await asyncio.to_thread(HermesVMManager.start, arguments.executable, arguments.directory,
                            arguments.credentials, arguments.executable_sha256, arguments.runtime_port, arguments.control_port,
                            {"memory_bytes": 1073741824, "processes": 64, "cpu_percent": 100},
                            dependencies_directory=arguments.dependencies, engine_directory=arguments.engine)
                        await asyncio.sleep(30)
                        if await asyncio.to_thread(manager.control.identity) == boot_id:
                            raise ValueError("客体启动身份没有变化")
                        restarted_listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                        restarted_listener.bind(("127.0.0.1", 0))
                        restarted_listener.listen()
                        restarted_listener.setblocking(False)
                        restarted_port = restarted_listener.getsockname()[1]
                        restarted_app = product_application(channel, broker, public_port=restarted_port, upstream_port=upstream_port)
                        install_run_recovery_routes(restarted_app, channel, recovery, public_port=restarted_port,
                                                    vm_manager=manager, workspace_root=workspace_root)
                        restarted_runner = web.AppRunner(restarted_app)
                        await restarted_runner.setup()
                        await web.SockSite(restarted_runner, restarted_listener).start()
                        origin = "http://127.0.0.1:" + str(restarted_port)
                        headers = {"Authorization": "Bearer " + authentication["api_token"], "Origin": origin}
                    else:
                        await asyncio.sleep(16)
                    with pytest.raises(ValueError):
                        await asyncio.to_thread(host.final_exit_receipt)
                    with pytest.raises(ValueError):
                        await asyncio.to_thread(host.start, budget, bootstrap)
                    response_url = origin + "/api/v2/runs/" + run_id + "/recover-expired"
                    async with client.post(response_url, json={}, headers={"Authorization": "Bearer invalid", "Origin": origin}) as response:
                        if response.status != 401:
                            raise ValueError("未认证恢复请求未被拒绝")
                    async with client.get(origin + "/webui/bootstrap", headers={"Authorization": "Bearer " + role_secrets["BOSS"]}) as response:
                        response.raise_for_status()
                        unattached = await response.json()
                    async with client.post(response_url, json={}, headers={"Authorization": "Bearer " + unattached["api_token"], "Origin": origin}) as response:
                        if response.status != 403:
                            raise ValueError("未订阅会话的恢复请求未被拒绝")
                    with store.connect() as db:
                        if db.execute("SELECT status FROM agent_runs WHERE run_id=?", (run_id,)).fetchone() != ("RUNNING",) or db.execute("SELECT state FROM agent_concurrency_reservations WHERE run_id=? AND request_key=?", (run_id, process_key)).fetchone() != ("ACTIVE",):
                            raise ValueError("未授权请求改变了恢复状态")
                    if arguments.expect_unknown:
                        for _ in range(2):
                            async with client.post(response_url, json={}, headers=headers) as response:
                                if response.status != 200 or await response.json() != {"run_id": run_id, "status": "INTERRUPTED", "unknown_reservations": 1}:
                                    raise ValueError("缺少最终回执的恢复状态不可核查")
                            with store.connect() as db:
                                state = db.execute("SELECT state FROM agent_concurrency_reservations WHERE run_id=? AND request_key=?", (run_id, process_key)).fetchone()
                                count = db.execute("SELECT count(*) FROM hermes_cpu_final_exits WHERE run_id=?", (run_id,)).fetchone()
                                if state != ("UNKNOWN",) or count != (0,):
                                    raise ValueError("缺少最终回执时预留状态不可核查")
                        print("AUTHENTICATED_MISSING_RECEIPT_REMAINS_UNKNOWN", flush=True)
                        return
                    async with client.post(response_url, json={}, headers=headers) as response:
                        body = await response.json()
                        if response.status != 200 or body != {"run_id": run_id, "status": "INTERRUPTED", "unknown_reservations": 0}:
                            raise ValueError("运行恢复响应不可核查: " + str(response.status) + " " + str(body))
                    async with client.post(response_url, json={}, headers=headers) as response:
                        if response.status != 200 or await response.json() != body:
                            raise ValueError("运行恢复重复请求不可核查")
                    async with client.post(response_url, json={}, headers={"Authorization": "Bearer invalid", "Origin": origin}) as response:
                        if response.status != 401:
                            raise ValueError("失效身份未被拒绝")
                    with store.connect() as db:
                        final = db.execute("SELECT cpu_ns,source FROM hermes_cpu_final_exits WHERE run_id=? AND request_key=?", (run_id, process_key)).fetchall()
                        state = db.execute("SELECT state FROM agent_concurrency_reservations WHERE run_id=? AND request_key=?", (run_id, process_key)).fetchone()
                        if len(final) != 1 or final[0][0] < sampled or final[0][1] != "SLICE_CPU_NSEC_V1" or state != ("RELEASED",):
                            raise ValueError("运行恢复结算不可核查")
                        db.execute("BEGIN")
                        dispatch = dispatcher.inspect_dispatch_recovery_in_transaction(db, run_id, "dispatch-check")
                        if dispatch["receipt_state"] != "UNKNOWN" or dispatch["reservation_state"] != "RELEASED" or dispatch["automatic_retry"] is not False:
                            raise ValueError("原派发恢复状态不可核查")
                        with pytest.raises(web.HTTPConflict):
                            dispatcher.require_no_unresolved_dispatch_in_transaction(db, run_id)
                    with pytest.raises(ValueError):
                        store.acquire_lease(run_id, store.read_run(run_id)["revision"], "new-worker", 15)
                    await websocket.send_json({"type": "webui_request", "action": "boss.auth.logout", "request_id": str(uuid4()), "payload": {}})
                    while True:
                        message = await websocket.receive()
                        if message.type in {aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR}:
                            break
                        event = json.loads(message.data)
                        if event.get("event") == "webui_response" and event.get("ok") is True:
                            break
                    async with client.post(response_url, json={}, headers=headers) as response:
                        if response.status != 401:
                            raise ValueError("退出后的恢复身份仍然有效")
                    print("LOGGED_OUT_RECOVERY_REJECTED", flush=True)
                    print("ORIGINAL_DISPATCH_REMAINS_UNKNOWN", flush=True)
                    print("AUTHENTICATED_EXPIRED_VM_RECOVERY", sampled, final[0][0], flush=True)
                    if arguments.reboot_before_recovery:
                        print("AUTHENTICATED_REBOOTED_VM_RECEIPT_RECOVERY", flush=True)
                    if arguments.expire_while_running:
                        print("AUTHENTICATED_EXPIRED_RUNNING_VM_STOPPED", flush=True)
        finally:
            if restarted_runner is not None:
                await restarted_runner.cleanup()
            await runner.cleanup()


try:
    print("VM_MANAGER_STARTED", flush=True)
    if not sys.stdin.readline():
        raise ValueError("客体启动等待被中断")
    asyncio.run(main())
finally:
    manager.stop()
    print("VM_MANAGER_GRACEFUL_STOP_OK", flush=True)
