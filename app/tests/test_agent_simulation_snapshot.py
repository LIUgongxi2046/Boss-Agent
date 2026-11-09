import multiprocessing
import os
import sqlite3

import pytest

from agent_recovery_checkpoint import AgentRecoveryCheckpoint
from agent_recovery_preflight import AgentRecoveryPreflight
from agent_run_store import RunStore
from agent_simulation_snapshot import AgentSimulationSnapshot
from controls import ControlStore
from hermes_source_invalidation import begin_source_cleanup


def interrupted_copy(source, target):
    with sqlite3.connect(source) as original, sqlite3.connect(target) as copy:
        original.backup(copy)
    os._exit(17)


def setup_snapshot(tmp_path):
    store = ControlStore(tmp_path / "business.sqlite")
    store.initialize("ui-check")
    RunStore(store.path)
    checkpoint = AgentRecoveryCheckpoint(AgentRecoveryPreflight(store), allow_migration=True)
    service = AgentSimulationSnapshot(checkpoint, tmp_path, allow_migration=True)
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        record = checkpoint.capture_in_transaction(db, "source-state")
    return store, checkpoint, service, record["checkpoint_id"]


def test_simulated_snapshot_reopens_and_rejects_changed_file(tmp_path):
    store, _, service, checkpoint_id = setup_snapshot(tmp_path)
    result = service.create("snapshot-request", "source-state", checkpoint_id)
    assert result["created"] is True and result["restore_state"] == "BLOCKED"
    assert result["manifest"]["coverage"] == ["business_sqlite"]
    assert result["manifest"]["namespace"] == "ui-check"
    repeated = service.create("snapshot-request", "source-state", checkpoint_id)
    assert repeated["created"] is False and repeated["sha256"] == result["sha256"]
    snapshot = tmp_path / result["snapshot_name"]
    with sqlite3.connect(snapshot) as db:
        assert db.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert db.execute("SELECT checkpoint_id FROM agent_recovery_checkpoints WHERE request_key='source-state'").fetchone() == (checkpoint_id,)
        db.execute("DELETE FROM objects WHERE namespace=? AND kind='memory' AND id='current'", ("ui-check",))
    with pytest.raises(ValueError, match="摘要不符"):
        service.create("snapshot-request", "source-state", checkpoint_id)
    with store.connect() as db:
        assert store.get(db, "ui-check", "memory", "current") is not None


def test_changed_current_source_and_missing_checkpoint_are_rejected(tmp_path):
    store, checkpoint, service, checkpoint_id = setup_snapshot(tmp_path)
    with pytest.raises(ValueError, match="仅允许独立模拟目录"):
        AgentSimulationSnapshot(checkpoint, tmp_path.anchor)
    with pytest.raises(ValueError, match="不存在或不匹配"):
        service.create("missing", "source-state", "0" * 64)
    assert begin_source_cleanup(store, "ui-check", "finance-note", "1")
    with pytest.raises(ValueError, match="当前状态已经变化"):
        service.create("changed", "source-state", checkpoint_id)
    with store.connect() as db:
        assert db.execute("SELECT count(*) FROM agent_simulation_snapshots").fetchone() == (0,)


def test_unrecorded_interrupted_copy_does_not_block_new_snapshot(tmp_path):
    store, _, service, checkpoint_id = setup_snapshot(tmp_path)
    abandoned = tmp_path / "interrupted.sqlite"
    process = multiprocessing.get_context("spawn").Process(target=interrupted_copy, args=(store.path, abandoned))
    process.start()
    process.join(timeout=60)
    assert process.exitcode == 17 and abandoned.is_file()
    result = service.create("after-interruption", "source-state", checkpoint_id)
    assert result["created"] is True and abandoned.is_file()
    assert service.create("after-interruption", "source-state", checkpoint_id)["created"] is False
