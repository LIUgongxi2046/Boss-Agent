import multiprocessing
import os
import sqlite3

import pytest

from agent_memory_deletion_log import inspect_memory_deletion_history_in_transaction
from agent_recovery_preflight import AgentRecoveryPreflight, inspect_deletion_evidence_readonly
from controls import ControlStore


def interrupt_uncommitted_deletion(path):
    store = ControlStore(path)
    db = store.connect()
    db.execute("BEGIN IMMEDIATE")
    memory = store.get(db, "ui-check", "memory", "current")
    store.put(db, "ui-check", "memory", "current", {**memory, "confirmation_state": "DELETED", "text": "", "version": "2"})
    os._exit(22)


def test_empty_ledger_can_be_checked_but_cannot_prove_completeness(tmp_path):
    store = ControlStore(tmp_path / "business.sqlite")
    store.initialize("ui-check")
    with store.connect() as db:
        with pytest.raises(ValueError, match="同一数据库事务"):
            inspect_memory_deletion_history_in_transaction(store, db, "ui-check")
    with sqlite3.connect(tmp_path / "other.sqlite") as db:
        db.execute("BEGIN")
        with pytest.raises(ValueError, match="同一数据库事务"):
            inspect_memory_deletion_history_in_transaction(store, db, "ui-check")
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        first = inspect_memory_deletion_history_in_transaction(store, db, "ui-check")
        assert first == {"event_count": 0, "marker_count": 0, "pending": [], "history_complete": False}
        assert inspect_memory_deletion_history_in_transaction(store, db, "ui-check") == first
        state = AgentRecoveryPreflight(store).current_state_in_transaction(db)
        assert state["memory_event_count"] == 0 and state["memory_history_complete"] is False
        assert state["restore_state"] == "BLOCKED"
    process = multiprocessing.get_context("spawn").Process(target=interrupt_uncommitted_deletion, args=(store.path,))
    process.start()
    process.join(50)
    assert process.exitcode == 22
    with ControlStore(store.path).connect() as db:
        db.execute("BEGIN IMMEDIATE")
        assert inspect_memory_deletion_history_in_transaction(store, db, "ui-check") == first


def test_unmatched_deletion_records_are_reported_without_authorization(tmp_path):
    store = ControlStore(tmp_path / "business.sqlite")
    store.initialize("ui-check")
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        original = store.get(db, "ui-check", "memory", "current")
        memory_id = original["memory_id"]
        store.put(db, "ui-check", "memory_deletion", memory_id, {"state": "CURRENT_AND_HISTORY_CLEARED", "version": "2", "backups": "NOT_VERIFIED"})
        check = inspect_memory_deletion_history_in_transaction(store, db, "ui-check")
        assert check["event_count"] == 0 and check["marker_count"] == 1
        assert "MEMORY_DELETION_HISTORY_MISSING" in check["pending"]
        assert "MEMORY_DELETION_CURRENT_UNVERIFIED" in check["pending"]
        assert AgentRecoveryPreflight(store).current_state_in_transaction(db)["restore_state"] == "BLOCKED"
        db.rollback()
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        store.put(db, "ui-check", "memory", "current", {**original, "confirmation_state": "DELETED", "text": "", "version": "2"})
        check = inspect_memory_deletion_history_in_transaction(store, db, "ui-check")
        assert "MEMORY_DELETION_HISTORY_MISSING" in check["pending"]
        db.rollback()
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        assert inspect_memory_deletion_history_in_transaction(store, db, "ui-check")["pending"] == []
        assert db.execute("SELECT count(*) FROM objects WHERE kind='authorization'").fetchone() == (0,)


def test_source_withdrawal_history_does_not_prove_memory_history(tmp_path):
    store = ControlStore(tmp_path / "business.sqlite")
    store.initialize("ui-check")
    store.control("ui-check", "withdraw", {"source_id": "finance-note", "version": "1"})
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        state = AgentRecoveryPreflight(store).current_state_in_transaction(db)
        assert state["source_event_count"] == 1 and state["source_missing_count"] == 0
        assert state["memory_event_count"] == 0 and state["memory_history_complete"] is False
        assert state["source_history_complete"] is False and state["restore_state"] == "BLOCKED"


def test_readonly_deletion_evidence_with_actual_source_withdrawal(tmp_path):
    store = ControlStore(tmp_path / "business.sqlite")
    store.initialize("ui-check")
    store.control("ui-check", "withdraw", {"source_id": "finance-note", "version": "1"})
    with sqlite3.connect(store.path.as_uri() + "?mode=ro", uri=True) as db:
        db.execute("PRAGMA query_only=ON")
        db.execute("BEGIN")
        before = db.total_changes
        result = inspect_deletion_evidence_readonly(db, "ui-check")
        assert result["source_events"] == 1 and result["withdrawn_without_event"] == 0
        assert result["memory_events"] == 0 and result["memory_markers_without_event"] == 0
        assert result["source_history_complete"] is False and result["memory_history_complete"] is False
        assert result["restore_state"] == "BLOCKED" and len(result["schema_sha256"]) == 64
        assert inspect_deletion_evidence_readonly(db, "ui-check") == result and db.total_changes == before


def test_deletion_event_without_authorization_is_rejected(tmp_path):
    store = ControlStore(tmp_path / "business.sqlite")
    store.initialize("ui-check")
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        initial = store.get(db, "ui-check", "initial", "snapshot")
        memory = store.get(db, "ui-check", "memory", "current")
        identifier = memory["memory_id"] + ":2"
        event = {"event_id": identifier, "namespace": "ui-check", "owner_id": initial["owner_id"], "dataset_id": initial["dataset_id"], "dataset_version": initial["dataset_version"], "memory_id": memory["memory_id"], "previous_version": "1", "deleted_version": "2", "authorization_id": "missing-record", "result": "CURRENT_AND_HISTORY_CLEARED"}
        store.put(db, "ui-check", "memory_deletion_event", identifier, event)
        with pytest.raises(ValueError, match="缺少授权记录"):
            inspect_memory_deletion_history_in_transaction(store, db, "ui-check")
        assert db.execute("SELECT count(*) FROM objects WHERE kind='authorization'").fetchone() == (0,)
        db.rollback()
