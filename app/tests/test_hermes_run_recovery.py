import asyncio
import sys
import time
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import pytest
import httpx
from aiohttp import web
from nanobot.bus.queue import MessageBus
from nanobot.channels.websocket.runtime import WebSocketChannel, WebSocketConfig
from nanobot.webui.gateway_services import build_gateway_services

from agent_run_concurrency import RunConcurrencyBudget
from agent_run_store import RunStore, utc_now
from boss_memory_sessions import MemorySessionManager
from controls import ControlStore
from hermes_bridge import EngineEventSink, EngineProcessSupervisor, EngineRunConfig
from hermes_process_evidence import HermesProcessEvidence
from hermes_product import SERVICES_KEY, hermes_product_application
from hermes_run_authority import HermesRunAuthority
from hermes_vm_identity import HermesVMRunAccess, HermesVMRunBindings
from role_channel import RoleChannel


def product_services(tmp_path):
    business = ControlStore(tmp_path / "business.sqlite")
    business.initialize("ui-check")
    runs = RunStore(business.path)
    sessions = MemorySessionManager(tmp_path / "workspace", business_store=business, sessions_root=tmp_path / "sessions")
    config = WebSocketConfig()
    gateway = build_gateway_services(config=config, bus=MessageBus(), session_manager=sessions,
        static_dist_path=None, workspace_path=tmp_path, default_restrict_to_workspace=True,
        config_path=tmp_path / "config.json", runtime_model_name=None,
        runtime_surface="webui", runtime_capabilities_overrides=None)
    channel = RoleChannel(WebSocketChannel(config, MessageBus(), gateway=gateway), {}, tmp_path / "access.jsonl", business)
    app = hermes_product_application(channel, business, sessions, "ui-check", public_port=1234, upstream_port=1235)
    return runs, app[SERVICES_KEY]


def test_canceled_run_stops_even_when_owner_session_is_unavailable(tmp_path):
    async def exercise():
        runs, services = product_services(tmp_path)
        run_id = runs.create_run("technical-actor", "ui-check", "cancel-recovery", "digest")
        lease = runs.acquire_lease(run_id, 0, "worker", 60)
        runs.transition(run_id, lease["revision"], "RUNNING", "worker", lease["epoch"])
        budget = RunConcurrencyBudget(runs, allow_migration=True)
        evidence = HermesProcessEvidence(runs, allow_migration=True)
        budget.configure(run_id, "worker", lease["epoch"], 1)
        with runs.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            budget.reserve_in_transaction(db, run_id, "worker", lease["epoch"], "cancel-slot", "cancel-digest")
        config = EngineRunConfig(run_id, lease["epoch"], "903230b1e23e0c496b28e5d2e8c4f2639cd506b6", "http://127.0.0.1:1234", 1)
        sink = EngineEventSink(runs, config, "worker")

        async def cancel_check(request):
            authority = HermesRunAuthority(services, request, sink, "technical-digest", {})
            probe = Path(__file__).with_name("hermes_lifecycle_probe.py").resolve()
            evidence.start(run_id, "cancel-slot", "cancel-digest", "worker", lease["epoch"], "technical-actor", "ui-check",
                           [sys.executable, str(probe), "child", "30"], cwd=tmp_path)
            process = evidence.processes[(run_id, "cancel-slot")]
            try:
                runs.cancel(run_id, runs.read_run(run_id)["revision"])
                supervisor = EngineProcessSupervisor(sink, process, process_group=True, authority=authority,
                                                     process_evidence=evidence, request_key="cancel-slot")
                assert supervisor.step() == "CANCEL_SIGNAL_SENT"
                assert process.wait(timeout=10) == -9
                assert supervisor.observe_exit() == "RECONCILING"
                assert evidence.read(run_id, "cancel-slot")["exit_scope"] == "LEADER_ONLY"
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=10)
            return web.Response()

        app = web.Application()
        app.router.add_get("/cancel-check", cancel_check)
        runner = web.AppRunner(app)
        await runner.setup()
        await web.TCPSite(runner, "127.0.0.1", 0).start()
        try:
            async with httpx.AsyncClient(trust_env=False) as client:
                response = await client.get("http://127.0.0.1:" + str(runner.addresses[0][1]) + "/cancel-check")
                assert response.status_code == 200
            assert runs.read_run(run_id)["status"] == "RECONCILING"
            with runs.connect() as db:
                assert db.execute("SELECT state FROM agent_concurrency_reservations WHERE run_id=?", (run_id,)).fetchone() == ("ACTIVE",)
        finally:
            await runner.cleanup()

    asyncio.run(exercise())


def test_product_recovery_records_interruption_and_retains_slot(tmp_path):
    runs, services = product_services(tmp_path)
    budget = RunConcurrencyBudget(runs, allow_migration=True)
    evidence = HermesProcessEvidence(runs, allow_migration=True)
    run_id = runs.create_run("boss-1", "ui-check", "recovery", "digest")
    lease = runs.acquire_lease(run_id, 0, "worker", 1.5)
    runs.transition(run_id, lease["revision"], "RUNNING", "worker", lease["epoch"])
    budget.configure(run_id, "worker", lease["epoch"], 1)
    with runs.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        budget.reserve_in_transaction(db, run_id, "worker", lease["epoch"], "slot", "slot-digest")
    probe = Path(__file__).with_name("hermes_lifecycle_probe.py").resolve()
    evidence.start(run_id, "slot", "slot-digest", "worker", lease["epoch"], "boss-1", "ui-check", [sys.executable, str(probe), "child", "5"], cwd=probe.parent)
    process = evidence.processes[(run_id, "slot")]
    try:
        with pytest.raises(ValueError, match="运行身份不可核查"):
            services.recovery.recover_expired(run_id, "other", "ui-check")
        with pytest.raises(ValueError, match="原租约仍然有效"):
            services.recovery.recover_expired(run_id, "boss-1", "ui-check")
        time.sleep(1.6)
        receipt = services.recovery.recover_expired(run_id, "boss-1", "ui-check")
        assert receipt == {"run_id": run_id, "status": "INTERRUPTED", "unknown_reservations": 1}
        assert services.recovery.recover_expired(run_id, "boss-1", "ui-check") == receipt
        assert evidence.read(run_id, "slot")["state"] == "UNKNOWN"
        with runs.connect() as db:
            assert db.execute("SELECT state FROM agent_concurrency_reservations WHERE run_id=?", (run_id,)).fetchone() == ("UNKNOWN",)
        events = runs.events(run_id, 0)
        assert len([event for event in events if event["type"] == "STATUS_CHANGED" and event["payload"]["to"] == "INTERRUPTED"]) == 1
    finally:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=10)
    assert evidence.observe_exit(run_id, "slot")["exit_scope"] == "LEADER_ONLY"
    with runs.connect() as db:
        assert db.execute("SELECT state FROM agent_concurrency_reservations WHERE run_id=?", (run_id,)).fetchone() == ("UNKNOWN",)


def test_product_recovery_keeps_vm_binding_and_unknown_reservation(tmp_path):
    runs, services = product_services(tmp_path)
    budget = RunConcurrencyBudget(runs, allow_migration=True)
    evidence = HermesProcessEvidence(runs, allow_migration=True)
    bindings = HermesVMRunBindings(runs, allow_migration=True)
    run_id = runs.create_run("boss-1", "ui-check", "vm-recovery", "digest")
    lease = runs.acquire_lease(run_id, 0, "worker", 60)
    runs.transition(run_id, lease["revision"], "RUNNING", "worker", lease["epoch"])
    budget.configure(run_id, "worker", lease["epoch"], 1)
    workspace = tmp_path / run_id
    workspace.mkdir()
    vm_id, boot_id = str(uuid4()), str(uuid4())
    with runs.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        budget.reserve_in_transaction(db, run_id, "worker", lease["epoch"], "slot", "slot-digest")
        unit = evidence.record_vm_start_in_transaction(db, bindings, run_id, "slot", "slot-digest", "worker", lease["epoch"],
                                                       "boss-1", "ui-check", vm_id, boot_id, workspace)
        db.execute("UPDATE agent_runs SET lease_expires_at=? WHERE run_id=?", ((utc_now() - timedelta(seconds=1)).isoformat(), run_id))
    receipt = services.recovery.recover_expired(run_id, "boss-1", "ui-check")
    assert receipt == {"run_id": run_id, "status": "INTERRUPTED", "unknown_reservations": 1}
    assert services.recovery.recover_expired(run_id, "boss-1", "ui-check") == receipt
    with runs.connect() as db:
        assert db.execute("SELECT state FROM agent_concurrency_reservations WHERE run_id=?", (run_id,)).fetchone() == ("UNKNOWN",)
        assert db.execute("SELECT state FROM hermes_process_evidence WHERE run_id=?", (run_id,)).fetchone() == ("UNKNOWN",)
        assert db.execute("SELECT vm_id,boot_id,unit_name FROM hermes_vm_run_bindings WHERE run_id=?", (run_id,)).fetchone() == (vm_id, boot_id, unit)
        db.execute("BEGIN IMMEDIATE")
        with pytest.raises(ValueError):
            evidence.record_vm_start_in_transaction(db, bindings, run_id, "slot", "slot-digest", "worker", lease["epoch"],
                                                    "boss-1", "ui-check", vm_id, boot_id, workspace)


def test_interrupted_run_releases_expired_lease_during_recovery(tmp_path):
    runs, services = product_services(tmp_path)
    RunConcurrencyBudget(runs, allow_migration=True)
    HermesProcessEvidence(runs, allow_migration=True)
    run_id = runs.create_run("boss-1", "ui-check", "interrupted-recovery", "digest")
    lease = runs.acquire_lease(run_id, 0, "worker", 60)
    runs.transition(run_id, lease["revision"], "RUNNING", "worker", lease["epoch"])
    runs.transition(run_id, runs.read_run(run_id)["revision"], "INTERRUPTED", "worker", lease["epoch"])
    with pytest.raises(ValueError, match="原租约仍然有效"):
        services.recovery.recover_expired(run_id, "boss-1", "ui-check")
    with runs.connect() as db:
        db.execute("UPDATE agent_runs SET lease_expires_at=? WHERE run_id=?", ((utc_now() - timedelta(seconds=1)).isoformat(), run_id))
    receipt = services.recovery.recover_expired(run_id, "boss-1", "ui-check")
    assert services.recovery.recover_expired(run_id, "boss-1", "ui-check") == receipt
    with runs.connect() as db:
        assert db.execute("SELECT status,lease_owner,lease_expires_at FROM agent_runs WHERE run_id=?", (run_id,)).fetchone() == ("INTERRUPTED", None, None)


def test_product_authority_binds_vm_without_bypassing_session(tmp_path):
    async def exercise():
        runs, services = product_services(tmp_path)
        budget = RunConcurrencyBudget(runs, allow_migration=True)
        evidence = HermesProcessEvidence(runs, allow_migration=True)
        bindings = HermesVMRunBindings(runs, allow_migration=True)
        run_id = runs.create_run("boss-1", "ui-check", "vm-authority", "digest")
        lease = runs.acquire_lease(run_id, 0, "worker", 60)
        runs.transition(run_id, lease["revision"], "RUNNING", "worker", lease["epoch"])
        budget.configure(run_id, "worker", lease["epoch"], 1)
        workspace = tmp_path / run_id
        workspace.mkdir()
        vm_id, boot_id = str(uuid4()), str(uuid4())
        with runs.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            budget.reserve_in_transaction(db, run_id, "worker", lease["epoch"], "slot", "slot-digest")
            evidence.record_vm_start_in_transaction(db, bindings, run_id, "slot", "slot-digest", "worker", lease["epoch"],
                                                    "boss-1", "ui-check", vm_id, boot_id, workspace)
        access = HermesVMRunAccess(bindings, run_id, "slot", "worker", lease["epoch"], vm_id, boot_id, workspace)
        invalid = HermesVMRunAccess(bindings, run_id, "slot", "worker", lease["epoch"], vm_id, str(uuid4()), workspace)
        config = EngineRunConfig(run_id, lease["epoch"], "903230b1e23e0c496b28e5d2e8c4f2639cd506b6", "http://127.0.0.1:1234", 1)
        sink = EngineEventSink(runs, config, "worker")

        async def bind(request):
            authority = HermesRunAuthority(services, request, sink, "digest", {})
            with pytest.raises(ValueError, match="绑定不可核查"):
                authority.bind_vm_access(invalid)
            authority.bind_vm_access(access)
            with pytest.raises(web.HTTPUnauthorized):
                authority.require()
            return web.Response()

        app = web.Application()
        app.router.add_get("/", bind)
        runner = web.AppRunner(app)
        await runner.setup()
        await web.TCPSite(runner, "127.0.0.1", 0).start()
        try:
            async with httpx.AsyncClient(trust_env=False) as client:
                response = await client.get("http://127.0.0.1:" + str(runner.addresses[0][1]) + "/")
                assert response.status_code == 200
        finally:
            await runner.cleanup()

    asyncio.run(exercise())


def test_supervisor_exit_records_failure_event(tmp_path):
    runs, services = product_services(tmp_path)
    budget = RunConcurrencyBudget(runs, allow_migration=True)
    evidence = HermesProcessEvidence(runs, allow_migration=True)
    run_id = runs.create_run("boss-1", "ui-check", "exit", "digest")
    lease = runs.acquire_lease(run_id, 0, "worker", 60)
    runs.transition(run_id, lease["revision"], "RUNNING", "worker", lease["epoch"])
    budget.configure(run_id, "worker", lease["epoch"], 1)
    with runs.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        budget.reserve_in_transaction(db, run_id, "worker", lease["epoch"], "slot", "slot-digest")
    probe = Path(__file__).with_name("hermes_lifecycle_probe.py").resolve()
    evidence.start(run_id, "slot", "slot-digest", "worker", lease["epoch"], "boss-1", "ui-check", [sys.executable, str(probe), "child", "0.2"], cwd=probe.parent)
    process = evidence.processes[(run_id, "slot")]
    config = EngineRunConfig(run_id, lease["epoch"], "903230b1e23e0c496b28e5d2e8c4f2639cd506b6", "http://127.0.0.1:1234", 1)
    sink = EngineEventSink(services.store, config, "worker")
    supervisor = EngineProcessSupervisor(sink, process, process_group=True, process_evidence=evidence, request_key="slot")
    process.wait(timeout=10)
    assert supervisor.observe_exit() == "FAILED"
    assert evidence.read(run_id, "slot")["exit_scope"] == "LEADER_ONLY"
    events = runs.events(run_id, 0)
    assert any(event["type"] == "RUN_FAILED" and event["payload"]["error_code"] == "ENGINE_GROUP_UNVERIFIED" for event in events)


def test_leader_exit_does_not_release_recovered_slot(tmp_path):
    runs, services = product_services(tmp_path)
    budget = RunConcurrencyBudget(runs, allow_migration=True)
    evidence = HermesProcessEvidence(runs, allow_migration=True)
    run_id = runs.create_run("boss-1", "ui-check", "leader-exit", "digest")
    lease = runs.acquire_lease(run_id, 0, "worker", 1.5)
    runs.transition(run_id, lease["revision"], "RUNNING", "worker", lease["epoch"])
    budget.configure(run_id, "worker", lease["epoch"], 1)
    with runs.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        budget.reserve_in_transaction(db, run_id, "worker", lease["epoch"], "slot", "slot-digest")
    probe = Path(__file__).with_name("hermes_lifecycle_probe.py").resolve()
    evidence.start(run_id, "slot", "slot-digest", "worker", lease["epoch"], "boss-1", "ui-check", [sys.executable, str(probe), "child", "0.2"], cwd=probe.parent)
    evidence.processes[(run_id, "slot")].wait(timeout=10)
    assert evidence.observe_exit(run_id, "slot")["exit_scope"] == "LEADER_ONLY"
    time.sleep(1.5)
    assert services.recovery.recover_expired(run_id, "boss-1", "ui-check")["unknown_reservations"] == 1
    assert evidence.read(run_id, "slot")["state"] == "EXITED"
    with runs.connect() as db:
        assert db.execute("SELECT state FROM agent_concurrency_reservations WHERE run_id=?", (run_id,)).fetchone() == ("UNKNOWN",)
