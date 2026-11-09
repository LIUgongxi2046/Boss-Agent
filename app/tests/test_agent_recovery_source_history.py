import sqlite3
from contextlib import closing

import pytest

from agent_recovery_checkpoint import AgentRecoveryCheckpoint
from agent_recovery_preflight import AgentRecoveryPreflight
from agent_run_store import RunStore
from agent_simulation_recovery import AgentSimulationRecovery
from agent_simulation_recovery_journal import AgentSimulationRecoveryJournal
from agent_simulation_snapshot import AgentSimulationSnapshot
from controls import ControlStore
from hermes_source_invalidation import begin_source_cleanup


def test_withdrawal_changes_checkpoint_and_missing_history_is_visible(tmp_path):
    store = ControlStore(tmp_path / "business.sqlite")
    store.initialize("ui-check")
    RunStore(store.path)
    preflight = AgentRecoveryPreflight(store)
    checkpoint = AgentRecoveryCheckpoint(preflight, allow_migration=True)
    snapshots = AgentSimulationSnapshot(checkpoint, tmp_path, allow_migration=True)
    journal = AgentSimulationRecoveryJournal(snapshots, allow_migration=True)
    recovery = AgentSimulationRecovery(snapshots, journal)
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        initial = preflight.current_state_in_transaction(db)
        original_id = checkpoint.capture_in_transaction(db, "before")["checkpoint_id"]
    before = snapshots.create("before", "before", original_id)
    assert snapshots.create("before", "before", original_id)["created"] is False
    assert begin_source_cleanup(store, "ui-check", "finance-note", "1")
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        pending = preflight.current_state_in_transaction(db)
        assert "SOURCE_CLEANUP" in pending["pending"]
        assert pending["state_sha256"] != initial["state_sha256"]
        with pytest.raises(ValueError, match="当前状态已经变化"):
            checkpoint.verify_in_transaction(db, "before", original_id)
        store.control_withdraw(db, "ui-check", {"source_id": "finance-note", "version": "1"})
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        withdrawn = preflight.current_state_in_transaction(db)
        assert "SOURCE_WITHDRAWAL_HISTORY_MISSING" in withdrawn["pending"]
        assert "SOURCE_CLEANUP" not in withdrawn["pending"]
        assert withdrawn["state_sha256"] != pending["state_sha256"]
        assert withdrawn["restore_state"] == "BLOCKED"
        changed_id = checkpoint.capture_in_transaction(db, "after")["checkpoint_id"]
    with pytest.raises(ValueError, match="当前状态已经变化"):
        snapshots.create("before", "before", original_id)
    after = snapshots.create("after", "after", changed_id)
    assert after["manifest"]["state_sha256"] == withdrawn["state_sha256"]
    assert snapshots.create("after", "after", changed_id)["created"] is False
    assert recovery.preflight("after", max_age_seconds=300)["restore_state"] == "BLOCKED"
    with closing(sqlite3.connect((tmp_path / after["snapshot_name"]).as_uri() + "?mode=ro", uri=True)) as db:
        assert db.execute("SELECT json_extract(body,'$.withdrawn') FROM objects WHERE namespace='ui-check' AND kind='document' AND id='finance-note'").fetchone() == (1,)
        assert db.execute("SELECT json_extract(body,'$.state') FROM objects WHERE namespace='ui-check' AND kind='hermes_source_cleanup' AND id='finance-note'").fetchone() == ("COMPLETED",)
    assert (tmp_path / before["snapshot_name"]).is_file()


def test_withdrawn_source_without_cleanup_is_not_treated_as_complete(tmp_path):
    store = ControlStore(tmp_path / "business.sqlite")
    store.initialize("ui-check")
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        store.control_withdraw(db, "ui-check", {"source_id": "finance-note", "version": "1"})
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        result = AgentRecoveryPreflight(store).current_state_in_transaction(db)
        assert "SOURCE_WITHDRAWAL_HISTORY_MISSING" in result["pending"]
        assert "SOURCE_WITHDRAWAL_HISTORY_UNVERIFIED" not in result["pending"]
        assert result["source_missing_count"] == 1
        assert result["restore_state"] == "BLOCKED"


def test_deleted_source_after_withdrawal_blocks_recovery_without_error(tmp_path):
    store = ControlStore(tmp_path / "business.sqlite")
    store.initialize("ui-check")
    RunStore(store.path)
    assert store.control("ui-check", "withdraw", {"source_id": "finance-note", "version": "1"})["withdrawn"] is True
    preflight = AgentRecoveryPreflight(store)
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute("DELETE FROM objects WHERE namespace=? AND kind='document' AND id=?", ("ui-check", "finance-note"))
        state = preflight.current_state_in_transaction(db)
        assert "SOURCE_DELETED" in state["pending"]
        assert state["source_event_count"] == 1
        assert state["source_missing_count"] == 1
        assert state["source_history_complete"] is False
        assert state["restore_state"] == "BLOCKED"
        db.rollback()
    with store.connect() as db:
        assert db.execute("SELECT count(*) FROM objects WHERE namespace=? AND kind='document' AND id=?", ("ui-check", "finance-note")).fetchone() == (1,)


def test_recorded_withdrawal_is_checked_but_complete_history_remains_unverified(tmp_path):
    store = ControlStore(tmp_path / "business.sqlite")
    store.initialize("ui-check")
    RunStore(store.path)
    preflight = AgentRecoveryPreflight(store)
    checkpoint = AgentRecoveryCheckpoint(preflight, allow_migration=True)
    snapshots = AgentSimulationSnapshot(checkpoint, tmp_path, allow_migration=True)
    source = {"source_id": "finance-note", "version": "1"}
    assert store.control("ui-check", "withdraw", source)["withdrawn"] is True
    assert store.control("ui-check", "withdraw", source)["withdrawn"] is True
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        state = preflight.current_state_in_transaction(db)
        assert state["source_event_count"] == 1
        assert state["source_missing_count"] == 0
        assert state["source_history_complete"] is False
        assert "SOURCE_WITHDRAWAL_HISTORY_UNVERIFIED" in state["pending"]
        assert "SOURCE_WITHDRAWAL_HISTORY_MISSING" not in state["pending"]
        assert state["restore_state"] == "BLOCKED"
        checkpoint_id = checkpoint.capture_in_transaction(db, "recorded")["checkpoint_id"]
    snapshot = snapshots.create("recorded", "recorded", checkpoint_id)
    assert snapshots.create("recorded", "recorded", checkpoint_id)["created"] is False
    with closing(sqlite3.connect((tmp_path / snapshot["snapshot_name"]).as_uri() + "?mode=ro", uri=True)) as db:
        assert db.execute("SELECT count(*) FROM objects WHERE kind='source_withdrawal_event'").fetchone() == (1,)
