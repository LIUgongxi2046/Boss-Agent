import sqlite3

import pytest

from agent_run_concurrency import RunConcurrencyBudget
from agent_run_store import RunStore
from hermes_bridge import EngineEventSink, EngineProcessSupervisor, EngineRunConfig
from hermes_budget_gateway import RunBoundBudgetStore
from hermes_process_evidence import HermesProcessEvidence
from test_hermes_process_evidence import expire_lease, start
from test_hermes_run_recovery import product_services


def test_process_exit_with_failed_usage_blocks_reacquire_after_real_recovery(tmp_path):
    store, services = product_services(tmp_path)
    run_id = store.create_run("boss-1", "ui-check", "exit-usage", "digest")
    lease = store.acquire_lease(run_id, 0, "worker", 60)
    store.transition(run_id, lease["revision"], "RUNNING", "worker", lease["epoch"])
    concurrency = RunConcurrencyBudget(store, allow_migration=True)
    concurrency.configure(run_id, "worker", lease["epoch"], 1)
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        concurrency.reserve_in_transaction(db, run_id, "worker", lease["epoch"], "slot", "digest")
    evidence = HermesProcessEvidence(store, allow_migration=True)
    config = EngineRunConfig(run_id, lease["epoch"], "903230b1e23e0c496b28e5d2e8c4f2639cd506b6", "http://127.0.0.1:1234", 1)
    sink = EngineEventSink(store, config, "worker")
    budget = RunBoundBudgetStore(sink, allow_migration=True)
    request = budget.reserve()
    budget.complete(request, {"total_tokens": 5})
    start(evidence, run_id, lease["epoch"], 0.2)
    process = evidence.processes[(run_id, "slot")]
    process.wait(timeout=10)
    with store.connect() as db:
        db.execute("CREATE TRIGGER usage_exit_rejected BEFORE INSERT ON agent_run_events WHEN NEW.type='USAGE_RECORDED' BEGIN SELECT RAISE(ABORT, 'usage event rejected'); END")
    supervisor = EngineProcessSupervisor(sink, process, cancel_grace=0.2, process_evidence=evidence, request_key="slot", usage_report=budget.usage_report)
    with pytest.raises(sqlite3.IntegrityError, match="usage event rejected"):
        supervisor.observe_exit()

    assert evidence.read(run_id, "slot")["state"] == "EXITED"
    assert store.read_run(run_id)["status"] == "RUNNING"
    with store.connect() as db:
        assert db.execute("SELECT count(*) FROM agent_run_events WHERE run_id=? AND type='USAGE_RECORDED'", (run_id,)).fetchone()[0] == 0
        assert db.execute("SELECT state FROM agent_concurrency_reservations WHERE run_id=? AND request_key='slot'", (run_id,)).fetchone()[0] == "ACTIVE"
        assert db.execute("SELECT state FROM hermes_model_requests WHERE root_run_id=?", (run_id,)).fetchone()[0] == "COMPLETED"

    expire_lease(store, run_id)
    receipt = services.recovery.recover_expired(run_id, "boss-1", "ui-check")
    assert receipt == {"run_id": run_id, "status": "INTERRUPTED", "unknown_reservations": 1}
    assert services.recovery.recover_expired(run_id, "boss-1", "ui-check") == receipt
    assert evidence.read(run_id, "slot")["state"] == "EXITED"
    with store.connect() as db:
        assert db.execute("SELECT state FROM agent_concurrency_reservations WHERE run_id=? AND request_key='slot'", (run_id,)).fetchone()[0] == "UNKNOWN"
        assert db.execute("SELECT count(*) FROM agent_run_events WHERE run_id=? AND type='USAGE_RECORDED'", (run_id,)).fetchone()[0] == 0
    with pytest.raises(ValueError, match="进程状态记录已保存"):
        store.acquire_lease(run_id, store.read_run(run_id)["revision"], "retry-worker", 60)

    reopened = RunStore(store.path, allow_migration=False)
    assert reopened.read_run(run_id)["status"] == "INTERRUPTED"
    assert HermesProcessEvidence(reopened).read(run_id, "slot")["state"] == "EXITED"
    with pytest.raises(ValueError, match="进程状态记录已保存"):
        reopened.acquire_lease(run_id, reopened.read_run(run_id)["revision"], "retry-worker", 60)
    with reopened.connect() as db:
        assert db.execute("SELECT count(*) FROM agent_run_events WHERE run_id=? AND type='USAGE_RECORDED'", (run_id,)).fetchone()[0] == 0
        assert db.execute("SELECT state FROM agent_concurrency_reservations WHERE run_id=? AND request_key='slot'", (run_id,)).fetchone()[0] == "UNKNOWN"
