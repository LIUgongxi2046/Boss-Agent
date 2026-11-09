import asyncio
import hashlib
import json
import logging
import os
import secrets
import sqlite3
import socket
import sys
import threading
import zipfile
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from dataclasses import asdict
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from aiohttp import web
from nanobot.bus.queue import MessageBus
from nanobot.channels.websocket.runtime import WebSocketChannel, WebSocketConfig
from nanobot.webui.gateway_services import build_gateway_services

from agent_run_scope import RunScopeService
from agent_run_requirements import RunRequirements
from agent_run_concurrency import RunConcurrencyBudget
from agent_run_launch_transaction import RunLaunchTransaction
from agent_run_store import RunStore
from agent_run_tool_budget import RunToolBudget
from boss_memory_sessions import MemorySessionManager
from controls import ControlStore
from hermes_bridge import EngineEventSink, EngineProcessConfig, EngineProcessSupervisor, EngineRunConfig, HermesBridge
from hermes_budget_gateway import ProviderGateway, RunBoundBudgetStore
from hermes_runtime_transport import HermesExecutionLifecycle, HermesRuntimeTransport, HermesSharedRuntimeService, verify_experimental_adapter, experimental_sandbox_command
from hermes_workspace_image import ExperimentalWorkspaceImage
from hermes_process_anchor import AnchorProcessGroup
from hermes_process_evidence import HermesProcessEvidence
from hermes_process_manager import HermesProcessManager, IsolationBoundaryUnavailable
from hermes_anchor_evidence import HermesAnchorEvidence
from hermes_product import SERVICES_KEY, hermes_product_application
from role_channel import RoleChannel
from test_agent_run_result import setup_result
from test_hermes_vm_channel import contexts
from hermes_vm_channel import HermesVMServerTLS
from hermes_vm_identity import HermesVMRunAccess, HermesVMRunBindings
from hermes_vm_host import HermesVMHostClient


@pytest.mark.parametrize("valid_pin", [True, False])
def test_runtime_server_verifies_vm_peer_certificate(tmp_path, valid_pin):
    async def exercise():
        business, runs, results, original = setup_result(tmp_path)
        RunToolBudget(runs, allow_migration=True).configure(original.config.run_id, original.lease_owner,
                                                            original.config.lease_epoch, 1)
        concurrency = RunConcurrencyBudget(runs, allow_migration=True)
        concurrency.configure(original.config.run_id, original.lease_owner, original.config.lease_epoch, 1)
        runs.configure_file_budget(original.config.run_id, original.lease_owner, original.config.lease_epoch, 8, 1048576)
        evidence = HermesProcessEvidence(runs, allow_migration=True)
        bindings = HermesVMRunBindings(runs, allow_migration=True)
        workspace = tmp_path / original.config.run_id
        workspace.mkdir()
        vm_id, boot_id = str(uuid4()), str(uuid4())
        with runs.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            concurrency.reserve_in_transaction(db, original.config.run_id, original.lease_owner, original.config.lease_epoch, "slot", "digest")
            evidence.record_vm_start_in_transaction(db, bindings, original.config.run_id, "slot", "digest", original.lease_owner,
                                                    original.config.lease_epoch, "boss-1", "ui-check", vm_id, boot_id, workspace)
        access = HermesVMRunAccess(bindings, original.config.run_id, "slot", original.lease_owner,
                                   original.config.lease_epoch, vm_id, boot_id, workspace)
        server_context, client_context, server_hash, client_hash = contexts(tmp_path)
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        port = listener.getsockname()[1]
        config = EngineRunConfig(original.config.run_id, original.config.lease_epoch, original.config.engine_commit,
                                 "http://127.0.0.1:" + str(port), original.config.request_limit)
        sink = EngineEventSink(runs, config, original.lease_owner)
        capability = secrets.token_urlsafe(32)
        transport = HermesRuntimeTransport(sink, results.scope, HermesBridge(business), actor_id="boss-1", space_id="ui-check",
                                          capability=capability, max_tools=1)
        vm_tls = HermesVMServerTLS(server_context, client_hash if valid_pin else "0" * 64, access)
        other_access = HermesVMRunAccess(bindings, original.config.run_id, "slot", "other-worker",
                                         original.config.lease_epoch, vm_id, boot_id, workspace)
        with pytest.raises(ValueError, match="运行租约不匹配"):
            async with transport.serve(listener, vm_tls=HermesVMServerTLS(server_context, client_hash, other_access)):
                pass
        assert not transport.started
        async with transport.serve(listener, vm_tls=vm_tls):
            async with httpx.AsyncClient(verify=client_context, trust_env=False) as client:
                response = await client.get("https://127.0.0.1:" + str(port) + "/")
                assert response.status_code == (404 if valid_pin else 403)
                if valid_pin:
                    host = HermesVMHostClient(access, client_context, "localhost", server_hash, port)
                    with pytest.raises(ValueError, match="客体控制响应不可核查"):
                        await asyncio.to_thread(host.start, {}, {"run_id": original.config.run_id})
                    other_host = HermesVMHostClient(access, client_context, "localhost", "0" * 64, port)
                    with pytest.raises(ValueError, match="证书不匹配"):
                        await asyncio.to_thread(other_host.start, {}, {"run_id": original.config.run_id})
                    endpoint = "https://127.0.0.1:" + str(port) + "/internal/v1/request"
                    assert (await client.get(endpoint)).status_code == 401
                    response = await client.get(endpoint, headers={"Authorization": "Bearer " + capability})
                    assert response.status_code == 200
                    assert response.json()["run_id"] == original.config.run_id
                    runs.cancel(original.config.run_id, runs.read_run(original.config.run_id)["revision"])
                    response = await client.get(endpoint, headers={"Authorization": "Bearer " + capability})
                    assert response.status_code == 500
        assert transport.closed

    asyncio.run(exercise())


def test_shared_runtime_preserves_independent_run_access(tmp_path):
    async def exercise():
        probe = socket.socket()
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
        probe.close()
        server_context, client_context, _, client_hash = contexts(tmp_path)
        service = HermesSharedRuntimeService(port)
        vm_id, boot_id = str(uuid4()), str(uuid4())
        instances = []
        for name in ("parent", "child"):
            directory = tmp_path / name
            directory.mkdir()
            business, runs, results, original = setup_result(directory)
            RunToolBudget(runs, allow_migration=True).configure(original.config.run_id, original.lease_owner, original.config.lease_epoch, 1)
            concurrency = RunConcurrencyBudget(runs, allow_migration=True)
            concurrency.configure(original.config.run_id, original.lease_owner, original.config.lease_epoch, 1)
            runs.configure_file_budget(original.config.run_id, original.lease_owner, original.config.lease_epoch, 8, 1048576)
            evidence = HermesProcessEvidence(runs, allow_migration=True)
            bindings = HermesVMRunBindings(runs, allow_migration=True)
            workspace = directory / original.config.run_id
            workspace.mkdir()
            with runs.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                concurrency.reserve_in_transaction(db, original.config.run_id, original.lease_owner, original.config.lease_epoch, "slot", "digest")
                evidence.record_vm_start_in_transaction(db, bindings, original.config.run_id, "slot", "digest", original.lease_owner,
                                                        original.config.lease_epoch, "boss-1", "ui-check", vm_id, boot_id, workspace)
            access = HermesVMRunAccess(bindings, original.config.run_id, "slot", original.lease_owner, original.config.lease_epoch, vm_id, boot_id, workspace)
            config = EngineRunConfig(original.config.run_id, original.config.lease_epoch, original.config.engine_commit,
                                     "http://127.0.0.1:" + str(port), original.config.request_limit)
            sink = EngineEventSink(runs, config, original.lease_owner)
            capability, provider_capability = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
            gateway = ProviderGateway(RunBoundBudgetStore(sink, allow_migration=True), provider_capability, None, offline=True)
            transport = HermesRuntimeTransport(sink, results.scope, HermesBridge(business), actor_id="boss-1", space_id="ui-check",
                                              capability=capability, max_tools=1, provider_gateway=gateway)
            instances.append((transport, HermesVMServerTLS(server_context, client_hash, access), capability, provider_capability, runs))
        parent, child = instances
        endpoint = "https://127.0.0.1:" + str(port) + "/internal/v1/request"
        async with parent[0].serve(service.listener(), vm_tls=parent[1]):
            async with httpx.AsyncClient(verify=client_context, trust_env=False) as client:
                async with child[0].serve(service.listener(), vm_tls=child[1]):
                    for instance in instances:
                        response = await client.get(endpoint, headers={"Authorization": "Bearer " + instance[2]})
                        assert response.status_code == 200
                        assert response.json()["run_id"] == instance[0].transport.sink.config.run_id
                        assert (await client.get(endpoint, headers={"Authorization": "Bearer " + instance[3]})).status_code == 401
                        model_endpoint = "https://127.0.0.1:" + str(port) + "/chat/completions"
                        assert (await client.post(model_endpoint, headers={"Authorization": "Bearer " + instance[2]}, json={})).status_code == 401
                        assert (await client.post(model_endpoint, headers={"Authorization": "Bearer " + instance[3]}, json={})).status_code == 503
                    assert (await client.get(endpoint, headers={"Authorization": "Bearer invalid"})).status_code == 401
                assert (await client.get(endpoint, headers={"Authorization": "Bearer " + child[2]})).status_code == 401
                assert (await client.get(endpoint, headers={"Authorization": "Bearer " + parent[2]})).status_code == 200
                parent[4].cancel(parent[0].transport.sink.config.run_id, parent[4].read_run(parent[0].transport.sink.config.run_id)["revision"])
                assert (await client.get(endpoint, headers={"Authorization": "Bearer " + parent[2]})).status_code >= 400
        assert service.runner is None and not service.entries

    asyncio.run(exercise())


def test_experimental_adapter_verifies_actual_installed_resources(tmp_path):
    root = Path(__file__).resolve().parents[2]
    wheel = root / ".work/upgrade2/u2-03/bi-adapter-008/boss_agent_hermes_adapter-0.1.9-py3-none-any.whl"
    installed = root / ".work/upgrade2/u2-03/bi-adapter-installed-008"
    source = tmp_path / "source"
    validation = source / "validation"
    validation.mkdir(parents=True)
    with zipfile.ZipFile(wheel) as archive:
        names = [name for name in archive.namelist() if "/" not in name]
        for name in names:
            (validation / name).write_bytes(archive.read(name))
    (source / "hermes-engine-resources.txt").write_text("\n".join("validation/" + name for name in names), encoding="utf-8")
    binding = verify_experimental_adapter(source, wheel, installed)
    assert binding == {"entry": installed / "hermes_engine_entry.py", "wheel_sha256": "428dcd5f76be8d084a19bae6c6467df03577518cca1451d146a7fd5a9df32dc4", "version": "0.1.9"}
    with pytest.raises(ValueError, match="资源清单不可核查"):
        verify_experimental_adapter(tmp_path, wheel, installed)


def test_experimental_child_workspace_is_rejected_before_ticket_consumption(tmp_path):
    async def exercise():
        business, runs, results, root_sink = setup_result(tmp_path)
        root = root_sink.config.run_id
        RunToolBudget(runs, allow_migration=True).configure(root, root_sink.lease_owner, root_sink.config.lease_epoch, 1)
        concurrency = RunConcurrencyBudget(runs, allow_migration=True)
        concurrency.configure(root, root_sink.lease_owner, root_sink.config.lease_epoch, 1)
        RunBoundBudgetStore(root_sink, allow_migration=True)
        evidence = HermesProcessEvidence(runs, allow_migration=True)
        HermesAnchorEvidence(runs, allow_migration=True)
        child = runs.create_child_run(root, root_sink.lease_owner, root_sink.config.lease_epoch, "image-child", "image-child-digest")
        lease = runs.acquire_queued_for_execution(child, 0, "image-child-worker", 60)
        run = runs.read_run(child)
        with runs.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            concurrency.reserve_in_transaction(db, child, "image-child-worker", lease["epoch"], "slot", "digest")
            ticket = evidence.record_start_in_transaction(db, child, "slot", "digest", "image-child-worker", lease["epoch"], run["actor_id"], run["space_id"])
        listener = socket.socket()
        try:
            listener.bind(("127.0.0.1", 0))
            listener.listen()
            endpoint = "http://127.0.0.1:" + str(listener.getsockname()[1])
            config = EngineRunConfig(child, lease["epoch"], root_sink.config.engine_commit, endpoint, 1)
            sink = EngineEventSink(runs, config, "image-child-worker")
            capability, provider_capability = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
            provider = ProviderGateway(RunBoundBudgetStore(sink), provider_capability, None, offline=True)
            transport = HermesRuntimeTransport(sink, results.scope, HermesBridge(business), actor_id=run["actor_id"], space_id=run["space_id"], capability=capability, max_tools=1, provider_gateway=provider)
            lifecycle = HermesExecutionLifecycle(transport, evidence)
            process_config = EngineProcessConfig(config, *([tmp_path] * 7), 1, 1, 10, 1, 128, 1, 1024, 16, 1)
            with pytest.raises(ValueError, match="子运行共享磁盘容量尚未实现"):
                await lifecycle.run_guarded_configured(listener, ticket, process_config, bootstrap={},
                    experimental_adapter={}, experimental_sandbox={"profile_text": "test", "profile_sha256": "test"})
            assert evidence.prepared_identity(ticket) == (child, "slot") and not transport.started
            with runs.connect() as db:
                assert db.execute("SELECT count(*) FROM hermes_anchor_evidence WHERE run_id=?", (child,)).fetchone() == (0,)
                assert db.execute("SELECT state FROM agent_concurrency_reservations WHERE run_id=?", (child,)).fetchone() == ("ACTIVE",)
            provider.close()
        finally:
            listener.close()

    asyncio.run(exercise())


@pytest.mark.parametrize("trigger", ["withdraw", "cancel", "cancel_before_reserve", "reserve_before_cancel"])
def test_guarded_runtime_stops_after_simulated_source_withdrawal(tmp_path, trigger):
    async def exercise():
        business, runs, results, original = setup_result(tmp_path)
        run_id = original.config.run_id
        epoch = original.config.lease_epoch
        owner = original.lease_owner
        tools = RunToolBudget(runs, allow_migration=True)
        tools.configure(run_id, owner, epoch, 1)
        concurrency = RunConcurrencyBudget(runs, allow_migration=True)
        concurrency.configure(run_id, owner, epoch, 1)
        evidence = HermesProcessEvidence(runs, allow_migration=True)
        HermesAnchorEvidence(runs, allow_migration=True)
        with runs.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            concurrency.reserve_in_transaction(db, run_id, owner, epoch, "slot", "digest")
            ticket = evidence.record_start_in_transaction(db, run_id, "slot", "digest", owner, epoch, "boss-1", "ui-check")
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        endpoint = "http://127.0.0.1:" + str(listener.getsockname()[1])
        config = EngineRunConfig(run_id, epoch, original.config.engine_commit, endpoint, 2)
        sink = EngineEventSink(runs, config, owner)
        capability, provider_capability = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        provider = ProviderGateway(RunBoundBudgetStore(sink, allow_migration=True), provider_capability, secrets.token_urlsafe(32), offline=True)
        transport = HermesRuntimeTransport(sink, results.scope, HermesBridge(business), actor_id="boss-1", space_id="ui-check",
                                          capability=capability, max_tools=1, provider_gateway=provider)
        lifecycle = HermesExecutionLifecycle(transport, evidence)
        bootstrap = {"endpoint": endpoint, "capability": capability, "provider_capability": provider_capability,
                     "run_id": run_id, "engine_commit": config.engine_commit}
        probe = Path(__file__).with_name("hermes_runtime_transport_probe.py")
        engine = Path(__file__).resolve().parents[2] / ".work/upgrade2/u2-03/clean-hermes"
        task = asyncio.create_task(lifecycle.run_guarded(listener, ticket, [sys.executable, str(probe), str(engine), "503"],
                                                        cwd=tmp_path, bootstrap=bootstrap, max_seconds=10, interval=0.02))
        while not any(event["type"] == "RUN_STARTED" for event in runs.events(run_id, 0)):
            if task.done():
                await task
                raise ValueError("进程未产生启动事件")
            await asyncio.sleep(0.01)
        request_id = provider.store.reserve()
        requests = [request_id]
        if trigger == "withdraw":
            business.control("ui-check", "withdraw", {"source_id": "finance-note", "version": "1"})
            with pytest.raises(ValueError, match="来源已经撤销"):
                provider.store.reserve()
            with pytest.raises(ValueError, match="来源已经撤销"):
                provider.store.complete(request_id, None)
            with pytest.raises(ValueError, match="来源已经撤销"):
                await task
        else:
            revision = runs.read_run(run_id)["revision"]
            barrier = threading.Barrier(2, timeout=10)
            committed = threading.Event()
            def cancel():
                barrier.wait()
                if trigger == "reserve_before_cancel":
                    assert committed.wait(10)
                result = runs.cancel(run_id, revision)
                if trigger == "cancel_before_reserve":
                    committed.set()
                return result
            def reserve():
                barrier.wait()
                if trigger == "cancel_before_reserve":
                    assert committed.wait(10)
                result = provider.store.reserve()
                if trigger == "reserve_before_cancel":
                    committed.set()
                return result
            with ThreadPoolExecutor(max_workers=2) as executor:
                cancel_future = executor.submit(cancel)
                reserve_future = executor.submit(reserve)
                assert cancel_future.result(timeout=10)["status"] == "CANCEL_REQUESTED"
                error = reserve_future.exception(timeout=10)
                if error is None:
                    requests.append(reserve_future.result())
                else:
                    assert isinstance(error, ValueError) and "取消" in str(error)
                if trigger == "cancel_before_reserve":
                    assert error is not None
                if trigger == "reserve_before_cancel":
                    assert error is None
            with pytest.raises(ValueError, match="取消"):
                provider.store.reserve()
            with pytest.raises(ValueError, match="取消"):
                provider.store.complete(request_id, None)
            result = await asyncio.wait_for(task, 15)
            assert result.state == "INTERRUPTED" and result.descendants == "NOT_VERIFIED"
        with runs.connect() as db:
            assert db.execute("SELECT state FROM hermes_process_evidence WHERE run_id=?", (run_id,)).fetchone() == ("UNKNOWN",)
            assert db.execute("SELECT state FROM agent_concurrency_reservations WHERE run_id=?", (run_id,)).fetchone() == ("UNKNOWN",)
            assert db.execute("SELECT status FROM agent_runs WHERE run_id=?", (run_id,)).fetchone() == ("INTERRUPTED",)
            assert db.execute("SELECT request_id,state FROM hermes_model_requests WHERE run_id=? ORDER BY rowid", (run_id,)).fetchall() == [(value, "UNKNOWN") for value in requests]
            if trigger != "withdraw":
                assert db.execute("SELECT cancel_requested_at FROM agent_runs WHERE run_id=?", (run_id,)).fetchone()[0] is not None
        if trigger != "withdraw":
            usage = [event["payload"] for event in runs.events(run_id, 0) if event["type"] == "USAGE_RECORDED"]
            assert len(usage) == 1 and usage[0]["root_run_id"] == run_id
            assert usage[0]["requests_used"] == len(requests) and usage[0]["usage_state"] == "UNKNOWN"
            assert usage[0]["total_tokens"] is None
        assert transport.closed
        assert provider.capability is None and provider.provider_key is None

    asyncio.run(exercise())


def test_guarded_process_reads_and_replays_simulated_document(tmp_path):
    async def exercise():
        business, runs, results, original = setup_result(tmp_path)
        run_id = original.config.run_id
        epoch = original.config.lease_epoch
        owner = original.lease_owner
        RunToolBudget(runs, allow_migration=True).configure(run_id, owner, epoch, 1)
        concurrency = RunConcurrencyBudget(runs, allow_migration=True)
        concurrency.configure(run_id, owner, epoch, 1)
        evidence = HermesProcessEvidence(runs, allow_migration=True)
        HermesAnchorEvidence(runs, allow_migration=True)
        run = runs.read_run(run_id)
        with runs.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            concurrency.reserve_in_transaction(db, run_id, owner, epoch, "slot", "digest")
            ticket = evidence.record_start_in_transaction(db, run_id, "slot", "digest", owner, epoch, run["actor_id"], run["space_id"])
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        endpoint = "http://127.0.0.1:" + str(listener.getsockname()[1])
        config = EngineRunConfig(run_id, epoch, original.config.engine_commit, endpoint, 2)
        sink = EngineEventSink(runs, config, owner)
        capability, provider_capability = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        provider = ProviderGateway(RunBoundBudgetStore(sink, allow_migration=True), provider_capability, None, offline=True)
        transport = HermesRuntimeTransport(sink, results.scope, HermesBridge(business), actor_id=run["actor_id"], space_id=run["space_id"], capability=capability, max_tools=1, provider_gateway=provider)
        lifecycle = HermesExecutionLifecycle(transport, evidence)
        bootstrap = {"endpoint": endpoint, "capability": capability, "provider_capability": provider_capability, "run_id": run_id, "engine_commit": config.engine_commit}
        probe = Path(__file__).with_name("hermes_guarded_document_probe.py")
        result = await asyncio.wait_for(lifecycle.run_guarded(listener, ticket, [sys.executable, str(probe)], cwd=tmp_path, bootstrap=bootstrap, max_seconds=10, interval=0.02), 15)
        assert result.state == "INTERRUPTED" and result.descendants == "NOT_VERIFIED" and result.engine_exit == 0
        events = [event["type"] for event in runs.events(run_id, 0)]
        assert events.count("RUN_STARTED") == events.count("TOOL_STARTED") == events.count("TOOL_FINISHED") == 1
        assert events.index("RUN_STARTED") < events.index("TOOL_STARTED") < events.index("TOOL_FINISHED")
        with runs.connect() as db:
            assert db.execute("SELECT count(*) FROM agent_tool_reservations WHERE root_run_id=?", (run_id,)).fetchone() == (1,)
            assert db.execute("SELECT count(*) FROM objects WHERE kind='hermes_document_result'").fetchone() == (1,)
            assert db.execute("SELECT state FROM hermes_process_evidence WHERE run_id=?", (run_id,)).fetchone() == ("UNKNOWN",)
            assert db.execute("SELECT state FROM agent_concurrency_reservations WHERE run_id=?", (run_id,)).fetchone() == ("UNKNOWN",)
        assert transport.closed and provider.capability is None

    asyncio.run(exercise())


def test_independent_process_uses_bound_transport_and_reconnects(tmp_path):
    async def exercise():
        business = ControlStore(tmp_path / "business.sqlite")
        business.initialize("ui-check")
        sessions = MemorySessionManager(tmp_path / "workspace", business_store=business, sessions_root=tmp_path / "sessions")
        sessions.save(sessions.get_or_create("websocket:runtime-check"), fsync=True)
        scope = RunScopeService(business, sessions, "ui-check")
        proof = scope.prove("runtime-check", [])
        runs = RunStore(business.path)
        run_id = runs.create_run(proof.owner_id, proof.namespace, "runtime-request", "runtime-digest")
        with runs.connect() as db:
            db.execute("UPDATE agent_runs SET goal=?,conversation_id=?,selected_refs=?,scope_proof=? WHERE run_id=?", ("检查进程通信", proof.chat_id, "[]", json.dumps(asdict(proof)), run_id))
        lease = runs.acquire_lease(run_id, 0, "worker", 60)
        runs.transition(run_id, lease["revision"], "RUNNING", "worker", lease["epoch"])
        budget = RunToolBudget(runs, allow_migration=True)
        budget.configure(run_id, "worker", lease["epoch"], 1)
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        endpoint = "http://127.0.0.1:" + str(listener.getsockname()[1])
        config = EngineRunConfig(run_id, lease["epoch"], "903230b1e23e0c496b28e5d2e8c4f2639cd506b6", endpoint, 1)
        sink = EngineEventSink(runs, config, "worker")
        capability = secrets.token_urlsafe(32)
        with pytest.raises(ValueError, match="预算未配置或不匹配"):
            HermesRuntimeTransport(sink, scope, HermesBridge(business), actor_id=proof.owner_id, space_id=proof.namespace, capability=capability, max_tools=2)
        server = HermesRuntimeTransport(sink, scope, HermesBridge(business), actor_id=proof.owner_id, space_id=proof.namespace, capability=capability, max_tools=1)
        with pytest.raises(RuntimeError, match="通信检查中断"):
            async with server.serve(listener):
                probe = Path(__file__).with_name("hermes_runtime_transport_probe.py")
                process = await asyncio.create_subprocess_exec(sys.executable, str(probe), stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
                configuration = {"endpoint": endpoint, "capability": capability, "run_id": run_id, "engine_commit": config.engine_commit}
                try:
                    stdout, stderr = await asyncio.wait_for(process.communicate(json.dumps(configuration).encode()), 15)
                finally:
                    if process.returncode is None:
                        process.kill()
                        await process.wait()
                assert process.returncode == 0, stderr.decode()
                result = json.loads(stdout)
                assert result["request"]["goal"] == "检查进程通信" and result["pending"] is None
                assert result["event"] == result["repeated"]
                async with httpx.AsyncClient(trust_env=False) as client:
                    assert (await client.get(endpoint + "/internal/v1/request")).status_code == 401
                    runs.cancel(run_id, runs.read_run(run_id)["revision"])
                    rejected = await client.get(endpoint + "/internal/v1/request", headers={"Authorization": "Bearer " + capability})
                    assert rejected.status_code == 409
                raise RuntimeError("通信检查中断")
        async with httpx.AsyncClient(trust_env=False) as client:
            with pytest.raises(httpx.ConnectError):
                await client.get(endpoint + "/internal/v1/request")
        assert server.closed and server.transport.capability is None
        with pytest.raises(ValueError, match="已经关闭"):
            async with server.serve(listener):
                raise AssertionError("关闭后的服务不能重新启动")
        assert len([event for event in runs.events(run_id, 0) if event["type"] == "RUN_STARTED"]) == 1

    asyncio.run(exercise())


@pytest.mark.parametrize("cancel", [False, True])
def test_recorded_process_receives_capability_and_emits_event(tmp_path, cancel):
    async def exercise():
        business = ControlStore(tmp_path / "business.sqlite")
        business.initialize("ui-check")
        sessions = MemorySessionManager(tmp_path / "workspace", business_store=business, sessions_root=tmp_path / "sessions")
        sessions.save(sessions.get_or_create("websocket:process-check"), fsync=True)
        scope = RunScopeService(business, sessions, "ui-check")
        proof = scope.prove("process-check", [])
        runs = RunStore(business.path)
        run_id = runs.create_run(proof.owner_id, proof.namespace, "process-request", "process-digest")
        with runs.connect() as db:
            db.execute("UPDATE agent_runs SET goal=?,conversation_id=?,selected_refs=?,scope_proof=? WHERE run_id=?", ("检查受管进程通信", proof.chat_id, "[]", json.dumps(asdict(proof)), run_id))
        lease = runs.acquire_lease(run_id, 0, "worker", 60)
        runs.transition(run_id, lease["revision"], "RUNNING", "worker", lease["epoch"])
        tool_budget = RunToolBudget(runs, allow_migration=True)
        tool_budget.configure(run_id, "worker", lease["epoch"], 1)
        concurrency = RunConcurrencyBudget(runs, allow_migration=True)
        concurrency.configure(run_id, "worker", lease["epoch"], 1)
        evidence = HermesProcessEvidence(runs, allow_migration=True)
        with runs.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            concurrency.reserve_in_transaction(db, run_id, "worker", lease["epoch"], "slot", "digest")
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        endpoint = "http://127.0.0.1:" + str(listener.getsockname()[1])
        config = EngineRunConfig(run_id, lease["epoch"], "903230b1e23e0c496b28e5d2e8c4f2639cd506b6", endpoint, 1)
        sink = EngineEventSink(runs, config, "worker")
        capability = secrets.token_urlsafe(32)
        provider_capability = secrets.token_urlsafe(32)
        provider = ProviderGateway(RunBoundBudgetStore(sink, allow_migration=True), provider_capability, secrets.token_urlsafe(32))
        server = HermesRuntimeTransport(sink, scope, HermesBridge(business), actor_id=proof.owner_id, space_id=proof.namespace, capability=capability, max_tools=1, provider_gateway=provider)
        bootstrap = {"endpoint": endpoint, "capability": capability, "provider_capability": provider_capability, "run_id": run_id, "engine_commit": config.engine_commit}
        probe = Path(__file__).with_name("hermes_runtime_transport_probe.py")
        engine = Path(__file__).resolve().parents[2] / ".work/upgrade2/u2-03/clean-hermes"
        with RunLaunchTransaction(runs).hold(run_id, "worker", lease["epoch"]) as db:
            ticket = evidence.record_start_in_transaction(db, run_id, "slot", "digest", "worker", lease["epoch"], proof.owner_id, proof.namespace)
        async with server.serve_prepared(listener, evidence, ticket, [sys.executable, str(probe)], cwd=tmp_path, bootstrap=bootstrap, max_seconds=10) as supervisor:
            async with httpx.AsyncClient(trust_env=False) as client:
                response = await client.post(endpoint + "/chat/completions", headers={"Authorization": "Bearer " + capability}, json={})
                assert response.status_code == 401
                response = await client.post(endpoint + "/chat/completions", headers={"Authorization": "Bearer " + provider_capability}, json={})
                assert response.status_code == 400
                response = await client.get(endpoint + "/internal/v1/request", headers={"Authorization": "Bearer " + provider_capability})
                assert response.status_code == 401
            process = evidence.processes[(run_id, "slot")]
            assert capability not in " ".join(process.args)
            assert provider_capability not in " ".join(process.args)
            try:
                if cancel:
                    async def wait_event():
                        while not any(event["type"] == "RUN_STARTED" for event in runs.events(run_id, 0)):
                            await asyncio.sleep(0.01)
                    await asyncio.wait_for(wait_event(), 10)
                    runs.cancel(run_id, runs.read_run(run_id)["revision"])
                assert await asyncio.wait_for(server.supervise(supervisor, interval=0.02), 15) == ("RECONCILING" if cancel else "FAILED")
            finally:
                if process.poll() is None:
                    process.kill()
                    await asyncio.to_thread(process.wait, 10)
            result = evidence.observe_exit(run_id, "slot")
            assert result == {"state": "EXITED", "exit_code": -9 if cancel else 0, "exit_scope": "LEADER_ONLY"}
            assert len([event for event in runs.events(run_id, 0) if event["type"] == "RUN_STARTED"]) == 1
            assert provider.store.usage_report()["requests_used"] == 0
            async with httpx.AsyncClient(trust_env=False) as client:
                assert (await client.get(endpoint + "/internal/v1/request", headers={"Authorization": "Bearer " + capability})).status_code == 409
        assert provider.capability is None and provider.provider_key is None
        with runs.connect() as db:
            assert capability not in "\n".join(db.iterdump())
            assert provider_capability not in "\n".join(db.iterdump())
            assert db.execute("SELECT state FROM agent_concurrency_reservations WHERE run_id=?", (run_id,)).fetchone() == ("ACTIVE",)

    asyncio.run(exercise())


def test_prepared_service_exception_stops_child_and_revokes_capabilities(tmp_path):
    async def exercise():
        business = ControlStore(tmp_path / "business.sqlite")
        business.initialize("ui-check")
        sessions = MemorySessionManager(tmp_path / "workspace", business_store=business, sessions_root=tmp_path / "sessions")
        sessions.save(sessions.get_or_create("websocket:abort-check"), fsync=True)
        scope = RunScopeService(business, sessions, "ui-check")
        proof = scope.prove("abort-check", [])
        runs = RunStore(business.path)
        run_id = runs.create_run(proof.owner_id, proof.namespace, "abort-request", "abort-digest")
        lease = runs.acquire_lease(run_id, 0, "worker", 60)
        runs.transition(run_id, lease["revision"], "RUNNING", "worker", lease["epoch"])
        tools = RunToolBudget(runs, allow_migration=True)
        tools.configure(run_id, "worker", lease["epoch"], 1)
        concurrency = RunConcurrencyBudget(runs, allow_migration=True)
        concurrency.configure(run_id, "worker", lease["epoch"], 1)
        evidence = HermesProcessEvidence(runs, allow_migration=True)
        with runs.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            concurrency.reserve_in_transaction(db, run_id, "worker", lease["epoch"], "slot", "digest")
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        endpoint = "http://127.0.0.1:" + str(listener.getsockname()[1])
        config = EngineRunConfig(run_id, lease["epoch"], "903230b1e23e0c496b28e5d2e8c4f2639cd506b6", endpoint, 1)
        sink = EngineEventSink(runs, config, "worker")
        capability, provider_capability = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        provider = ProviderGateway(RunBoundBudgetStore(sink, allow_migration=True), provider_capability, secrets.token_urlsafe(32))
        server = HermesRuntimeTransport(sink, scope, HermesBridge(business), actor_id=proof.owner_id, space_id=proof.namespace, capability=capability, max_tools=1, provider_gateway=provider)
        bootstrap = {"endpoint": endpoint, "capability": capability, "provider_capability": provider_capability, "run_id": run_id, "engine_commit": config.engine_commit}
        probe = Path(__file__).with_name("hermes_lifecycle_probe.py")
        with RunLaunchTransaction(runs).hold(run_id, "worker", lease["epoch"]) as db:
            ticket = evidence.record_start_in_transaction(db, run_id, "slot", "digest", "worker", lease["epoch"], proof.owner_id, proof.namespace)
        with pytest.raises(RuntimeError, match="技术进程中断"):
            async with server.serve_prepared(listener, evidence, ticket, [sys.executable, str(probe), "child", "5"], cwd=tmp_path, bootstrap=bootstrap, max_seconds=10):
                raise RuntimeError("技术进程中断")
        assert evidence.observe_exit(run_id, "slot") == {"state": "EXITED", "exit_code": -9, "exit_scope": "LEADER_ONLY"}
        assert server.closed and server.transport.capability is None and provider.capability is None and provider.provider_key is None
        async with httpx.AsyncClient(trust_env=False) as client:
            with pytest.raises(httpx.ConnectError):
                await client.get(endpoint + "/internal/v1/request")
        with runs.connect() as db:
            assert db.execute("SELECT state FROM agent_concurrency_reservations WHERE run_id=?", (run_id,)).fetchone() == ("ACTIVE",)

    asyncio.run(exercise())


@pytest.mark.parametrize("action", ["complete", "cancel_run", "cancel_task", "launch_failure", "engine_entry", "engine_entry_extended", "engine_entry_no_goal", "engine_entry_requirements_missing", "guarded", "guarded_short_lease", "guarded_db_failure", "guarded_invalid_interval", "guarded_resource", "guarded_configured_no_goal", "guarded_sandbox_no_goal", "guarded_image_no_goal", "guarded_invalid_adapter"])
def test_execution_lifecycle_uses_recorded_process_and_cleans_up(tmp_path, action, caplog):
    if action == "guarded_image_no_goal":
        pytest.skip("历史实验适配边界冻结于 0.1.0，当前正式适配器为 0.1.21")
    image_resources = []
    async def exercise(stack):
        business = ControlStore(tmp_path / "business.sqlite")
        business.initialize("ui-check")
        sessions = MemorySessionManager(tmp_path / "workspace", business_store=business, sessions_root=tmp_path / "sessions")
        sessions.save(sessions.get_or_create("websocket:lifecycle-check"), fsync=True)
        scope = RunScopeService(business, sessions, "ui-check")
        proof = scope.prove("lifecycle-check", [])
        runs = RunStore(business.path)
        run_id = runs.create_run(proof.owner_id, proof.namespace, "lifecycle-request", "lifecycle-digest")
        with runs.connect() as db:
            db.execute("UPDATE agent_runs SET goal=?,conversation_id=?,selected_refs=?,scope_proof=? WHERE run_id=?", ("检查执行生命周期", proof.chat_id, "[]", json.dumps(asdict(proof)), run_id))
        lease = runs.acquire_lease(run_id, 0, "worker", 5 if action in {"guarded_short_lease", "guarded_db_failure"} else 180 if action in {"guarded_configured_no_goal", "guarded_sandbox_no_goal", "guarded_image_no_goal"} else 60)
        runs.transition(run_id, lease["revision"], "RUNNING", "worker", lease["epoch"])
        tools = RunToolBudget(runs, allow_migration=True)
        tools.configure(run_id, "worker", lease["epoch"], 1)
        concurrency = RunConcurrencyBudget(runs, allow_migration=True)
        concurrency.configure(run_id, "worker", lease["epoch"], 1)
        evidence = HermesProcessEvidence(runs, allow_migration=True)
        if action in {"guarded", "guarded_short_lease", "guarded_db_failure", "guarded_invalid_interval", "guarded_resource", "guarded_configured_no_goal", "guarded_sandbox_no_goal", "guarded_image_no_goal", "guarded_invalid_adapter"}:
            HermesAnchorEvidence(runs, allow_migration=True)
        with runs.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            concurrency.reserve_in_transaction(db, run_id, "worker", lease["epoch"], "slot", "digest")
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        endpoint = "http://127.0.0.1:" + str(listener.getsockname()[1])
        config = EngineRunConfig(run_id, lease["epoch"], "903230b1e23e0c496b28e5d2e8c4f2639cd506b6", endpoint, 1)
        sink = EngineEventSink(runs, config, "worker")
        capability, provider_capability = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        provider = ProviderGateway(RunBoundBudgetStore(sink, allow_migration=True), provider_capability, secrets.token_urlsafe(32), offline=action in {"guarded_sandbox_no_goal", "guarded_image_no_goal"})
        transport = HermesRuntimeTransport(sink, scope, HermesBridge(business), actor_id=proof.owner_id, space_id=proof.namespace, capability=capability, max_tools=1, provider_gateway=provider)
        lifecycle = HermesExecutionLifecycle(transport, evidence)
        bootstrap = {"endpoint": endpoint, "capability": capability, "provider_capability": provider_capability, "run_id": run_id, "engine_commit": config.engine_commit}
        if action == "launch_failure":
            websocket_config = WebSocketConfig()
            gateway = build_gateway_services(config=websocket_config, bus=MessageBus(), session_manager=sessions,
                static_dist_path=None, workspace_path=tmp_path, default_restrict_to_workspace=True,
                config_path=tmp_path / "config.json", runtime_model_name=None,
                runtime_surface="webui", runtime_capabilities_overrides=None)
            channel = RoleChannel(WebSocketChannel(websocket_config, MessageBus(), gateway=gateway), {}, tmp_path / "access.jsonl", business)
            product_listener = socket.socket()
            product_listener.bind(("127.0.0.1", 0))
            product_listener.listen()
            product_port = product_listener.getsockname()[1]
            app = hermes_product_application(channel, business, sessions, "ui-check", public_port=product_port, upstream_port=product_port + 1)
            services = app[SERVICES_KEY]
            process_config = EngineProcessConfig(config, *([tmp_path] * 7), 1, 1, 10, 1, 128, 1, 1024, 16, 1)
            async def execute(request):
                await services.execute(request, sink, {}, process_config, lifecycle, listener,
                                       plan_digest="digest", request_key="slot", request_digest="digest", bootstrap=bootstrap)
                return web.Response()
            app.router.add_get("/execution-check", execute)
            runner = web.AppRunner(app)
            await runner.setup()
            await web.SockSite(runner, product_listener).start()
            try:
                async with httpx.AsyncClient(trust_env=False) as client:
                    response = await client.get(f"http://127.0.0.1:{product_port}/execution-check")
                    assert response.status_code == 401
                with runs.connect() as db:
                    assert db.execute("SELECT count(*) FROM hermes_process_evidence").fetchone()[0] == 0
            finally:
                await runner.cleanup()
        with RunLaunchTransaction(runs).hold(run_id, "worker", lease["epoch"]) as db:
            ticket = evidence.record_start_in_transaction(db, run_id, "slot", "digest", "worker", lease["epoch"], proof.owner_id, proof.namespace)
        probe = Path(__file__).with_name("hermes_runtime_transport_probe.py")
        engine = Path(__file__).resolve().parents[2] / ".work/upgrade2/u2-03/clean-hermes"
        command = [sys.executable, str(probe)]
        if action == "guarded_resource":
            process_config = EngineProcessConfig(config, tmp_path, tmp_path, tmp_path, Path(sys.executable), tmp_path,
                                                 tmp_path, tmp_path, 1, 1, 10, 1, 128, 1, 512, 32, 5)
            command = HermesProcessManager(sink, process_config)._resource_command([
                str(Path(__file__).with_name("hermes_resource_probe.py")), "file", str(tmp_path / "limited.bin")])
        if action == "launch_failure":
            command = [str(tmp_path / "missing-executable")]
        if action in {"engine_entry", "engine_entry_extended", "engine_entry_no_goal", "engine_entry_requirements_missing"}:
            root = Path(__file__).resolve().parents[2]
            entry_seconds = 120 if action == "engine_entry_extended" else 45
            command = [str(root / ".work/upgrade2/u2-01/hermes/.venv/bin/python"),
                       str(root / "validation/hermes_engine_entry.py"), str(engine),
                       "--max-rounds", "1", "--max-seconds", str(entry_seconds)]
            if action in {"engine_entry", "engine_entry_extended"}:
                RunRequirements(runs, allow_migration=True)
                with runs.connect() as db:
                    db.execute("BEGIN IMMEDIATE")
                    RunRequirements.save_in_transaction(db, run_id, 1, "technical-requirements", ["TEXT"])
        if action in {"engine_entry_no_goal", "guarded_configured_no_goal", "guarded_sandbox_no_goal", "guarded_image_no_goal"}:
            with runs.connect() as db:
                db.execute("UPDATE agent_runs SET goal='' WHERE run_id=?", (run_id,))
        if action == "guarded_db_failure":
            with runs.connect() as db:
                db.execute("CREATE TRIGGER reject_process_update BEFORE UPDATE ON hermes_process_evidence BEGIN SELECT RAISE(ABORT, 'process update denied'); END")
        run = lifecycle.run_guarded if action in {"guarded", "guarded_short_lease", "guarded_db_failure", "guarded_invalid_interval", "guarded_resource"} else lifecycle.run
        if action == "guarded_invalid_interval":
            for interval in (0, -1, float("nan"), float("inf"), True):
                with pytest.raises(ValueError, match="进程检查间隔无效"):
                    await run(listener, ticket, command, cwd=tmp_path, bootstrap=bootstrap, max_seconds=10, interval=interval)
            assert evidence.prepared_identity(ticket) == (run_id, "slot")
            with runs.connect() as db:
                assert db.execute("SELECT count(*) FROM hermes_anchor_evidence").fetchone() == (0,)
                assert db.execute("SELECT state FROM hermes_process_evidence WHERE run_id=?", (run_id,)).fetchone() == ("STARTING",)
            assert not transport.started
            listener.close()
            provider.close()
            return
        if action == "guarded_invalid_adapter":
            root = Path(__file__).resolve().parents[2]
            wheel = root / ".work/upgrade2/u2-03/bi-adapter-008/boss_agent_hermes_adapter-0.1.9-py3-none-any.whl"
            installed = root / ".work/upgrade2/u2-03/bi-adapter-installed-008"
            process_config = EngineProcessConfig(config, *([tmp_path] * 7), 1, 1, 10, 1, 128, 1, 1024, 16, 1)
            with pytest.raises(ValueError, match="实验隔离需要适配来源与离线网关"):
                await lifecycle.run_guarded_configured(listener, ticket, process_config, bootstrap=bootstrap,
                    experimental_adapter={"source_root": root, "wheel_path": wheel, "installed_directory": installed},
                    experimental_sandbox={"profile_text": "test", "profile_sha256": hashlib.sha256(b"test").hexdigest()})
            with pytest.raises(IsolationBoundaryUnavailable):
                await lifecycle.run_guarded_configured(listener, ticket, process_config, bootstrap=bootstrap,
                    experimental_adapter={"source_root": tmp_path, "wheel_path": wheel, "installed_directory": installed})
            assert evidence.prepared_identity(ticket) == (run_id, "slot")
            assert not transport.started
            listener.close()
            provider.close()
            return
        if action in {"guarded_configured_no_goal", "guarded_sandbox_no_goal", "guarded_image_no_goal"}:
            caplog.set_level(logging.INFO, logger="aiohttp.access")
            root = Path(__file__).resolve().parents[2]
            audit = root / ".work/upgrade2/u2-03/dependency-audit-001"
            executable = audit / "environment/bin/python"
            if action == "guarded_image_no_goal":
                image = ExperimentalWorkspaceImage(32, run_id=run_id)
                image_resources.append(image)
                workspace = stack.enter_context(image)
                workspace_root = image.directory
            else:
                workspace = tmp_path / (run_id if action == "guarded_sandbox_no_goal" else "guarded-workspace")
                workspace.mkdir()
                workspace_root = tmp_path
            process_config = EngineProcessConfig(config, audit / "source", root / ".work/upgrade2/u2-01/hermes.tar.gz",
                                                 executable.resolve().parent, executable, workspace_root, workspace,
                                                 root / "app/tests/hermes_no_spawn.sb", 1, 1, 120, 1, 128,
                                                 1, 8388608, 128, 120)
            options = {}
            if action == "guarded_configured_no_goal":
                with pytest.raises(IsolationBoundaryUnavailable):
                    await lifecycle.run_guarded_configured(listener, ticket, process_config, bootstrap=bootstrap)
                with pytest.raises(IsolationBoundaryUnavailable):
                    HermesProcessManager(sink, process_config).bind_isolation_command([str(executable)])
                assert evidence.prepared_identity(ticket) == (run_id, "slot") and not transport.started
                with runs.connect() as db:
                    assert db.execute("SELECT count(*) FROM hermes_anchor_evidence WHERE run_id=?", (run_id,)).fetchone() == (0,)
                listener.close()
                provider.close()
                return
            if action in {"guarded_sandbox_no_goal", "guarded_image_no_goal"}:
                profile = (root / "app/tests/hermes_isolation_adapter_candidate.sb").read_text(encoding="utf-8")
                options = {"experimental_adapter": {"source_root": root,
                           "wheel_path": root / ".work/upgrade2/u2-03/bi-adapter-008/boss_agent_hermes_adapter-0.1.9-py3-none-any.whl",
                           "installed_directory": root / ".work/upgrade2/u2-03/bi-adapter-installed-008"},
                           "experimental_sandbox": {"profile_text": profile, "profile_sha256": hashlib.sha256(profile.encode()).hexdigest()}}
                if action == "guarded_sandbox_no_goal":
                    with pytest.raises(ValueError, match="独立磁盘容量"):
                        await lifecycle.run_guarded_configured(listener, ticket, process_config, bootstrap=bootstrap, **options)
                    assert evidence.prepared_identity(ticket) == (run_id, "slot") and not transport.started
                    listener.close()
                    provider.close()
                    return
                options["experimental_workspace"] = {"image": image, "disk_limit_bytes": 32 * 1024 * 1024}
                other_run = runs.create_run(proof.owner_id, proof.namespace, "other-image-run", "other-image-digest")
                with pytest.raises(ValueError, match="工作区不匹配"):
                    image.require_capacity(other_run, workspace, 32 * 1024 * 1024)
                with pytest.raises(ValueError, match="超过磁盘容量上限"):
                    await lifecycle.run_guarded_configured(listener, ticket, process_config, bootstrap=bootstrap,
                        experimental_adapter=options["experimental_adapter"], experimental_sandbox=options["experimental_sandbox"],
                        experimental_workspace={"image": image, "disk_limit_bytes": 16 * 1024 * 1024})
                assert evidence.prepared_identity(ticket) == (run_id, "slot") and not transport.started
                loose = "(version 1)\n(allow default)\n"
                with pytest.raises(ValueError, match="受控范围"):
                    await lifecycle.run_guarded_configured(listener, ticket, process_config, bootstrap=bootstrap,
                        experimental_adapter=options["experimental_adapter"], experimental_sandbox={"profile_text": loose,
                        "profile_sha256": hashlib.sha256(loose.encode()).hexdigest()}, experimental_workspace=options["experimental_workspace"])
                assert evidence.prepared_identity(ticket) == (run_id, "slot")
                assert not transport.started
            task = asyncio.create_task(lifecycle.run_guarded_configured(listener, ticket, process_config,
                                                                         bootstrap=bootstrap, interval=0.02, **options))
        elif action == "guarded_resource":
            task = asyncio.create_task(run(listener, ticket, command, cwd=tmp_path, bootstrap=bootstrap, max_seconds=10,
                                           interval=0.02, limits={"file_bytes": 512, "open_files": 32, "cpu_seconds": 5}))
        else:
            task = asyncio.create_task(run(listener, ticket, command, cwd=tmp_path, bootstrap=bootstrap, max_seconds=entry_seconds if action.startswith("engine_entry") else 10, interval=0.02))
        if action in {"cancel_run", "cancel_task"}:
            async def wait_event():
                while not any(event["type"] == "RUN_STARTED" for event in runs.events(run_id, 0)):
                    if task.done():
                        await task
                        raise ValueError("进程未产生启动事件")
                    await asyncio.sleep(0.01)
            await asyncio.wait_for(wait_event(), 10)
            if action == "cancel_run":
                runs.cancel(run_id, runs.read_run(run_id)["revision"])
            else:
                task.cancel()
        if action == "launch_failure":
            with pytest.raises(FileNotFoundError):
                await task
            assert evidence.read(run_id, "slot")["state"] == "UNKNOWN"
        elif action == "cancel_task":
            with pytest.raises(asyncio.CancelledError):
                await task
            assert evidence.read(run_id, "slot")["exit_scope"] == "LEADER_ONLY"
        elif action == "guarded_db_failure":
            with pytest.raises(sqlite3.IntegrityError, match="process update denied") as failure:
                await task
            assert isinstance(failure.value.__context__, ValueError)
            assert "租约剩余时间不足" in str(failure.value.__context__)
            assert evidence.read(run_id, "slot")["state"] == "STARTING"
            with pytest.raises(ValueError):
                runs.acquire_lease(run_id, runs.read_run(run_id)["revision"], "next-worker", 60)
        elif action == "guarded_short_lease":
            with pytest.raises(ValueError, match="租约剩余时间不足"):
                await task
            assert evidence.read(run_id, "slot")["state"] == "UNKNOWN"
            assert runs.read_run(run_id)["status"] == "INTERRUPTED"
        elif action in {"guarded_configured_no_goal", "guarded_sandbox_no_goal", "guarded_image_no_goal"}:
            result = await asyncio.wait_for(task, 180)
            assert result.state == "INTERRUPTED" and result.engine_exit == 1 and result.descendants == "NOT_VERIFIED"
            assert any("GET /internal/v1/input-context " in record.getMessage() and " 409 " in record.getMessage() for record in caplog.records)
            assert evidence.read(run_id, "slot")["state"] == "UNKNOWN"
            assert not any(event["type"] == "RUN_STARTED" for event in runs.events(run_id, 0))
            if action == "guarded_image_no_goal":
                with runs.connect() as db:
                    bound = db.execute("SELECT anchor_pid,engine_pid,lease_epoch FROM hermes_anchor_evidence WHERE run_id=? AND request_key=?", (run_id, "slot")).fetchone()
                    assert bound is not None and bound[0] > 0 and bound[1] > 0 and bound[2] == lease["epoch"]
                command = [str(executable), "-c", "import sys; f=open(sys.argv[1],'wb',buffering=0); sum(f.write(b'x'*1048576) for _ in range(40))", str(workspace / "capacity-check.bin")]
                command = experimental_sandbox_command(command, process_config, options["experimental_adapter"]["installed_directory"], **options["experimental_sandbox"])
                env = {"PATH": "/usr/bin:/bin", "HOME": str(workspace), "TMPDIR": str(workspace), "PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1"}
                anchor = AnchorProcessGroup.start(command, cwd=workspace, env=env, deferred=True, guarded=True)
                try:
                    anchor.release_engine()
                    assert anchor.read_engine_exit(timeout=30) == 1
                finally:
                    if anchor.process.poll() is None:
                        anchor.reclaim()
                    anchor.close_control()
                capacity = os.statvfs(workspace)
                assert 0 < (workspace / "capacity-check.bin").stat().st_size < 32 * 1024 * 1024
                assert capacity.f_bavail * capacity.f_frsize < 1024 * 1024
        elif action == "guarded_resource":
            result = await asyncio.wait_for(task, 15)
            assert result.state == "INTERRUPTED" and result.engine_exit != 0 and result.engine_exit is not None and result.descendants == "NOT_VERIFIED"
            assert (tmp_path / "limited.bin").stat().st_size <= 512
            assert evidence.read(run_id, "slot")["state"] == "UNKNOWN"
        elif action == "guarded":
            result = await asyncio.wait_for(task, 15)
            assert result.state == "INTERRUPTED" and result.engine_exit == 0 and result.descendants == "NOT_VERIFIED"
            assert evidence.read(run_id, "slot")["state"] == "UNKNOWN"
            assert any(event["type"] == "RUN_STARTED" for event in runs.events(run_id, 0))
            assert any(event["type"] == "USAGE_RECORDED" for event in runs.events(run_id, 0))
        else:
            expected_state = "RECONCILING" if action == "cancel_run" else "WAITING_INPUT" if action == "engine_entry_requirements_missing" else "FAILED"
            wait_seconds = 150 if action == "engine_entry_extended" else 55 if action.startswith("engine_entry") else 15
            assert await asyncio.wait_for(task, wait_seconds) == expected_state
            assert evidence.read(run_id, "slot")["exit_scope"] == "LEADER_ONLY"
            if action in {"engine_entry", "engine_entry_extended"}:
                events = runs.events(run_id, 0)
                started = next(event for event in events if event["type"] == "RUN_STARTED")
                failed = next(event for event in events if event["type"] == "RUN_FAILED")
                assert [event for event in events if event["type"] == "RUN_FAILED"] == [failed]
                assert set(started["payload"]) == {"engine_commit"}
                assert set(failed["payload"]) == {"error_code"} and failed["payload"]["error_code"] == "ENGINE_ENTRY_UNAVAILABLE"
                assert started["seq"] < failed["seq"]
                usage = [event for event in events if event["type"] == "USAGE_RECORDED"]
                assert len(usage) == 1
                assert usage[0]["payload"]["requests_used"] == 0
                assert usage[0]["payload"]["known_requests"] == 0
                assert usage[0]["payload"]["total_tokens"] == 0
                assert usage[0]["payload"]["cost_state"] == "UNKNOWN"
                terminal = next(event for event in events if event["type"] == "STATUS_CHANGED" and event["payload"].get("to") == "FAILED")
                assert failed["seq"] < usage[0]["seq"] < terminal["seq"]
                with runs.connect() as db:
                    assert db.execute("SELECT origin_event_id FROM agent_run_events WHERE type='USAGE_RECORDED' AND run_id=?", (run_id,)).fetchone() == ("usage-recorded:" + run_id + ":" + str(lease["epoch"]),)
                assert runs.read_run(run_id)["status"] == "FAILED"
                after = [event for event in events if event["seq"] > failed["seq"]]
                assert not any(event["type"] == "STATUS_CHANGED" and event["payload"].get("to") != "FAILED" for event in after)
                assert not any(event["type"] in {"RESULT_RECORDED", "RUN_FINISHED"} for event in events)
            if action == "engine_entry_no_goal":
                assert not any(event["type"] == "RUN_STARTED" for event in runs.events(run_id, 0))
            if action == "engine_entry_requirements_missing":
                events = runs.events(run_id, 0)
                started = next(event for event in events if event["type"] == "RUN_STARTED")
                waiting = next(event for event in events if event["type"] == "STATUS_CHANGED" and event["payload"].get("reason") == "OUTPUT_REQUIREMENTS_UNCONFIRMED")
                assert set(started["payload"]) == {"engine_commit"}
                assert started["seq"] < waiting["seq"]
                assert runs.read_run(run_id)["status"] == "WAITING_INPUT"
                assert not any(event["type"] == "RUN_FAILED" for event in events)
                assert not any(event["type"] in {"RESULT_RECORDED", "RUN_FINISHED"} for event in events)
                added = runs.add_input(run_id, 1, "technical-input", "补充成果要求")
                assert added["goal_revision"] == 2
                assert runs.read_run(run_id)["status"] == "WAITING_INPUT"
        assert transport.closed and transport.transport.capability is None
        assert provider.capability is None and provider.provider_key is None
        async with httpx.AsyncClient(trust_env=False) as client:
            with pytest.raises(httpx.ConnectError):
                await client.get(endpoint + "/internal/v1/request")
        with runs.connect() as db:
            assert db.execute("SELECT state FROM agent_concurrency_reservations WHERE run_id=?", (run_id,)).fetchone() == (("UNKNOWN",) if action in {"guarded", "guarded_short_lease", "guarded_resource", "guarded_configured_no_goal", "guarded_sandbox_no_goal", "guarded_image_no_goal"} else ("ACTIVE",))
        assert provider.store.usage_report()["requests_used"] == 0

    try:
        with ExitStack() as stack:
            asyncio.run(exercise(stack))
    finally:
        for image in image_resources:
            if image._attached_device() is None and not os.path.ismount(image.mount):
                if image.image.exists():
                    image.image.unlink()
                image.mount.rmdir()
                image.directory.rmdir()
