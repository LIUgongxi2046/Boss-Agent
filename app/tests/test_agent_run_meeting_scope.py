import json
import sqlite3
from dataclasses import asdict, replace

import pytest
from aiohttp import web

from agent_run_meeting_scope import meeting_context_in_transaction
from agent_run_object_scope import AgentRunObjectScope
from boss_command_api import BossCommandAPI
from boss_page_api import BossPageAPI
from boss_simulation_api import _context
from business import checksum
from hermes_bridge import EngineEventSink
from test_agent_run_result import setup_result
from test_v7_backend_services import activate_configuration, metric_values


def test_meeting_selection_checks_members_versions_and_sources(tmp_path):
    store, runs, results, sink = setup_result(tmp_path)
    service = AgentRunObjectScope(runs, results.scope, allow_migration=True)
    with store.connect() as db:
        session = results.scope.sources._session(db, _context(db), "result-check")
        binding = store.get(db, "ui-check", "conversation_source_binding", session["session_id"])
        document = store.get(db, "ui-check", "document", "meeting-minutes")
        binding["source_refs"].append({"source_id": "meeting-minutes", "version": document["version"]})
        binding["source_pins"].append({"source_id": "meeting-minutes", "version": document["version"], "content_sha256": checksum(document)})
        store.put(db, "ui-check", "conversation_source_binding", session["session_id"], binding)
    proof = results.scope.prove("result-check", ["finance-note", "meeting-minutes"])
    insufficient = results.scope.prove("result-check", ["finance-note"])
    run_id = runs.create_run(proof.owner_id, proof.namespace, "meeting-scope-create", "meeting-scope-digest")
    with runs.connect() as db:
        db.execute("UPDATE agent_runs SET conversation_id=?,goal=?,selected_refs=?,scope_proof=? WHERE run_id=?", ("result-check", "会议资料技术核查", json.dumps(["finance-note", "meeting-minutes"]), json.dumps(asdict(proof)), run_id))
    with runs.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        with pytest.raises(web.HTTPForbidden):
            meeting_context_in_transaction(service, db, insufficient, "meeting-1")
        data = meeting_context_in_transaction(service, db, proof, "meeting-1")
        assert len(data["participants"]) == 2
        assert {item["entity_type"] for item in data["members"]} >= {"task", "event", "metric_detail"}
        assert len(data["metric_configurations"]) == 6
        ref = {"entity_type": "meeting_context", "object_id": "meeting-1", "version": data["meeting"]["version"], "sha256": checksum(data)}
        payload = {"expected_goal_revision": 1, "request_key": "meeting-scope-selection", "objects": [ref]}
        db.row_factory = sqlite3.Row
        run = db.execute("SELECT * FROM agent_runs WHERE run_id=?", (run_id,)).fetchone()
        db.row_factory = None
        assert service._selection_reasons(db, run) == []
        saved = service._bind_in_transaction(db, run, proof, payload)
        assert service._selection_reasons(db, run) == ["GOAL_ALREADY_SELECTED"]
        assert service._bind_in_transaction(db, run, proof, payload) == saved
        assert service._receipt_in_transaction(db, run_id, payload["request_key"], proof) == saved
        with pytest.raises(web.HTTPConflict):
            service._bind_in_transaction(db, run, proof, {**payload, "request_key": "another-selection"})
    lease = runs.acquire_queued_for_execution(run_id, 0, "meeting-scope-worker", 60)
    meeting_sink = EngineEventSink(runs, replace(sink.config, run_id=run_id, lease_epoch=lease["epoch"]), "meeting-scope-worker")
    with runs.connect() as db:
        db.execute("BEGIN")
        assert service.read_meeting_in_transaction(db, meeting_sink, 1, "meeting-1")["meeting_context"] == data
        with pytest.raises(ValueError):
            service.read_meeting_in_transaction(db, meeting_sink, 1, "other-meeting")
    with runs.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        initial = store.get(db, "ui-check", "initial", "snapshot")
        initial["metric_definitions"][0]["definition_version"] = "2"
        store.put(db, "ui-check", "initial", "snapshot", initial)
        with pytest.raises(web.HTTPConflict):
            service._receipt_in_transaction(db, run_id, payload["request_key"], proof)
        with pytest.raises((ValueError, web.HTTPConflict)):
            service.read_meeting_in_transaction(db, meeting_sink, 1, "meeting-1")
        db.rollback()
    with runs.connect() as db:
        db.execute("BEGIN")
        assert service._receipt_in_transaction(db, run_id, payload["request_key"], proof) == saved
    activate_configuration(BossCommandAPI(store), BossPageAPI(store), "metrics", metric_values("gross_margin"), "gross_margin")
    with runs.connect() as db:
        db.execute("BEGIN")
        current = meeting_context_in_transaction(service, db, proof, "meeting-1")
        assert current["metric_configurations"]["gross_margin"]["version"] == "1"
        current_ref = {**ref, "sha256": checksum(current)}
        assert service._resolve(db, current_ref, proof)["object_id"] == "meeting-1"
        with pytest.raises(web.HTTPConflict):
            service._receipt_in_transaction(db, run_id, payload["request_key"], proof)
    with store.connect() as db:
        initial = store.get(db, "ui-check", "initial", "snapshot")
        initial["meeting"]["participant_ids"] = ["finance-1"]
        store.put(db, "ui-check", "initial", "snapshot", initial)
    with runs.connect() as db:
        db.execute("BEGIN")
        with pytest.raises(web.HTTPConflict):
            service._resolve(db, current_ref, proof)
        with pytest.raises(web.HTTPConflict):
            service._receipt_in_transaction(db, run_id, payload["request_key"], proof)
        updated = meeting_context_in_transaction(service, db, proof, "meeting-1")
        updated_ref = {**ref, "sha256": checksum(updated)}
    store.control("ui-check", "withdraw", {"source_id": "meeting-minutes", "version": "1"})
    with runs.connect() as db:
        db.execute("BEGIN")
        with pytest.raises((ValueError, web.HTTPException)):
            service._resolve(db, updated_ref, proof)
