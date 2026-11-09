import subprocess
import sys
from datetime import timedelta
from pathlib import Path

from agent_run_concurrency import RunConcurrencyBudget
from agent_run_store import RunStore, utc_now
from hermes_process_evidence import HermesProcessEvidence
from hermes_run_recovery import inspect_recovery


def test_recovery_inspection_links_unknown_process_and_reservation(tmp_path):
    store = RunStore(tmp_path / "runs.sqlite")
    budget = RunConcurrencyBudget(store, allow_migration=True)
    evidence = HermesProcessEvidence(store, allow_migration=True)
    run_id = store.create_run("boss-1", "ui-check", "recovery", "digest")
    lease = store.acquire_lease(run_id, 0, "worker", 60)
    store.transition(run_id, lease["revision"], "RUNNING", "worker", lease["epoch"])
    budget.configure(run_id, "worker", lease["epoch"], 1)
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        budget.reserve_in_transaction(db, run_id, "worker", lease["epoch"], "slot", "digest")
    process = None
    try:
        evidence.start(run_id, "slot", "digest", "worker", lease["epoch"], "boss-1", "ui-check",
                       [sys.executable, "-c", "import time; time.sleep(30)"], cwd=Path(__file__).resolve().parent)
        process = evidence.processes[(run_id, "slot")]
        with store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("UPDATE agent_runs SET lease_expires_at=? WHERE run_id=?", ((utc_now() - timedelta(seconds=1)).isoformat(), run_id))
        assert evidence.mark_unknown(run_id, "slot") == "UNKNOWN"
        with store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            assert budget.mark_unknown_in_transaction(db, run_id, "slot") == "UNKNOWN"
            db.execute("UPDATE agent_runs SET status='INTERRUPTED',lease_owner=NULL,lease_expires_at=NULL,revision=revision+1 WHERE run_id=?", (run_id,))
        result = inspect_recovery(store, run_id, "boss-1", "ui-check")
        assert result["status"] == "INTERRUPTED"
        assert result["unknown_reservations"] == 1
        assert result["process_evidence"] == [{"request_key": "slot", "state": "UNKNOWN", "exit_code": None, "exit_scope": None}]
        assert result["intents"] == [] and result["receipts"] == [] and result["original_receipt"] is None
        assert result["duplicate_execution_allowed"] is False and result["automatic_requeue"] is False
        assert result["recovery_action"] == "NO_RECORDED_DECISION"
    finally:
        if process is not None and process.poll() is None:
            process.kill()
            process.wait(timeout=10)
