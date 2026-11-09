import hashlib
import json
import sqlite3
import subprocess
from pathlib import Path

from agent_run_broker import RunBroker
from agent_run_store import RunStore
from controls import ControlStore


def test_actual_plan_component_and_run_actions(tmp_path):
    project = Path(__file__).resolve().parents[2]
    previous = project / ".work/upgrade2-u2-04/pytest-plan-handover-final/test_plan_handover_captures_di0/business.sqlite"
    with previous.open("rb") as content:
        source_sha256 = hashlib.file_digest(content, "sha256").hexdigest()
    with sqlite3.connect(previous.as_uri() + "?immutable=1", uri=True) as db:
        plan = json.loads(db.execute("SELECT body FROM objects WHERE kind='owner_plan' AND id='technical-plan'").fetchone()[0])
    assert plan["state"] == "PAUSED" and plan["source_type"] == "SIMULATED"

    store = ControlStore(tmp_path / "business.sqlite")
    store.initialize("ui-check")
    runs = RunStore(store.path)
    run_id = runs.create_run("technical-check", "ui-check", "panel-check", "panel-digest")
    snapshots = []
    row = runs.read_run(run_id)
    snapshots.append({**row, "allowed_actions": RunBroker.allowed_actions(row)})
    lease = runs.acquire_lease(run_id, row["revision"], "panel-worker", 60)
    runs.transition(run_id, lease["revision"], "RUNNING", "panel-worker", lease["epoch"])
    row = runs.read_run(run_id)
    snapshots.append({**row, "allowed_actions": RunBroker.allowed_actions(row)})
    runs.transition(run_id, row["revision"], "WAITING_INPUT", "panel-worker", lease["epoch"])
    row = runs.read_run(run_id)
    snapshots.append({**row, "allowed_actions": RunBroker.allowed_actions(row)})
    runs.transition(run_id, row["revision"], "INTERRUPTED", "panel-worker", lease["epoch"])
    row = runs.read_run(run_id)
    snapshots.append({**row, "allowed_actions": RunBroker.allowed_actions(row)})
    assert [item["status"] for item in snapshots] == ["QUEUED", "RUNNING", "WAITING_INPUT", "INTERRUPTED"]
    with store.connect() as db:
        supplement = store.get(db, "ui-check", "document", "finance-note")["source_id"]
    result = subprocess.run(["node", str(project / "app/tests/u2_09_plan_panel_check.cjs")],
        input=json.dumps({"plan": plan, "runs": snapshots, "supplement": supplement}, ensure_ascii=False),
        text=True, capture_output=True, check=True, cwd=project)
    actual = json.loads(result.stdout)
    assert actual["run_states"] == ["QUEUED", "RUNNING", "WAITING_INPUT", "INTERRUPTED"]
    assert actual["plan_component"] == "disabled-and-empty" and actual["disconnected"] == "disabled"
    (tmp_path / "result.json").write_text(json.dumps({**actual, "source_sha256": source_sha256}, ensure_ascii=False), encoding="utf-8")
