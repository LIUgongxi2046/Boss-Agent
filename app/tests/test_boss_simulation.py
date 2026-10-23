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


def source_review_scenario(tmp_path):
    from boss_assignment_sources import AssignmentSourcesAPI
    from test_boss_assignment_sources import confirmation, revise_finance
    store = ControlStore(tmp_path / "source-review-backup.sqlite")
    store.initialize("ui-check")
    status, response = BossPageAPI(store).serve("BOSS", "/api/boss/ui/metrics")
    assert status == 200
    status, created = BossCommandAPI(store).execute("BOSS", "boss.assignment.create", create_input())
    assert status == 200
    document = revise_finance(store)
    review = AssignmentSourcesAPI(store)
    payload = confirmation(review, created["task_id"], "backup-owner-source-review")
    result = review.execute("BOSS", payload)
    return store, review, payload, result, response["result"], document


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


def test_native_backup_restores_review_history_without_reactivating_withdrawn_source_or_memory(tmp_path):
    from boss_assignment_sources import AssignmentSourcesAPI
    store, _, payload, result, query, document = source_review_scenario(tmp_path)
    store.control("ui-check", "withdraw", {"source_id": "finance-note", "version": document["version"]})
    assert BossCommandAPI(store).execute("BOSS", "boss.memory.delete", {"client_request_id": "review-backup-delete-memory", "expected_version": "1"})[0] == 200
    backup_path = tmp_path / "current-review-backup.sqlite"
    with store.connect() as source, sqlite3.connect(backup_path) as destination:
        source.backup(destination)
        for table, columns in (("objects", "namespace,kind,id,body"), ("idempotency", "namespace,operation,key,digest,result"),
                               ("audit", "id,namespace,operation,input,output,created_at"), ("spaces", "namespace,active,snapshot")):
            statement = "SELECT " + columns + " FROM " + table + " ORDER BY " + columns
            assert source.execute(statement).fetchall() == destination.execute(statement).fetchall()
        assert destination.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    restored = ControlStore(backup_path)
    review = AssignmentSourcesAPI(restored)
    assert review.execute("BOSS", payload) == result
    view = review.read("BOSS", payload["task_id"])
    assert view["binding_state"] == "NEEDS_REVIEW" and view["can_confirm"] is False
    assert view["sources"][0]["source_status"] == "WITHDRAWN" and view["sources"][0]["excerpt"] is None
    assert view["history"][0]["source_versions"] == {"finance-note": "1"}
    assert restored.context("ui-check")["memory"] is None
    with pytest.raises(web.HTTPGone):
        restored.invoke("read_evidence", {"envelope": query["envelope"], "query_id": query["query_id"],
            "source_ids": ["finance-note"], "detail_refs": query["detail_refs"]})
    with restored.connect() as db:
        assert restored.get(db, "ui-check", "task", payload["task_id"])["status"] == "OPEN"
        assert restored.get(db, "ui-check", "memory", "current")["text"] == ""
        assert db.execute("SELECT COUNT(*) FROM knowledge WHERE namespace='ui-check' AND source_id='finance-note'").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind IN ('outbox','notification')").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM idempotency WHERE operation='boss.assignment.sources.confirm'").fetchone()[0] == 1


def test_reset_keeps_reviewed_assignment_history_separate_from_new_active_space(tmp_path):
    store, review, payload, result, query, _ = source_review_scenario(tmp_path)
    reset = store.control("ui-check", "reset", {"namespace": "after-reviewed-assignment"})
    assert reset["snapshot_sha256"] == checksum(initial_materials())
    with pytest.raises(web.HTTPConflict):
        review.execute("BOSS", payload)
    with store.connect() as db:
        assert store.get(db, "ui-check", "task", payload["task_id"])["version"] == result["version"]
        assert store.get(db, "ui-check", "assignment_source_binding_revision", payload["task_id"] + ":v1")["binding"]["source_versions"] == {"finance-note": "1"}
        assert db.execute("SELECT COUNT(*) FROM objects WHERE namespace=? AND kind IN ('task','assignment_source_binding','assignment_source_binding_revision','authorization','query','query_source_binding','outbox','feedback')", (reset["namespace"],)).fetchone()[0] == 0
        assert store.get(db, reset["namespace"], "initial", "snapshot") == initial_materials()
    envelope = {**query["envelope"], "execution_namespace": reset["namespace"]}
    with pytest.raises(web.HTTPNotFound):
        store.invoke("read_assignment", {"envelope": envelope, "task_id": payload["task_id"]})
