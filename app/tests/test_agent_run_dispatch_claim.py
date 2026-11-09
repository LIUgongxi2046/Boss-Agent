import multiprocessing
import os
import time
from concurrent.futures import ProcessPoolExecutor

import pytest

from agent_run_store import RunStore
from controls import ControlStore
from hermes_source_invalidation import begin_source_cleanup


def claim(path, run_id, owner):
    return RunStore(path, allow_migration=False).acquire_queued_for_execution(run_id, 0, owner, 60)


def claim_and_exit(path, run_id):
    store = RunStore(path, allow_migration=False)
    store.acquire_queued_for_execution(run_id, 0, "technical-worker", 0.2)
    os._exit(19)


def test_queued_claim_competes_across_processes_and_records_transition(tmp_path):
    store = RunStore(tmp_path / "runs.sqlite")
    run_id = store.create_run("technical-owner", "technical-space", "request", "digest")
    with ProcessPoolExecutor(max_workers=2) as pool:
        attempts = [pool.submit(claim, store.path, run_id, owner) for owner in ("worker-a", "worker-b")]
        errors = [item.exception() for item in attempts]
    assert sum(error is None for error in errors) == 1
    assert sum(isinstance(error, ValueError) for error in errors) == 1
    result = attempts[errors.index(None)].result()
    run = store.read_run(run_id)
    assert (run["status"], run["revision"], run["lease_epoch"]) == ("RUNNING", 1, result["epoch"])
    events = store.events(run_id, 0)
    assert len(events) == 1 and events[0]["payload"] == {"from": "QUEUED", "to": "RUNNING"}


def test_interrupted_claim_can_be_recorded_after_expiry(tmp_path):
    store = RunStore(tmp_path / "runs.sqlite")
    run_id = store.create_run("technical-owner", "technical-space", "request", "digest")
    process = multiprocessing.get_context("spawn").Process(target=claim_and_exit, args=(store.path, run_id))
    process.start()
    process.join(20)
    assert process.exitcode == 19
    time.sleep(0.25)
    store.interrupt_expired(run_id)
    run = store.read_run(run_id)
    assert run["status"] == "INTERRUPTED" and run["lease_owner"] is None
    assert [event["payload"]["to"] for event in store.events(run_id, 0)] == ["RUNNING", "INTERRUPTED"]


def test_claim_rejects_cancellation_and_source_cleanup(tmp_path):
    business = ControlStore(tmp_path / "business.sqlite")
    business.initialize("ui-check")
    store = RunStore(business.path)
    canceled = store.create_run("technical-owner", "ui-check", "cancel", "digest")
    store.cancel(canceled, 0)
    with pytest.raises(ValueError, match="不可取得"):
        store.acquire_queued_for_execution(canceled, 1, "worker", 60)
    blocked = store.create_run("technical-owner", "ui-check", "source", "digest")
    with store.connect() as db:
        db.execute("UPDATE agent_runs SET selected_refs=? WHERE run_id=?", ('["finance-note"]', blocked))
    begin_source_cleanup(business, "ui-check", "finance-note", "1")
    with pytest.raises(ValueError, match="来源清理"):
        store.acquire_queued_for_execution(blocked, 0, "worker", 60)
    assert store.read_run(blocked)["status"] == "QUEUED"
    assert store.events(blocked, 0) == []


def test_child_claim_requires_active_parent(tmp_path):
    store = RunStore(tmp_path / "runs.sqlite")
    parent = store.create_run("technical-owner", "technical-space", "parent", "digest")
    parent_lease = store.acquire_queued_for_execution(parent, 0, "parent-worker", 60)
    child = store.create_child_run(parent, "parent-worker", parent_lease["epoch"], "child", "digest")
    store.cancel(parent, parent_lease["revision"])
    with pytest.raises(ValueError, match="父运行"):
        store.acquire_queued_for_execution(child, 0, "child-worker", 60)
    assert store.read_run(child)["status"] == "QUEUED"
    assert store.events(child, 0) == []


def test_transaction_rollback_preserves_queued_run(tmp_path):
    store = RunStore(tmp_path / "runs.sqlite")
    run_id = store.create_run("technical-owner", "technical-space", "request", "digest")
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        result = store.acquire_queued_in_transaction(db, run_id, 0, "worker", 60)
        assert result["epoch"] == 1
        db.rollback()
    assert store.read_run(run_id)["status"] == "QUEUED"
    assert store.events(run_id, 0) == []
