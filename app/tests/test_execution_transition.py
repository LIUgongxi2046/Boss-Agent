import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_public_transition_stops_native_work_and_new_process_adopts_scope(tmp_path):
    helper = ROOT / "app/tests/helpers/execution_transition_probe.py"
    prepared = subprocess.run([sys.executable, str(helper), "prepare", str(tmp_path)], cwd=ROOT,
        env={**os.environ, "BOSS_EXECUTION_NAMESPACE": "ui-check"}, capture_output=True, text=True, timeout=60)
    assert prepared.returncode == 0, prepared.stdout + prepared.stderr
    result = json.loads(prepared.stdout)
    assert result["transition_state"] == "ADOPTED" and result["namespace"].startswith("execution-")
    assert result["run_id"]
