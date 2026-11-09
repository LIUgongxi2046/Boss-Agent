import sqlite3

import pytest

from agent_recovery_preflight import AgentRecoveryPreflight
from controls import ControlStore
from hermes_source_invalidation import begin_source_cleanup
from hermes_memory_adapter import HermesMemoryAdapter
from test_agent_run_result import setup_result


def test_current_recovery_state_tracks_changes_and_transaction_rollback(tmp_path):
    store = ControlStore(tmp_path / "business.sqlite")
    store.initialize("ui-check")
    preflight = AgentRecoveryPreflight(store)
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        before = preflight.current_state_in_transaction(db)
        assert before["restore_state"] == "BLOCKED"
        assert before["reason"] == "DELETION_LEDGER_COMPLETENESS_UNVERIFIED"
        assert before["memory_reference"]["eligible"] is True
        db.execute("DELETE FROM objects WHERE namespace=? AND kind='memory' AND id='current'", ("ui-check",))
        changed = preflight.current_state_in_transaction(db)
        assert changed["memory_reference"] is None
        assert changed["state_sha256"] != before["state_sha256"]
        db.rollback()
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        assert preflight.current_state_in_transaction(db) == before
    assert begin_source_cleanup(store, "ui-check", "finance-note", "1") is True
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        pending = preflight.current_state_in_transaction(db)
        assert pending["state_sha256"] != before["state_sha256"]
        assert pending["pending"] == ["SOURCE_CLEANUP"]
        assert pending["restore_state"] == "BLOCKED"
    reopened = ControlStore(store.path)
    with reopened.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        assert AgentRecoveryPreflight(reopened).current_state_in_transaction(db) == pending


def test_recovery_preflight_rejects_wrong_database_and_missing_transaction(tmp_path):
    store = ControlStore(tmp_path / "business.sqlite")
    store.initialize("ui-check")
    preflight = AgentRecoveryPreflight(store)
    with store.connect() as db:
        with pytest.raises(ValueError, match="同一业务数据库事务"):
            preflight.current_state_in_transaction(db)
    with sqlite3.connect(tmp_path / "other.sqlite") as db:
        db.execute("BEGIN")
        with pytest.raises(ValueError, match="同一业务数据库事务"):
            preflight.current_state_in_transaction(db)


def test_recovery_state_tracks_actual_memory_adoption(tmp_path):
    store, runs, results, sink = setup_result(tmp_path)
    preflight = AgentRecoveryPreflight(store)
    with runs.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        before = preflight.current_state_in_transaction(db)
    HermesMemoryAdapter(store, results.scope, run_gate=sink).read()
    with runs.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        after = preflight.current_state_in_transaction(db)
        assert after["state_sha256"] != before["state_sha256"]
        assert after["restore_state"] == "BLOCKED"
