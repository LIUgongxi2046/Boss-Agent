import sqlite3
import sys
from pathlib import Path

import pytest
from aiohttp import web

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "validation"))

from business import checksum, initial_materials
from boss_command_api import BossCommandAPI
from boss_page_api import BossPageAPI
from controls import ControlStore
from test_boss_command_api import create_input


def test_approved_snapshot_relationships_and_repeatable_reset_are_isolated(tmp_path):
    store = ControlStore(tmp_path / "simulation.sqlite")
    first = store.initialize("ui-check")
    data = initial_materials()
    assert first["snapshot_sha256"] == checksum(data)
    assert len({row["record_id"] for row in data["details"]}) == len(data["details"])
    contacts = {row["contact_id"] for row in data["contacts"]}
    assert set(data["meeting"]["participant_ids"]) <= contacts
    assert data["event"]["coordinator_id"] in contacts
    assert data["event"]["task_id"] == data["historical_task"]["task_id"]
    api = BossCommandAPI(store)
    assert api.execute("BOSS", "boss.assignment.create", create_input())[0] == 200
    reset = store.control("ui-check", "reset", {"namespace": "next-execution"})
    assert reset["snapshot_sha256"] == first["snapshot_sha256"]
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM objects WHERE namespace='ui-check' AND kind='task'").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM objects WHERE namespace='next-execution' AND kind IN ('task','authorization','outbox','notification','owner_plan','today_order')").fetchone()[0] == 0
        assert store.get(db, "next-execution", "initial", "snapshot") == data
        store.active(db, "next-execution")
        with pytest.raises(web.HTTPConflict):
            store.active(db, "ui-check")
    assert api.execute("BOSS", "boss.assignment.create", create_input("old-space-rejected"))[0] == 409


def test_sqlite_backup_preserves_source_withdrawal_and_deleted_memory(tmp_path):
    store = ControlStore(tmp_path / "source.sqlite")
    store.initialize("ui-check")
    status, response = BossPageAPI(store).serve("BOSS", "/api/boss/ui/metrics")
    assert status == 200
    query = response["result"]
    status, created = BossCommandAPI(store).execute("BOSS", "boss.assignment.create", create_input())
    assert status == 200
    store.control("ui-check", "withdraw", {"source_id": "finance-note", "version": "1"})
    status, result = BossCommandAPI(store).execute("BOSS", "boss.memory.delete", {
        "client_request_id": "backup-memory-delete", "expected_version": "1",
    })
    assert status == 200, result
    backup_path = tmp_path / "verified-backup.sqlite"
    with store.connect() as source, sqlite3.connect(backup_path) as destination:
        source.backup(destination)
        assert source.execute("SELECT namespace,kind,id,body FROM objects ORDER BY namespace,kind,id").fetchall() == destination.execute("SELECT namespace,kind,id,body FROM objects ORDER BY namespace,kind,id").fetchall()
        assert destination.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    restored = ControlStore(backup_path)
    assert restored.context("ui-check")["memory"] is None
    with pytest.raises(web.HTTPGone):
        restored.invoke("read_evidence", {"envelope": query["envelope"], "query_id": query["query_id"], "source_ids": ["finance-note"], "detail_refs": query["detail_refs"]})
    with restored.connect() as db:
        assert restored.get(db, "ui-check", "document", "finance-note")["withdrawn"] is True
        assert restored.get(db, "ui-check", "memory", "current")["text"] == ""
        assert restored.get(db, "ui-check", "query_source_binding", query["query_id"])["source_version"] == query["sources"][0]["version"]
        assert restored.get(db, "ui-check", "assignment_source_binding", created["task_id"])["source_versions"] == {"finance-note": "1"}
        assert db.execute("SELECT COUNT(*) FROM knowledge WHERE namespace='ui-check' AND source_id='finance-note'").fetchone()[0] == 0
