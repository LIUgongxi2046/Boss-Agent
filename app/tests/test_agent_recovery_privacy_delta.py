import json
import multiprocessing
import os
import sqlite3
from contextlib import closing

import pytest
from aiohttp import web

from agent_recovery_preflight import AgentRecoveryPreflight
from agent_recovery_checkpoint import AgentRecoveryCheckpoint
from agent_run_store import RunStore
from agent_simulation_recovery import AgentSimulationRecovery
from agent_simulation_recovery_journal import AgentSimulationRecoveryJournal
from agent_simulation_snapshot import AgentSimulationSnapshot
from boss_source_access import require_current_business_source
from boss_command_api import BossCommandAPI
from controls import ControlStore
from hermes_memory_adapter import HermesMemoryAdapter
from test_agent_run_result import setup_result
from test_agent_simulation_recovery import setup_recovery
from test_hermes_source_invalidation import recorded_result


def interrupt_memory_change(path):
    store = ControlStore(path)
    db = store.connect()
    db.execute("BEGIN IMMEDIATE")
    db.execute("DELETE FROM objects WHERE namespace=? AND kind='memory' AND id='current'", ("ui-check",))
    os._exit(21)


def interrupt_source_withdrawal(path):
    store = ControlStore(path)
    db = store.connect()
    db.execute("BEGIN IMMEDIATE")
    store.control_withdraw(db, "ui-check", {"source_id": "finance-note", "version": "1"})
    os._exit(22)


def test_old_snapshot_privacy_changes_block_restoration_and_survive_interruption(tmp_path):
    store, recovery, snapshot = setup_recovery(tmp_path)
    initial = recovery.inspect_privacy_delta("snapshot")
    assert initial["state_matches_current"] is True
    assert initial["restore_state"] == "BLOCKED" and initial["source_history_complete"] is False
    with pytest.raises(ValueError, match="记录不存在"):
        recovery.inspect_privacy_delta("missing")
    process = multiprocessing.get_context("spawn").Process(target=interrupt_memory_change, args=(store.path,))
    process.start()
    process.join(50)
    assert process.exitcode == 21
    assert recovery.inspect_privacy_delta("snapshot") == initial
    store.control("ui-check", "withdraw", {"source_id": "finance-note", "version": "1"})
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute("DELETE FROM objects WHERE namespace=? AND kind='memory' AND id='current'", ("ui-check",))
    current = recovery.inspect_privacy_delta("snapshot")
    assert current["state_matches_current"] is False
    assert current["snapshot_only_records"]["memory"] == 1
    assert current["changed_records"]["document"] == 1
    assert current["missing_current_records"]["source_withdrawal_event"] == 1
    assert current["restore_state"] == "BLOCKED"
    with pytest.raises(ValueError, match="当前状态已经变化"):
        recovery.preflight("snapshot", max_age_seconds=300)
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        current_state = AgentRecoveryPreflight(store).current_state_in_transaction(db)
        with pytest.raises(web.HTTPGone):
            require_current_business_source(store, db, "ui-check", "boss-1", "finance-note")
    copy_path = tmp_path / "isolated-restored.sqlite"
    with closing(sqlite3.connect((tmp_path / snapshot["snapshot_name"]).as_uri() + "?mode=ro&immutable=1", uri=True)) as source, closing(sqlite3.connect(copy_path)) as target:
        source.backup(target)
    restored = ControlStore(copy_path)
    with restored.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        restored_state = AgentRecoveryPreflight(restored).current_state_in_transaction(db)
        assert restored_state["restore_state"] == "BLOCKED"
        assert restored_state["state_sha256"] != current_state["state_sha256"]
        assert require_current_business_source(restored, db, "ui-check", "boss-1", "finance-note")["version"] == "1"
        assert store.get(db, "ui-check", "memory", "current")["version"] == "1"
    reopened = ControlStore(store.path)
    with reopened.connect() as db:
        db.execute("BEGIN")
        with pytest.raises(web.HTTPGone):
            require_current_business_source(reopened, db, "ui-check", "boss-1", "finance-note")


def test_privacy_delta_rejects_changed_snapshot(tmp_path):
    _, recovery, snapshot = setup_recovery(tmp_path)
    with sqlite3.connect(tmp_path / snapshot["snapshot_name"]) as db:
        db.execute("DELETE FROM objects WHERE namespace=? AND kind='memory' AND id='current'", ("ui-check",))
    with pytest.raises(ValueError, match="摘要不符"):
        recovery.inspect_privacy_delta("snapshot")


def test_privacy_delta_tracks_real_run_invalidation(tmp_path):
    store, runs, results, sink = setup_result(tmp_path)
    HermesMemoryAdapter(store, results.scope, run_gate=sink).read()
    checkpoint = AgentRecoveryCheckpoint(AgentRecoveryPreflight(store), allow_migration=True)
    snapshots = AgentSimulationSnapshot(checkpoint, tmp_path, allow_migration=True)
    journal = AgentSimulationRecoveryJournal(snapshots, allow_migration=True)
    recovery = AgentSimulationRecovery(snapshots, journal)
    with runs.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        checkpoint_id = checkpoint.capture_in_transaction(db, "state")["checkpoint_id"]
    snapshots.create("snapshot", "state", checkpoint_id)
    store.hermes_source_sessions = results.scope.sources.sessions
    store.control("ui-check", "withdraw", {"source_id": "finance-note", "version": "1"})
    delta = recovery.inspect_privacy_delta("snapshot")
    assert delta["missing_current_records"]["source_withdrawal_event"] == 1
    assert delta["missing_current_records"]["hermes_memory_invalidation"] == 1
    assert delta["missing_current_records"]["hermes_source_cleanup"] == 1
    assert delta["state_matches_current"] is False and delta["restore_state"] == "BLOCKED"


def test_snapshot_tracks_document_result_revocation_and_interruption(tmp_path):
    store = ControlStore(tmp_path / "business.sqlite")
    store.initialize("ui-check")
    runs = RunStore(store.path)
    run_id = runs.create_run("boss-1", "ui-check", "document-result", "technical-request")
    key, original = recorded_result(store, run_id, "read-finance", ["finance-note"])
    checkpoint = AgentRecoveryCheckpoint(AgentRecoveryPreflight(store), allow_migration=True)
    snapshots = AgentSimulationSnapshot(checkpoint, tmp_path, allow_migration=True)
    journal = AgentSimulationRecoveryJournal(snapshots, allow_migration=True)
    recovery = AgentSimulationRecovery(snapshots, journal)
    with runs.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        checkpoint_id = checkpoint.capture_in_transaction(db, "document-checkpoint")["checkpoint_id"]
    snapshot = snapshots.create("document-snapshot", "document-checkpoint", checkpoint_id)
    before = recovery.inspect_privacy_delta("document-snapshot")
    assert before["changed_records"]["hermes_document_result"] == 0
    process = multiprocessing.get_context("spawn").Process(target=interrupt_source_withdrawal, args=(store.path,))
    process.start()
    process.join(50)
    assert process.exitcode == 22
    assert recovery.inspect_privacy_delta("document-snapshot") == before
    store.control("ui-check", "withdraw", {"source_id": "finance-note", "version": "1"})
    store.control("ui-check", "withdraw", {"source_id": "finance-note", "version": "1"})
    delta = recovery.inspect_privacy_delta("document-snapshot")
    assert delta["changed_records"]["hermes_document_result"] == 1
    assert delta["restore_state"] == "BLOCKED" and delta["state_matches_current"] is False
    with store.connect() as db:
        assert store.get(db, "ui-check", "hermes_document_result", key)["state"] == "REVOKED"
        assert "result" not in store.get(db, "ui-check", "hermes_document_result", key)
    with closing(sqlite3.connect((tmp_path / snapshot["snapshot_name"]).as_uri() + "?mode=ro&immutable=1", uri=True)) as old:
        body = old.execute("SELECT body FROM objects WHERE namespace=? AND kind='hermes_document_result' AND id=?", ("ui-check", key)).fetchone()[0]
        assert json.loads(body)["result"] == original
    with pytest.raises(ValueError, match="当前状态已经变化"):
        recovery.preflight("document-snapshot", max_age_seconds=300)


def test_new_document_result_invalidates_snapshot_without_source_change(tmp_path):
    store, recovery, _ = setup_recovery(tmp_path)
    runs = RunStore(store.path, allow_migration=False)
    run_id = runs.create_run("boss-1", "ui-check", "later-document-result", "technical-request")
    recorded_result(store, run_id, "read-finance", ["finance-note"])
    delta = recovery.inspect_privacy_delta("snapshot")
    assert delta["missing_current_records"]["hermes_document_result"] == 1
    assert delta["changed_records"]["document"] == 0
    assert delta["state_matches_current"] is False
    with pytest.raises(ValueError, match="当前状态已经变化"):
        recovery.preflight("snapshot", max_age_seconds=300)


def test_revised_source_marks_cached_document_result_outdated(tmp_path):
    store, recovery, _ = setup_recovery(tmp_path)
    commands = BossCommandAPI(store)
    create = {"client_request_id": "privacy-source-create", "source_id": "sim-doc-privacy-source", "title": "模拟资料", "author_contact_id": "finance-1", "published_at": "2020-01-01", "content": "模拟会议资料包含讨论事项、负责人和用于验证资料历史读取的完整原始正文。"}
    code, result = commands.execute("MAINTAINER", "boss.knowledge.source.create", create)
    assert code == 200, result
    run_id = RunStore(store.path, allow_migration=False).create_run("boss-1", "ui-check", "privacy-source-run", "technical-request")
    recorded_result(store, run_id, "read-source", ["sim-doc-privacy-source"])
    revise = {**create, "client_request_id": "privacy-source-revise", "expected_version": "1", "content": "模拟会议资料已经更新，包含新的讨论事项、负责人以及当前版本的完整原文。"}
    assert commands.execute("MAINTAINER", "boss.knowledge.source.revise", revise)[0] == 200
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        state = recovery.snapshots.checkpoint.preflight.current_state_in_transaction(db)
        assert "DOCUMENT_RESULT_SOURCE_CHANGED" in state["pending"]
        assert state["restore_state"] == "BLOCKED"
