import multiprocessing
import os
import sqlite3

import pytest

from agent_recovery_checkpoint import AgentRecoveryCheckpoint
from agent_recovery_preflight import AgentRecoveryPreflight
from agent_run_store import RunStore
from controls import ControlStore
from hermes_source_invalidation import begin_source_cleanup


def interrupted_capture(path):
    store = ControlStore(path)
    checkpoint = AgentRecoveryCheckpoint(AgentRecoveryPreflight(store))
    db = store.connect()
    db.execute("BEGIN IMMEDIATE")
    checkpoint.capture_in_transaction(db, "interrupted")
    os._exit(17)


def setup_checkpoint(tmp_path):
    store = ControlStore(tmp_path / "business.sqlite")
    store.initialize("ui-check")
    RunStore(store.path)
    checkpoint = AgentRecoveryCheckpoint(AgentRecoveryPreflight(store), allow_migration=True)
    return store, checkpoint


def test_checkpoint_tracks_current_source_and_memory_changes(tmp_path):
    store, checkpoint = setup_checkpoint(tmp_path)
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        first = checkpoint.capture_in_transaction(db, "request")
        assert first["created"] is True and first["restore_state"] == "BLOCKED"
        assert checkpoint.capture_in_transaction(db, "request")["created"] is False
        assert checkpoint.verify_in_transaction(db, "request", first["checkpoint_id"])["restore_state"] == "BLOCKED"
        with pytest.raises(ValueError, match="不存在或不匹配"):
            checkpoint.verify_in_transaction(db, "request", "0" * 64)
        with pytest.raises(ValueError, match="不存在或不匹配"):
            checkpoint.verify_in_transaction(db, "missing", first["checkpoint_id"])
        db.execute("DELETE FROM objects WHERE namespace=? AND kind='memory' AND id='current'", ("ui-check",))
        with pytest.raises(ValueError, match="当前状态已经变化"):
            checkpoint.verify_in_transaction(db, "request", first["checkpoint_id"])
        db.rollback()
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        first = checkpoint.capture_in_transaction(db, "request")
    assert begin_source_cleanup(store, "ui-check", "finance-note", "1")
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        with pytest.raises(ValueError, match="当前状态已经变化"):
            checkpoint.verify_in_transaction(db, "request", first["checkpoint_id"])
        with pytest.raises(ValueError, match="当前状态已经变化"):
            checkpoint.capture_in_transaction(db, "request")


def test_checkpoint_rejects_forged_record_and_interrupted_transaction(tmp_path):
    store, checkpoint = setup_checkpoint(tmp_path)
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute("INSERT INTO agent_recovery_checkpoints VALUES (?,?,?,?,?)", ("ui-check", "forged", "a" * 64, "{}", "2026-10-30"))
        with pytest.raises(ValueError, match="当前状态已经变化"):
            checkpoint.verify_in_transaction(db, "forged", "a" * 64)
    process = multiprocessing.get_context("spawn").Process(target=interrupted_capture, args=(store.path,))
    process.start()
    process.join(timeout=60)
    assert process.exitcode == 17
    reopened = ControlStore(store.path)
    recovery = AgentRecoveryCheckpoint(AgentRecoveryPreflight(reopened))
    with reopened.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        assert db.execute("SELECT count(*) FROM agent_recovery_checkpoints WHERE request_key='interrupted'").fetchone() == (0,)
        assert recovery.capture_in_transaction(db, "interrupted")["created"] is True
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("DELETE FROM agent_recovery_checkpoints")
