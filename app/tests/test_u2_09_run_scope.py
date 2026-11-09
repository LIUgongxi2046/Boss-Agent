import json
import sqlite3
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / ".work/upgrade2-u2-04/pytest-run-result-verified/test_result_persists_idempoten0/business.sqlite"


def test_run_scope_key_includes_identity_space_run_and_token():
    with sqlite3.connect(f"file:{SOURCE}?mode=ro&immutable=1", uri=True) as db:
        run_id, conversation_id = db.execute("SELECT run_id,conversation_id FROM agent_runs").fetchone()
    assert run_id and conversation_id
    result = subprocess.run(["node", str(ROOT / "app/tests/u2_09_run_scope_check.cjs")],
                            input=json.dumps({"run_id": run_id, "conversation_id": conversation_id}),
                            text=True, capture_output=True, check=True, cwd=ROOT)
    actual = json.loads(result.stdout)
    assert actual["scope_key_changes_with_token"] is True
    assert actual["scope_key_changes_with_identity"] is True
    assert actual["scope_key_changes_with_space"] is True
    assert actual["scope_key_changes_with_run"] is True
    assert actual["wiring"] is True
