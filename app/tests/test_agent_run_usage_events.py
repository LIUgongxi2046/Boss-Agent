import asyncio
import json
import sqlite3
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import httpx
import pytest
from aiohttp import web

from agent_run_broker import RunBroker, RunIdentity
from agent_run_store import RunStore
from agent_run_usage import latest_usage_snapshot_in_transaction
from hermes_bridge import ENGINE_EVENT_FIELDS, USAGE_EVENT_FIELDS, EngineEventSink, EngineProcessSupervisor
from hermes_budget_gateway import BudgetStore, RunBoundBudgetStore
from test_agent_run_api import start_server
from test_agent_run_result import setup_result


def usage_page(store, run_id):
    with store.connect() as db:
        db.execute("BEGIN")
        return store.event_page_in_transaction(db, run_id, 0)


def test_cancelled_usage_snapshot_requires_current_lease(tmp_path):
    _, runs, _, sink = setup_result(tmp_path)
    budget = RunBoundBudgetStore(sink, allow_migration=True)
    budget.reserve()
    run_id = sink.config.run_id
    runs.cancel(run_id, runs.read_run(run_id)["revision"])
    runs.release_lease(run_id, sink.lease_owner, sink.config.lease_epoch)
    with pytest.raises(ValueError, match="租约"):
        budget.record_usage_snapshot()
    assert not [event for event in runs.events(run_id, 0) if event["type"] == "USAGE_RECORDED"]


@pytest.mark.parametrize("first", ["cancel", "withdraw"])
def test_cancelled_usage_snapshot_rejects_withdrawn_source(tmp_path, first):
    business, runs, _, sink = setup_result(tmp_path)
    budget = RunBoundBudgetStore(sink, allow_migration=True)
    request_id = budget.reserve()
    run_id = sink.config.run_id
    if first == "cancel":
        runs.cancel(run_id, runs.read_run(run_id)["revision"])
    business.control("ui-check", "withdraw", {"source_id": "finance-note", "version": "1"})
    if first == "withdraw":
        runs.cancel(run_id, runs.read_run(run_id)["revision"])
    with pytest.raises(ValueError, match="来源已经撤销"):
        budget.record_usage_snapshot()
    assert not [event for event in runs.events(run_id, 0) if event["type"] == "USAGE_RECORDED"]
    with runs.connect() as db:
        assert db.execute("SELECT request_id,state FROM hermes_model_requests WHERE run_id=?", (run_id,)).fetchall() == [(request_id, "UNKNOWN")]


@pytest.mark.parametrize("condition", ["valid", "identity_mismatch", "ancestor_lease_released"])
def test_parent_cancellation_records_child_usage_after_real_process_stop(tmp_path, condition):
    _, runs, _, root_sink = setup_result(tmp_path)
    root_id = root_sink.config.run_id
    root_budget = RunBoundBudgetStore(root_sink, allow_migration=True)
    child_id = runs.create_child_run(root_id, root_sink.lease_owner, root_sink.config.lease_epoch, "child-cancel", "child-digest")
    lease = runs.acquire_queued_for_execution(child_id, 0, "child-worker", 60)
    runs.transition(child_id, runs.read_run(child_id)["revision"], "INTERRUPTED", "child-worker", lease["epoch"])
    runs.release_lease(child_id, "child-worker", lease["epoch"])
    lease = runs.acquire_lease(child_id, runs.read_run(child_id)["revision"], "child-worker-next", 60)
    runs.transition(child_id, lease["revision"], "RECONCILING", "child-worker-next", lease["epoch"])
    runs.transition(child_id, runs.read_run(child_id)["revision"], "RUNNING", "child-worker-next", lease["epoch"])
    assert lease["epoch"] != root_sink.config.lease_epoch
    child_sink = EngineEventSink(runs, replace(root_sink.config, run_id=child_id, lease_epoch=lease["epoch"]), "child-worker-next")
    child_budget = RunBoundBudgetStore(child_sink)
    request_id = child_budget.reserve()
    process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        supervisor = EngineProcessSupervisor(child_sink, process, usage_report=child_budget.usage_report)
        runs.cancel(root_id, runs.read_run(root_id)["revision"])
        if condition == "identity_mismatch":
            with runs.connect() as db:
                db.execute("UPDATE agent_runs SET space_id='' WHERE run_id=?", (child_id,))
        if condition == "ancestor_lease_released":
            runs.release_lease(root_id, root_sink.lease_owner, root_sink.config.lease_epoch)
        expected = {"valid": "运行或父运行已经取消或不可执行", "identity_mismatch": "主体或空间不一致", "ancestor_lease_released": "租约"}[condition]
        with pytest.raises(ValueError, match=expected):
            asyncio.run(supervisor.monitor(interval=0.01))
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=10)
    assert process.poll() is not None
    events = [event for event in runs.events(child_id, 0) if event["type"] == "USAGE_RECORDED"]
    if condition == "valid":
        assert len(events) == 1 and events[0]["payload"]["root_run_id"] == root_id
        assert events[0]["payload"]["usage_state"] == "UNKNOWN" and events[0]["payload"]["requests_used"] == 1
    else:
        assert not events
    assert root_budget.usage_report()["requests"][0]["request_id"] == request_id


def test_parent_lease_release_races_child_usage_transaction(tmp_path):
    _, runs, _, root_sink = setup_result(tmp_path)
    root_id = root_sink.config.run_id
    RunBoundBudgetStore(root_sink, allow_migration=True)
    child_id = runs.create_child_run(root_id, root_sink.lease_owner, root_sink.config.lease_epoch, "child-race", "child-race-digest")
    lease = runs.acquire_queued_for_execution(child_id, 0, "child-worker", 60)
    sink = EngineEventSink(runs, replace(root_sink.config, run_id=child_id, lease_epoch=lease["epoch"]), "child-worker")
    budget = RunBoundBudgetStore(sink)
    budget.reserve()
    runs.cancel(root_id, runs.read_run(root_id)["revision"])
    barrier = threading.Barrier(2, timeout=10)
    def release():
        barrier.wait()
        return runs.release_lease(root_id, root_sink.lease_owner, root_sink.config.lease_epoch)
    def snapshot():
        barrier.wait()
        return budget.record_usage_snapshot()
    with ThreadPoolExecutor(max_workers=2) as executor:
        release_future = executor.submit(release)
        snapshot_future = executor.submit(snapshot)
        release_future.result(timeout=10)
        error = snapshot_future.exception(timeout=10)
        if error is not None:
            assert isinstance(error, ValueError) and "租约" in str(error)
    events = [event for event in runs.events(child_id, 0) if event["type"] == "USAGE_RECORDED"]
    if error is None:
        assert len(events) == 1 and events[0]["payload"]["usage_state"] == "UNKNOWN"
    else:
        assert not events
    with pytest.raises(ValueError, match="租约"):
        budget.record_usage_snapshot()


def real_exit(sink, budget):
    process = subprocess.Popen([sys.executable, "-c", "pass"])
    process.wait(timeout=10)
    supervisor = EngineProcessSupervisor(sink, process, cancel_grace=0.2, usage_report=budget.usage_report)
    assert supervisor.observe_exit() == "ENGINE_EXITED"


def failing_exit(sink, budget):
    process = subprocess.Popen([sys.executable, "-c", "pass"])
    process.wait(timeout=10)
    supervisor = EngineProcessSupervisor(sink, process, cancel_grace=0.2, usage_report=budget.usage_report)
    with pytest.raises(sqlite3.IntegrityError, match="usage event rejected"):
        supervisor.observe_exit()


def test_real_budget_snapshots_across_root_lease_epochs(tmp_path):
    store, runs, results, base_sink = setup_result(tmp_path)
    run_id = base_sink.config.run_id
    first_sink = EngineEventSink(runs, replace(base_sink.config, request_limit=2), base_sink.lease_owner)
    first_budget = RunBoundBudgetStore(first_sink, allow_migration=True)
    first_request = first_budget.reserve()
    first_budget.complete(first_request, {"total_tokens": 10})
    first_report = first_budget.usage_report()
    assert (first_report["requests_used"], first_report["total_tokens"], first_report["usage_state"]) == (1, 10, "COMPLETE")
    with runs.connect() as db:
        db.execute("CREATE TRIGGER usage_event_rejected BEFORE INSERT ON agent_run_events WHEN NEW.type='USAGE_RECORDED' BEGIN SELECT RAISE(ABORT, 'usage event rejected'); END")
    failing_exit(first_sink, first_budget)
    with runs.connect() as db:
        assert db.execute("SELECT count(*) FROM agent_run_events WHERE type='USAGE_RECORDED'").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM hermes_usage_revisions").fetchone()[0] == 0
        db.execute("DROP TRIGGER usage_event_rejected")
    real_exit(first_sink, first_budget)
    real_exit(first_sink, first_budget)

    with runs.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute("UPDATE agent_runs SET lease_expires_at=? WHERE run_id=?", ("2000-01-01T00:00:00+00:00", run_id))
    runs.interrupt_expired(run_id)
    current = runs.read_run(run_id)
    assert current["status"] == "INTERRUPTED" and current["cancel_requested_at"] is None
    lease = runs.acquire_lease(run_id, current["revision"], "second-worker", 60)
    current = runs.read_run(run_id)
    runs.transition(run_id, current["revision"], "RECONCILING", "second-worker", lease["epoch"])
    current = runs.read_run(run_id)
    runs.transition(run_id, current["revision"], "RUNNING", "second-worker", lease["epoch"])
    second_sink = EngineEventSink(runs, replace(first_sink.config, lease_epoch=lease["epoch"]), "second-worker")
    second_budget = RunBoundBudgetStore(second_sink, allow_migration=False)
    second_request = second_budget.reserve()
    second_budget.complete(second_request, None)
    second_report = second_budget.usage_report()
    assert second_report["requests_used"] == 2
    assert second_report["total_tokens"] is None
    assert second_report["usage_state"] in {"PARTIAL", "UNKNOWN"}
    real_exit(second_sink, second_budget)
    real_exit(second_sink, second_budget)

    page = usage_page(runs, run_id)
    usage = [event for event in page["events"] if event["type"] == "USAGE_RECORDED"]
    assert [event["payload"]["requests_used"] for event in usage] == [1, 2]
    assert [event["payload"]["total_tokens"] for event in usage] == [10, None]
    assert [event["payload"]["snapshot_revision"] for event in usage] == [1, 2]
    assert len({event["payload"]["snapshot_revision"] for event in usage}) == len(usage)
    assert [event["payload"]["lease_epoch"] for event in usage] == [first_sink.config.lease_epoch, lease["epoch"]]
    assert all(event["payload"]["usage_kind"] == "CUMULATIVE_SNAPSHOT" for event in usage)
    assert all(event["payload"]["snapshot_final"] is False for event in usage)
    assert all(event["payload"]["root_run_id"] == run_id for event in usage)
    assert all(event["payload"]["cost"] is None and event["payload"]["cost_state"] == "UNKNOWN" for event in usage)
    with runs.connect() as db:
        assert [row[0] for row in db.execute("SELECT lease_epoch FROM agent_run_events WHERE run_id=? AND type='USAGE_RECORDED' ORDER BY seq", (run_id,)).fetchall()] == [first_sink.config.lease_epoch, lease["epoch"]]
    assert sum(event["payload"]["requests_used"] for event in usage) != second_report["requests_used"]
    with runs.connect() as db:
        db.execute("BEGIN")
        latest = latest_usage_snapshot_in_transaction(db, run_id)
    assert latest["snapshot_revision"] == 2
    assert latest["requests_used"] == 2 and latest["snapshot_final"] is False
    assert latest["total_tokens"] is None and latest["cost"] is None
    assert ENGINE_EVENT_FIELDS["USAGE_RECORDED"] == {"requests_used", "total_tokens"}
    assert {"snapshot_revision", "lease_epoch", "root_run_id", "usage_kind"} <= USAGE_EVENT_FIELDS
    broker = RunBroker(runs, scope_service=results.scope)
    run = runs.read_run(run_id)
    identity = RunIdentity(run["actor_id"], run["space_id"], "BOSS", frozenset({"result-check"}), frozenset({"finance-note"}))
    projected = broker.usage(identity, run_id)
    assert projected["snapshot_revision"] == 2 and projected["requests_used"] == 2
    assert projected["snapshot_final"] is False and projected["total_tokens"] is None
    assert projected["cost"] is None and projected["cost_state"] == "UNKNOWN"

    current = runs.read_run(run_id)
    runs.cancel(run_id, current["revision"], request_key="usage-root-cancel")
    with runs.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute("UPDATE agent_runs SET lease_expires_at=? WHERE run_id=?", ("2000-01-01T00:00:00+00:00", run_id))
    with pytest.raises(ValueError, match="租约无效"):
        second_budget.record_usage_snapshot()
    process = subprocess.Popen([sys.executable, "-c", "pass"])
    process.wait(timeout=10)
    expired = EngineProcessSupervisor(second_sink, process, cancel_grace=0.2, usage_report=second_budget.usage_report)
    with pytest.raises(ValueError, match="租约无效"):
        expired.observe_exit()

    reopened = RunStore(store.path, allow_migration=False)
    replay = [event for event in usage_page(reopened, run_id)["events"] if event["type"] == "USAGE_RECORDED"]
    assert replay == usage
    assert [event["seq"] for event in replay] == [event["seq"] for event in usage]
    assert reopened.read_run(run_id)["cancel_requested_at"] is not None


def test_legacy_usage_payload_remains_readable_after_schema_extension(tmp_path):
    store, runs, _, sink = setup_result(tmp_path)
    budget = BudgetStore(store.path, sink.config.run_id, 2)
    request = budget.reserve()
    budget.complete(request, {"total_tokens": 10})
    real_exit(sink, budget)
    reopened = RunStore(store.path, allow_migration=False)
    replay = [item for item in usage_page(reopened, sink.config.run_id)["events"] if item["type"] == "USAGE_RECORDED"]
    assert len(replay) == 1
    assert replay[0]["payload"] == {"requests_used": 1, "total_tokens": 10}
    with reopened.connect() as db:
        db.execute("BEGIN")
        assert latest_usage_snapshot_in_transaction(db, sink.config.run_id) is None


def test_old_database_installs_revision_migration_before_snapshot(tmp_path):
    store, runs, _, sink = setup_result(tmp_path)
    budget = RunBoundBudgetStore(sink, allow_migration=True)
    budget.reserve()
    with runs.connect() as db:
        db.execute("DROP TABLE hermes_usage_revisions")
        db.execute("DELETE FROM agent_schema_migrations WHERE version='hermes_budget_002'")
    restored = RunBoundBudgetStore(sink, allow_migration=True)
    event = restored.record_usage_snapshot()
    assert event["payload"]["snapshot_revision"] == 1
    with runs.connect() as db:
        assert db.execute("SELECT count(*) FROM hermes_usage_revisions").fetchone()[0] == 1


def test_process_termination_before_commit_rolls_back_snapshot(tmp_path):
    store, runs, _, sink = setup_result(tmp_path)
    budget = RunBoundBudgetStore(sink, allow_migration=True)
    script = (
        "import os,sqlite3,sys\n"
        "db=sqlite3.connect(sys.argv[1]); db.execute('BEGIN IMMEDIATE')\n"
        "db.execute(\"INSERT INTO hermes_usage_revisions VALUES (?, 1)\", (sys.argv[2],))\n"
        "os._exit(1)\n"
    )
    process = subprocess.run([sys.executable, "-c", script, str(store.path), sink.config.run_id])
    assert process.returncode == 1
    with runs.connect() as db:
        assert db.execute("SELECT count(*) FROM hermes_usage_revisions").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM agent_run_events WHERE type='USAGE_RECORDED'").fetchone()[0] == 0
    event = budget.record_usage_snapshot()
    assert event["payload"]["snapshot_revision"] == 1
    assert event["payload"]["snapshot_final"] is False


def test_concurrent_completion_and_snapshot_claims_are_idempotent(tmp_path):
    store, runs, _, base_sink = setup_result(tmp_path)
    run_id = base_sink.config.run_id
    sink = EngineEventSink(runs, replace(base_sink.config, request_limit=2), base_sink.lease_owner)
    budget = RunBoundBudgetStore(sink, allow_migration=True)
    requests = [budget.reserve(), budget.reserve()]
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda request: budget.complete(request, {"total_tokens": 5}), requests))
    with ThreadPoolExecutor(max_workers=2) as pool:
        events = list(pool.map(lambda _: budget.record_usage_snapshot(), range(2)))
    assert events[0]["event_id"] == events[1]["event_id"]
    assert events[0]["payload"]["requests_used"] == 2
    assert events[0]["payload"]["known_requests"] == 2
    assert events[0]["payload"]["total_tokens"] == 10
    assert events[0]["payload"]["snapshot_revision"] == 1
    with runs.connect() as db:
        assert db.execute("SELECT count(*) FROM agent_run_events WHERE run_id=? AND type='USAGE_RECORDED'", (run_id,)).fetchone()[0] == 1
        assert db.execute("SELECT revision FROM hermes_usage_revisions WHERE root_run_id=?", (run_id,)).fetchone()[0] == 1
    reopened = RunStore(store.path, allow_migration=False)
    with reopened.connect() as db:
        row = db.execute("SELECT payload FROM agent_run_events WHERE run_id=? AND type='USAGE_RECORDED'", (run_id,)).fetchone()
        assert json.loads(row[0])["snapshot_revision"] == 1


def test_real_budget_snapshots_across_root_and_child_leases(tmp_path):
    store, runs, _, base_sink = setup_result(tmp_path)
    root_id = base_sink.config.run_id
    root_sink = EngineEventSink(runs, replace(base_sink.config, request_limit=2), base_sink.lease_owner)
    child_id = runs.create_child_run(root_id, base_sink.lease_owner, base_sink.config.lease_epoch, "usage-child", "usage-child-digest")
    child_lease = runs.acquire_queued_for_execution(child_id, 0, "child-worker", 60)
    child_sink = EngineEventSink(runs, replace(root_sink.config, run_id=child_id, lease_epoch=child_lease["epoch"]), "child-worker")

    root_budget = RunBoundBudgetStore(root_sink, allow_migration=True)
    root_request = root_budget.reserve()
    root_budget.complete(root_request, {"total_tokens": 10})
    assert root_budget.usage_report()["requests_used"] == 1
    real_exit(root_sink, root_budget)
    real_exit(root_sink, root_budget)

    child_budget = RunBoundBudgetStore(child_sink, allow_migration=False)
    child_request = child_budget.reserve()
    child_budget.complete(child_request, None)
    child_report = child_budget.usage_report()
    assert child_report["requests_used"] == 2 and child_report["total_tokens"] is None
    real_exit(child_sink, child_budget)
    real_exit(child_sink, child_budget)

    root_usage = [event for event in usage_page(runs, root_id)["events"] if event["type"] == "USAGE_RECORDED"]
    child_usage = [event for event in usage_page(runs, child_id)["events"] if event["type"] == "USAGE_RECORDED"]
    assert [event["payload"]["requests_used"] for event in root_usage] == [1]
    assert [event["payload"]["requests_used"] for event in child_usage] == [2]
    assert root_usage[0]["payload"]["total_tokens"] == 10
    assert child_usage[0]["payload"]["total_tokens"] is None
    assert sum(event["payload"]["requests_used"] for event in root_usage + child_usage) != child_report["requests_used"]
    with runs.connect() as db:
        db.execute("BEGIN")
        latest = latest_usage_snapshot_in_transaction(db, child_id)
    assert latest["root_run_id"] == root_id and latest["snapshot_revision"] == 2
    assert latest["requests_used"] == 2 and latest["total_tokens"] is None

    child_current = runs.read_run(child_id)
    runs.cancel(child_id, child_current["revision"], request_key="usage-child-cancel")
    reopened = RunStore(store.path, allow_migration=False)
    replay_root = [event for event in usage_page(reopened, root_id)["events"] if event["type"] == "USAGE_RECORDED"]
    replay_child = [event for event in usage_page(reopened, child_id)["events"] if event["type"] == "USAGE_RECORDED"]
    assert replay_root == root_usage and replay_child == child_usage
    assert reopened.read_run(child_id)["cancel_requested_at"] is not None


def test_usage_query_checks_descendant_without_usage_event(tmp_path):
    store, runs, results, sink = setup_result(tmp_path)
    budget = RunBoundBudgetStore(sink, allow_migration=True)
    request = budget.reserve()
    budget.complete(request, {"total_tokens": 5})
    real_exit(sink, budget)
    child_id = runs.create_child_run(sink.config.run_id, sink.lease_owner, sink.config.lease_epoch, "usage-no-event", "usage-no-event-digest")
    broker = RunBroker(runs, scope_service=results.scope)
    run = runs.read_run(sink.config.run_id)
    identity = RunIdentity(run["actor_id"], run["space_id"], "BOSS", frozenset({"result-check"}), frozenset({"finance-note"}))
    assert broker.usage(identity, sink.config.run_id)["requests_used"] == 1


def test_usage_http_endpoint_remains_closed(tmp_path):
    async def exercise():
        store, runs, results, sink = setup_result(tmp_path)
        broker = RunBroker(runs, scope_service=results.scope)
        run = runs.read_run(sink.config.run_id)
        identity = RunIdentity(run["actor_id"], run["space_id"], "BOSS", frozenset({"result-check"}), frozenset({"finance-note"}))
        runner, base = await start_server(broker, identity)
        try:
            async with httpx.AsyncClient(trust_env=False) as client:
                response = await client.get(base + "/api/v2/runs/" + run["run_id"] + "/usage")
                assert response.status_code == 503
                assert response.json()["code"] == "SERVICE_NOT_READY"
        finally:
            await runner.cleanup()

    asyncio.run(exercise())


def test_usage_snapshot_rejects_dangling_parent_and_cycle_without_mutation(tmp_path):
    store = RunStore(tmp_path / "lineage.sqlite")
    first = store.create_run("boss-lineage", "space-lineage", "lineage-first", "lineage-first-digest")
    second = store.create_run("boss-lineage", "space-lineage", "lineage-second", "lineage-second-digest")
    with sqlite3.connect(store.path) as db:
        db.execute("UPDATE agent_runs SET parent_run_id=? WHERE run_id=?", ("missing-root", second))
    before = _lineage_state(store, first, second)
    with store.connect() as db:
        db.execute("BEGIN")
        with pytest.raises(ValueError, match="根运行不存在"):
            latest_usage_snapshot_in_transaction(db, second)
    assert _lineage_state(store, first, second) == before

    with sqlite3.connect(store.path) as db:
        db.execute("UPDATE agent_runs SET parent_run_id=? WHERE run_id=?", (second, first))
        db.execute("UPDATE agent_runs SET parent_run_id=? WHERE run_id=?", (first, second))
    before = _lineage_state(store, first, second)
    with store.connect() as db:
        db.execute("BEGIN")
        with pytest.raises(ValueError, match="循环"):
            latest_usage_snapshot_in_transaction(db, first)
    assert _lineage_state(store, first, second) == before


def _lineage_state(store, *run_ids):
    with store.connect() as db:
        rows = [tuple(db.execute("SELECT run_id,parent_run_id,status,revision FROM agent_runs WHERE run_id=?", (run_id,)).fetchone()) for run_id in run_ids]
        return (rows, db.execute("SELECT count(*) FROM agent_run_events").fetchone()[0])


def test_budget_exhaustion_leaves_reservations_rolls_back(tmp_path):
    store, runs, results, sink = setup_result(tmp_path)
    budget = RunBoundBudgetStore(EngineEventSink(runs, replace(sink.config, request_limit=1), sink.lease_owner), allow_migration=True)
    first = budget.reserve()
    assert first
    with runs.connect() as db:
        before = db.execute("SELECT count(*) FROM hermes_model_requests").fetchone()[0]
    with pytest.raises(web.HTTPTooManyRequests):
        budget.reserve()
    with runs.connect() as db:
        assert db.execute("SELECT count(*) FROM hermes_model_requests").fetchone()[0] == before
        assert db.execute("SELECT state,usage FROM hermes_model_requests").fetchall() == [("UNKNOWN", None)]
