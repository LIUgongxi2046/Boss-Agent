import asyncio
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import secrets
import sqlite3

import httpx
import pytest
from aiohttp import web
from jsonschema import Draft202012Validator

from agent_artifacts import ArtifactPreparation, read_verified_file, verify_stored_artifact_file_in_transaction
from agent_run_api import product_application
from agent_run_broker import RunBroker
from agent_run_business_receipts import RunBusinessReceipts
from agent_run_result import AgentRunResult
from agent_run_requirements import RunRequirements
from agent_run_scope import RunScopeService
from agent_run_store import EVENT_SCHEMA, RunStore
from boss_memory_sessions import MemorySessionManager
from boss_comprehensive_simulation import populate
from boss_simulation_api import _context
from business import checksum
from controls import ControlStore
from hermes_bridge import EngineEventSink, EngineRunConfig
from hermes_source_invalidation import begin_source_cleanup
from hermes_transport import HermesTransport
from test_agent_run_dispatcher import services_for


def setup_result(path, *, full_sources=False):
    store = ControlStore(path / "business.sqlite")
    store.initialize("ui-check")
    if full_sources:
        populate(store, "2026-10-28T10:00:00+08:00")
    sessions = MemorySessionManager(path / "workspace", business_store=store, sessions_root=path / "sessions")
    session = sessions.get_or_create("websocket:result-check")
    sessions.save(session, fsync=True)
    scope = RunScopeService(store, sessions, "ui-check")
    source_id = "simulation-meeting-material" if full_sources else "finance-note"
    with store.connect() as db:
        context = _context(db)
        document = store.get(db, "ui-check", "document", source_id)
        selection = {"source_id": source_id, "version": document["version"]}
        binding = {key: context[key] for key in ("namespace", "owner_id", "dataset_id", "dataset_version")}
        binding.update({"chat_id": "result-check", "session_id": session.key, "native_session_created_at": session.created_at.isoformat(), "binding_id": "technical-binding", "context_version": "1", "source_refs": [selection], "source_pins": [{**selection, "content_sha256": checksum(document)}]})
        store.put(db, "ui-check", "conversation_source_binding", session.key, binding)
    proof = scope.prove("result-check", [source_id])
    runs = RunStore(store.path)
    run_id = runs.create_run(proof.owner_id, proof.namespace, "technical-create", "technical-digest")
    with runs.connect() as db:
        db.execute("UPDATE agent_runs SET conversation_id=?,goal=?,selected_refs=?,scope_proof=? WHERE run_id=?", ("result-check", "技术核查", json.dumps([source_id]), json.dumps(asdict(proof)), run_id))
    lease = runs.acquire_queued_for_execution(run_id, 0, "technical-worker", 60)
    config = EngineRunConfig(run_id, lease["epoch"], "903230b1e23e0c496b28e5d2e8c4f2639cd506b6", "http://127.0.0.1:1234", 1)
    return store, runs, AgentRunResult(runs, scope), EngineEventSink(runs, config, "technical-worker")


def test_result_persists_idempotently_with_scope_and_goal_version(tmp_path):
    _, runs, results, sink = setup_result(tmp_path)
    citations = [{"source_id": "finance-note", "locator": "第一节"}]
    with ThreadPoolExecutor(max_workers=2) as pool:
        events = list(pool.map(lambda _: results.record(sink, "answer-1", 1, "会议资料的技术结果", citations), range(2)))
    assert events[0] == events[1]
    event = events[0]
    assert event["type"] == "RESULT_RECORDED"
    assert event["payload"]["source_pins"][0]["source_id"] == "finance-note"
    assert event["payload"]["source_pins"][0]["version"] == "1"
    assert event["payload"]["citations"] == citations
    with pytest.raises(ValueError, match="冲突"):
        results.record(sink, "answer-1", 1, "其他内容", citations)
    with pytest.raises(ValueError, match="冲突"):
        results.record(sink, "answer-2", 1, "会议资料的技术结果", citations)
    with pytest.raises(ValueError):
        runs.append_event(sink.config.run_id, sink.lease_owner, sink.config.lease_epoch, "bypass", "RESULT_RECORDED", event["payload"])
    reopened = RunStore(runs.path, allow_migration=False)
    with reopened.connect() as db:
        db.execute("BEGIN")
        assert reopened.result_in_transaction(db, sink.config.run_id, 1) == event
        assert reopened.event_page_in_transaction(db, sink.config.run_id, 0)["events"][-1] == event
    assert reopened.read_run(sink.config.run_id)["status"] == "RUNNING"
    reopened.add_input(sink.config.run_id, 1, "input-2", "补充要求")
    assert results.record(sink, "answer-1", 1, "会议资料的技术结果", citations) == event
    with reopened.connect() as db:
        db.execute("BEGIN")
        assert reopened.result_in_transaction(db, sink.config.run_id, 2) is None
    with pytest.raises(ValueError):
        results.record(sink, "answer-2", 2, "尚未采用补充要求", citations)
    reopened.apply_input(sink.config.run_id, 1, sink.lease_owner, sink.config.lease_epoch)
    with pytest.raises(ValueError, match="冲突"):
        results.record(sink, "answer-1", 2, "包含补充要求", citations)
    updated = results.record(sink, "answer-2", 2, "包含补充要求", citations)
    with reopened.connect() as db:
        db.execute("BEGIN")
        assert reopened.result_in_transaction(db, sink.config.run_id, 1) == event
        assert reopened.result_in_transaction(db, sink.config.run_id, 2) == updated


def test_result_rejects_invalid_citation_cancel_and_source_change(tmp_path):
    store, runs, results, sink = setup_result(tmp_path)
    with pytest.raises(ValueError, match="引用无效"):
        results.record(sink, "answer", 1, "技术结果", [{"source_id": "unknown", "locator": "第一节"}])
    with pytest.raises(ValueError, match="引用无效"):
        results.record(sink, "answer", 1, "", [])
    assert begin_source_cleanup(store, "ui-check", "finance-note", "1") is True
    with pytest.raises(ValueError):
        results.record(sink, "answer", 1, "技术结果", [])
    with runs.connect() as db:
        assert db.execute("SELECT count(*) FROM agent_run_events WHERE type='RESULT_RECORDED'").fetchone() == (0,)


def test_result_cannot_be_recorded_after_cancellation(tmp_path):
    _, runs, results, sink = setup_result(tmp_path)
    runs.cancel(sink.config.run_id, runs.read_run(sink.config.run_id)["revision"])
    with pytest.raises(ValueError):
        results.record(sink, "answer", 1, "技术结果", [])


def test_result_caller_transaction_controls_commit(tmp_path):
    _, runs, results, sink = setup_result(tmp_path)
    with runs.connect() as db:
        with pytest.raises(ValueError, match="同一数据库事务"):
            results.record_in_transaction(db, sink, "answer", 1, "技术结果", [])
        db.execute("BEGIN IMMEDIATE")
        event = results.record_in_transaction(db, sink, "answer", 1, "技术结果", [])
        assert results.record_in_transaction(db, sink, "answer", 1, "技术结果", []) == event
        db.rollback()
    with runs.connect() as db:
        db.execute("BEGIN")
        assert runs.result_in_transaction(db, sink.config.run_id, 1) is None
    with sqlite3.connect(tmp_path / "other.sqlite") as db:
        db.execute("BEGIN")
        with pytest.raises(ValueError, match="同一数据库事务"):
            results.record_in_transaction(db, sink, "answer", 1, "技术结果", [])
    with runs.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        event = results.record_in_transaction(db, sink, "answer", 1, "技术结果", [])
    with runs.connect() as db:
        db.execute("BEGIN")
        assert runs.result_in_transaction(db, sink.config.run_id, 1) == event


def test_cancellation_waits_for_result_transaction(tmp_path):
    _, runs, results, sink = setup_result(tmp_path)
    revision = runs.read_run(sink.config.run_id)["revision"]
    with ThreadPoolExecutor(max_workers=1) as pool:
        with runs.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            results.record_in_transaction(db, sink, "answer", 1, "技术结果", [])
            pending = pool.submit(runs.cancel, sink.config.run_id, revision)
            with pytest.raises(TimeoutError):
                pending.result(timeout=0.2)
            db.rollback()
        assert pending.result(timeout=10)["status"] == "CANCEL_REQUESTED"
    with runs.connect() as db:
        db.execute("BEGIN")
        assert runs.result_in_transaction(db, sink.config.run_id, 1) is None
    with pytest.raises(ValueError):
        results.record(sink, "answer", 1, "技术结果", [])


def test_completion_inspection_preserves_result_and_status(tmp_path):
    _, runs, results, sink = setup_result(tmp_path)
    result = results.record(sink, "answer", 1, "技术结果", [{"source_id": "finance-note", "locator": "第一节"}])
    finish = sink.emit("finish", "RUN_FINISHED", {"outcome": "TECHNICAL"})
    revision = runs.read_run(sink.config.run_id)["revision"]
    with runs.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        with pytest.raises(ValueError, match="本人运行授权"):
            results.inspect_completion_in_transaction(db, None, sink, revision, result["event_id"], finish["event_id"], "check-authority")
        transactional = results.inspect_completion(sink, revision, result["event_id"], finish["event_id"], "check-transaction", _db=db)
        assert transactional["completion_state"] == "BLOCKED" and "PROCESS_GROUP_EXIT_UNVERIFIED" in transactional["blockers"]
        db.rollback()
    with runs.connect() as db:
        assert db.execute("SELECT 1 FROM agent_run_operations WHERE run_id=? AND request_key=?", (sink.config.run_id, "completion-inspection:check-transaction")).fetchone() is None
    checked = results.inspect_completion(sink, revision, result["event_id"], finish["event_id"], "check-1")
    assert checked["completion_state"] == "BLOCKED"
    assert checked["goal_revision"] == 1 and checked["result_event_id"] == result["event_id"] and checked["finish_event_id"] == finish["event_id"]
    assert checked["artifacts"] == [] and "ACCEPTANCE_REQUIREMENTS_UNAVAILABLE" in checked["blockers"]
    assert results.inspect_completion(sink, revision, result["event_id"], finish["event_id"], "check-1") == checked
    with runs.connect() as db:
        saved = db.execute("SELECT receipt FROM agent_run_operations WHERE run_id=? AND request_key=?", (sink.config.run_id, "completion-inspection:check-1")).fetchone()
        assert json.loads(saved[0]) == checked
    with pytest.raises(ValueError, match="尚未接入"):
        runs.transition(sink.config.run_id, revision, "SUCCEEDED", sink.lease_owner, sink.config.lease_epoch, verified=True)
    reopened = RunStore(runs.path, allow_migration=False)
    assert reopened.read_run(sink.config.run_id)["status"] == "RUNNING"
    assert reopened.read_run(sink.config.run_id)["revision"] == revision
    assert [item["type"] for item in reopened.events(sink.config.run_id, 0)] == ["STATUS_CHANGED", "RESULT_RECORDED", "RUN_FINISHED"]
    with pytest.raises(ValueError):
        results.inspect_completion(sink, revision, result["event_id"], result["event_id"], "check-2")
    runs.add_input(sink.config.run_id, 1, "input", "补充要求")
    with pytest.raises(ValueError):
        results.inspect_completion(sink, revision, result["event_id"], finish["event_id"], "check-2")
    with pytest.raises(ValueError):
        results.inspect_completion(sink, runs.read_run(sink.config.run_id)["revision"], result["event_id"], finish["event_id"], "check-2")


def test_completion_requires_result_before_matching_finish(tmp_path):
    _, runs, results, sink = setup_result(tmp_path)
    premature = sink.emit("premature-finish", "RUN_FINISHED", {"outcome": "TECHNICAL"})
    result = results.record(sink, "meeting-result", 1, "会议资料技术记录", [{"source_id": "finance-note", "locator": "经营明细"}])
    revision = runs.read_run(sink.config.run_id)["revision"]
    with pytest.raises(ValueError, match="事件顺序"):
        results.inspect_completion(sink, revision, result["event_id"], premature["event_id"], "invalid-order")
    with runs.connect() as db:
        assert db.execute("SELECT count(*) FROM agent_run_operations WHERE request_key=?", ("completion-inspection:invalid-order",)).fetchone() == (0,)
    finish = sink.emit("current-finish", "RUN_FINISHED", {"outcome": "TECHNICAL"})
    revision = runs.read_run(sink.config.run_id)["revision"]
    checked = results.inspect_completion(sink, revision, result["event_id"], finish["event_id"], "valid-order")
    assert checked["completion_state"] == "BLOCKED"
    assert results.inspect_completion(sink, revision, result["event_id"], finish["event_id"], "valid-order") == checked


def test_completion_inspection_rejects_cancel_and_withdrawal(tmp_path):
    store, runs, results, sink = setup_result(tmp_path)
    result = results.record(sink, "answer", 1, "技术结果", [])
    finish = sink.emit("finish", "RUN_FINISHED", {"outcome": "TECHNICAL"})
    revision = runs.read_run(sink.config.run_id)["revision"]
    assert begin_source_cleanup(store, "ui-check", "finance-note", "1") is True
    with pytest.raises(ValueError):
        results.inspect_completion(sink, revision, result["event_id"], finish["event_id"], "check")
    runs.cancel(sink.config.run_id, revision)
    with pytest.raises(ValueError):
        results.inspect_completion(sink, runs.read_run(sink.config.run_id)["revision"], result["event_id"], finish["event_id"], "check")


def test_business_receipt_requires_evidence_for_current_goal(tmp_path):
    store, runs, results, sink = setup_result(tmp_path)
    RunRequirements(runs, allow_migration=True)
    with runs.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        RunRequirements.save_in_transaction(db, sink.config.run_id, 1, "technical-selection", ["BUSINESS_RECEIPT"])
        meeting = store.get(db, "ui-check", "initial", "snapshot")["meeting"]
        assert meeting["meeting_id"] == "meeting-1"
    result = results.record(sink, "answer", 1, "技术结果", [])
    finish = sink.emit("finish", "RUN_FINISHED", {"outcome": "TECHNICAL"})
    revision = runs.read_run(sink.config.run_id)["revision"]
    checked = results.inspect_completion(sink, revision, result["event_id"], finish["event_id"], "business-check")
    assert checked["output_checks"] == [{"type": "BUSINESS_RECEIPT", "state": "NOT_VERIFIED"}]
    assert "REQUIRED_OUTPUT_UNVERIFIED" in checked["blockers"]
    assert results.inspect_completion(sink, revision, result["event_id"], finish["event_id"], "business-check") == checked
    runs.add_input(sink.config.run_id, 1, "input", "补充要求")
    with runs.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        RunRequirements.save_in_transaction(db, sink.config.run_id, 2, "input", ["BUSINESS_RECEIPT"])
    runs.apply_input(sink.config.run_id, 1, sink.lease_owner, sink.config.lease_epoch)
    result = results.record(sink, "answer-2", 2, "补充要求的技术结果", [])
    finish = sink.emit("finish-2", "RUN_FINISHED", {"outcome": "TECHNICAL"})
    revision = runs.read_run(sink.config.run_id)["revision"]
    checked = results.inspect_completion(sink, revision, result["event_id"], finish["event_id"], "business-check-2")
    assert checked["goal_revision"] == 2
    assert checked["output_checks"] == [{"type": "BUSINESS_RECEIPT", "state": "NOT_VERIFIED"}]
    assert "REQUIRED_OUTPUT_UNVERIFIED" in checked["blockers"]


def test_business_receipt_inspection_uses_current_transaction(tmp_path):
    _, runs, results, sink = setup_result(tmp_path)
    RunRequirements(runs, allow_migration=True)
    business = RunBusinessReceipts(runs, results.scope, allow_migration=True)
    with runs.connect() as db:
        with pytest.raises(ValueError, match="同一数据库事务"):
            business.inspect_in_transaction(db, sink.config.run_id, 1)
        db.execute("BEGIN IMMEDIATE")
        RunRequirements.save_in_transaction(db, sink.config.run_id, 1, "technical-selection", ["BUSINESS_RECEIPT"])
        assert business.inspect_in_transaction(db, sink.config.run_id, 1) == {"state": "NOT_VERIFIED", "count": 0}
    result = results.record(sink, "answer", 1, "技术结果", [])
    finish = sink.emit("finish", "RUN_FINISHED", {"outcome": "TECHNICAL"})
    revision = runs.read_run(sink.config.run_id)["revision"]
    checked = results.inspect_completion(sink, revision, result["event_id"], finish["event_id"], "business-evidence", business_receipts=business)
    assert checked["business_receipt_inspection"] == {"state": "NOT_VERIFIED", "count": 0}
    assert checked["output_checks"] == [{"type": "BUSINESS_RECEIPT", "state": "NOT_VERIFIED"}]
    assert results.inspect_completion(sink, revision, result["event_id"], finish["event_id"], "business-evidence", business_receipts=business) == checked
    with sqlite3.connect(tmp_path / "other.sqlite") as db:
        db.execute("BEGIN")
        with pytest.raises(ValueError, match="同一数据库事务"):
            business.inspect_in_transaction(db, sink.config.run_id, 1)
    runs.cancel(sink.config.run_id, revision)
    with pytest.raises(ValueError):
        results.inspect_completion(sink, runs.read_run(sink.config.run_id)["revision"], result["event_id"], finish["event_id"], "business-canceled", business_receipts=business)


def test_terminal_business_receipt_inspection_does_not_require_active_lease(tmp_path):
    _, runs, results, sink = setup_result(tmp_path)
    RunRequirements(runs, allow_migration=True)
    business = RunBusinessReceipts(runs, results.scope, allow_migration=True)
    with runs.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        RunRequirements.save_in_transaction(db, sink.config.run_id, 1, "technical-selection", ["BUSINESS_RECEIPT"])
    run = runs.read_run(sink.config.run_id)
    runs.transition(sink.config.run_id, run["revision"], "FAILED", sink.lease_owner, sink.config.lease_epoch)
    with runs.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute("UPDATE agent_runs SET lease_expires_at=? WHERE run_id=?", ("2000-01-01T00:00:00+00:00", sink.config.run_id))
        assert business.inspect_terminal_in_transaction(db, sink.config.run_id, 1, sink.config.lease_epoch) == {"state": "NOT_VERIFIED", "count": 0}


def test_business_receipt_rejects_missing_intent_and_stale_goal(tmp_path):
    _, runs, results, sink = setup_result(tmp_path)
    RunRequirements(runs, allow_migration=True)
    business = RunBusinessReceipts(runs, results.scope, allow_migration=True)
    migration = Path(__file__).resolve().parents[2] / "validation/migrations/upgrade2_intents_001.sql"
    with runs.connect() as db:
        db.executescript("BEGIN IMMEDIATE;\n" + migration.read_text(encoding="utf-8"))
        db.execute("INSERT INTO agent_schema_migrations VALUES (?,?)", ("upgrade2_intents_001", hashlib.sha256(migration.read_bytes()).hexdigest()))
        RunRequirements.save_in_transaction(db, sink.config.run_id, 1, "technical-selection", ["BUSINESS_RECEIPT"])
        db.row_factory = sqlite3.Row
        with pytest.raises(ValueError, match="业务意图"):
            business._verify(db, sink.config.run_id, 1, "missing-intent", "missing-decision")
        with pytest.raises(ValueError, match="目标版本"):
            business._verify(db, sink.config.run_id, 2, "missing-intent", "missing-decision")
        with pytest.raises(web.HTTPUnauthorized):
            business.bind_decision_in_transaction(db, None, sink.config.run_id, 1, "missing-intent", "missing-decision", request=None)
        assert business.inspect_in_transaction(db, sink.config.run_id, 1) == {"state": "NOT_VERIFIED", "count": 0}
        assert db.execute("SELECT count(*) FROM agent_run_business_receipts").fetchone()[0] == 0


def test_completion_inspection_records_actual_artifact_metadata(tmp_path):
    store, runs, results, sink = setup_result(tmp_path, full_sources=True)
    workspace = tmp_path / "artifacts"
    workspace.mkdir()
    runs.configure_file_budget(sink.config.run_id, sink.lease_owner, sink.config.lease_epoch, 2, 200000)
    preparation = ArtifactPreparation(store, workspace, run_gate=sink, scope_service=results.scope, max_files=2, max_bytes=200000)
    RunRequirements(runs, allow_migration=True)
    with runs.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        RunRequirements.save_in_transaction(db, sink.config.run_id, 1, "technical-selection", ["TEXT", "MARKDOWN", "PDF"])
    artifact = preparation.create_meeting_brief(sink.config.run_id, ["simulation-meeting-material"], request_key="technical-file", format_name="MARKDOWN")
    result = results.record(sink, "answer", 1, "技术结果", [])
    finish = sink.emit("finish", "RUN_FINISHED", {"outcome": "TECHNICAL"})
    revision = runs.read_run(sink.config.run_id)["revision"]
    checked = results.inspect_completion(sink, revision, result["event_id"], finish["event_id"], "check-artifact")
    assert checked["artifacts"] == [{"artifact_id": artifact["artifact_id"], "version": artifact["version"], "sha256": artifact["sha256"], "media_type": "text/markdown", "verification_status": "VERIFIED", "status": "VERIFIED", "records_match": True, "goal_match": True}]
    assert checked["output_checks"] == [{"type": "TEXT", "state": "RECORD_PRESENT"}, {"type": "MARKDOWN", "state": "RECORD_PRESENT"}, {"type": "PDF", "state": "MISSING"}]
    assert "REQUIRED_OUTPUT_MISSING" in checked["blockers"]
    assert "ARTIFACT_FILES_UNVERIFIED" in checked["blockers"]
    runs.add_input(sink.config.run_id, 1, "input", "补充事项")
    with runs.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        RunRequirements.save_in_transaction(db, sink.config.run_id, 2, "input", ["MARKDOWN"])
    runs.apply_input(sink.config.run_id, 1, sink.lease_owner, sink.config.lease_epoch)
    next_result = results.record(sink, "answer-2", 2, "包含补充事项的技术结果", [])
    next_finish = sink.emit("finish-2", "RUN_FINISHED", {"outcome": "TECHNICAL"})
    next_revision = runs.read_run(sink.config.run_id)["revision"]
    checked = results.inspect_completion(sink, next_revision, next_result["event_id"], next_finish["event_id"], "check-next", artifact_preparation=preparation)
    assert checked["output_checks"] == [{"type": "MARKDOWN", "state": "MISSING"}]
    assert not checked["artifacts"][0]["goal_match"]


@pytest.mark.parametrize("format_name", ["MARKDOWN", "PDF", "DOCX", "XLSX", "PPTX"])
def test_completion_inspects_real_selected_file(tmp_path, format_name):
    store, runs, results, sink = setup_result(tmp_path, full_sources=True)
    workspace = tmp_path / "artifacts"
    workspace.mkdir()
    runs.configure_file_budget(sink.config.run_id, sink.lease_owner, sink.config.lease_epoch, 2, 1000000)
    preparation = ArtifactPreparation(store, workspace, run_gate=sink, scope_service=results.scope, max_files=2, max_bytes=1000000)
    RunRequirements(runs, allow_migration=True)
    with runs.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        RunRequirements.save_in_transaction(db, sink.config.run_id, 1, "technical-selection", [format_name])
    artifact = preparation.create_meeting_brief(sink.config.run_id, ["simulation-meeting-material"], request_key="technical-file", format_name=format_name)
    with store.connect() as db:
        document = store.get(db, "ui-check", "document", "simulation-meeting-material")
        assert artifact["source_refs"] == [{"source_id": document["source_id"], "revision": document["version"], "locator": document["original_locator"], "classification": document["source_type"], "sha256": checksum(document)}]
    assert preparation.create_meeting_brief(sink.config.run_id, ["simulation-meeting-material"], request_key="technical-file", format_name=format_name) == artifact
    with runs.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        evidence = preparation.verify_meeting_brief_in_transaction(db, artifact["artifact_id"], artifact["version"])
        assert evidence["format"] == format_name and evidence["sha256"] == artifact["sha256"]
        with pytest.raises(ValueError, match="版本"):
            preparation.verify_meeting_brief_in_transaction(db, artifact["artifact_id"], artifact["version"] + 1)
    result = results.record(sink, "answer", 1, "技术结果", [])
    finish = sink.emit("finish", "RUN_FINISHED", {"outcome": "TECHNICAL"})
    revision = runs.read_run(sink.config.run_id)["revision"]
    checked = results.inspect_completion(sink, revision, result["event_id"], finish["event_id"], "check-file", artifact_preparation=preparation)
    assert checked["output_checks"] == [{"type": format_name, "state": "FILE_VERIFIED"}]
    assert "ARTIFACT_FILES_UNVERIFIED" not in checked["blockers"]
    assert "RESULT_SEMANTICS_UNVERIFIED" in checked["blockers"] and checked["completion_state"] == "BLOCKED"
    assert results.inspect_completion(sink, revision, result["event_id"], finish["event_id"], "check-file", artifact_preparation=preparation) == checked
    path = workspace / artifact["storage_key"]
    with runs.connect() as db:
        db.execute("BEGIN")
        verified = verify_stored_artifact_file_in_transaction(db, artifact["artifact_id"], artifact["version"])
        assert verified["sha256"] == artifact["sha256"] and verified["file_state"] == "VERIFIED"
        with pytest.raises(ValueError, match="版本|元数据"):
            verify_stored_artifact_file_in_transaction(db, artifact["artifact_id"], artifact["version"] + 1)
    linked_workspace = tmp_path / "artifact-link"
    linked_workspace.symlink_to(workspace, target_is_directory=True)
    with pytest.raises((ValueError, OSError)):
        read_verified_file(linked_workspace, artifact["storage_key"], artifact["size_bytes"], artifact["sha256"])
    linked_parent = tmp_path / "parent-link"
    linked_parent.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises((ValueError, OSError)):
        read_verified_file(linked_parent / "artifacts", artifact["storage_key"], artifact["size_bytes"], artifact["sha256"])
    outside = tmp_path / "outside-artifact"
    path.rename(outside)
    path.symlink_to(outside)
    with runs.connect() as db:
        db.execute("BEGIN")
        with pytest.raises(OSError):
            verify_stored_artifact_file_in_transaction(db, artifact["artifact_id"], artifact["version"])
    path.unlink()
    outside.rename(path)
    original = path.read_bytes()
    path.write_bytes(b"x" * len(original))
    with runs.connect() as db:
        db.execute("BEGIN")
        with pytest.raises(ValueError, match="摘要"):
            verify_stored_artifact_file_in_transaction(db, artifact["artifact_id"], artifact["version"])
    path.write_bytes(original + b"changed")
    with runs.connect() as db:
        db.execute("BEGIN")
        with pytest.raises(ValueError, match="大小|摘要"):
            verify_stored_artifact_file_in_transaction(db, artifact["artifact_id"], artifact["version"])
    with pytest.raises(ValueError, match="大小|摘要"):
        results.inspect_completion(sink, revision, result["event_id"], finish["event_id"], "check-file", artifact_preparation=preparation)
    path.unlink()
    with runs.connect() as db:
        db.execute("BEGIN")
        with pytest.raises(FileNotFoundError):
            verify_stored_artifact_file_in_transaction(db, artifact["artifact_id"], artifact["version"])
    with pytest.raises(FileNotFoundError):
        results.inspect_completion(sink, revision, result["event_id"], finish["event_id"], "check-file", artifact_preparation=preparation)


def test_completion_does_not_credit_files_created_after_result(tmp_path):
    store, runs, results, sink = setup_result(tmp_path, full_sources=True)
    RunRequirements(runs, allow_migration=True)
    workspace = tmp_path / "artifacts"
    workspace.mkdir()
    runs.configure_file_budget(sink.config.run_id, sink.lease_owner, sink.config.lease_epoch, 2, 400000)
    preparation = ArtifactPreparation(store, workspace, run_gate=sink, scope_service=results.scope, max_files=2, max_bytes=400000)
    with runs.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        RunRequirements.save_in_transaction(db, sink.config.run_id, 1, "technical-selection", ["MARKDOWN"])
    result = results.record(sink, "early-result", 1, "模拟会议材料的技术结果。", [])
    late = preparation.create_meeting_brief(sink.config.run_id, ["simulation-meeting-material"], request_key="late-brief", format_name="MARKDOWN")
    finish = sink.emit("finish", "RUN_FINISHED", {"outcome": "TECHNICAL"})
    revision = runs.read_run(sink.config.run_id)["revision"]
    inspected = results.inspect_completion(sink, revision, result["event_id"], finish["event_id"], "late-check", artifact_preparation=preparation)
    assert inspected["output_checks"] == [{"type": "MARKDOWN", "state": "MISSING"}]
    assert inspected["artifacts"][0]["artifact_id"] == late["artifact_id"] and inspected["artifacts"][0]["goal_match"] is False
    assert "REQUIRED_OUTPUT_MISSING" in inspected["blockers"] and inspected["completion_state"] == "BLOCKED"
    assert results.inspect_completion(sink, revision, result["event_id"], finish["event_id"], "late-check", artifact_preparation=preparation) == inspected
    runs.add_input(sink.config.run_id, 1, "technical-input", "补充会议材料要求")
    with runs.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        RunRequirements.save_in_transaction(db, sink.config.run_id, 2, "technical-selection-2", ["MARKDOWN"])
    runs.apply_input(sink.config.run_id, 1, sink.lease_owner, sink.config.lease_epoch)
    current = preparation.create_meeting_brief(sink.config.run_id, ["simulation-meeting-material"], request_key="current-brief", format_name="MARKDOWN")
    next_result = results.record(sink, "current-result", 2, "模拟会议材料的当前技术结果。", [])
    next_finish = sink.emit("current-finish", "RUN_FINISHED", {"outcome": "TECHNICAL"})
    next_revision = runs.read_run(sink.config.run_id)["revision"]
    inspected = results.inspect_completion(sink, next_revision, next_result["event_id"], next_finish["event_id"], "current-check", artifact_preparation=preparation)
    assert inspected["output_checks"] == [{"type": "MARKDOWN", "state": "FILE_VERIFIED"}]
    assert next(item for item in inspected["artifacts"] if item["artifact_id"] == current["artifact_id"])["goal_match"] is True
    assert next(item for item in inspected["artifacts"] if item["artifact_id"] == late["artifact_id"])["goal_match"] is False
    assert inspected["completion_state"] == "BLOCKED"


def test_artifact_creation_waits_for_applied_goal(tmp_path):
    store, runs, results, sink = setup_result(tmp_path, full_sources=True)
    workspace = tmp_path / "artifacts"
    workspace.mkdir()
    runs.configure_file_budget(sink.config.run_id, sink.lease_owner, sink.config.lease_epoch, 1, 200000)
    preparation = ArtifactPreparation(store, workspace, run_gate=sink, scope_service=results.scope, max_files=1, max_bytes=200000)
    runs.add_input(sink.config.run_id, 1, "new-goal", "补充会议材料要求")
    with pytest.raises(ValueError, match="目标补充尚未采用"):
        preparation.create_meeting_brief(sink.config.run_id, ["simulation-meeting-material"], request_key="pending-file", format_name="MARKDOWN")
    with runs.connect() as db:
        assert db.execute("SELECT count(*) FROM agent_file_reservations WHERE run_id=?", (sink.config.run_id,)).fetchone() == (0,)
    assert list(workspace.iterdir()) == []
    runs.apply_input(sink.config.run_id, 1, sink.lease_owner, sink.config.lease_epoch)
    artifact = preparation.create_meeting_brief(sink.config.run_id, ["simulation-meeting-material"], request_key="pending-file", format_name="MARKDOWN")
    assert preparation.read_meeting_brief(artifact["artifact_id"])


def test_completion_file_check_requires_current_source(tmp_path):
    store, runs, results, sink = setup_result(tmp_path, full_sources=True)
    workspace = tmp_path / "artifacts"
    workspace.mkdir()
    runs.configure_file_budget(sink.config.run_id, sink.lease_owner, sink.config.lease_epoch, 1, 200000)
    preparation = ArtifactPreparation(store, workspace, run_gate=sink, scope_service=results.scope, max_files=1, max_bytes=200000)
    artifact = preparation.create_meeting_brief(sink.config.run_id, ["simulation-meeting-material"], request_key="technical-file", format_name="MARKDOWN")
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        store.control_withdraw(db, "ui-check", {"source_id": "simulation-meeting-material", "version": "1"})
    with runs.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        with pytest.raises((ValueError, web.HTTPException)):
            preparation.verify_meeting_brief_in_transaction(db, artifact["artifact_id"], artifact["version"])


def test_result_product_endpoint_rejects_unauthenticated_request(tmp_path):
    services = services_for(tmp_path)

    async def exercise():
        runner = web.AppRunner(product_application(services.recovery.channel, services.broker))
        await runner.setup()
        await web.TCPSite(runner, "127.0.0.1", 0).start()
        try:
            async with httpx.AsyncClient(trust_env=False) as client:
                url = "http://127.0.0.1:" + str(runner.addresses[0][1]) + "/api/v2/runs/unknown/result"
                response = await client.get(url)
                assert response.status_code == 401
        finally:
            await runner.cleanup()

    asyncio.run(exercise())


def test_result_citation_checks_use_persisted_service_record(tmp_path):
    _, runs, results, sink = setup_result(tmp_path)
    citations = [{"source_id": "finance-note", "locator": "原始定位"}]
    event = results.record(sink, "answer", 1, "技术结果", citations)
    run = runs.read_run(sink.config.run_id)
    transport = HermesTransport(sink, secrets.token_urlsafe(32), actor_id=run["actor_id"], space_id=run["space_id"], scope_service=results.scope)
    with runs.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        assert RunBroker.result_citation_checks_in_transaction(db, "ui-check", sink.config.run_id, event) is None
        saved = transport._record_citation_checks(db, event)
        assert RunBroker.result_citation_checks_in_transaction(db, "ui-check", sink.config.run_id, event) == saved
        assert saved == [{**citations[0], "locator_verification": "NOT_VERIFIED"}]
        output = {"run_id": sink.config.run_id, "goal_revision": 1, "result": event, "citation_checks": saved}
        Draft202012Validator({"$ref": "#/$defs/result", "$defs": EVENT_SCHEMA["$defs"]}).validate(output)
    with runs.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT body FROM objects WHERE namespace=? AND kind='hermes_result_citation_checks' AND id=?", ("ui-check", event["event_id"])).fetchone()
        modified = json.loads(row[0])
        modified["citations"][0]["locator_verification"] = "VERIFIED"
        db.execute("UPDATE objects SET body=? WHERE namespace=? AND kind='hermes_result_citation_checks' AND id=?", (json.dumps(modified), "ui-check", event["event_id"]))
        with pytest.raises(ValueError, match="不可核查"):
            RunBroker.result_citation_checks_in_transaction(db, "ui-check", sink.config.run_id, event)
        db.rollback()
    with runs.connect() as db:
        db.execute("BEGIN")
        assert RunBroker.result_citation_checks_in_transaction(db, "ui-check", sink.config.run_id, event) == saved
        assert RunBroker.result_citation_checks_in_transaction(db, "ui-check", sink.config.run_id, None) is None


def test_terminal_business_receipt_rejects_missing_intent_without_mutation(tmp_path):
    _, runs, results, sink = setup_result(tmp_path)
    RunRequirements(runs, allow_migration=True)
    business = RunBusinessReceipts(runs, results.scope, allow_migration=True)
    with runs.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        RunRequirements.save_in_transaction(db, sink.config.run_id, 1, "terminal-receipt", ["BUSINESS_RECEIPT"])
    run = runs.read_run(sink.config.run_id)
    runs.transition(sink.config.run_id, run["revision"], "FAILED", sink.lease_owner, sink.config.lease_epoch)
    migration = Path(__file__).resolve().parents[2] / "validation/migrations/upgrade2_intents_001.sql"
    with runs.connect() as db:
        db.executescript("BEGIN IMMEDIATE;\n" + migration.read_text(encoding="utf-8"))
        db.execute("INSERT INTO agent_schema_migrations VALUES (?,?)", ("upgrade2_intents_001", hashlib.sha256(migration.read_bytes()).hexdigest()))
    with runs.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute("UPDATE agent_runs SET lease_expires_at=? WHERE run_id=?", ("2000-01-01T00:00:00+00:00", sink.config.run_id))
        db.execute(
            "INSERT INTO agent_run_business_receipts VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (sink.config.run_id, 1, "missing-intent", sink.lease_owner, "ui-check", "missing-decision",
             "boss.assignment.create", "missing-object", "1", "missing-payload", "missing-decision", "missing-receipt"),
        )
    before = terminal_receipt_state(runs, sink.config.run_id)
    with runs.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        with pytest.raises(ValueError):
            business.inspect_terminal_in_transaction(db, sink.config.run_id, 1, sink.config.lease_epoch)
        db.rollback()
    assert terminal_receipt_state(runs, sink.config.run_id) == before


def terminal_receipt_state(runs, run_id):
    with runs.connect() as db:
        run = db.execute("SELECT status,revision,lease_owner,lease_epoch,lease_expires_at FROM agent_runs WHERE run_id=?", (run_id,)).fetchone()
        return (tuple(run), db.execute("SELECT count(*) FROM agent_run_business_receipts WHERE run_id=?", (run_id,)).fetchone()[0],
                db.execute("SELECT count(*) FROM agent_run_events WHERE run_id=?", (run_id,)).fetchone()[0],
                db.execute("SELECT count(*) FROM agent_run_operations WHERE run_id=?", (run_id,)).fetchone()[0])
