import pytest
from uuid import uuid4

from agent_run_concurrency import RunConcurrencyBudget
from hermes_process_evidence import HermesProcessEvidence
from hermes_vm_identity import HermesVMRunBindings
from test_agent_run_dispatcher import services_for
from test_hermes_process_evidence import expire_lease, start


def test_start_failure_marks_reservation_and_process_unknown_before_reacquire(tmp_path):
    services = services_for(tmp_path)
    store = services.store
    run_id = store.create_run("boss-1", "ui-check", "start-failure", "digest")
    lease = store.acquire_lease(run_id, 0, "worker", 60)
    store.transition(run_id, lease["revision"], "RUNNING", "worker", lease["epoch"])
    budget = RunConcurrencyBudget(store, allow_migration=True)
    budget.configure(run_id, "worker", lease["epoch"], 1)
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        budget.reserve_in_transaction(db, run_id, "worker", lease["epoch"], "slot", "digest")
    evidence = HermesProcessEvidence(store, allow_migration=True)
    start(evidence, run_id, lease["epoch"], 5)
    process = evidence.processes[(run_id, "slot")]
    try:
        from agent_run_dispatcher import AgentRunDispatcher
        dispatcher = AgentRunDispatcher(services)
        assert dispatcher.record_start_failure(run_id, "worker", lease["epoch"]) == "INTERRUPTED"
        assert evidence.read(run_id, "slot")["state"] == "UNKNOWN"
        with store.connect() as db:
            assert db.execute("SELECT state FROM agent_concurrency_reservations WHERE run_id=? AND request_key='slot'", (run_id,)).fetchone()[0] == "UNKNOWN"
            assert db.execute("SELECT status,lease_owner,lease_epoch FROM agent_runs WHERE run_id=?", (run_id,)).fetchone() == ("INTERRUPTED", "worker", lease["epoch"])
        expire_lease(store, run_id)
        with pytest.raises(ValueError, match="进程状态记录已保存"):
            store.acquire_lease(run_id, store.read_run(run_id)["revision"], "retry-worker", 60)
    finally:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=10)


def test_start_failure_without_process_record_blocks_on_unknown_reservation(tmp_path):
    services = services_for(tmp_path)
    store = services.store
    run_id = store.create_run("boss-1", "ui-check", "start-failure", "digest")
    lease = store.acquire_lease(run_id, 0, "worker", 60)
    store.transition(run_id, lease["revision"], "RUNNING", "worker", lease["epoch"])
    budget = RunConcurrencyBudget(store, allow_migration=True)
    budget.configure(run_id, "worker", lease["epoch"], 1)
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        budget.reserve_in_transaction(db, run_id, "worker", lease["epoch"], "slot", "digest")
    from agent_run_dispatcher import AgentRunDispatcher
    dispatcher = AgentRunDispatcher(services)
    assert dispatcher.record_start_failure(run_id, "worker", lease["epoch"]) == "INTERRUPTED"
    expire_lease(store, run_id)
    with pytest.raises(ValueError, match="并发预留尚未核查"):
        store.acquire_lease(run_id, store.read_run(run_id)["revision"], "retry-worker", 60)


@pytest.mark.parametrize("next_status", ["CANCEL_REQUESTED", "WAITING_INPUT", "WAITING_CONFIRMATION", "RECONCILING"])
def test_start_failure_preserves_vm_reservation_for_waiting_or_canceled_run(tmp_path, next_status):
    from agent_run_dispatcher import AgentRunDispatcher
    services = services_for(tmp_path)
    store = services.store
    run_id = store.create_run("boss-1", "ui-check", "vm-cancel-start", "digest")
    lease = store.acquire_lease(run_id, 0, "worker", 60)
    store.transition(run_id, lease["revision"], "RUNNING", "worker", lease["epoch"])
    budget = RunConcurrencyBudget(store, allow_migration=True)
    evidence = HermesProcessEvidence(store, allow_migration=True)
    bindings = HermesVMRunBindings(store, allow_migration=True)
    budget.configure(run_id, "worker", lease["epoch"], 1)
    workspace = tmp_path / run_id
    workspace.mkdir()
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        budget.reserve_in_transaction(db, run_id, "worker", lease["epoch"], "slot", "digest")
        evidence.record_vm_start_in_transaction(db, bindings, run_id, "slot", "digest", "worker", lease["epoch"],
                                                "boss-1", "ui-check", str(uuid4()), str(uuid4()), workspace)
    revision = store.read_run(run_id)["revision"]
    if next_status == "CANCEL_REQUESTED":
        store.cancel(run_id, revision)
    else:
        store.transition(run_id, revision, next_status, "worker", lease["epoch"])
    assert AgentRunDispatcher(services).record_start_failure(run_id, "worker", lease["epoch"]) == next_status
    with store.connect() as db:
        assert db.execute("SELECT state FROM agent_concurrency_reservations WHERE run_id=?", (run_id,)).fetchone() == ("UNKNOWN",)
        assert db.execute("SELECT state FROM hermes_process_evidence WHERE run_id=?", (run_id,)).fetchone() == ("UNKNOWN",)
        assert db.execute("SELECT status FROM agent_runs WHERE run_id=?", (run_id,)).fetchone() == (next_status,)
