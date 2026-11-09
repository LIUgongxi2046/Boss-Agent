from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest

from hermes_vm_identity import HermesVMRunAccess, HermesVMRunBindings
from agent_run_launch_transaction import RunLaunchTransaction
from test_hermes_process_evidence import expire_lease, running_process_store
from test_agent_run_concurrency import running_family
from hermes_process_evidence import HermesProcessEvidence


def test_vm_workspace_context_requires_active_root_budget(tmp_path):
    store, _, evidence, run_id, epoch = running_process_store(tmp_path)
    bindings = HermesVMRunBindings(store, allow_migration=True)
    workspace = tmp_path / run_id
    workspace.mkdir()
    vm_id, boot_id = str(uuid4()), str(uuid4())
    with RunLaunchTransaction(store).hold(run_id, "worker", epoch) as db:
        unit = evidence.record_vm_start_in_transaction(db, bindings, run_id, "slot", "digest", "worker", epoch,
                                                       "boss-1", "ui-check", vm_id, boot_id, workspace)
    access = HermesVMRunAccess(bindings, run_id, "slot", "worker", epoch, vm_id, boot_id, workspace)
    with pytest.raises(ValueError, match="额度或版本不可核查"):
        access.require_workspace_context()
    store.configure_file_budget(run_id, "worker", epoch, 5, 1024)
    assert access.require_workspace_context() == {"unit": unit, "root_run_id": run_id, "root_epoch": epoch,
                                                   "max_files": 5, "max_bytes": 1024}
    expire_lease(store, run_id)
    with pytest.raises(ValueError):
        access.require_workspace_context()


def test_child_vm_workspace_context_uses_root_budget(tmp_path):
    store, concurrency, root, root_lease, child, child_lease = running_family(tmp_path)
    store.configure_file_budget(root, "root-worker", root_lease["epoch"], 5, 1024)
    evidence = HermesProcessEvidence(store, allow_migration=True)
    bindings = HermesVMRunBindings(store, allow_migration=True)
    workspace = tmp_path / child
    workspace.mkdir()
    vm_id, boot_id = str(uuid4()), str(uuid4())
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        concurrency.reserve_in_transaction(db, child, "child-worker", child_lease["epoch"], "slot", "digest")
        unit = evidence.record_vm_start_in_transaction(db, bindings, child, "slot", "digest", "child-worker", child_lease["epoch"],
                                                       "boss-1", "ui-check", vm_id, boot_id, workspace)
    access = HermesVMRunAccess(bindings, child, "slot", "child-worker", child_lease["epoch"], vm_id, boot_id, workspace)
    assert access.require_workspace_context() == {"unit": unit, "root_run_id": root, "root_epoch": root_lease["epoch"],
                                                   "max_files": 5, "max_bytes": 1024}


def test_vm_binding_is_transactional_and_rejects_changed_identity(tmp_path):
    store, _, evidence, run_id, epoch = running_process_store(tmp_path)
    bindings = HermesVMRunBindings(store, allow_migration=True)
    workspace = tmp_path / run_id
    workspace.mkdir()
    vm_id, boot_id = str(uuid4()), str(uuid4())
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        unit = evidence.record_vm_start_in_transaction(db, bindings, run_id, "slot", "digest", "worker", epoch,
                                                       "boss-1", "ui-check", vm_id, boot_id, workspace)
        assert bindings.register_in_transaction(db, run_id, "slot", "worker", epoch, vm_id, boot_id, workspace) == unit
        with pytest.raises(ValueError, match="绑定已经变化"):
            bindings.register_in_transaction(db, run_id, "slot", "worker", epoch, vm_id, str(uuid4()), workspace)
    with store.connect() as db:
        assert db.execute("SELECT run_id,request_key,vm_id,boot_id,unit_name FROM hermes_vm_run_bindings").fetchone() == (run_id, "slot", vm_id, boot_id, unit)
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        with pytest.raises(ValueError):
            bindings.register_in_transaction(db, run_id, "slot", "other", epoch, vm_id, boot_id, workspace)


def test_vm_binding_rolls_back_when_workspace_is_wrong(tmp_path):
    store, _, evidence, run_id, epoch = running_process_store(tmp_path)
    bindings = HermesVMRunBindings(store, allow_migration=True)
    workspace = tmp_path / "other"
    workspace.mkdir()
    with pytest.raises(ValueError, match="工作区无效"):
        with store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            evidence.record_vm_start_in_transaction(db, bindings, run_id, "slot", "digest", "worker", epoch,
                                                    "boss-1", "ui-check", str(uuid4()), str(uuid4()), workspace)
    with store.connect() as db:
        assert db.execute("SELECT count(*) FROM hermes_process_evidence").fetchone() == (0,)
        assert db.execute("SELECT count(*) FROM hermes_vm_run_bindings").fetchone() == (0,)


def test_failed_binding_does_not_leave_evidence_when_caller_continues(tmp_path):
    store, _, evidence, run_id, epoch = running_process_store(tmp_path)
    bindings = HermesVMRunBindings(store, allow_migration=True)
    workspace = tmp_path / "other"
    workspace.mkdir()
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        with pytest.raises(ValueError, match="工作区无效"):
            evidence.record_vm_start_in_transaction(db, bindings, run_id, "slot", "digest", "worker", epoch,
                                                    "boss-1", "ui-check", str(uuid4()), str(uuid4()), workspace)
        assert db.execute("SELECT count(*) FROM hermes_process_evidence").fetchone() == (0,)


def test_expired_lease_and_other_run_workspace_are_rejected(tmp_path):
    store, _, evidence, run_id, epoch = running_process_store(tmp_path)
    bindings = HermesVMRunBindings(store, allow_migration=True)
    workspace = tmp_path / run_id
    workspace.mkdir()
    vm_id, boot_id = str(uuid4()), str(uuid4())
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        evidence.record_vm_start_in_transaction(db, bindings, run_id, "slot", "digest", "worker", epoch,
                                                "boss-1", "ui-check", vm_id, boot_id, workspace)
    other_workspace = tmp_path / str(uuid4())
    other_workspace.mkdir()
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        with pytest.raises(ValueError, match="工作区无效"):
            bindings.register_in_transaction(db, run_id, "slot", "worker", epoch, vm_id, boot_id, other_workspace)
    expire_lease(store, run_id)
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        with pytest.raises(ValueError):
            bindings.register_in_transaction(db, run_id, "slot", "worker", epoch, vm_id, boot_id, workspace)


def test_vm_start_requires_caller_transaction(tmp_path):
    store, _, evidence, run_id, epoch = running_process_store(tmp_path)
    bindings = HermesVMRunBindings(store, allow_migration=True)
    workspace = tmp_path / run_id
    workspace.mkdir()
    with store.connect() as db:
        assert not db.in_transaction
        with pytest.raises(ValueError, match="当前数据库事务"):
            evidence.record_vm_start_in_transaction(db, bindings, run_id, "slot", "digest", "worker", epoch,
                                                    "boss-1", "ui-check", str(uuid4()), str(uuid4()), workspace)
        assert not db.in_transaction
    with store.connect() as db:
        assert db.execute("SELECT count(*) FROM hermes_process_evidence").fetchone() == (0,)
        assert db.execute("SELECT count(*) FROM hermes_vm_run_bindings").fetchone() == (0,)


def test_vm_start_respects_launch_transaction_rollback(tmp_path):
    store, _, evidence, run_id, epoch = running_process_store(tmp_path)
    bindings = HermesVMRunBindings(store, allow_migration=True)
    workspace = tmp_path / run_id
    workspace.mkdir()
    with RunLaunchTransaction(store).hold(run_id, "worker", epoch) as db:
        evidence.record_vm_start_in_transaction(db, bindings, run_id, "slot", "digest", "worker", epoch,
                                                "boss-1", "ui-check", str(uuid4()), str(uuid4()), workspace)
        assert db.in_transaction
        db.rollback()
    with store.connect() as db:
        for table in ("hermes_process_evidence", "hermes_vm_run_bindings", "hermes_vm_workspace_ownership"):
            assert db.execute("SELECT count(*) FROM " + table).fetchone() == (0,)


def test_vm_start_repeated_request_requires_identical_binding(tmp_path):
    store, _, evidence, run_id, epoch = running_process_store(tmp_path)
    bindings = HermesVMRunBindings(store, allow_migration=True)
    workspace = tmp_path / run_id
    workspace.mkdir()
    vm_id, boot_id = str(uuid4()), str(uuid4())
    with RunLaunchTransaction(store).hold(run_id, "worker", epoch) as db:
        unit = evidence.record_vm_start_in_transaction(db, bindings, run_id, "slot", "digest", "worker", epoch,
                                                       "boss-1", "ui-check", vm_id, boot_id, workspace)
        assert evidence.record_vm_start_in_transaction(db, bindings, run_id, "slot", "digest", "worker", epoch,
                                                        "boss-1", "ui-check", vm_id, boot_id, workspace) == unit
        with pytest.raises(ValueError):
            evidence.record_vm_start_in_transaction(db, bindings, run_id, "slot", "other", "worker", epoch,
                                                    "boss-1", "ui-check", vm_id, boot_id, workspace)
        with pytest.raises(ValueError, match="绑定已经变化"):
            evidence.record_vm_start_in_transaction(db, bindings, run_id, "slot", "digest", "worker", epoch,
                                                    "boss-1", "ui-check", vm_id, str(uuid4()), workspace)
    with RunLaunchTransaction(store).hold(run_id, "worker", epoch) as db:
        assert evidence.record_vm_start_in_transaction(db, bindings, run_id, "slot", "digest", "worker", epoch,
                                                        "boss-1", "ui-check", vm_id, boot_id, workspace) == unit
        assert db.execute("SELECT count(*) FROM hermes_process_evidence").fetchone() == (1,)
        assert db.execute("SELECT count(*) FROM hermes_vm_run_bindings").fetchone() == (1,)


def test_vm_start_rejects_existing_unbound_process(tmp_path):
    store, _, evidence, run_id, epoch = running_process_store(tmp_path)
    bindings = HermesVMRunBindings(store, allow_migration=True)
    workspace = tmp_path / run_id
    workspace.mkdir()
    with RunLaunchTransaction(store).hold(run_id, "worker", epoch) as db:
        evidence.record_start_in_transaction(db, run_id, "slot", "digest", "worker", epoch, "boss-1", "ui-check")
        with pytest.raises(ValueError, match="已有进程记录"):
            evidence.record_vm_start_in_transaction(db, bindings, run_id, "slot", "digest", "worker", epoch,
                                                    "boss-1", "ui-check", str(uuid4()), str(uuid4()), workspace)
        assert db.execute("SELECT count(*) FROM hermes_vm_run_bindings").fetchone() == (0,)


def test_vm_start_concurrent_identical_requests_share_binding(tmp_path):
    store, _, evidence, run_id, epoch = running_process_store(tmp_path)
    bindings = HermesVMRunBindings(store, allow_migration=True)
    workspace = tmp_path / run_id
    workspace.mkdir()
    vm_id, boot_id = str(uuid4()), str(uuid4())
    barrier = Barrier(2)

    def register():
        barrier.wait(timeout=10)
        with RunLaunchTransaction(store).hold(run_id, "worker", epoch) as db:
            return evidence.record_vm_start_in_transaction(db, bindings, run_id, "slot", "digest", "worker", epoch,
                                                           "boss-1", "ui-check", vm_id, boot_id, workspace)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: register(), range(2)))
    assert results[0] == results[1]
    with store.connect() as db:
        assert db.execute("SELECT count(*) FROM hermes_process_evidence").fetchone() == (1,)
        assert db.execute("SELECT count(*) FROM hermes_vm_run_bindings").fetchone() == (1,)


def test_vm_access_rejects_changed_boot_and_workspace_identity(tmp_path):
    store, _, evidence, run_id, epoch = running_process_store(tmp_path)
    bindings = HermesVMRunBindings(store, allow_migration=True)
    workspace = tmp_path / run_id
    workspace.mkdir()
    vm_id, boot_id = str(uuid4()), str(uuid4())
    with RunLaunchTransaction(store).hold(run_id, "worker", epoch) as db:
        unit = evidence.record_vm_start_in_transaction(db, bindings, run_id, "slot", "digest", "worker", epoch,
                                                       "boss-1", "ui-check", vm_id, boot_id, workspace)
    access = HermesVMRunAccess(bindings, run_id, "slot", "worker", epoch, vm_id, boot_id, workspace)
    assert access.require() == unit
    other_boot = HermesVMRunAccess(bindings, run_id, "slot", "worker", epoch, vm_id, str(uuid4()), workspace)
    with pytest.raises(ValueError, match="绑定不可核查"):
        other_boot.require()
    workspace.rename(tmp_path / "previous-workspace")
    workspace.mkdir()
    with pytest.raises(ValueError, match="绑定不可核查"):
        access.require()
