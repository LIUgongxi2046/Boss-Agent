import argparse
from contextlib import closing
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
from urllib.parse import urlencode
import xml.etree.ElementTree as ET

import pytest
from aiohttp import web
from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "validation"))
from boss_command_api import BossCommandAPI
from boss_recovery_api import BossRecoveryAPI
from boss_simulation_api import KINDS, SCHEMA, SimulationAPI
from business import checksum, initial_materials
from controls import ControlStore

CASES = {
    "withdrawn_memory_deleted": "test_sqlite_backup_preserves_s0/verified-backup.sqlite",
    "memory_deleted": "test_memory_confirm_delete_and0/api-schema.sqlite",
    "meeting_current": "test_draft_and_owner_confirmat0/meeting-arrangement.sqlite",
    "message_sent": "test_send_records_simulated_on0/messaging.sqlite",
    "owner_goals": "test_confirmed_goal_is_read_by0/owner-preferences.sqlite",
    "reset": "test_approved_snapshot_relatio0/simulation.sqlite",
    "legacy_result": "test_result_submitted_cannot_b0/boss.sqlite",
}
TABLES = {"objects": "namespace,kind,id,body", "spaces": "namespace,active,snapshot", "idempotency": "namespace,operation,key,digest,result",
          "audit": "id,namespace,operation,input,output,created_at", "knowledge": "namespace,source_id,content"}


def manifest(db):
    return {table: checksum(db.execute("SELECT " + columns + " FROM " + table + " ORDER BY " + columns).fetchall()) for table, columns in TABLES.items()}


def schema_digest(db):
    return checksum(db.execute("SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name").fetchall())


def rows(db, namespace, kind):
    return [json.loads(row[0]) for row in db.execute("SELECT body FROM objects WHERE namespace=? AND kind=? ORDER BY id", (namespace, kind)).fetchall()]


parser = argparse.ArgumentParser()
parser.add_argument("--legacy-root", type=Path, required=True)
parser.add_argument("--source-result", type=Path, required=True)
parser.add_argument("--output-dir", type=Path, required=True)
args = parser.parse_args()
assert args.legacy_root.is_dir() and args.source_result.is_file()
assert all(path.resolve().is_relative_to((ROOT / ".work").resolve()) for path in (args.legacy_root, args.source_result, args.output_dir))
assert not args.output_dir.exists(), "恢复目录必须尚未存在"
report = ET.parse(args.source_result).getroot().find("testsuite")
assert report is not None and report.get("tests") == "465" and report.get("failures") == report.get("errors") == "0"
started = datetime.fromisoformat(report.get("timestamp"))
finished = started + timedelta(seconds=float(report.get("time")))
args.output_dir.mkdir(parents=True, mode=0o700)
validator = Draft202012Validator(SCHEMA, format_checker=FormatChecker())
results = []
for name, relative in CASES.items():
    source_path = args.legacy_root / relative
    assert source_path.is_file(), source_path
    target_path = args.output_dir / (name + ".sqlite")
    with closing(sqlite3.connect(source_path.resolve().as_uri() + "?mode=ro", uri=True)) as source:
        before = manifest(source)
        before_schema = schema_digest(source)
        audit_times = [datetime.fromisoformat(row[0]) for row in source.execute("SELECT created_at FROM audit").fetchall()]
        assert audit_times and all(started <= stamp <= finished for stamp in audit_times), name
        with closing(sqlite3.connect(target_path)) as target:
            source.backup(target)
            assert manifest(target) == before and schema_digest(target) == before_schema
            assert target.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert manifest(source) == before
    target_path.chmod(0o600)
    store = ControlStore(target_path)
    api = SimulationAPI(store)
    with store.connect() as db:
        assert manifest(db) == before and schema_digest(db) == before_schema
        namespaces = db.execute("SELECT namespace FROM spaces WHERE active=1").fetchall()
        assert len(namespaces) == 1
        namespace = namespaces[0][0]
        initial = store.get(db, namespace, "initial", "snapshot")
        assert checksum(initial) == checksum(initial_materials())
    projections = {}
    for interface in KINDS:
        query = {"interface_id": interface, "object_ids": [], "filters": {}}
        projection = api.query("BOSS", query)
        technical = api.inspect("MAINTAINER", query)
        validator.validate(projection)
        validator.validate(technical)
        assert projection["execution_namespace"] == technical["execution_namespace"] == namespace
        assert all(record["data"] is None for record in technical["records"])
        projections[interface] = projection
    checked_receipts = 0
    recovery = BossRecoveryAPI(store, namespace)
    with store.connect() as db:
        receipts = db.execute("SELECT operation,key FROM idempotency WHERE namespace=? ORDER BY operation,key", (namespace,)).fetchall()
    for action, key in receipts:
        if action not in BossCommandAPI.ACTION_ROLES:
            continue
        status, outcome = recovery.serve(BossCommandAPI.ACTION_ROLES[action], "/api/boss/ui/operation-status", urlencode({"action": action, "client_request_id": key}))
        assert status == 200 and outcome["outcome"] == "RECORDED" and outcome["write_performed_by_lookup"] is False
        checked_receipts += 1
    checks = []
    if name in ("withdrawn_memory_deleted", "memory_deleted"):
        assert store.context(namespace)["memory"] is None
        with store.connect() as db:
            deleted_memory = store.get(db, namespace, "memory", "current")
            assert deleted_memory["confirmation_state"] == "DELETED" and deleted_memory["text"] == ""
        memory_records = [record for record in projections["SI13"]["records"] if record["entity_type"] == "memory"]
        assert memory_records and all(record["data"] is None and record["content_state"] == "INACTIVE" for record in memory_records)
        checks.append("deleted memory remains excluded from current context and query content")
    if name == "withdrawn_memory_deleted":
        documents = [record for record in projections["SI13"]["records"] if record["entity_type"] == "document" and record["object_id"] == "finance-note"]
        assert documents and documents[0]["data"] is None and documents[0]["source_refs"][0]["status"] == "WITHDRAWN"
        with store.connect() as db:
            assert db.execute("SELECT COUNT(*) FROM knowledge WHERE namespace=? AND source_id='finance-note'", (namespace,)).fetchone()[0] == 0
            query = rows(db, namespace, "query")[0]
        with pytest.raises(web.HTTPGone):
            store.invoke("read_evidence", {"envelope": query["envelope"], "query_id": query["query_id"], "source_ids": ["finance-note"], "detail_refs": query["detail_refs"]})
        checks.append("withdrawn source, original evidence and removed FTS content stay unavailable")
    if name == "meeting_current":
        with store.connect() as db:
            current = rows(db, namespace, "meeting")[0]
        exposed = [record["data"] for record in projections["SI03"]["records"] if record["entity_type"] == "meeting"]
        assert exposed == [current] and current["version"] != initial["meeting"]["version"]
        checks.append("confirmed current meeting is read instead of initial arrangement")
    if name == "message_sent":
        sent = [record for record in projections["SI04"]["records"] if record["entity_type"] == "message_outbox"]
        assert len(sent) == 1 and sent[0]["data"]["send_state"] == "SENT_SIMULATED" and sent[0]["data"]["external_channel_invoked"] is False
        checks.append("sent simulated message and original receipt stay singular without another send")
    if name == "owner_goals":
        with store.connect() as db:
            active = rows(db, namespace, "owner_goals_active")[0]
        profile = [record["data"] for record in projections["SI01"]["records"] if record["entity_type"] == "profile"][0]
        assert profile["goals"] == active["content"]["goals"] and profile["active_version"] == active["version"]
        checks.append("historical owner confirmation binding remains valid without incrementing adoption counts")
    if name == "reset":
        with store.connect() as db:
            inactive = db.execute("SELECT namespace FROM spaces WHERE active=0").fetchall()
            assert inactive
            for (previous,) in inactive:
                with pytest.raises(web.HTTPConflict):
                    store.active(db, previous)
                for task in rows(db, previous, "task"):
                    assert not api.query("BOSS", {"interface_id": "SI06", "object_ids": [task["task_id"]], "filters": {}})["records"]
        checks.append("inactive execution history remains separate from current reset space")
    if name == "legacy_result":
        with store.connect() as db:
            tasks = rows(db, namespace, "task")
            pending = [task for task in tasks if task["status"] == "RESULT_SUBMITTED"]
            assert pending
            task = pending[0]
            feedbacks = [feedback for feedback in rows(db, namespace, "feedback") if feedback["task_id"] == task["task_id"] and feedback["kind"] == "RESULT_SUBMITTED"]
            assert feedbacks and "evidence_versions" not in feedbacks[0]
        status, _ = BossCommandAPI(store).execute("BOSS", "boss.assignment.complete", {"client_request_id": "legacy-result-current-check", "task_id": task["task_id"], "task_version": task["version"], "feedback_id": feedbacks[0]["feedback_id"]})
        assert status == 409
        checks.append("legacy submitted evidence requires a fresh submission without creating completion authorization")
    with store.connect() as db:
        assert manifest(db) == before and schema_digest(db) == before_schema
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    with closing(sqlite3.connect(source_path.resolve().as_uri() + "?mode=ro", uri=True)) as source:
        assert manifest(source) == before and schema_digest(source) == before_schema
    results.append({"case": name, "source_database": str(source_path.relative_to(ROOT)), "restored_database": str(target_path.relative_to(ROOT)),
                    "source_audit_rows_within_report": len(audit_times), "schema_unchanged": True, "tables_sha256": before,
                    "owner_queries": 14, "technical_queries": 14, "baseline_receipts_read": checked_receipts, "verified": checks})
print(json.dumps({"status": "PASS", "source_release_evidence": "evidence/T06/interface-version-1.3.1.json",
                  "source_result": str(args.source_result.relative_to(ROOT)), "source_result_sha256": hashlib.sha256(args.source_result.read_bytes()).hexdigest(),
                  "source_database_producer_commit": None, "provenance": "existing prior test databases with all audit timestamps inside the recorded 465-test run; individual databases have no producer commit field",
                  "current_schema_id": SCHEMA["$id"], "cases": results, "new_external_requests": False, "new_agricultural_facts": False}, ensure_ascii=False, indent=2))
