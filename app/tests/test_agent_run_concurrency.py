import multiprocessing
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from agent_run_concurrency import RunConcurrencyBudget
from agent_run_store import RunStore
from hermes_process_evidence import HermesProcessEvidence


def leave_transaction_open(path, run_id, owner, epoch):
    store = RunStore(path, allow_migration=False)
    budget = RunConcurrencyBudget(store)
    db = store.connect()
    db.execute("BEGIN IMMEDIATE")
    budget.reserve_in_transaction(db, run_id, owner, epoch, "interrupted-request", "interrupted-digest")
    os._exit(17)


def recover_in_process(path, run_id, request_key, result):
    store = RunStore(path, allow_migration=False)
    budget = RunConcurrencyBudget(store)
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        recovered = budget.recover_in_transaction(db, run_id, request_key)
    result.put(recovered)


def running_family(tmp_path, child_ttl=60):
    store = RunStore(tmp_path / "runs.sqlite")
    budget = RunConcurrencyBudget(store, allow_migration=True)
    RunConcurrencyBudget(store, allow_migration=True)
    root = store.create_run("boss-1", "ui-check", "root-request", "root-digest")
    root_lease = store.acquire_lease(root, 0, "root-worker", 60)
    store.transition(root, root_lease["revision"], "RUNNING", "root-worker", root_lease["epoch"])
    budget.configure(root, "root-worker", root_lease["epoch"], 1)
    child = store.create_child_run(root, "root-worker", root_lease["epoch"], "child-request", "child-digest")
    child_lease = store.acquire_lease(child, 0, "child-worker", child_ttl)
    store.transition(child, child_lease["revision"], "RUNNING", "child-worker", child_lease["epoch"])
    return store, budget, root, root_lease, child, child_lease


def test_parent_and_child_compete_for_shared_slot(tmp_path):
    store, budget, root, root_lease, child, child_lease = running_family(tmp_path)

    def reserve(run_id, owner, epoch):
        with store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            return budget.reserve_in_transaction(db, run_id, owner, epoch, "same-request", "same-digest")

    choices = [(root, "root-worker", root_lease["epoch"]), (child, "child-worker", child_lease["epoch"])]
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(reserve, *choice) for choice in choices]
    errors = [future.exception() for future in futures]
    assert sum(error is None for error in errors) == 1
    assert [str(error) for error in errors if error is not None] == ["并发额度不足"]
    winner = choices[errors.index(None)]
    assert futures[errors.index(None)].result() == {"state": "ACTIVE", "created": True}
    assert reserve(*winner) == {"state": "ACTIVE", "created": False}
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        with pytest.raises(ValueError, match="请求冲突"):
            budget.reserve_in_transaction(db, *winner, "same-request", "changed-digest")
        assert budget.release_in_transaction(db, *winner, "same-request", "same-digest") == "RELEASED"
        assert budget.release_in_transaction(db, *winner, "same-request", "same-digest") == "RELEASED"
    assert reserve(*winner) == {"state": "RELEASED", "created": False}
    assert reserve(*choices[errors.index(next(error for error in errors if error is not None))]) == {"state": "ACTIVE", "created": True}


def test_expired_lease_retains_unknown_reservation(tmp_path):
    store, budget, root, root_lease, child, child_lease = running_family(tmp_path, child_ttl=0.15)
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        budget.reserve_in_transaction(db, child, "child-worker", child_lease["epoch"], "child-slot", "child-slot-digest")
        with pytest.raises(ValueError, match="仍然有效"):
            budget.mark_unknown_in_transaction(db, child, "child-slot")
    time.sleep(0.2)
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        assert budget.mark_unknown_in_transaction(db, child, "child-slot") == "UNKNOWN"
        assert budget.mark_unknown_in_transaction(db, child, "child-slot") == "UNKNOWN"
        with pytest.raises(ValueError, match="并发额度不足"):
            budget.reserve_in_transaction(db, root, "root-worker", root_lease["epoch"], "root-slot", "root-slot-digest")
    store.interrupt_expired(child)
    new_lease = store.acquire_lease(child, store.read_run(child)["revision"], "new-worker", 60)
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        with pytest.raises(ValueError, match="不可核查"):
            budget.release_in_transaction(db, child, "new-worker", new_lease["epoch"], "child-slot", "child-slot-digest")
        assert db.execute("SELECT state FROM agent_concurrency_reservations WHERE run_id=?", (child,)).fetchone() == ("UNKNOWN",)


def test_interrupted_process_rolls_back_uncommitted_reservation(tmp_path):
    store, budget, root, lease, _, _ = running_family(tmp_path)
    process = multiprocessing.get_context("spawn").Process(target=leave_transaction_open, args=(store.path, root, "root-worker", lease["epoch"]))
    process.start()
    process.join(timeout=15)
    assert process.exitcode == 17
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        assert db.execute("SELECT count(*) FROM agent_concurrency_reservations").fetchone()[0] == 0
        assert budget.reserve_in_transaction(db, root, "root-worker", lease["epoch"], "after-restart", "after-digest") == {"state": "ACTIVE", "created": True}


def test_recovery_preserves_slot_after_leader_exit_and_restart(tmp_path):
    store, budget, root, root_lease, child, child_lease = running_family(tmp_path, child_ttl=2)
    evidence = HermesProcessEvidence(store, allow_migration=True)
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        budget.reserve_in_transaction(db, child, "child-worker", child_lease["epoch"], "slot", "digest")
    probe = Path(__file__).with_name("hermes_lifecycle_probe.py").resolve()
    evidence.start(child, "slot", "digest", "child-worker", child_lease["epoch"], "boss-1", "ui-check", [sys.executable, str(probe), "child", "0.2"], cwd=probe.parent)
    process = evidence.processes[(child, "slot")]
    try:
        with store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            assert budget.recover_in_transaction(db, child, "slot") == {"state": "ACTIVE", "process_state": "RUNNING", "exit_scope": None}
            with pytest.raises(ValueError, match="进程范围尚未确认"):
                budget.release_in_transaction(db, child, "child-worker", child_lease["epoch"], "slot", "digest")
        process.wait(timeout=10)
        assert evidence.observe_exit(child, "slot")["exit_scope"] == "LEADER_ONLY"
        with store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            with pytest.raises(ValueError, match="进程范围尚未确认"):
                budget.release_in_transaction(db, child, "child-worker", child_lease["epoch"], "slot", "digest")
            assert budget.recover_in_transaction(db, child, "slot") == {"state": "UNKNOWN", "process_state": "EXITED", "exit_scope": "LEADER_ONLY"}
        time.sleep(2.1)
        context = multiprocessing.get_context("spawn")
        result = context.Queue()
        recovery_process = context.Process(target=recover_in_process, args=(store.path, child, "slot", result))
        recovery_process.start()
        recovery_process.join(timeout=15)
        assert recovery_process.exitcode == 0
        expected = {"state": "UNKNOWN", "process_state": "EXITED", "exit_scope": "LEADER_ONLY"}
        assert result.get(timeout=5) == expected
        restarted_store = RunStore(store.path, allow_migration=False)
        restarted_budget = RunConcurrencyBudget(restarted_store)
        with restarted_store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            assert restarted_budget.recover_in_transaction(db, child, "slot") == expected
            assert restarted_budget.recover_in_transaction(db, child, "slot") == expected
            with pytest.raises(ValueError, match="并发额度不足"):
                restarted_budget.reserve_in_transaction(db, root, "root-worker", root_lease["epoch"], "another", "another-digest")
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=10)


def test_recovery_with_no_process_record_keeps_expired_slot(tmp_path):
    store, budget, root, root_lease, child, child_lease = running_family(tmp_path, child_ttl=0.15)
    HermesProcessEvidence(store, allow_migration=True)
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        budget.reserve_in_transaction(db, child, "child-worker", child_lease["epoch"], "slot", "digest")
    time.sleep(0.2)
    context = multiprocessing.get_context("spawn")
    result = context.Queue()
    process = context.Process(target=recover_in_process, args=(store.path, child, "slot", result))
    process.start()
    process.join(timeout=15)
    assert process.exitcode == 0
    assert result.get(timeout=5) == {"state": "UNKNOWN", "process_state": None, "exit_scope": None}
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        assert budget.recover_in_transaction(db, child, "slot") == {"state": "UNKNOWN", "process_state": None, "exit_scope": None}
        with pytest.raises(ValueError, match="并发额度不足"):
            budget.reserve_in_transaction(db, root, "root-worker", root_lease["epoch"], "another", "another-digest")
