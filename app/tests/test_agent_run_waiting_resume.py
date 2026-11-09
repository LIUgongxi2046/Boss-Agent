import asyncio
import time

import httpx
import pytest
from aiohttp import web

from agent_run_broker import RunBroker, RunIdentity
from agent_run_concurrency import RunConcurrencyBudget
from agent_run_requirements import RunRequirements
from agent_run_store import RunStore
from agent_simulation_migration_install import install_simulation_migrations
from controls import ControlStore
from hermes_bridge import EngineEventSink, EngineRunConfig
from hermes_budget_gateway import RunBoundBudgetStore


def prepare_waiting(path, *, reserve=False, reserve_model=False):
    business = ControlStore(path / "business.sqlite")
    business.initialize("ui-check")
    install_simulation_migrations(business.path)
    runs = RunStore(business.path, allow_migration=False)
    run_id = runs.create_run("technical-owner", "ui-check", "technical-run", "technical-digest")
    lease = runs.acquire_queued_for_execution(run_id, 0, "technical-worker", 2)
    budget = RunConcurrencyBudget(runs)
    if reserve:
        budget.configure(run_id, "technical-worker", lease["epoch"], 1)
        with runs.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            budget.reserve_in_transaction(db, run_id, "technical-worker", lease["epoch"], "technical-process", "technical-digest")
    if reserve_model:
        config = EngineRunConfig(run_id, lease["epoch"], "903230b1e23e0c496b28e5d2e8c4f2639cd506b6", "http://127.0.0.1:1234", 1)
        RunBoundBudgetStore(EngineEventSink(runs, config, "technical-worker")).reserve()
    current = runs.read_run(run_id)
    runs.transition(run_id, current["revision"], "WAITING_INPUT", "technical-worker", lease["epoch"])
    runs.add_input(run_id, 1, "technical-input", "补充成果要求")
    with runs.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        RunRequirements.save_in_transaction(db, run_id, 2, "technical-input", ["TEXT"])
    return runs, budget, run_id


def test_requeue_waiting_checks_lease_and_is_idempotent(tmp_path):
    runs, _, run_id = prepare_waiting(tmp_path)
    revision = runs.read_run(run_id)["revision"]
    with runs.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        with pytest.raises(ValueError, match="租约仍然有效"):
            runs.requeue_waiting_in_transaction(db, run_id, revision, 2, "technical-resume")
    time.sleep(2.1)
    with runs.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        with pytest.raises(ValueError, match="版本已经变化"):
            runs.requeue_waiting_in_transaction(db, run_id, revision, 1, "technical-resume")
        receipt = runs.requeue_waiting_in_transaction(db, run_id, revision, 2, "technical-resume")
        assert runs.requeue_waiting_in_transaction(db, run_id, revision, 2, "technical-resume") == receipt
        with pytest.raises(ValueError, match="请求冲突"):
            runs.requeue_waiting_in_transaction(db, run_id, revision, 3, "technical-resume")
        db.rollback()
    assert runs.read_run(run_id)["status"] == "WAITING_INPUT"
    with runs.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        receipt = runs.requeue_waiting_in_transaction(db, run_id, revision, 2, "technical-resume")
    assert receipt["status"] == "QUEUED" and receipt["goal_revision"] == 2
    claimed = runs.acquire_queued_for_execution(run_id, receipt["revision"], "next-worker", 60)
    assert claimed["epoch"] == 2
    assert [event["payload"].get("to") for event in runs.events(run_id, 0) if event["type"] == "STATUS_CHANGED"] == ["RUNNING", "WAITING_INPUT", "INTERRUPTED", "QUEUED", "RUNNING"]


def test_requeue_waiting_preserves_unknown_reservation(tmp_path):
    runs, budget, run_id = prepare_waiting(tmp_path, reserve=True)
    revision = runs.read_run(run_id)["revision"]
    time.sleep(2.1)
    with runs.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        assert budget.mark_unknown_in_transaction(db, run_id, "technical-process") == "UNKNOWN"
        with pytest.raises(ValueError, match="额度尚未释放"):
            runs.requeue_waiting_in_transaction(db, run_id, revision, 2, "technical-resume")
        assert db.execute("SELECT state FROM agent_concurrency_reservations WHERE run_id=?", (run_id,)).fetchone() == ("UNKNOWN",)
    assert runs.read_run(run_id)["status"] == "WAITING_INPUT"


def test_requeue_waiting_preserves_unknown_model_request(tmp_path):
    runs, _, run_id = prepare_waiting(tmp_path, reserve_model=True)
    revision = runs.read_run(run_id)["revision"]
    time.sleep(2.1)
    with runs.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        with pytest.raises(ValueError, match="模型请求结果尚未核查"):
            runs.requeue_waiting_in_transaction(db, run_id, revision, 2, "technical-resume")
        assert db.execute("SELECT state FROM hermes_model_requests WHERE root_run_id=?", (run_id,)).fetchone() == ("UNKNOWN",)
    assert runs.read_run(run_id)["status"] == "WAITING_INPUT"


def test_requeue_waiting_rejects_missing_owner_session(tmp_path):
    runs, _, run_id = prepare_waiting(tmp_path)
    broker = RunBroker(runs)
    with pytest.raises(web.HTTPUnauthorized):
        broker.requeue_waiting(None, run_id, 1, 2, "technical-resume", request=None)
    with pytest.raises(web.HTTPUnauthorized):
        broker.waiting_resume_inspection(None, run_id, request_key="technical-resume")
    assert runs.read_run(run_id)["status"] == "WAITING_INPUT"


def test_broker_resume_requeues_waiting_run_without_adopting_input(tmp_path):
    from test_agent_run_result import setup_result

    store, runs, result, sink = setup_result(tmp_path, full_sources=True)
    install_simulation_migrations(store.path)
    run_id = sink.config.run_id
    current = runs.read_run(run_id)
    runs.transition(run_id, current["revision"], "WAITING_INPUT", sink.lease_owner, sink.config.lease_epoch)
    runs.add_input(run_id, 1, "resume-input", "补充经营查询要求")
    with runs.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        RunRequirements.save_in_transaction(db, run_id, 2, "resume-input", ["TEXT"])
    runs.release_lease(run_id, sink.lease_owner, sink.config.lease_epoch)
    revision = runs.read_run(run_id)["revision"]
    proof = result.scope.prove("result-check", ["simulation-meeting-material"])
    identity = RunIdentity(proof.owner_id, proof.namespace, "BOSS", frozenset({proof.chat_id}),
                           frozenset({"simulation-meeting-material"}),
                           verify=lambda: result.scope.prove(proof.chat_id, ["simulation-meeting-material"]))
    broker = RunBroker(runs, scope_service=result.scope)

    async def exercise():
        async def resume(request):
            return web.json_response(broker.requeue_waiting(identity, run_id, revision, 2, "resume-request", request=request))

        app = web.Application()
        app.router.add_post("/resume", resume)
        runner = web.AppRunner(app)
        await runner.setup()
        await web.TCPSite(runner, "127.0.0.1", 0).start()
        try:
            async with httpx.AsyncClient(trust_env=False) as client:
                address = "http://127.0.0.1:" + str(runner.addresses[0][1])
                first = await client.post(address + "/resume")
                assert first.status_code == 200
                receipt = first.json()
                assert receipt == {"run_id": run_id, "status": "QUEUED", "revision": revision + 2, "goal_revision": 2}
                assert (await client.post(address + "/resume")).json() == receipt
                return receipt
        finally:
            await runner.cleanup()

    receipt = asyncio.run(exercise())
    saved = runs.read_run(run_id)
    assert (saved["status"], saved["goal_revision"], saved["applied_goal_revision"]) == ("QUEUED", 2, 1)
    with runs.connect() as db:
        assert db.execute("SELECT applied_event_id FROM agent_run_inputs WHERE run_id=?", (run_id,)).fetchone() == (None,)
        assert db.execute("SELECT count(*) FROM agent_run_events WHERE run_id=? AND type='INPUT_APPLIED'", (run_id,)).fetchone() == (0,)
    assert [event["payload"].get("to") for event in runs.events(run_id, 0) if event["type"] == "STATUS_CHANGED"] == ["RUNNING", "WAITING_INPUT", "INTERRUPTED", "QUEUED"]
    claimed = runs.acquire_queued_for_execution(run_id, receipt["revision"], "next-worker", 60)
    assert claimed["epoch"] == 2
