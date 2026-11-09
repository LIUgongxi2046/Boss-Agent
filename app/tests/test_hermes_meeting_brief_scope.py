import json
import sqlite3
from dataclasses import asdict, replace

import pytest
from aiohttp import web

from agent_run_meeting_scope import meeting_context_in_transaction
from agent_run_object_scope import AgentRunObjectScope
from boss_simulation_api import _context
from business import checksum
from hermes_bridge import EngineEventSink
from hermes_domain_intents import prepare_meeting_brief_in_transaction
from test_agent_run_result import setup_result


def test_scoped_meeting_brief_transaction_and_replay(tmp_path):
    store, runs, results, original = setup_result(tmp_path)
    service = AgentRunObjectScope(runs, results.scope, allow_migration=True)
    with runs.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        with pytest.raises(ValueError):
            prepare_meeting_brief_in_transaction(db, store, service, original, {"meeting_id": "meeting-1", "meeting_version": "1", "expected_version": "0"}, "missing-selection")
    with store.connect() as db:
        session = results.scope.sources._session(db, _context(db), "result-check")
        binding = store.get(db, "ui-check", "conversation_source_binding", session["session_id"])
        document = store.get(db, "ui-check", "document", "meeting-minutes")
        binding["source_refs"].append({"source_id": document["source_id"], "version": document["version"]})
        binding["source_pins"].append({"source_id": document["source_id"], "version": document["version"], "content_sha256": checksum(document)})
        store.put(db, "ui-check", "conversation_source_binding", session["session_id"], binding)
    proof = results.scope.prove("result-check", ["finance-note", "meeting-minutes"])
    run_id = runs.create_run(proof.owner_id, proof.namespace, "brief-scope-run", "brief-scope-digest")
    with runs.connect() as db:
        db.execute("UPDATE agent_runs SET conversation_id=?,goal=?,selected_refs=?,scope_proof=? WHERE run_id=?", (proof.chat_id, "会议简报技术核查", json.dumps(["finance-note", "meeting-minutes"]), json.dumps(asdict(proof)), run_id))
    with runs.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        meeting = meeting_context_in_transaction(service, db, proof, "meeting-1")
        ref = {"entity_type": "meeting_context", "object_id": "meeting-1", "version": meeting["meeting"]["version"], "sha256": checksum(meeting)}
        db.row_factory = sqlite3.Row
        run = db.execute("SELECT * FROM agent_runs WHERE run_id=?", (run_id,)).fetchone()
        db.row_factory = None
        service._bind_in_transaction(db, run, proof, {"expected_goal_revision": 1, "request_key": "meeting-scope-selection", "objects": [ref]})
    lease = runs.acquire_queued_for_execution(run_id, 0, "brief-worker", 60)
    sink = EngineEventSink(runs, replace(original.config, run_id=run_id, lease_epoch=lease["epoch"]), "brief-worker")
    params = {"meeting_id": "meeting-1", "meeting_version": meeting["meeting"]["version"], "expected_version": "0"}
    with runs.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        with pytest.raises(web.HTTPConflict):
            prepare_meeting_brief_in_transaction(db, store, service, sink, {**params, "meeting_version": "0"}, "brief-request")
        result = prepare_meeting_brief_in_transaction(db, store, service, sink, params, "brief-request")
        assert result["version"] == "1" and result["message_sent"] is False
        assert result["brief"] == store.get(db, "ui-check", "meeting_brief", "meeting-1")
        assert result["brief"]["compiled"] == meeting["compiled"]
        assert result["brief"]["compiled"]["commitments"]
        assert all(source["source_sha256"] for source in result["brief"]["compiled"]["sources"])
        assert result["content_checks"] == {kind: "NOT_VERIFIED" for kind in ("AGENDA", "CONSENSUS", "CONFLICT", "DECISION")}
        for material in result["source_materials"]:
            current = store.get(db, "ui-check", "document", material["source_id"])
            assert material == {"source_id": current["source_id"], "version": current["version"], "source_sha256": checksum(current), "content": current["content"]}
        assert prepare_meeting_brief_in_transaction(db, store, service, sink, params, "brief-request") == result
        assert store.get(db, "ui-check", "meeting_brief", "meeting-1")["compiled"] == meeting["compiled"]
        with pytest.raises(web.HTTPConflict):
            prepare_meeting_brief_in_transaction(db, store, service, sink, {**params, "expected_version": "1"}, "brief-request")
        db.rollback()
    with runs.connect() as db:
        assert db.execute("SELECT count(*) FROM objects WHERE kind='meeting_brief'").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM idempotency WHERE operation='boss.meeting.brief.prepare'").fetchone()[0] == 0
    with runs.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        result = prepare_meeting_brief_in_transaction(db, store, service, sink, params, "brief-request")
        assert result["version"] == "1"
    store.control("ui-check", "withdraw", {"source_id": "meeting-minutes", "version": document["version"]})
    with runs.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        with pytest.raises((ValueError, web.HTTPException)):
            prepare_meeting_brief_in_transaction(db, store, service, sink, params, "brief-request")
