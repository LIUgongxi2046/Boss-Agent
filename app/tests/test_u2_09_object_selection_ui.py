import json
import sqlite3
import subprocess
from pathlib import Path

from agent_run_object_scope import AgentRunObjectScope
from test_agent_run_result import setup_result


ROOT = Path(__file__).resolve().parents[2]


def test_object_choices_show_actual_candidates_and_require_selection(tmp_path):
    _, runs, results, sink = setup_result(tmp_path)
    service = AgentRunObjectScope(runs, results.scope, allow_migration=True)
    proof = results.scope.prove("result-check", ["finance-note"])
    queued_id = runs.create_run(proof.owner_id, proof.namespace, "object-ui-check", "object-ui-digest")
    with runs.connect() as db:
        db.execute("BEGIN")
        objects = service.candidates_in_transaction(db, proof)
        db.row_factory = sqlite3.Row
        running = db.execute("SELECT * FROM agent_runs WHERE run_id=?", (sink.config.run_id,)).fetchone()
        queued = db.execute("SELECT * FROM agent_runs WHERE run_id=?", (queued_id,)).fetchone()
        running_reasons = service._selection_reasons(db, running)
        queued_reasons = service._selection_reasons(db, queued)
    assert {"task", "event", "metric_detail"}.issubset({item["entity_type"] for item in objects})
    assert "RUN_STATE_UNAVAILABLE" in running_reasons and queued_reasons == []
    catalog = {"run_id": queued_id, "goal_revision": queued["goal_revision"], "selection_allowed": not queued_reasons, "unavailable_reasons": queued_reasons, "objects": objects}
    unavailable = {"run_id": sink.config.run_id, "goal_revision": running["goal_revision"], "selection_allowed": not running_reasons, "unavailable_reasons": running_reasons, "objects": objects}
    result = subprocess.run(["node", str(ROOT / "app/tests/u2_09_object_selection_ui_check.cjs")], cwd=ROOT,
                            input=json.dumps({"catalog": catalog, "unavailable": unavailable}, ensure_ascii=False), text=True, capture_output=True, check=True)
    assert json.loads(result.stdout)["objects"] == len(objects)
