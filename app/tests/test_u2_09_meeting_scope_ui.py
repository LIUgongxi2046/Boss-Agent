import json
import sqlite3
import subprocess
from dataclasses import asdict
from pathlib import Path

from agent_run_meeting_scope import meeting_context_in_transaction
from agent_run_broker import RunBroker, RunIdentity
from agent_run_object_scope import AgentRunObjectScope
from boss_simulation_api import _context
from business import checksum
from test_agent_run_result import setup_result


ROOT = Path(__file__).resolve().parents[2]


def test_meeting_scope_details_show_actual_members_and_allow_explicit_selection(tmp_path):
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
    run_id = runs.create_run(proof.owner_id, proof.namespace, "meeting-ui-check", "meeting-ui-digest")
    with runs.connect() as db:
        db.execute("UPDATE agent_runs SET conversation_id=?,goal=?,selected_refs=?,scope_proof=? WHERE run_id=?", ("result-check", "会议资料技术核查", json.dumps(["finance-note", "meeting-minutes"]), json.dumps(asdict(proof)), run_id))
    with runs.connect() as db:
        db.execute("BEGIN")
        data = meeting_context_in_transaction(service, db, proof, "meeting-1")
        ref = {"entity_type": "meeting_context", "object_id": "meeting-1", "version": data["meeting"]["version"], "sha256": checksum(data)}
        item = {**service._resolve(db, ref, proof), "data": data}
        db.row_factory = sqlite3.Row
        run = db.execute("SELECT * FROM agent_runs WHERE run_id=?", (run_id,)).fetchone()
        reasons = service._selection_reasons(db, run)
    assert len(data["participants"]) == 2 and data["members"]
    catalog = {"run_id": run_id, "goal_revision": run["goal_revision"], "selection_allowed": not reasons, "unavailable_reasons": reasons, "objects": [item]}
    with runs.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        db.row_factory = sqlite3.Row
        current = db.execute("SELECT * FROM agent_runs WHERE run_id=?", (run_id,)).fetchone()
        db.row_factory = None
        receipt = service._bind_in_transaction(db, current, proof, {"expected_goal_revision": 1, "request_key": "meeting-ui-selection", "objects": [ref]})
    current_identity = RunIdentity(proof.owner_id, proof.namespace, "BOSS", frozenset({proof.chat_id}), frozenset({"finance-note", "meeting-minutes"}))
    snapshot = RunBroker(runs, scope_service=results.scope, object_scope=service).read(current_identity, run_id)
    result = subprocess.run(["node", str(ROOT / "app/tests/u2_09_meeting_scope_ui_check.cjs")], cwd=ROOT,
                            input=json.dumps({"catalog": catalog, "snapshot": snapshot, "receipt": receipt}, ensure_ascii=False), text=True, capture_output=True, check=True)
    assert json.loads(result.stdout)["members"] == len(data["members"])
