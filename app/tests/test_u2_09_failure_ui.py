import json
import sqlite3
import subprocess
from pathlib import Path

from agent_run_store import RunStore


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / ".work/upgrade2/u2-03/bridge-manager-final-tests/test_process_exit_updates_stat1/runs.sqlite"


def test_saved_engine_failure_reaches_run_panel():
    with sqlite3.connect(f"file:{SOURCE}?mode=ro&immutable=1", uri=True) as db:
        run_id, status, revision = db.execute("SELECT run_id,status,revision FROM agent_runs").fetchone()
    assert status == "FAILED"
    store = RunStore(SOURCE, allow_migration=False)
    events = store.events(run_id, 0)
    failure = next(event for event in events if event["type"] == "RUN_FAILED")
    assert failure["payload"]["error_code"] == "ENGINE_PROCESS_EXIT"
    data = {"run_id":run_id, "status":status, "revision":revision, "events":events, "failure":failure}
    result = subprocess.run(["node", str(ROOT / "app/tests/u2_09_failure_ui_check.cjs")], input=json.dumps(data, ensure_ascii=False), text=True, capture_output=True, check=True, cwd=ROOT)
    assert json.loads(result.stdout)["failure_visible"]
