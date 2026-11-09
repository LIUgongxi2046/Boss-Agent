import asyncio
import json
import multiprocessing
import os
import socket
import sqlite3
import sys
import time
from dataclasses import asdict, replace
from datetime import datetime
from pathlib import Path

import httpx
import pytest
from aiohttp import web
from nanobot.bus.queue import MessageBus
from nanobot.channels.websocket.runtime import WebSocketChannel, WebSocketConfig
from nanobot.webui.gateway_services import build_gateway_services

from agent_run_dispatcher import AgentRunDispatcher
from agent_artifact_workspace import ArtifactWorkspace
from agent_chat_budget import AgentChatBudget
from agent_run_concurrency import RunConcurrencyBudget
from agent_simulation_migration_install import install_simulation_migrations
from agent_run_store import RunStore, utc_now
from boss_memory_sessions import MemorySessionManager
from controls import ControlStore
from hermes_bridge import EngineProcessConfig, EngineRunConfig
from hermes_product import SERVICES_KEY, hermes_product_application
from hermes_schedule_adapter import HermesScheduleAdapter
from hermes_process_evidence import HermesProcessEvidence
from hermes_runtime_transport import GuardedExecutionResult
from hermes_runtime_binding import ArtifactWorkspaceOwnership, HermesDeploymentConfig, HermesExecutionFactory, require_application_deployment
from role_channel import RoleChannel
from business import checksum


def claim_and_exit(path, run_id):
    store = RunStore(path, allow_migration=False)
    store.acquire_queued_for_execution(run_id, 0, "technical-worker", 60)
    os._exit(23)


def services_for(path, *, store=None):
    if store is None:
        store = ControlStore(path / "business.sqlite")
        store.initialize("ui-check")
    RunStore(store.path)
    HermesScheduleAdapter(store).install_schema()
    sessions = MemorySessionManager(path / "workspace", business_store=store, sessions_root=path / "sessions")
    bus, config = MessageBus(), WebSocketConfig()
    gateway = build_gateway_services(config=config, bus=bus, session_manager=sessions, static_dist_path=None,
        workspace_path=path, default_restrict_to_workspace=True, config_path=path / "config.json",
        runtime_model_name=None, runtime_surface="webui", runtime_capabilities_overrides=None)
    channel = RoleChannel(WebSocketChannel(config, bus, gateway=gateway), {}, path / "access.jsonl", store)
    app = hermes_product_application(channel, store, sessions, "ui-check", public_port=1234, upstream_port=1235)
    return app[SERVICES_KEY]


def test_execution_factory_requires_valid_server_deployment(tmp_path):
    services = services_for(tmp_path)
    config = HermesDeploymentConfig(*([tmp_path] * 6), 0, None, True)
    with pytest.raises(ValueError, match="部署网关配置无效"):
        HermesExecutionFactory(services, config)
    config = HermesDeploymentConfig(*([tmp_path] * 6), 12345, None, False)
    with pytest.raises(ValueError, match="部署网关凭据不可用"):
        HermesExecutionFactory(services, config)
    config = HermesDeploymentConfig(*([tmp_path] * 6), 12345, None, True)
    assert HermesExecutionFactory(services, config).services is services


def test_dispatch_receipt_lease_and_concurrency_commit_together(tmp_path):
    services = services_for(tmp_path)
    install_simulation_migrations(services.store.path)
    dispatcher = AgentRunDispatcher(services)
    concurrency = RunConcurrencyBudget(services.store)
    run_id = services.store.create_run("technical-owner", "ui-check", "create-request", "create-digest")
    with pytest.raises(sqlite3.IntegrityError):
        with services.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            lease = services.store.acquire_queued_in_transaction(db, run_id, 0, "worker", 60)
            db.execute("INSERT INTO agent_concurrency_budgets VALUES (?,?)", (run_id, 1))
            concurrency.reserve_in_transaction(db, run_id, "worker", lease["epoch"], "dispatch:" + run_id + ":" + str(lease["epoch"]), "digest")
            dispatcher.record_dispatch_in_transaction(db, run_id, "dispatch", 0, "worker", lease["epoch"])
            dispatcher.record_dispatch_in_transaction(db, run_id, "dispatch", 0, "worker", lease["epoch"])
    assert services.store.read_run(run_id)["status"] == "QUEUED"
    with services.store.connect() as db:
        assert db.execute("SELECT count(*) FROM agent_dispatch_receipts").fetchone() == (0,)
        assert db.execute("SELECT count(*) FROM agent_concurrency_reservations").fetchone() == (0,)
        db.execute("BEGIN IMMEDIATE")
        lease = services.store.acquire_queued_in_transaction(db, run_id, 0, "worker", 60)
        db.execute("INSERT INTO agent_concurrency_budgets VALUES (?,?)", (run_id, 1))
        concurrency.reserve_in_transaction(db, run_id, "worker", lease["epoch"], "dispatch:" + run_id + ":" + str(lease["epoch"]), "digest")
        dispatcher.record_dispatch_in_transaction(db, run_id, "dispatch", 0, "worker", lease["epoch"])
    with services.store.connect() as db:
        assert db.execute("SELECT state,lease_epoch FROM agent_dispatch_receipts WHERE run_id=?", (run_id,)).fetchone() == ("ACCEPTED", lease["epoch"])
        assert db.execute("SELECT state,lease_epoch FROM agent_concurrency_reservations WHERE run_id=?", (run_id,)).fetchone() == ("ACTIVE", lease["epoch"])
        db.execute("BEGIN")
        inspection = dispatcher.inspect_dispatch_recovery_in_transaction(db, run_id, "dispatch")
        assert inspection["reservation_state"] == "ACTIVE" and inspection["process_state"] == "NOT_RECORDED"
        assert inspection["lease_owner_matches"] and inspection["automatic_retry"] is False
        with pytest.raises(web.HTTPConflict) as unresolved:
            dispatcher.require_no_unresolved_dispatch_in_transaction(db, run_id)
        assert "原派发结果尚未确定" in unresolved.value.text
    with services.store.connect() as db:
        db.execute("BEGIN")
        assert dispatcher.inspect_dispatch_recovery_in_transaction(db, run_id, "dispatch") == inspection
    assert dispatcher.record_start_failure(run_id, "worker", lease["epoch"]) == "INTERRUPTED"
    with services.store.connect() as db:
        db.execute("BEGIN")
        inspection = dispatcher.inspect_dispatch_recovery_in_transaction(db, run_id, "dispatch")
        assert inspection["run_status"] == "INTERRUPTED" and inspection["reservation_state"] == "UNKNOWN"
        assert inspection["process_state"] == "NOT_RECORDED" and inspection["automatic_retry"] is False


def test_expired_dispatch_recovery_keeps_unknown_after_real_leader_exit(tmp_path):
    services = services_for(tmp_path)
    install_simulation_migrations(services.store.path)
    dispatcher = AgentRunDispatcher(services)
    concurrency = RunConcurrencyBudget(services.store)
    evidence = HermesProcessEvidence(services.store)
    run_id = services.store.create_run("technical-owner", "ui-check", "recovery-create", "recovery-digest")
    with services.store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        lease = services.store.acquire_queued_in_transaction(db, run_id, 0, "recovery-worker", 15)
        db.execute("INSERT INTO agent_concurrency_budgets VALUES (?,?)", (run_id, 1))
        process_key = "dispatch:" + run_id + ":" + str(lease["epoch"])
        concurrency.reserve_in_transaction(db, run_id, "recovery-worker", lease["epoch"], process_key, "process-digest")
        dispatcher.record_dispatch_in_transaction(db, run_id, "recovery-request", 0, "recovery-worker", lease["epoch"])
    evidence.start(run_id, process_key, "process-digest", "recovery-worker", lease["epoch"],
                   "technical-owner", "ui-check", [sys.executable, "-c", "import time; time.sleep(1)"], cwd=tmp_path)
    process = evidence.processes[(run_id, process_key)]
    process.wait(timeout=10)
    assert evidence.observe_exit(run_id, process_key) == {"state": "EXITED", "exit_code": 0, "exit_scope": "LEADER_ONLY"}
    time.sleep(max(0, (datetime.fromisoformat(lease["expires_at"]) - utc_now()).total_seconds()) + 0.05)
    result = services.recovery.recover_expired(run_id, "technical-owner", "ui-check")
    assert result == {"run_id": run_id, "status": "INTERRUPTED", "unknown_reservations": 1}
    assert services.recovery.recover_expired(run_id, "technical-owner", "ui-check") == result
    with services.store.connect() as db:
        db.execute("BEGIN")
        inspection = dispatcher.inspect_dispatch_recovery_in_transaction(db, run_id, "recovery-request")
        assert inspection["receipt_state"] == "UNKNOWN" and inspection["reservation_state"] == "UNKNOWN"
        assert inspection["process_state"] == "EXITED" and inspection["exit_scope"] == "LEADER_ONLY"
        assert inspection["automatic_retry"] is False
        with pytest.raises(web.HTTPConflict):
            dispatcher.require_no_unresolved_dispatch_in_transaction(db, run_id)


def test_dispatch_preconditions_preserve_queued_run(tmp_path):
    from agent_run_method_selection import AgentRunMethodSelection
    from agent_run_requirements import RunRequirements
    from boss_native_skills import BossSkillCatalog
    from boss_skill_drafts import BossSkillDrafts
    from nanobot.agent.skills import SkillsLoader
    from nanobot.agent.tools.registry import ToolRegistry
    from nanobot.config.loader import save_config
    from nanobot.config.schema import Config

    services = services_for(tmp_path)
    install_simulation_migrations(services.store.path)
    dispatcher = AgentRunDispatcher(services)
    run_id = services.store.create_run("technical-owner", "ui-check", "preflight-request", "preflight-digest")
    with services.store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        with pytest.raises(web.HTTPConflict) as missing_goal:
            dispatcher.require_dispatch_preconditions_in_transaction(db, run_id)
        assert "目标尚未准备" in missing_goal.value.text
        db.execute("UPDATE agent_runs SET goal=? WHERE run_id=?", ("核查会议资料", run_id))
        with pytest.raises(web.HTTPConflict) as missing_requirements:
            dispatcher.require_dispatch_preconditions_in_transaction(db, run_id)
        assert "成果要求尚未确认" in missing_requirements.value.text
        RunRequirements.save_in_transaction(db, run_id, 1, "requirements-request", ["TEXT"])
        with pytest.raises(web.HTTPServiceUnavailable) as missing_service:
            dispatcher.require_dispatch_preconditions_in_transaction(db, run_id)
        assert "方法服务尚未准备" in missing_service.value.text
    config = Config()
    config.agents.defaults.workspace = str(Path(__file__).resolve().parents[2] / "agent")
    config_path = tmp_path / "method-config.json"
    save_config(config, config_path)
    catalog = BossSkillCatalog(SkillsLoader(Path(config.agents.defaults.workspace)), ToolRegistry())
    drafts = BossSkillDrafts(services.scope.store, catalog, config_path)
    services.broker.method_selection = AgentRunMethodSelection(services.store, services.scope, catalog, drafts)
    with drafts._locked(), services.store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        with pytest.raises(web.HTTPConflict) as missing_method:
            dispatcher.require_dispatch_preconditions_in_transaction(db, run_id)
        assert "尚未选择方法" in missing_method.value.text
        assert db.execute("SELECT status,lease_owner,lease_epoch FROM agent_runs WHERE run_id=?", (run_id,)).fetchone() == ("QUEUED", None, 0)
        assert db.execute("SELECT count(*) FROM agent_dispatch_receipts").fetchone() == (0,)
        assert db.execute("SELECT count(*) FROM agent_concurrency_reservations").fetchone() == (0,)


def test_finalize_dispatch_receipt_consumes_exactly_once(tmp_path):
    services = services_for(tmp_path)
    install_simulation_migrations(services.store.path)
    dispatcher = AgentRunDispatcher(services)
    run_id = services.store.create_run("technical-owner", "ui-check", "finalize-request", "finalize-digest")
    lease = services.store.acquire_queued_for_execution(run_id, 0, "worker", 60)
    with services.store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        dispatcher.record_dispatch_in_transaction(db, run_id, "dispatch-finalize", 0, "worker", lease["epoch"])
    result = GuardedExecutionResult("WAITING_INPUT", None, "VERIFIED_EXITED")
    assert dispatcher.finalize_dispatch_receipt(run_id, "dispatch-finalize", "worker", lease["epoch"], result) == "COMPLETED"
    with services.store.connect() as db:
        receipt = db.execute("SELECT state,result FROM agent_dispatch_receipts WHERE run_id=? AND request_key=?", (run_id, "dispatch-finalize")).fetchone()
    assert receipt[0] == "COMPLETED" and json.loads(receipt[1]) == {"state": "WAITING_INPUT", "engine_exit": None, "descendants": "VERIFIED_EXITED"}
    with pytest.raises(ValueError, match="回执消费状态"):
        dispatcher.finalize_dispatch_receipt(run_id, "dispatch-finalize", "worker", lease["epoch"], result)


def test_dispatch_preconditions_accept_unapplied_owner_inputs(tmp_path):
    from agent_run_requirements import RunRequirements

    services = services_for(tmp_path)
    install_simulation_migrations(services.store.path)
    dispatcher = AgentRunDispatcher(services)
    run_id = services.store.create_run("technical-owner", "ui-check", "pending-input-request", "pending-input-digest")
    services.store.add_input(run_id, 1, "pending-input-1", "补充第一项要求")
    services.store.add_input(run_id, 2, "pending-input-2", "补充第二项要求")
    with services.store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute("UPDATE agent_runs SET goal=? WHERE run_id=?", ("核查会议资料", run_id))
        RunRequirements.save_in_transaction(db, run_id, 3, "pending-input-2", ["TEXT"])
        with pytest.raises(web.HTTPServiceUnavailable) as missing_service:
            dispatcher.require_dispatch_preconditions_in_transaction(db, run_id)
        assert "方法服务尚未准备" in missing_service.value.text
        assert db.execute("SELECT goal_revision,applied_goal_revision FROM agent_runs WHERE run_id=?", (run_id,)).fetchone() == (3, 1)
        assert db.execute("SELECT count(*) FROM agent_run_events WHERE run_id=? AND type='INPUT_APPLIED'", (run_id,)).fetchone() == (0,)


def test_queued_run_does_not_offer_dispatch_while_engine_is_unavailable(tmp_path):
    from agent_run_api import require_product_engine_ready
    from agent_run_broker import RunBroker
    from hermes_process_manager import HermesProcessManager, IsolationBoundaryUnavailable

    services = services_for(tmp_path)
    run_id = services.store.create_run("technical-owner", "ui-check", "action-request", "action-digest")
    run = services.store.read_run(run_id)
    assert run["status"] == "QUEUED"
    assert "DISPATCH" not in RunBroker.allowed_actions(run)
    with pytest.raises(web.HTTPServiceUnavailable):
        require_product_engine_ready()
    with pytest.raises(IsolationBoundaryUnavailable):
        HermesProcessManager.require_isolation()
    with pytest.raises(IsolationBoundaryUnavailable):
        HermesProcessManager.require_bound_isolation()


def test_plan_authority_rejects_supplemented_goal_before_adoption(tmp_path):
    from test_agent_run_result import setup_result

    business, runs, _, sink = setup_result(tmp_path)
    dispatcher = AgentRunDispatcher(services_for(tmp_path, store=business))
    runs.add_input(sink.config.run_id, 1, "plan-additional-input", "补充会议资料")
    with runs.connect() as db:
        db.execute("BEGIN")
        with pytest.raises(ValueError, match="目标版本超出本人授权"):
            dispatcher.require_authorized_plan_execution_in_transaction(db, sink.config.run_id, {})
        assert db.execute("SELECT goal_revision,applied_goal_revision FROM agent_runs WHERE run_id=?", (sink.config.run_id,)).fetchone() == (2, 1)
        assert db.execute("SELECT count(*) FROM objects WHERE kind='authorization'").fetchone() == (0,)


def test_application_deployment_requires_explicit_offline_product_configuration(tmp_path):
    offline = HermesDeploymentConfig(*([tmp_path] * 6), 12345, None, True)
    assert require_application_deployment(None, product_mode=True, run_port="1234") is None
    assert require_application_deployment(offline, product_mode=True, run_port="1234") is offline
    with pytest.raises(ValueError, match="产品模式和运行接口"):
        require_application_deployment(offline, product_mode=False, run_port="1234")
    with pytest.raises(ValueError, match="产品模式和运行接口"):
        require_application_deployment(offline, product_mode=True, run_port=None)
    with pytest.raises(ValueError, match="在线运行需要模型凭据"):
        require_application_deployment(HermesDeploymentConfig(*([tmp_path] * 6), 12345, None, False), product_mode=True, run_port="1234")


def test_factory_artifact_preparation_uses_run_directory_and_budget(tmp_path):
    services = services_for(tmp_path)
    run_id = services.store.create_run("technical-owner", "ui-check", "artifact-request", "artifact-digest")
    lease = services.store.acquire_queued_for_execution(run_id, 0, "artifact-worker", 60)
    services.store.configure_file_budget(run_id, "artifact-worker", lease["epoch"], 2, 4096)
    root = tmp_path / "artifacts"
    root.mkdir()
    mapping = ArtifactWorkspace(root.resolve())
    services = replace(services, artifact_workspace=mapping)
    deployment = HermesDeploymentConfig(*([tmp_path] * 6), 12345, None, True)
    factory = HermesExecutionFactory(services, deployment)
    from hermes_bridge import EngineEventSink
    config = EngineRunConfig(run_id, lease["epoch"], "903230b1e23e0c496b28e5d2e8c4f2639cd506b6", "http://127.0.0.1:12345", 1)
    sink = EngineEventSink(services.store, config, "artifact-worker")
    budget = {"files": 2, "file_bytes": 4096}
    ArtifactWorkspaceOwnership(services.store, mapping, allow_migration=True)
    preparation = factory.artifact_preparation(sink, budget)
    assert preparation is not None
    directory = mapping._path(run_id)
    assert directory.is_dir()
    with pytest.raises(ValueError, match="预算"):
        factory.artifact_preparation(sink, {"files": 3, "file_bytes": 4096})
    services.store.release_lease(run_id, "artifact-worker", lease["epoch"])
    with pytest.raises(ValueError, match="租约"):
        factory.artifact_preparation(sink, budget)
    assert list(directory.iterdir()) == []


def test_execution_factory_rejects_unauthenticated_real_lease(tmp_path):
    services = services_for(tmp_path)
    run_id = services.store.create_run("technical-owner", "ui-check", "factory-request", "factory-digest")
    lease = services.store.acquire_queued_for_execution(run_id, 0, "factory-worker", 60)
    with socket.create_server(("127.0.0.1", 0)) as reserved:
        provider_port = reserved.getsockname()[1]
    deployment = HermesDeploymentConfig(*([tmp_path] * 6), provider_port, None, True)
    factory = HermesExecutionFactory(services, deployment)
    run = EngineRunConfig(run_id, lease["epoch"], "903230b1e23e0c496b28e5d2e8c4f2639cd506b6", f"http://127.0.0.1:{provider_port}", 1)
    from hermes_bridge import EngineEventSink
    sink = EngineEventSink(services.store, run, "factory-worker")

    async def exercise():
        async def prepare(request):
            factory.prepare(request, run_id, lease["epoch"] + 1)
            return web.Response()

        async def assemble(request):
            factory.assemble(request, sink, {}, "factory-digest")
            return web.Response()

        app = web.Application()
        app.router.add_post("/prepare", prepare)
        app.router.add_post("/assemble", assemble)
        runner = web.AppRunner(app)
        await runner.setup()
        await web.TCPSite(runner, "127.0.0.1", 0).start()
        try:
            async with httpx.AsyncClient(trust_env=False) as client:
                address = "http://127.0.0.1:" + str(runner.addresses[0][1])
                assert (await client.post(address + "/prepare")).status_code == 401
                assert (await client.post(address + "/assemble")).status_code == 401
            with socket.create_server(("127.0.0.1", provider_port)):
                pass
        finally:
            await runner.cleanup()

    asyncio.run(exercise())
    assert services.store.read_run(run_id)["lease_epoch"] == lease["epoch"]


@pytest.mark.parametrize("condition", ["valid", "widened", "withdrawn", "lease_released"])
def test_child_scope_lineage_uses_real_root_and_rejects_changes(tmp_path, condition):
    from test_agent_run_result import setup_result
    business, runs, _, sink = setup_result(tmp_path)
    services = services_for(tmp_path, store=business)
    dispatcher = AgentRunDispatcher(services)
    root = sink.config.run_id
    child = runs.create_child_run(root, sink.lease_owner, sink.config.lease_epoch, "scope-child", "scope-digest")
    runs.acquire_queued_for_execution(child, 0, "child-worker", 60)
    if condition == "valid":
        proof = services.scope.prove("result-check", [])
        AgentChatBudget(services.store, services.recovery.channel, services.scope, allow_migration=True)
        budget = {"model_requests": 2, "rounds": 2, "tools": 2, "seconds": 2, "concurrency": 1, "context_tokens": 128, "files": 1, "file_bytes": 1024, "open_files": 16, "cpu_seconds": 1}
        later = {**budget, "tools": 4}
        with runs.connect() as db:
            db.execute("UPDATE agent_runs SET selected_refs=?,scope_proof=? WHERE run_id=?", ("[]", json.dumps(asdict(proof)), child))
            db.execute("INSERT INTO agent_chat_budget_configs VALUES (?,?,?,?,?)", (1, "technical-1", json.dumps(budget), checksum(budget), "2026-10-30T00:00:00+00:00"))
            db.execute("INSERT INTO agent_chat_run_budgets VALUES (?,?,?,?)", (root, 1, checksum(budget), "2026-10-30T00:00:00+00:00"))
            db.execute("INSERT INTO agent_chat_budget_configs VALUES (?,?,?,?,?)", (2, "technical-2", json.dumps(later), checksum(later), "2026-10-30T00:00:00+00:00"))
    if condition == "widened":
        proof = services.scope.prove("result-check", [])
        with runs.connect() as db:
            db.execute("UPDATE agent_runs SET selected_refs=?,scope_proof=? WHERE run_id=?", ("[]", json.dumps(asdict(proof)), root))
    if condition == "withdrawn":
        business.control("ui-check", "withdraw", {"source_id": "finance-note", "version": "1"})
    if condition == "lease_released":
        runs.release_lease(root, sink.lease_owner, sink.config.lease_epoch)
    with runs.connect() as db:
        db.execute("BEGIN")
        if condition == "valid":
            verified_root, row = dispatcher._verify_scope_lineage_in_transaction(db, child)
            assert verified_root == root and json.loads(row[4]) == ["finance-note"]
            assert db.execute("SELECT count(*) FROM agent_chat_run_budgets WHERE run_id=?", (child,)).fetchone() == (0,)
            plan, recorded = dispatcher.approved_budget_in_transaction(db, root)
            assert recorded == budget and plan["config_version"] == 1
            dispatcher._verify_lineage_approval_in_transaction(db, child, checksum(plan), budget)
            with pytest.raises(ValueError, match="计划或预算已经变化"):
                dispatcher._verify_lineage_approval_in_transaction(db, child, checksum(plan), later)
            with pytest.raises(ValueError, match="计划或预算已经变化"):
                dispatcher._verify_lineage_approval_in_transaction(db, child, checksum({**plan, "config_version": 2}), budget)
        elif condition == "widened":
            with pytest.raises(ValueError, match="超过父运行"):
                dispatcher._verify_scope_lineage_in_transaction(db, child)
        elif condition == "withdrawn":
            with pytest.raises(ValueError, match="来源已经撤销"):
                dispatcher._verify_scope_lineage_in_transaction(db, child)
        else:
            with pytest.raises(ValueError, match="租约"):
                dispatcher._verify_scope_lineage_in_transaction(db, child)


def test_missing_persisted_budget_rejected_without_claim(tmp_path):
    services = services_for(tmp_path)
    run_id = services.store.create_run("technical-owner", "ui-check", "request", "digest")
    dispatcher = AgentRunDispatcher(services)
    with services.store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        with pytest.raises(ValueError, match="本人批准计划预算"):
            dispatcher.approved_budget_in_transaction(db, run_id)
        with pytest.raises(ValueError, match="本人批准计划预算"):
            dispatcher.bind_budget_in_transaction(db, run_id, "technical-worker", 1)
        assert db.execute("SELECT count(*) FROM agent_file_budgets").fetchone() == (0,)
    assert services.store.read_run(run_id)["status"] == "QUEUED"
    assert services.store.events(run_id, 0) == []


def test_dispatch_binds_approved_cpu_budget_to_root(tmp_path):
    from agent_run_tool_budget import RunToolBudget
    from hermes_budget_gateway import RunBoundBudgetStore
    from hermes_cpu_budget import HermesCPUBudget
    from hermes_vm_identity import HermesVMRunBindings
    from test_agent_run_result import setup_result

    business, runs, _, sink = setup_result(tmp_path)
    services = services_for(tmp_path, store=business)
    AgentChatBudget(runs, services.recovery.channel, services.scope, allow_migration=True)
    RunToolBudget(runs, allow_migration=True)
    RunConcurrencyBudget(runs, allow_migration=True)
    RunBoundBudgetStore(sink, allow_migration=True)
    HermesProcessEvidence(runs, allow_migration=True)
    HermesVMRunBindings(runs, allow_migration=True)
    HermesCPUBudget(runs, allow_migration=True)
    budget = {"model_requests": 1, "rounds": 2, "tools": 2, "seconds": 4, "concurrency": 1,
              "context_tokens": 128, "files": 1, "file_bytes": 1024, "open_files": 16, "cpu_seconds": 3}
    with runs.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute("INSERT INTO agent_chat_budget_configs VALUES (?,?,?,?,?)", (1, "technical-budget", json.dumps(budget), checksum(budget), "2026-10-30T00:00:00+00:00"))
        db.execute("INSERT INTO agent_chat_run_budgets VALUES (?,?,?,?)", (sink.config.run_id, 1, checksum(budget), "2026-10-30T00:00:00+00:00"))
        dispatcher = AgentRunDispatcher(services)
        assert dispatcher.bind_budget_in_transaction(db, sink.config.run_id, sink.lease_owner, sink.config.lease_epoch)["budget"] == budget
        assert dispatcher.bind_budget_in_transaction(db, sink.config.run_id, sink.lease_owner, sink.config.lease_epoch)["budget"] == budget
    with runs.connect() as db:
        assert db.execute("SELECT root_run_id,limit_ns FROM hermes_cpu_budgets").fetchall() == [(sink.config.run_id, 3_000_000_000)]


def test_plan_event_recheck_requires_transaction_and_valid_scope(tmp_path):
    services = services_for(tmp_path)
    dispatcher = AgentRunDispatcher(services)
    with services.store.connect() as db:
        with pytest.raises(ValueError, match="同一数据库事务"):
            dispatcher.require_plan_events_in_transaction(db, "ui-check", {})
        db.execute("BEGIN IMMEDIATE")
        with pytest.raises(ValueError, match="事件范围"):
            dispatcher.require_plan_events_in_transaction(db, "ui-check", {"event_ids": [], "event_versions": {}})
        with pytest.raises(ValueError, match="事件范围"):
            dispatcher.require_plan_events_in_transaction(db, "ui-check", {"event_ids": ["event-1", "event-1"], "event_versions": {"event-1": "1"}})


def test_unauthenticated_dispatch_has_no_effect(tmp_path):
    services = services_for(tmp_path)
    run_id = services.store.create_run("technical-owner", "ui-check", "request", "digest")
    dispatcher = AgentRunDispatcher(services)
    run = EngineRunConfig(run_id, 1, "903230b1e23e0c496b28e5d2e8c4f2639cd506b6", "http://127.0.0.1:1234", 1)
    config = EngineProcessConfig(run, *([Path(tmp_path)] * 7), 1, 1, 1, 1, 1, 1, 1, 16, 1)

    async def exercise():
        async def start(request):
            await dispatcher.dispatch(request, run_id, 0, "dispatch-request")
            return web.Response()

        async def inspect(request):
            return web.json_response(dispatcher.inspect(request, run_id))

        async def recheck(request):
            dispatcher.recheck_after_claim(request, run_id, "technical-worker", 1, "digest", {})
            return web.Response()

        async def launch_transaction(request):
            with dispatcher.launch_transaction(request, run_id, "technical-worker", 1, "digest", {}):
                return web.Response()

        app = web.Application()
        app.router.add_post("/dispatch", start)
        app.router.add_get("/inspect", inspect)
        app.router.add_post("/recheck", recheck)
        app.router.add_post("/launch-transaction", launch_transaction)
        runner = web.AppRunner(app)
        await runner.setup()
        await web.TCPSite(runner, "127.0.0.1", 0).start()
        try:
            async with httpx.AsyncClient(trust_env=False) as client:
                response = await client.post("http://127.0.0.1:" + str(runner.addresses[0][1]) + "/dispatch")
                assert response.status_code == 401
                response = await client.get("http://127.0.0.1:" + str(runner.addresses[0][1]) + "/inspect")
                assert response.status_code == 401
                response = await client.post("http://127.0.0.1:" + str(runner.addresses[0][1]) + "/recheck")
                assert response.status_code == 401
                response = await client.post("http://127.0.0.1:" + str(runner.addresses[0][1]) + "/launch-transaction")
                assert response.status_code == 401
        finally:
            await runner.cleanup()

    asyncio.run(exercise())
    assert services.store.read_run(run_id)["status"] == "QUEUED"
    assert services.store.events(run_id, 0) == []


def test_failure_record_replays_after_real_process_exit(tmp_path):
    services = services_for(tmp_path)
    run_id = services.store.create_run("technical-owner", "ui-check", "request", "digest")
    process = multiprocessing.get_context("spawn").Process(target=claim_and_exit, args=(services.store.path, run_id))
    process.start()
    process.join(60)
    assert process.exitcode == 23
    dispatcher = AgentRunDispatcher(services)
    assert dispatcher.record_start_failure(run_id, "technical-worker", 1) == "INTERRUPTED"
    assert dispatcher.record_start_failure(run_id, "technical-worker", 1) == "INTERRUPTED"
    run = services.store.read_run(run_id)
    assert run["lease_owner"] == "technical-worker" and run["lease_epoch"] == 1
    assert [event["payload"]["to"] for event in services.store.events(run_id, 0)] == ["RUNNING", "INTERRUPTED"]


def test_failure_record_preserves_cancel_request(tmp_path):
    services = services_for(tmp_path)
    run_id = services.store.create_run("technical-owner", "ui-check", "request", "digest")
    lease = services.store.acquire_queued_for_execution(run_id, 0, "technical-worker", 60)
    services.store.cancel(run_id, lease["revision"])
    dispatcher = AgentRunDispatcher(services)
    assert dispatcher.record_start_failure(run_id, "technical-worker", lease["epoch"]) == "CANCEL_REQUESTED"
    assert dispatcher.record_start_failure(run_id, "technical-worker", lease["epoch"]) == "CANCEL_REQUESTED"
    assert [event["payload"]["to"] for event in services.store.events(run_id, 0)] == ["RUNNING", "CANCEL_REQUESTED"]
