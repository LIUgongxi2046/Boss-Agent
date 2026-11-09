import multiprocessing
import os
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from aiohttp import web

from agent_run_concurrency import RunConcurrencyBudget
from agent_run_store import RunStore
from hermes_bridge import EngineEventSink, EngineRunConfig
from hermes_cpu_budget import HermesCPUBudget, vm_cpu_allocation_seconds
from hermes_process_evidence import HermesProcessEvidence
from hermes_vm_identity import HermesVMRunAccess, HermesVMRunBindings
from hermes_runtime_transport import record_vm_exit_recovery
from test_hermes_process_evidence import expire_lease


def reserve_then_interrupt(path, identity):
    store = RunStore(path, allow_migration=False)
    bindings = HermesVMRunBindings(store)
    cpu = HermesCPUBudget(store)
    access = HermesVMRunAccess(bindings, *identity)
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        cpu.reserve_in_transaction(db, access, 60)
        os._exit(17)


def family(path, limit=100):
    store = RunStore(path / "runs.sqlite")
    concurrency = RunConcurrencyBudget(store, allow_migration=True)
    evidence = HermesProcessEvidence(store, allow_migration=True)
    bindings = HermesVMRunBindings(store, allow_migration=True)
    cpu = HermesCPUBudget(store, allow_migration=True)
    root = store.create_run("boss-1", "ui-check", "root", "root-digest")
    root_lease = store.acquire_lease(root, 0, "root-worker", 60)
    store.transition(root, root_lease["revision"], "RUNNING", "root-worker", root_lease["epoch"])
    concurrency.configure(root, "root-worker", root_lease["epoch"], 2)
    child = store.create_child_run(root, "root-worker", root_lease["epoch"], "child", "child-digest")
    child_lease = store.acquire_lease(child, 0, "child-worker", 60)
    store.transition(child, child_lease["revision"], "RUNNING", "child-worker", child_lease["epoch"])
    vm_id, boot_id = str(uuid4()), str(uuid4())
    access = []
    for run_id, owner, lease in ((root, "root-worker", root_lease), (child, "child-worker", child_lease)):
        workspace = path / run_id
        workspace.mkdir()
        with store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            concurrency.reserve_in_transaction(db, run_id, owner, lease["epoch"], "slot", "digest")
            evidence.record_vm_start_in_transaction(db, bindings, run_id, "slot", "digest", owner, lease["epoch"],
                                                    "boss-1", "ui-check", vm_id, boot_id, workspace)
        access.append(HermesVMRunAccess(bindings, run_id, "slot", owner, lease["epoch"], vm_id, boot_id, workspace))
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        cpu.configure_in_transaction(db, root, "root-worker", root_lease["epoch"], limit)
    return store, cpu, root, access


def test_approved_concurrency_allocates_cpu_to_parent_and_child(tmp_path):
    budget = {"cpu_seconds": 100, "concurrency": 2}
    allocation = vm_cpu_allocation_seconds(budget)
    assert allocation == 50
    store, cpu, root, accesses = family(tmp_path, limit=100_000_000_000)

    def reserve(access):
        with store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            return cpu.reserve_in_transaction(db, access, allocation * 1_000_000_000)

    with ThreadPoolExecutor(max_workers=2) as executor:
        assert list(executor.map(reserve, accesses)) == [True, True]
    with store.connect() as db:
        assert db.execute("SELECT root_run_id,sum(reserved_ns),count(*) FROM hermes_cpu_reservations").fetchone() == (root, 100_000_000_000, 2)
    assert vm_cpu_allocation_seconds({"cpu_seconds": 23, "concurrency": 3}) == 7
    with pytest.raises(web.HTTPTooManyRequests) as insufficient:
        vm_cpu_allocation_seconds({"cpu_seconds": 1, "concurrency": 2})
    assert "并发额度" in insufficient.value.text


def test_parent_and_child_compete_for_one_cpu_budget(tmp_path):
    store, cpu, root, accesses = family(tmp_path)

    def reserve(access):
        with store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            return cpu.reserve_in_transaction(db, access, 60)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(reserve, access) for access in accesses]
    errors = [future.exception() for future in futures]
    assert sum(error is None for error in errors) == 1
    assert [str(error) for error in errors if error is not None] == ["CPU 预算不足"]
    winner = accesses[errors.index(None)]
    assert reserve(winner) is False
    reopened = RunStore(store.path, allow_migration=False)
    HermesCPUBudget(reopened)
    with reopened.connect() as db:
        assert db.execute("SELECT root_run_id,reserved_ns,observed_ns FROM hermes_cpu_reservations").fetchall() == [(root, 60, 0)]
    expire_lease(store, winner.run_id)
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        with pytest.raises(ValueError):
            cpu.reserve_in_transaction(db, winner, 60)
        assert db.execute("SELECT reserved_ns FROM hermes_cpu_reservations").fetchall() == [(60,)]


def test_cancel_recovery_requires_vm_final_receipt(tmp_path):
    store, _, root, accesses = family(tmp_path)
    access = accesses[0]
    config = EngineRunConfig(root, access.epoch, '903230b1e23e0c496b28e5d2e8c4f2639cd506b6', 'http://127.0.0.1:12345', 1)
    sink = EngineEventSink(store, config, access.owner)
    store.cancel(root, store.read_run(root)['revision'])
    with pytest.raises(ValueError, match='尚未完成结算'):
        record_vm_exit_recovery(sink, access, False)
    assert store.read_run(root)['status'] == 'CANCEL_REQUESTED'
    with store.connect() as db:
        assert db.execute("SELECT state FROM agent_concurrency_reservations WHERE run_id=? AND request_key=?", (root, 'slot')).fetchone() == ('ACTIVE',)


def test_rolled_back_cpu_reservation_does_not_consume_budget(tmp_path):
    store, cpu, root, accesses = family(tmp_path)
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        assert cpu.reserve_in_transaction(db, accesses[0], 60)
        db.rollback()
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        assert cpu.reserve_in_transaction(db, accesses[1], 100)
    with store.connect() as db:
        assert db.execute("SELECT root_run_id,reserved_ns FROM hermes_cpu_reservations").fetchall() == [(root, 100)]


def test_parent_and_child_can_reserve_within_shared_limit(tmp_path):
    store, cpu, root, accesses = family(tmp_path)

    def reserve(access):
        with store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            return cpu.reserve_in_transaction(db, access, 40)

    with ThreadPoolExecutor(max_workers=2) as executor:
        assert list(executor.map(reserve, accesses)) == [True, True]
    with store.connect() as db:
        assert db.execute("SELECT root_run_id,sum(reserved_ns),count(*) FROM hermes_cpu_reservations").fetchone() == (root, 80, 2)


def test_cpu_budget_can_be_opened_inside_launch_transaction(tmp_path):
    store, _, root, accesses = family(tmp_path)
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        cpu = HermesCPUBudget(store)
        assert cpu.reserve_in_transaction(db, accesses[0], 40)
    with store.connect() as db:
        assert db.execute("SELECT root_run_id,reserved_ns FROM hermes_cpu_reservations").fetchall() == [(root, 40)]


def test_process_interruption_rolls_back_pending_cpu_reservation(tmp_path):
    store, cpu, root, accesses = family(tmp_path)
    access = accesses[0]
    identity = (access.run_id, access.request_key, access.owner, access.epoch, access.vm_id, access.boot_id, access.workspace)
    process = multiprocessing.get_context("spawn").Process(target=reserve_then_interrupt, args=(store.path, identity))
    process.start()
    process.join(timeout=15)
    assert process.exitcode == 17
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        assert db.execute("SELECT count(*) FROM hermes_cpu_reservations").fetchone() == (0,)
        assert cpu.reserve_in_transaction(db, accesses[1], 100)
    with store.connect() as db:
        assert db.execute("SELECT root_run_id,reserved_ns FROM hermes_cpu_reservations").fetchall() == [(root, 100)]


def test_expired_child_epoch_retains_unknown_cpu_reservation(tmp_path):
    store, cpu, root, accesses = family(tmp_path)
    parent, child = accesses
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        assert cpu.reserve_in_transaction(db, child, 60)
    expire_lease(store, child.run_id)
    store.interrupt_expired(child.run_id)
    with pytest.raises(ValueError, match="进程状态记录已保存"):
        store.acquire_lease(child.run_id, store.read_run(child.run_id)["revision"], "new-worker", 60)
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        with pytest.raises(ValueError):
            cpu.reserve_in_transaction(db, child, 60)
        with pytest.raises(ValueError, match="CPU 预留状态不可核查"):
            cpu.reserve_in_transaction(db, parent, 10)
        assert db.execute("SELECT root_run_id,lease_epoch,reserved_ns FROM hermes_cpu_reservations").fetchall() == [(root, child.epoch, 60)]


def test_unknown_concurrency_requires_final_vm_receipt(tmp_path):
    store, cpu, _, accesses = family(tmp_path)
    child = accesses[1]
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        assert cpu.reserve_in_transaction(db, child, 60)
    expire_lease(store, child.run_id)
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        assert RunConcurrencyBudget(store).mark_unknown_in_transaction(db, child.run_id, child.request_key) == "UNKNOWN"
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("UPDATE agent_concurrency_reservations SET state='RELEASED' WHERE run_id=? AND request_key=?", (child.run_id, child.request_key))
    with store.connect() as db:
        assert db.execute("SELECT state FROM agent_concurrency_reservations WHERE run_id=? AND request_key=?", (child.run_id, child.request_key)).fetchone() == ("UNKNOWN",)
