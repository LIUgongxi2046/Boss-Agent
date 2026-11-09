import sqlite3

import pytest
from aiohttp import web

from agent_run_api import VALIDATORS
from agent_run_broker import RunBroker, RunIdentity
from agent_run_object_scope import AgentRunObjectScope
from business import checksum
from test_agent_run_result import setup_result


def test_object_scope_resolves_selected_simulated_objects_and_rejects_changes(tmp_path):
    store, runs, results, sink = setup_result(tmp_path)
    service = AgentRunObjectScope(runs, results.scope, allow_migration=True)
    broker = RunBroker(runs, scope_service=results.scope, object_scope=service)
    proof = results.scope.prove("result-check", ["finance-note"])
    identity = RunIdentity(proof.owner_id, proof.namespace, "BOSS", frozenset({proof.chat_id}), frozenset({"finance-note"}))
    with runs.connect() as db:
        db.execute("BEGIN")
        candidates = service.candidates_in_transaction(db, proof)
        assert {"task", "event", "metric_detail"}.issubset({item["entity_type"] for item in candidates})
        assert VALIDATORS["object_scope_candidates"].is_valid({"run_id": sink.config.run_id, "goal_revision": 1, "selection_allowed": True, "unavailable_reasons": [], "objects": candidates})
        assert all(item["sha256"] == checksum(item["data"]) for item in candidates)
        for kind, interface, identifier in (("task", "SI06", "historical-1"), ("event", "SI14", "event-1")):
            projection = service.simulation.project_in_transaction("BOSS", db, {"interface_id": interface, "object_ids": [kind + ":" + identifier], "filters": {}})
            actual = next(item for item in projection["records"] if item["entity_type"] == kind and item["object_id"] == identifier)
            object_ref = {"entity_type": kind, "object_id": identifier, "version": actual["version"], "sha256": checksum(actual["data"])}
            assert service._resolve(db, object_ref, proof)["object_id"] == identifier
        projection = service.simulation.project_in_transaction("BOSS", db, {"interface_id": "SI07", "object_ids": ["metric_detail:BASE-0"], "filters": {}})
        record = next(item for item in projection["records"] if item["entity_type"] == "metric_detail")
        ref = {"entity_type": "metric_detail", "object_id": record["object_id"], "version": record["version"], "sha256": checksum(record["data"])}
        selected = service._resolve(db, ref, proof)
        assert selected["source_refs"][0]["source_id"] == "finance-note"
        with pytest.raises(web.HTTPConflict):
            service._resolve(db, {**ref, "sha256": "0" * 64}, proof)
        with pytest.raises(ValueError, match="缺少明确对象选择"):
            service.read_in_transaction(db, sink, 1)
    payload = {"expected_goal_revision": 1, "request_key": "object-selection", "objects": [ref]}
    assert VALIDATORS["object_scope_request"].is_valid(payload)
    assert not VALIDATORS["object_scope_request"].is_valid({**payload, "actor_id": proof.owner_id})
    with pytest.raises(web.HTTPUnauthorized):
        service.bind(broker, identity, sink.config.run_id, payload, request=None)
    with pytest.raises(web.HTTPUnauthorized):
        service.candidates(broker, identity, sink.config.run_id, request=None)
    with pytest.raises(web.HTTPUnauthorized):
        service.request_receipt(broker, identity, sink.config.run_id, "object-selection", request=None)
    with runs.connect() as db:
        assert db.execute("SELECT count(*) FROM agent_run_object_scopes").fetchone() == (0,)
    store.control("ui-check", "withdraw", {"source_id": "finance-note", "version": "1"})
    with runs.connect() as db:
        db.execute("BEGIN")
        assert all(item["entity_type"] != "metric_detail" for item in service.candidates_in_transaction(db, proof))
        with pytest.raises((ValueError, web.HTTPException)):
            service._resolve(db, ref, proof)


def test_object_scope_rejects_unknown_records_and_unselected_sources(tmp_path):
    _, runs, results, sink = setup_result(tmp_path, full_sources=True)
    service = AgentRunObjectScope(runs, results.scope, allow_migration=True)
    proof = results.scope.prove("result-check", ["simulation-meeting-material"])
    with runs.connect() as db:
        db.execute("BEGIN")
        travel = service.simulation.project_in_transaction("BOSS", db, {"interface_id": "SI03", "object_ids": [], "filters": {}})
        assert any(item["entity_type"] == "travel_plan" and item["source_refs"] for item in travel["records"])
        trip = next(item for item in travel["records"] if item["entity_type"] == "travel_plan" and item["data"] is not None)
        transport = (trip["data"].get("pending") or {}).get("details", {}).get("transport_refs", [])
        assert transport and all(any(source["source_id"] == item["source_id"] and source["version"] == item["version"] for source in service._record_sources(trip)) for item in transport)
        assert all(item["entity_type"] != "travel_plan" for item in service.candidates_in_transaction(db, proof))
        projection = service.simulation.project_in_transaction("BOSS", db, {"interface_id": "SI07", "object_ids": ["metric_detail:BASE-0"], "filters": {}})
        record = next(item for item in projection["records"] if item["entity_type"] == "metric_detail")
        ref = {"entity_type": "metric_detail", "object_id": record["object_id"], "version": record["version"], "sha256": checksum(record["data"])}
        with pytest.raises(web.HTTPForbidden):
            service._resolve(db, ref, proof)
        with pytest.raises(web.HTTPConflict):
            service._resolve(db, {**ref, "object_id": "unknown"}, proof)


def test_object_selection_transaction_replays_and_detects_changed_objects(tmp_path):
    store, runs, results, sink = setup_result(tmp_path)
    service = AgentRunObjectScope(runs, results.scope, allow_migration=True)
    proof = results.scope.prove("result-check", ["finance-note"])
    run_id = runs.create_run(proof.owner_id, proof.namespace, "object-test-create", "object-test-digest")
    with runs.connect() as db:
        db.execute("UPDATE agent_runs SET conversation_id=(SELECT conversation_id FROM agent_runs WHERE run_id=?),goal=(SELECT goal FROM agent_runs WHERE run_id=?),selected_refs=(SELECT selected_refs FROM agent_runs WHERE run_id=?),scope_proof=(SELECT scope_proof FROM agent_runs WHERE run_id=?) WHERE run_id=?", (sink.config.run_id, sink.config.run_id, sink.config.run_id, sink.config.run_id, run_id))
    with runs.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        db.row_factory = sqlite3.Row
        run = db.execute("SELECT * FROM agent_runs WHERE run_id=?", (run_id,)).fetchone()
        db.row_factory = None
        candidate = next(item for item in service.candidates_in_transaction(db, proof) if item["entity_type"] == "metric_detail")
        ref = {key: candidate[key] for key in ("entity_type", "object_id", "version", "sha256")}
        payload = {"expected_goal_revision": 1, "request_key": "selection-1", "objects": [ref]}
        receipt = service._bind_in_transaction(db, run, proof, payload)
        assert service._bind_in_transaction(db, run, proof, payload) == receipt
        assert service._receipt_in_transaction(db, run_id, "selection-1", proof) == receipt
        with pytest.raises(web.HTTPConflict):
            service._bind_in_transaction(db, run, proof, {**payload, "request_key": "selection-2"})
    with store.connect() as db:
        initial = store.get(db, "ui-check", "initial", "snapshot")
        detail = next(item for item in initial["details"] if item["record_id"] == ref["object_id"])
        detail["version"] = str(int(detail["version"]) + 1)
        store.put(db, "ui-check", "initial", "snapshot", initial)
    with runs.connect() as db:
        db.execute("BEGIN")
        with pytest.raises(web.HTTPConflict):
            service._receipt_in_transaction(db, run_id, "selection-1", proof)
