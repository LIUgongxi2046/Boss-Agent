import multiprocessing
import os

import pytest
from aiohttp import web

from agent_memory_deletion_log import memory_deletion_event_exists
from agent_recovery_preflight import AgentRecoveryPreflight
from boss_v7_memory import delete_memory_records
from controls import ControlStore


def interrupted_update(path):
    store = ControlStore(path)
    db = store.connect()
    db.execute("BEGIN IMMEDIATE")
    db.execute("DELETE FROM objects WHERE namespace=? AND kind='memory' AND id='current'", ("ui-check",))
    os._exit(17)


def test_deletion_without_authorization_rolls_back(tmp_path):
    store = ControlStore(tmp_path / "business.sqlite")
    store.initialize("ui-check")
    with store.connect() as db:
        original = store.get(db, "ui-check", "memory", "current")
    with pytest.raises(web.HTTPNotFound):
        with store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            delete_memory_records(store, db, original, "missing-authorization")
    with store.connect() as db:
        assert store.get(db, "ui-check", "memory", "current") == original
        assert db.execute("SELECT count(*) FROM objects WHERE kind IN ('memory_deletion','memory_deletion_event')").fetchone() == (0,)


def test_missing_legacy_deletion_event_stays_blocked_after_restart(tmp_path):
    store = ControlStore(tmp_path / "business.sqlite")
    store.initialize("ui-check")
    with store.connect() as db:
        memory = store.get(db, "ui-check", "memory", "current")
        store.put(db, "ui-check", "memory_deletion", memory["memory_id"], {"state": "CURRENT_AND_HISTORY_CLEARED", "version": "2", "backups": "NOT_VERIFIED"})
    process = multiprocessing.get_context("spawn").Process(target=interrupted_update, args=(store.path,))
    process.start()
    process.join(timeout=15)
    assert process.exitcode == 17
    reopened = ControlStore(store.path)
    with reopened.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        assert reopened.get(db, "ui-check", "memory", "current") == memory
        assert memory_deletion_event_exists(db, "ui-check", memory["memory_id"], "2") is False
        result = AgentRecoveryPreflight(reopened).current_state_in_transaction(db)
        assert "MEMORY_DELETION_HISTORY_MISSING" in result["pending"]
        assert "MEMORY_BACKUPS" in result["pending"] and result["restore_state"] == "BLOCKED"
