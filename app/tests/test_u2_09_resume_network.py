import json
import sqlite3
import subprocess
from pathlib import Path

from agent_run_store import RunStore


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / ".work/upgrade2-u2-09/pytest-goal-waiting-final/test_existing_run_through_loca1/business.sqlite"


def test_resume_network_failure_is_visible_and_retryable():
    with sqlite3.connect(f"file:{SOURCE}?mode=ro&immutable=1", uri=True) as db:
        run_id = db.execute("SELECT run_id FROM agent_runs").fetchone()[0]
    snapshot = RunStore(SOURCE, allow_migration=False).read_run(run_id)
    assert snapshot["status"] == "WAITING_INPUT"
    result = subprocess.run(["node", str(ROOT / "app/tests/u2_09_resume_network_check.cjs")],
                            cwd=ROOT, input=json.dumps(snapshot), text=True, capture_output=True, check=True)
    assert "UnhandledPromiseRejectionWarning" not in result.stderr
    assert json.loads(result.stdout) == {"network_error_visible": True, "retry_visible": True}


def test_resume_permission_response_reaches_component():
    with sqlite3.connect(f"file:{SOURCE}?mode=ro&immutable=1", uri=True) as db:
        run_id = db.execute("SELECT run_id FROM agent_runs").fetchone()[0]
    snapshot = RunStore(SOURCE, allow_migration=False).read_run(run_id)
    assert snapshot["status"] == "WAITING_INPUT"
    result = subprocess.run(["node", str(ROOT / "app/tests/u2_09_resume_permission_check.cjs")],
                            cwd=ROOT, input=json.dumps(snapshot), text=True, capture_output=True, check=True, timeout=120)
    assert json.loads(result.stdout) == {"status": 401, "expired": 1}
