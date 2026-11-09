import json
import sqlite3
from dataclasses import asdict
from pathlib import Path
import sys

import pytest
from aiohttp import web

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "validation"))

from agent_run_scope import RunScopeService
from agent_run_broker import RunBroker
from agent_run_store import RunStore
from agent_run_tool_budget import RunToolBudget
from boss_comprehensive_simulation import populate
from boss_memory_sessions import MemorySessionManager
from boss_meetings import MeetingAPI
from business import checksum
from controls import ControlStore
from hermes_domain_intents import preview_domain_intent, read_minutes_context_in_transaction
from hermes_intents import INTENT_VALIDATORS, bind_required_business_receipt, execute_domain_decision, validate_current_preview, validate_domain_decision_receipt, validate_domain_intent_provenance, validate_domain_snapshot


def test_assignment_preview_uses_current_sources_without_business_write(tmp_path):
    store = ControlStore(tmp_path / "business.sqlite")
    store.initialize("ui-check")
    populate(store, "2026-10-28T10:00:00+08:00")
    sessions = MemorySessionManager(tmp_path / "workspace", business_store=store, sessions_root=tmp_path / "sessions")
    session = sessions.get_or_create("websocket:domain-preview")
    sessions.save(session, fsync=True)
    with store.connect() as db:
        initial = store.get(db, "ui-check", "initial", "snapshot")
        source = store.get(db, "ui-check", "document", "finance-note")
        minute_source = store.get(db, "ui-check", "document", "meeting-minutes")
        minute = store.get(db, "ui-check", "minutes", initial["meeting"]["meeting_id"])
        meeting_sources = [item for item in initial["meeting"]["material_ids"] if item != initial["event"]["event_id"]]
        documents = [store.get(db, "ui-check", "document", source_id) for source_id in meeting_sources]
        refs = [{"source_id": item["source_id"], "version": item["version"]} for item in documents]
        binding = {"namespace": "ui-check", "owner_id": initial["owner_id"], "dataset_id": initial["dataset_id"], "dataset_version": initial["dataset_version"], "chat_id": "domain-preview", "session_id": session.key, "native_session_created_at": session.created_at.isoformat(), "binding_id": "domain-preview-binding", "context_version": "1", "source_refs": refs, "source_pins": [{**ref, "content_sha256": checksum(item)} for ref, item in zip(refs, documents)]}
        store.put(db, "ui-check", "conversation_source_binding", session.key, binding)
    scope = RunScopeService(store, sessions, "ui-check")
    selected = [item["source_id"] for item in documents]
    proof = scope.prove("domain-preview", selected)
    runs = RunStore(store.path)
    RunToolBudget(runs, allow_migration=True)
    run_id = runs.create_run(proof.owner_id, proof.namespace, "domain-preview-run", "domain-preview-digest")
    with runs.connect() as db:
        db.execute("UPDATE agent_runs SET conversation_id=?,selected_refs=?,scope_proof=? WHERE run_id=?", (proof.chat_id, json.dumps(selected), json.dumps(asdict(proof)), run_id))
    lease = runs.acquire_lease(run_id, 0, "domain-worker", 300)
    runs.transition(run_id, lease["revision"], "RUNNING", "domain-worker", lease["epoch"])
    meeting_api = MeetingAPI(store)
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        data = meeting_api._data(db)
        meeting = data["meeting"]
        meeting_draft = meeting_api._save(db, data, {"client_request_id": "technical-draft", "meeting_id": meeting["meeting_id"], "meeting_version": meeting["version"], "expected_version": "0", "purpose": "核查会议资料", "starts_at": meeting["starts_at"], "ends_at": meeting["ends_at"], "timezone": "Asia/Shanghai", "preparation_due_at": meeting["preparation_due_at"], "participant_ids": ["coordinator-1"], "source_refs": [{"source_id": source["source_id"], "version": source["version"]}]})
    params = {"purpose": "核查会议资料", "coordinator_id": "coordinator-1", "due_at": "2026-10-30T17:00:00+08:00", "timezone": "Asia/Shanghai", "evidence_requirements": ["核查记录"], "related_meeting_id": initial["meeting"]["meeting_id"], "related_event_ids": [initial["event"]["event_id"]], "source_refs": ["finance-note"], "content_version": "1"}
    with runs.connect() as db:
        db.execute("BEGIN")
        db.row_factory = sqlite3.Row
        run = db.execute("SELECT * FROM agent_runs WHERE run_id=?", (run_id,)).fetchone()
        before = db.execute("SELECT count(*) FROM objects WHERE kind IN ('authorization','task')").fetchone()[0]
        preview = preview_domain_intent(db, store, scope, run, "boss.assignment.create", params)
        assignment_context = read_minutes_context_in_transaction(db, store, scope, run)["assignment_context"]
        assert {key: assignment_context[key] for key in ("related_meeting_id", "related_event_ids", "source_refs", "content_version")} == {key: params[key] for key in ("related_meeting_id", "related_event_ids", "source_refs", "content_version")}
        assert params["coordinator_id"] in assignment_context["eligible_coordinator_ids"]
        assert preview["source_refs"][0]["source_sha256"] == checksum(source)
        assert preview["goal_revision"] == run["goal_revision"]
        assert preview["owner_decision_required"] is True
        assert preview["business_authority_granted"] is False
        minute_params = {"meeting_id": minute["meeting_id"], "expected_version": minute["version"], "source_id": minute["source_id"], "source_version": minute["source_version"]}
        minute_preview = preview_domain_intent(db, store, scope, run, "boss.minutes.confirm", minute_params)
        assert minute_preview["object_id"] == minute["minute_id"]
        assert minute_preview["source_refs"][0]["source_sha256"] == checksum(minute_source)
        with pytest.raises(web.HTTPConflict):
            preview_domain_intent(db, store, scope, run, "boss.minutes.confirm", {**minute_params, "expected_version": "0"})
        meeting_params = {"meeting_id": meeting["meeting_id"], "meeting_version": meeting["version"], "draft_version": meeting_draft["version"], "review_sha256": meeting_draft["review_sha256"]}
        meeting_preview = preview_domain_intent(db, store, scope, run, "boss.meeting.confirm", meeting_params)
        assert meeting_preview["object_id"] == meeting["meeting_id"]
        finish_params = {"meeting_id": meeting["meeting_id"], "expected_version": meeting["version"], "reason": "根据会议安排核查决定"}
        cancel_preview = preview_domain_intent(db, store, scope, run, "boss.meeting.cancel", finish_params)
        assert cancel_preview == preview_domain_intent(db, store, scope, run, "boss.meeting.cancel", finish_params)
        assert cancel_preview["details"]["version"] == meeting["version"]
        assert {item["source_id"] for item in cancel_preview["source_refs"]} == set(meeting_sources)
        assert cancel_preview["owner_decision_required"] is True and cancel_preview["business_authority_granted"] is False
        cancel_saved = {**cancel_preview, "plan_digest": "1" * 64, "budget_digest": "2" * 64}
        INTENT_VALIDATORS["preview_content"].validate(cancel_saved)
        cancel_item = {"intent_id": "preview-check", "status": "WAITING_CONFIRMATION", "revision": 0, "action": "boss.meeting.cancel", "payload_digest": checksum(cancel_saved), "object_id": cancel_saved["object_id"], "expected_revision": cancel_saved["object_revision"], "scope_revision": checksum(cancel_saved["source_refs"]), "client_request_id": "intent-preview-check"}
        decision = {"decision": "CONFIRM", "expected_revision": 0, "payload_digest": cancel_item["payload_digest"]}
        provenance_item = {**cancel_item, "run_id": run_id, "request_key": "unrecorded-intent", "request_digest": checksum({"action": cancel_item["action"], "params": finish_params}), "preview": json.dumps(cancel_saved)}
        with pytest.raises(web.HTTPConflict) as missing_provenance:
            validate_domain_intent_provenance(db, provenance_item)
        assert missing_provenance.value.text == "业务意图工具预留不可核查"
        with pytest.raises(web.HTTPConflict):
            validate_domain_decision_receipt(cancel_item, {})
        for changed in ({"action": "boss.meeting.held"}, {"payload_digest": "0" * 64}, {"object_id": "other-meeting"}, {"expected_revision": "0"}, {"scope_revision": "0" * 64}, {"client_request_id": "other-request"}, {"status": "SUCCEEDED"}):
            with pytest.raises(web.HTTPConflict):
                execute_domain_decision(db, meeting_api.commands, {**cancel_item, **changed}, cancel_saved, decision)
        with pytest.raises(web.HTTPConflict):
            execute_domain_decision(db, meeting_api.commands, cancel_item, cancel_saved, {"decision": "REJECT"})
        with pytest.raises(web.HTTPConflict):
            execute_domain_decision(db, meeting_api.commands, cancel_item, {**cancel_saved, "goal_revision": 2}, decision)
        for candidate in (preview, minute_preview, meeting_preview):
            saved_candidate = {**candidate, "plan_digest": "1" * 64, "budget_digest": "2" * 64}
            intent_candidate = {**cancel_item, "action": candidate["action"], "payload_digest": checksum(saved_candidate), "object_id": candidate["object_id"], "expected_revision": candidate["object_revision"], "scope_revision": checksum(candidate["source_refs"])}
            with pytest.raises(web.HTTPConflict):
                execute_domain_decision(db, meeting_api.commands, {**intent_candidate, "scope_revision": "0" * 64}, saved_candidate, {**decision, "payload_digest": intent_candidate["payload_digest"]})
        with pytest.raises(web.HTTPConflict):
            preview_domain_intent(db, store, scope, run, "boss.meeting.cancel", {**finish_params, "expected_version": "0"})
        with pytest.raises(web.HTTPBadRequest):
            preview_domain_intent(db, store, scope, run, "boss.meeting.cancel", {**finish_params, "reason": " "})
        with pytest.raises(web.HTTPConflict):
            preview_domain_intent(db, store, scope, run, "boss.meeting.held", finish_params)
        with pytest.raises(web.HTTPConflict):
            preview_domain_intent(db, store, scope, run, "boss.meeting.confirm", {**meeting_params, "draft_version": "0"})
        with pytest.raises(web.HTTPBadRequest):
            preview_domain_intent(db, store, scope, run, "boss.assignment.create", {**params, "actor_id": proof.owner_id})
        with pytest.raises(web.HTTPConflict):
            preview_domain_intent(db, store, scope, run, "boss.assignment.create", {**params, "source_refs": []})
        with pytest.raises(web.HTTPBadRequest):
            preview_domain_intent(db, store, scope, run, "boss.assignment.create", {**params, "evidence_requirements": []})
        with pytest.raises(web.HTTPConflict):
            preview_domain_intent(db, store, scope, {**dict(run), "goal_revision": run["goal_revision"] + 1}, "boss.assignment.create", params)
        with pytest.raises(ValueError):
            preview_domain_intent(db, store, scope, {**dict(run), "lease_epoch": run["lease_epoch"] + 1}, "boss.assignment.create", params)
        assert db.execute("SELECT count(*) FROM objects WHERE kind IN ('authorization','task')").fetchone()[0] == before
    narrow_selected = selected[:-1]
    with runs.connect() as db:
        with pytest.raises(web.HTTPConflict):
            execute_domain_decision(db, meeting_api.commands, cancel_item, cancel_saved, decision)
    narrow_proof = scope.prove("domain-preview", narrow_selected)
    with runs.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute("UPDATE agent_runs SET selected_refs=?,scope_proof=? WHERE run_id=?", (json.dumps(narrow_selected), json.dumps(asdict(narrow_proof)), run_id))
        db.row_factory = sqlite3.Row
        narrowed_run = db.execute("SELECT * FROM agent_runs WHERE run_id=?", (run_id,)).fetchone()
        with pytest.raises(web.HTTPForbidden):
            preview_domain_intent(db, store, scope, narrowed_run, "boss.meeting.cancel", finish_params)
        db.rollback()
    saved = {**minute_preview, "plan_digest": "1" * 64, "budget_digest": "2" * 64}
    INTENT_VALIDATORS["preview_content"].validate(saved)
    with runs.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute("UPDATE agent_runs SET status='WAITING_CONFIRMATION' WHERE run_id=?", (run_id,))
        db.row_factory = sqlite3.Row
        run = db.execute("SELECT * FROM agent_runs WHERE run_id=?", (run_id,)).fetchone()
        item = {"action": "boss.minutes.confirm", "payload_digest": checksum(saved), "object_id": saved["object_id"], "expected_revision": saved["object_revision"], "scope_revision": checksum(saved["source_refs"]), "preview": json.dumps(saved)}
        assert validate_current_preview(db, store, item, selected) == saved
        with pytest.raises(web.HTTPConflict):
            validate_current_preview(db, store, {**item, "payload_digest": "0" * 64}, selected)
        with pytest.raises(web.HTTPConflict):
            validate_current_preview(db, store, item, [])
        validate_domain_snapshot(db, scope, item, run, saved)
        with pytest.raises(web.HTTPConflict):
            validate_domain_snapshot(db, scope, item, run, {**saved, "goal_revision": 2})
        with pytest.raises(web.HTTPConflict):
            validate_domain_snapshot(db, scope, item, run, {**saved, "context_digest": "0" * 64})
        broker = RunBroker(runs, scope_service=scope)
        with pytest.raises(web.HTTPUnauthorized):
            bind_required_business_receipt(db, broker, None, None, run_id, run["goal_revision"], "missing-intent", "missing-decision")
    original_goal = runs.read_run(run_id)["goal"]
    with pytest.raises(web.HTTPUnauthorized):
        with runs.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("UPDATE agent_runs SET goal=? WHERE run_id=?", ("事务核查", run_id))
            bind_required_business_receipt(db, broker, None, None, run_id, 1, "missing-intent", "missing-decision")
    assert runs.read_run(run_id)["goal"] == original_goal
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        current_minute = store.get(db, "ui-check", "minutes", minute["meeting_id"])
        current_minute["version"] = str(int(current_minute["version"]) + 1)
        store.put(db, "ui-check", "minutes", minute["meeting_id"], current_minute)
    with runs.connect() as db:
        db.execute("BEGIN")
        db.row_factory = sqlite3.Row
        run = db.execute("SELECT * FROM agent_runs WHERE run_id=?", (run_id,)).fetchone()
        with pytest.raises(web.HTTPConflict):
            validate_domain_snapshot(db, scope, item, run, saved)
    store.control("ui-check", "withdraw", {"source_id": minute_source["source_id"], "version": minute_source["version"]})
    with runs.connect() as db:
        db.execute("BEGIN")
        db.row_factory = sqlite3.Row
        run = db.execute("SELECT * FROM agent_runs WHERE run_id=?", (run_id,)).fetchone()
        with pytest.raises(web.HTTPConflict) as denied:
            validate_domain_snapshot(db, scope, item, run, saved)
        assert denied.value.text == "来源已经撤销"
