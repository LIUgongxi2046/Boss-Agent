import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_completion_inspection_display_logic_and_wiring():
    result = subprocess.run(["node", str(ROOT / "app/tests/u2_09_completion_logic_check.cjs")],
                            cwd=ROOT, text=True, capture_output=True, timeout=120)
    assert result.returncode == 0, result.stderr
    value = json.loads(result.stdout)
    assert value["blocker_label"] is True
    assert value["historical_notice"] is True
    assert value["historical_state_hidden"] is True
    assert value["finish_goal_run_match"] is True
    assert value["invalid_schema_rejected"] is True
    assert value["wiring"] is True
