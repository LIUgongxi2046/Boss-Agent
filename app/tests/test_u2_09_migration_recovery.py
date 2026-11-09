import hashlib
import sqlite3

import pytest
from nanobot.config.loader import set_config_path

from agent_migration_inventory import AgentMigrationInventory
from agent_recovery_checkpoint import AgentRecoveryCheckpoint
from agent_recovery_preflight import AgentRecoveryPreflight
from agent_run_store import RunStore
from agent_simulation_recovery import AgentSimulationRecovery
from agent_simulation_recovery_journal import AgentSimulationRecoveryJournal
from agent_simulation_snapshot import AgentSimulationSnapshot
from boss_memory_sessions import MemorySessionManager
from controls import ControlStore
from hermes_source_invalidation import begin_source_cleanup


@pytest.mark.parametrize("change", ["memory", "source"])
def test_snapshot_rejects_changed_state_and_preserves_history(tmp_path, change):
    set_config_path(tmp_path / "config.json")
    store = ControlStore(tmp_path / "business.sqlite")
    store.initialize("ui-check")
    RunStore(store.path)
    inventory = AgentMigrationInventory(store, allow_migration=True)
    checkpoint = AgentRecoveryCheckpoint(AgentRecoveryPreflight(store), allow_migration=True)
    snapshots = AgentSimulationSnapshot(checkpoint, tmp_path, allow_migration=True)
    journal = AgentSimulationRecoveryJournal(snapshots, allow_migration=True)
    recovery = AgentSimulationRecovery(snapshots, journal)
    sessions = MemorySessionManager(tmp_path / "workspace", business_store=store, sessions_root=tmp_path / "sessions")
    session = sessions.get_or_create("websocket:technical-history")
    sessions.save(session, fsync=True)

    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        first = inventory.record_in_transaction(db, "business-to-hermes")
        assert inventory.record_in_transaction(db, "business-to-hermes")["created"] is False
        saved = checkpoint.capture_in_transaction(db, "state")
    snapshot = snapshots.create("snapshot", "state", saved["checkpoint_id"])
    snapshot_path = tmp_path / snapshot["snapshot_name"]
    assert snapshots.create("snapshot", "state", saved["checkpoint_id"])["created"] is False
    checked = recovery.preflight("snapshot", max_age_seconds=300)
    assert checked["restore_state"] == "BLOCKED"
    assert checked["reason"] == "DELETION_LEDGER_COMPLETENESS_UNVERIFIED"
    with sqlite3.connect(snapshot_path.as_uri() + "?mode=ro", uri=True) as db:
        assert db.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
        assert db.execute("SELECT checkpoint_id FROM agent_recovery_checkpoints WHERE request_key='state'").fetchone() == (saved["checkpoint_id"],)

    reopened_inventory = AgentMigrationInventory(ControlStore(store.path))
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        assert reopened_inventory.record_in_transaction(db, "business-to-hermes")["input_digest"] == first["input_digest"]
    if change == "memory":
        with store.connect() as db:
            db.execute("DELETE FROM objects WHERE namespace=? AND kind='memory' AND id='current'", ("ui-check",))
    else:
        assert begin_source_cleanup(store, "ui-check", "finance-note", "1") is True
        store.control("ui-check", "withdraw", {"source_id": "finance-note", "version": "1"})
    with pytest.raises(ValueError, match="当前状态已经变化"):
        recovery.preflight("snapshot", max_age_seconds=300)
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        with pytest.raises(ValueError, match="当前状态已经变化"):
            checkpoint.verify_in_transaction(db, "state", saved["checkpoint_id"])
        with pytest.raises(ValueError, match="业务资料已经变化"):
            reopened_inventory.record_in_transaction(db, "business-to-hermes")
    with snapshot_path.open("rb") as content:
        assert hashlib.file_digest(content, "sha256").hexdigest() == snapshot["sha256"]
    reopened_sessions = MemorySessionManager(tmp_path / "workspace", business_store=ControlStore(store.path), sessions_root=tmp_path / "sessions")
    assert reopened_sessions.read_session_snapshot(session.key).messages == []
    assert not (tmp_path / "recovery").exists()
