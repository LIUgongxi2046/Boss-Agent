import json
import sqlite3
import subprocess
from pathlib import Path

from agent_artifact_api import artifact_goal_revision_in_transaction


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / ".work/upgrade2-u2-08-simulated/pytest-artifact-goal-002/test_created_artifact_preserve0/business.sqlite"


def test_actual_saved_goal_revision_reaches_component():
    with sqlite3.connect(f"file:{SOURCE}?mode=ro&immutable=1", uri=True) as db:
        db.execute("BEGIN")
        db.row_factory = sqlite3.Row
        record = db.execute("SELECT * FROM agent_artifacts").fetchone()
        db.row_factory = None
        saved_revision = artifact_goal_revision_in_transaction(db, record)
        saved = db.execute("SELECT goal_revision FROM agent_artifact_goals WHERE artifact_id=?", (record["artifact_id"],)).fetchone()[0]
        current = db.execute("SELECT goal_revision FROM agent_runs WHERE run_id=?", (record["run_id"],)).fetchone()[0]
        assert saved_revision == saved == 1 and current == 2
        artifact = {"artifact_id": record["artifact_id"], "run_id": record["run_id"], "goal_revision": saved_revision}
    result = subprocess.run(["node", str(ROOT / "app/tests/u2_09_artifact_goal_ui_check.cjs")], cwd=ROOT,
                            input=json.dumps({"artifact": artifact, "before": saved, "after": current}),
                            text=True, capture_output=True, check=True)
    assert json.loads(result.stdout) == {"current": saved, "historical": current}
