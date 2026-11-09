import hashlib
import json
import os
import secrets
import sqlite3
import subprocess
import sys
import threading
from contextlib import closing
from pathlib import Path

import pytest
import yaml
from aiohttp import web

from agent_run_store import RunStore
from business import checksum
from boss_command_api import BossCommandAPI
from boss_memory_sessions import MemorySessionManager
from boss_supply_quality import IMPORT_ACTION, WITHDRAW_ACTION, SupplyQualityAPI
from controls import ControlStore
from hermes_bridge import EngineEventSink, EngineRunConfig, HermesBridge, ReadScope
from hermes_budget_gateway import RunBoundBudgetStore
from hermes_transport import HermesTransport


def recorded_result(store, run_id, call_id, source_ids):
    result = HermesBridge(store).read_documents(scope=ReadScope("boss-1", "ui-check", "selection", "1"), source_ids=source_ids)
    key = hashlib.sha256(json.dumps([run_id, call_id], ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
    record = {"run_id": run_id, "call_id": call_id, "request_digest": checksum(source_ids), "result": result}
    with store.connect() as db:
        store.put(db, "ui-check", "hermes_document_result", key, record)
    return key, result


def test_withdraw_clears_result_in_same_transaction_and_preserves_audit(tmp_path):
    store = ControlStore(tmp_path / "business.sqlite")
    store.initialize("ui-check")
    runs = RunStore(store.path)
    run_id = runs.create_run("boss-1", "ui-check", "source-check", "source-digest")
    lease = runs.acquire_lease(run_id, 0, "worker", 60)
    config = EngineRunConfig(run_id, lease["epoch"], "903230b1e23e0c496b28e5d2e8c4f2639cd506b6", "http://127.0.0.1:1234", 1)
    transport = HermesTransport(EngineEventSink(runs, config, "worker"), secrets.token_urlsafe(32), actor_id="boss-1", space_id="ui-check")
    affected_key, original = recorded_result(store, run_id, "read-finance", ["finance-note", "meeting-minutes"])
    other_key, other = recorded_result(store, run_id, "read-meeting", ["meeting-minutes"])
    source = {"source_id": "finance-note", "version": "1"}
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        store.control_withdraw(db, "ui-check", source)
        marker = store.get(db, "ui-check", "hermes_document_result", affected_key)
        assert marker["state"] == "REVOKED" and marker["result_sha256"] == checksum(original)
        assert marker["run_id"] == run_id and marker["call_id"] == "read-finance" and "result" not in marker
        assert store.get(db, "ui-check", "hermes_document_result", other_key)["result"] == other
        db.rollback()
    with store.connect() as db:
        assert store.get(db, "ui-check", "hermes_document_result", affected_key)["result"] == original
        assert transport._document_result(db, "read-finance", checksum(["finance-note", "meeting-minutes"])) == original
    store.control("ui-check", "withdraw", source)
    store.control("ui-check", "withdraw", source)
    reopened = ControlStore(store.path)
    with reopened.connect() as db:
        marker = reopened.get(db, "ui-check", "hermes_document_result", affected_key)
        assert marker["state"] == "REVOKED" and marker["revoked_source_id"] == "finance-note"
        assert reopened.get(db, "ui-check", "hermes_source_cleanup", "finance-note")["session_state"] == "PENDING"
        assert "result" not in marker and store.get(db, "ui-check", "hermes_document_result", other_key)["result"] == other
        with pytest.raises(web.HTTPConflict) as rejected:
            transport._document_result(db, "read-finance", checksum(["finance-note", "meeting-minutes"]))
        assert json.loads(rejected.value.text)["code"] == "TOOL_SOURCE_REVOKED"


def test_withdraw_serializes_with_result_read(tmp_path):
    store = ControlStore(tmp_path / "business.sqlite")
    store.initialize("ui-check")
    run_id = RunStore(store.path).create_run("boss-1", "ui-check", "concurrent-check", "concurrent-digest")
    key, original = recorded_result(store, run_id, "read-finance", ["finance-note"])
    entered = threading.Event()
    finished = threading.Event()
    outcome = []

    def withdraw():
        entered.set()
        outcome.append(store.control("ui-check", "withdraw", {"source_id": "finance-note", "version": "1"}))
        finished.set()

    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        assert store.get(db, "ui-check", "hermes_document_result", key)["result"] == original
        thread = threading.Thread(target=withdraw)
        thread.start()
        assert entered.wait(5) and not finished.wait(0.2)
    thread.join(5)
    assert not thread.is_alive() and finished.is_set() and outcome[0]["withdrawn"] is True
    with store.connect() as db:
        assert store.get(db, "ui-check", "hermes_document_result", key)["state"] == "REVOKED"


def test_unreadable_result_prevents_partial_withdrawal(tmp_path):
    store = ControlStore(tmp_path / "business.sqlite")
    store.initialize("ui-check")
    runs = RunStore(store.path)
    run_id = runs.create_run("boss-1", "ui-check", "invalid-check", "invalid-digest")
    with runs.connect() as db:
        db.execute("UPDATE agent_runs SET selected_refs=? WHERE run_id=?", (json.dumps(["finance-note"]), run_id))
    lease = runs.acquire_lease(run_id, 0, "worker", 60)
    runs.transition(run_id, runs.read_run(run_id)["revision"], "RUNNING", "worker", lease["epoch"])
    config = EngineRunConfig(run_id, lease["epoch"], "903230b1e23e0c496b28e5d2e8c4f2639cd506b6", "http://127.0.0.1:1234", 1)
    sink = EngineEventSink(runs, config, "worker")
    budget = RunBoundBudgetStore(sink, allow_migration=True)
    key, original = recorded_result(store, run_id, "read-finance", ["finance-note"])
    with store.connect() as db:
        record = store.get(db, "ui-check", "hermes_document_result", key)
        del record["result"]["records"][0]["source_refs"]
        store.put(db, "ui-check", "hermes_document_result", key, record)
    with pytest.raises(ValueError, match="来源无法核查"):
        store.control("ui-check", "withdraw", {"source_id": "finance-note", "version": "1"})
    with store.connect() as db:
        assert store.get(db, "ui-check", "document", "finance-note").get("withdrawn") is not True
        assert store.get(db, "ui-check", "hermes_source_cleanup", "finance-note")["state"] == "FAILED"
        assert db.execute("SELECT count(*) FROM objects WHERE namespace=? AND kind='source_withdrawal_event'", ("ui-check",)).fetchone() == (0,)
    with pytest.raises(ValueError, match="来源清理尚未完成"):
        sink.require_tool_access("boss-1", "ui-check")
    with pytest.raises(ValueError, match="来源清理尚未完成"):
        budget.reserve()
    with store.connect() as db:
        record = store.get(db, "ui-check", "hermes_document_result", key)
        record["result"] = original
        store.put(db, "ui-check", "hermes_document_result", key, record)
    store.control("ui-check", "withdraw", {"source_id": "finance-note", "version": "1"})
    with store.connect() as db:
        assert store.get(db, "ui-check", "hermes_source_cleanup", "finance-note")["state"] == "COMPLETED"
        assert store.get(db, "ui-check", "hermes_document_result", key)["state"] == "REVOKED"
        assert db.execute("SELECT count(*) FROM objects WHERE namespace=? AND kind='source_withdrawal_event'", ("ui-check",)).fetchone() == (1,)
    with pytest.raises(ValueError, match="来源已经撤销"):
        sink.require_tool_access("boss-1", "ui-check")


def test_interrupted_cleanup_remains_blocked_and_recovers(tmp_path):
    store = ControlStore(tmp_path / "business.sqlite")
    store.initialize("ui-check")
    runs = RunStore(store.path)
    run_id = runs.create_run("boss-1", "ui-check", "interrupted-check", "interrupted-digest")
    with runs.connect() as db:
        db.execute("UPDATE agent_runs SET selected_refs=? WHERE run_id=?", (json.dumps(["finance-note"]), run_id))
    lease = runs.acquire_lease(run_id, 0, "worker", 60)
    runs.transition(run_id, runs.read_run(run_id)["revision"], "RUNNING", "worker", lease["epoch"])
    sink = EngineEventSink(runs, EngineRunConfig(run_id, lease["epoch"], "903230b1e23e0c496b28e5d2e8c4f2639cd506b6", "http://127.0.0.1:1234", 1), "worker")
    key, _ = recorded_result(store, run_id, "interrupted-read", ["finance-note"])
    probe = Path(__file__).with_name("hermes_source_crash_probe.py")
    process = subprocess.run([sys.executable, str(probe), str(store.path)], env=os.environ.copy(), check=False)
    assert process.returncode == 17
    with store.connect() as db:
        assert store.get(db, "ui-check", "hermes_source_cleanup", "finance-note")["state"] == "PENDING"
    with pytest.raises(ValueError, match="来源清理尚未完成"):
        sink.require_tool_access("boss-1", "ui-check")
    store.control("ui-check", "withdraw", {"source_id": "finance-note", "version": "1"})
    with store.connect() as db:
        assert store.get(db, "ui-check", "hermes_source_cleanup", "finance-note")["state"] == "COMPLETED"
        assert store.get(db, "ui-check", "hermes_document_result", key)["state"] == "REVOKED"


def test_database_maintenance_does_not_remove_existing_backup(tmp_path):
    store = ControlStore(tmp_path / "business.sqlite")
    store.initialize("ui-check")
    run_id = RunStore(store.path).create_run("boss-1", "ui-check", "backup-check", "backup-digest")
    key, original = recorded_result(store, run_id, "backup-read", ["finance-note"])
    backup_path = tmp_path / "backup.sqlite"
    with closing(store.connect()) as live, closing(sqlite3.connect(backup_path)) as backup:
        live.backup(backup)
    store.control("ui-check", "withdraw", {"source_id": "finance-note", "version": "1"})
    with closing(store.connect()) as live:
        assert live.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()[0] == 0
        live.execute("VACUUM")
    with closing(sqlite3.connect(backup_path)) as backup:
        row = backup.execute("SELECT body FROM objects WHERE namespace=? AND kind='hermes_document_result' AND id=?", ("ui-check", key)).fetchone()
        assert json.loads(row[0])["result"] == original


def test_knowledge_withdraw_failure_and_retry(tmp_path):
    store = ControlStore(tmp_path / "business.sqlite")
    store.initialize("ui-check")
    with store.connect() as db:
        original = store.get(db, "ui-check", "document", "finance-note")
    commands = BossCommandAPI(store)
    payload = {"client_request_id": "knowledge-create", "source_id": "sim-doc-cleanup-check", "title": "模拟财务资料",
               "author_contact_id": original["author_contact_id"], "published_at": original["published_at"][:10], "content": original["content"]}
    assert commands.execute("MAINTAINER", "boss.knowledge.source.create", payload)[0] == 200
    runs = RunStore(store.path)
    run_id = runs.create_run("boss-1", "ui-check", "knowledge-check", "knowledge-digest")
    store.hermes_source_sessions = MemorySessionManager(tmp_path / "workspace", business_store=store, sessions_root=tmp_path / "sessions")
    key, result = recorded_result(store, run_id, "knowledge-read", [payload["source_id"]])
    with store.connect() as db:
        saved = store.get(db, "ui-check", "hermes_document_result", key)
        del saved["result"]["records"][0]["source_refs"]
        store.put(db, "ui-check", "hermes_document_result", key, saved)
    withdrawal = {"client_request_id": "knowledge-withdraw", "source_id": payload["source_id"], "expected_version": "1"}
    assert commands.execute("MAINTAINER", "boss.knowledge.source.withdraw", withdrawal)[0] == 400
    with store.connect() as db:
        assert store.get(db, "ui-check", "hermes_source_cleanup", payload["source_id"])["state"] == "FAILED"
        saved = store.get(db, "ui-check", "hermes_document_result", key)
        saved["result"] = result
        store.put(db, "ui-check", "hermes_document_result", key, saved)
    assert commands.execute("MAINTAINER", "boss.knowledge.source.withdraw", withdrawal)[0] == 200
    assert commands.execute("MAINTAINER", "boss.knowledge.source.withdraw", withdrawal)[0] == 200
    with store.connect() as db:
        assert store.get(db, "ui-check", "hermes_source_cleanup", payload["source_id"])["state"] == "COMPLETED"
        assert store.get(db, "ui-check", "hermes_source_cleanup", payload["source_id"])["session_state"] == "COMPLETED"
        assert store.get(db, "ui-check", "hermes_document_result", key)["state"] == "REVOKED"


def test_supply_withdraw_failure_and_retry(tmp_path):
    store = ControlStore(tmp_path / "business.sqlite")
    store.initialize("ui-check")
    api = SupplyQualityAPI(store)
    source_file = Path(__file__).resolve().parents[2] / "data/simulation/supply-quality-v1.yaml"
    data = yaml.safe_load(source_file.read_text())
    assert api.execute("MAINTAINER", IMPORT_ACTION, data["initial_request"])["state"] == "SUCCESS"
    source_id = "sim-business:inventory_lot:sim-stock-available-1"
    runs = RunStore(store.path)
    run_id = runs.create_run("boss-1", "ui-check", "supply-check", "supply-digest")
    store.hermes_source_sessions = MemorySessionManager(tmp_path / "workspace", business_store=store, sessions_root=tmp_path / "sessions")
    key, result = recorded_result(store, run_id, "supply-read", [source_id])
    with store.connect() as db:
        saved = store.get(db, "ui-check", "hermes_document_result", key)
        del saved["result"]["records"][0]["source_refs"]
        store.put(db, "ui-check", "hermes_document_result", key, saved)
    withdrawal = {"client_request_id": "supply-withdraw-check", "entity_type": "inventory_lot", "record_id": "sim-stock-available-1", "expected_version": "1", "reason": "模拟来源撤销"}
    with pytest.raises(ValueError, match="来源无法核查"):
        api.execute("MAINTAINER", WITHDRAW_ACTION, withdrawal)
    with store.connect() as db:
        assert store.get(db, "ui-check", "hermes_source_cleanup", source_id)["state"] == "FAILED"
        saved = store.get(db, "ui-check", "hermes_document_result", key)
        saved["result"] = result
        store.put(db, "ui-check", "hermes_document_result", key, saved)
    first = api.execute("MAINTAINER", WITHDRAW_ACTION, withdrawal)
    assert api.execute("MAINTAINER", WITHDRAW_ACTION, withdrawal) == first
    with store.connect() as db:
        assert store.get(db, "ui-check", "hermes_source_cleanup", source_id)["state"] == "COMPLETED"
        assert store.get(db, "ui-check", "hermes_source_cleanup", source_id)["session_state"] == "COMPLETED"
        assert store.get(db, "ui-check", "hermes_document_result", key)["state"] == "REVOKED"
