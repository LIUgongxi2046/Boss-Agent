import json
import sqlite3
import subprocess
from pathlib import Path

from agent_run_broker import RunBroker
from agent_run_requirements import RunRequirements
from agent_run_store import RunStore


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / ".work/upgrade2-u2-09/pytest-goal-waiting-final/test_existing_run_through_loca1/business.sqlite"


def test_waiting_panel_with_saved_technical_run(tmp_path):
    database = tmp_path / "business.sqlite"
    with sqlite3.connect(f"file:{SOURCE}?mode=ro&immutable=1", uri=True) as source, sqlite3.connect(database) as target:
        source.backup(target)
    runs = RunStore(database, allow_migration=False)
    with runs.connect() as db:
        db.execute("BEGIN")
        run_id = db.execute("SELECT run_id FROM agent_runs").fetchone()[0]
        run = runs.read_run(run_id)
        requirements = RunRequirements.read_in_transaction(db, run_id, run["goal_revision"])
        events = runs.event_page_in_transaction(db, run_id, 0)["events"]
    assert run["status"] == "WAITING_INPUT"
    assert requirements["state"] == "PENDING_CONFIRMATION"
    payload = {"run": run, "requirements": requirements, "events": events, "actions": RunBroker.allowed_actions(run)}
    result = subprocess.run(["node", str(ROOT / "app/tests/u2_07_waiting_check.cjs")], cwd=ROOT,
                            input=json.dumps(payload, ensure_ascii=False), text=True, capture_output=True, check=True)
    assert json.loads(result.stdout)["waiting_input"] is True
