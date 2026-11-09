import sqlite3
import sys
import hashlib
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest

from hermes_guest_identity import HermesGuestIdentityRegistry, identity_for_run


def workspace_for(run_id):
    return {"root_run_id": run_id, "root_epoch": 1, "max_files": 5, "max_bytes": 1024}


def test_absent_control_identity_remains_unknown_without_accepting_changed_identity(tmp_path):
    tmp_path.chmod(0o700)
    registry = HermesGuestIdentityRegistry(tmp_path.resolve())
    run_id, boot_id = str(uuid4()), str(uuid4())
    assert registry.control_state_or_none(run_id, 1, boot_id) is None
    assert registry.has_final_exit(run_id, 1, boot_id) is False
    with pytest.raises(ValueError, match="不可核查"):
        registry.read_control(run_id, 1, boot_id)
    digest = hashlib.sha256(b"control identity").hexdigest()
    registry.reserve_start(run_id, 1, boot_id, digest, workspace_for(run_id))
    assert registry.control_state_or_none(run_id, 1, boot_id) == "RESERVED"
    with pytest.raises(ValueError, match="不可核查"):
        registry.control_state_or_none(run_id, 1, str(uuid4()))


def test_unknown_exit_receipt_is_durable_and_immutable(tmp_path):
    tmp_path.chmod(0o700)
    registry = HermesGuestIdentityRegistry(tmp_path.resolve())
    run_id, boot_id = str(uuid4()), str(uuid4())
    digest = hashlib.sha256(b"independent control request").hexdigest()
    unit, _ = registry.reserve_start(run_id, 1, boot_id, digest, workspace_for(run_id))
    with pytest.raises(ValueError, match="退出身份不可核查"):
        registry.record_unknown_exit(run_id, 1, boot_id)
    registry.mark_stopped(run_id, 1, boot_id)
    expected = {"run_id": run_id, "epoch": 1, "boot_id": boot_id, "unit": unit, "state": "UNKNOWN", "cpu_ns": None}
    assert registry.record_unknown_exit(run_id, 1, boot_id) == expected
    assert registry.record_unknown_exit(run_id, 1, boot_id) == expected
    reopened = HermesGuestIdentityRegistry(tmp_path.resolve())
    assert reopened.read_exit(run_id, 1, boot_id) == expected
    with pytest.raises(ValueError):
        reopened.read_exit(run_id, 1, str(uuid4()))
    with reopened.connect() as db:
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("UPDATE guest_exit_receipts SET state='CONFIRMED' WHERE run_id=?", (run_id,))
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("DELETE FROM guest_exit_receipts WHERE run_id=?", (run_id,))


def test_guest_identity_reservation_persists_and_cannot_be_reassigned(tmp_path):
    tmp_path.chmod(0o700)
    registry = HermesGuestIdentityRegistry(tmp_path.resolve())
    run_id = str(uuid4())
    account, uid = identity_for_run(run_id)
    assert registry.reserve(run_id) == (account, uid, "RESERVED")
    reopened = HermesGuestIdentityRegistry(tmp_path.resolve())
    assert reopened.reserve(run_id) == (account, uid, "RESERVED")
    with reopened.connect() as db:
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("UPDATE guest_identities SET uid=uid+1 WHERE run_id=?", (run_id,))
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("DELETE FROM guest_identities WHERE run_id=?", (run_id,))


def test_guest_identity_rejects_invalid_directory_permissions(tmp_path):
    tmp_path.chmod(0o755)
    with pytest.raises(ValueError, match="目录权限无效"):
        HermesGuestIdentityRegistry(tmp_path.resolve())


def test_guest_control_registration_survives_restart_and_blocks_replay(tmp_path):
    tmp_path.chmod(0o700)
    registry = HermesGuestIdentityRegistry(tmp_path.resolve())
    run_id, boot_id = str(uuid4()), str(uuid4())
    digest = hashlib.sha256(b"actual independent control request").hexdigest()
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: registry.reserve_start(run_id, 1, boot_id, digest, workspace_for(run_id)), range(2)))
    assert {item[1] for item in results} == {True, False}
    assert results[0][0] == results[1][0]
    reopened = HermesGuestIdentityRegistry(tmp_path.resolve())
    assert reopened.reserve_start(run_id, 1, boot_id, digest, workspace_for(run_id)) == (results[0][0], False)
    with pytest.raises(ValueError, match="工作区身份已经变化"):
        reopened.reserve_start(run_id, 1, boot_id, digest, {**workspace_for(run_id), "max_files": 6})
    with reopened.connect() as db:
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("UPDATE guest_workspace_bindings SET max_files=6 WHERE run_id=?", (run_id,))
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("DELETE FROM guest_workspace_bindings WHERE run_id=?", (run_id,))
    with pytest.raises(ValueError, match="已经变化或停止"):
        reopened.reserve_start(run_id, 1, boot_id, hashlib.sha256(b"other request").hexdigest(), workspace_for(run_id))
    assert reopened.mark_stopped(run_id, 1, boot_id) == (results[0][0], True)
    with pytest.raises(ValueError, match="已经变化或停止"):
        HermesGuestIdentityRegistry(tmp_path.resolve()).reserve_start(run_id, 1, boot_id, digest, workspace_for(run_id))
    with pytest.raises(ValueError, match="不可核查"):
        reopened.read_control(run_id, 1, str(uuid4()))


def test_guest_stop_before_start_persists_tombstone(tmp_path):
    tmp_path.chmod(0o700)
    registry = HermesGuestIdentityRegistry(tmp_path.resolve())
    run_id, boot_id = str(uuid4()), str(uuid4())
    unit, existed = registry.mark_stopped(run_id, 1, boot_id)
    assert not existed
    assert registry.read_control(run_id, 1, boot_id) == "STOPPED"
    with pytest.raises(ValueError, match="已经变化或停止"):
        HermesGuestIdentityRegistry(tmp_path.resolve()).reserve_start(run_id, 1, boot_id, hashlib.sha256(b"late request").hexdigest(), workspace_for(run_id))
    assert unit == "boss-" + run_id + "-1.service"


def test_workspace_domain_and_run_bindings_are_immutable(tmp_path):
    tmp_path.chmod(0o700)
    registry = HermesGuestIdentityRegistry(tmp_path.resolve())
    root, child, boot_id = str(uuid4()), str(uuid4()), str(uuid4())
    digest = hashlib.sha256(b"workspace binding").hexdigest()
    domain = workspace_for(root)
    registry.reserve_start(root, 1, boot_id, digest, domain)
    registry.reserve_start(child, 1, boot_id, digest, domain)
    with pytest.raises(ValueError, match="根额度已经变化"):
        registry.reserve_start(str(uuid4()), 1, boot_id, digest, {**domain, "max_files": 6})
    with pytest.raises(ValueError, match="归属已经变化"):
        registry.reserve_start(child, 2, boot_id, digest, workspace_for(str(uuid4())))
    with registry.connect() as db:
        assert db.execute("SELECT count(*) FROM guest_workspace_domains").fetchone() == (1,)
        assert db.execute("SELECT count(*) FROM guest_workspace_runs").fetchone() == (2,)


@pytest.mark.skipif(sys.platform == "linux", reason="此检查针对非 Linux 宿主")
def test_guest_identity_does_not_provision_accounts_on_host(tmp_path):
    tmp_path.chmod(0o700)
    registry = HermesGuestIdentityRegistry(tmp_path.resolve())
    with pytest.raises(ValueError, match="需要 Linux 系统管理权限"):
        registry.ensure(str(uuid4()))
    with registry.connect() as db:
        assert db.execute("SELECT count(*) FROM guest_identities").fetchone() == (0,)
