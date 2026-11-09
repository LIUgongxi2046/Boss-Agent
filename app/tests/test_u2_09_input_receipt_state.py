import json
import subprocess
from pathlib import Path

import pytest

from agent_run_store import RunStore
from controls import ControlStore


ROOT = Path(__file__).resolve().parents[2]


def test_duplicate_and_stale_input_receipts_show_goal_version(tmp_path):
    store = ControlStore(tmp_path / "business.sqlite")
    store.initialize("ui-check")
    runs = RunStore(store.path)
    run_id = runs.create_run("technical-check", "ui-check", "input-receipt-check", "input-receipt-digest")
    row = runs.read_run(run_id)
    lease = runs.acquire_lease(run_id, row["revision"], "input-receipt-worker", 60)
    runs.transition(run_id, lease["revision"], "RUNNING", "input-receipt-worker", lease["epoch"])

    first = runs.add_input(run_id, 1, "input-1", "补充关注事项一")
    assert first["goal_revision"] == 2
    duplicate = runs.add_input(run_id, 1, "input-1", "补充关注事项一")
    assert duplicate == first
    with pytest.raises(ValueError, match="补充目标版本无效"):
        runs.add_input(run_id, 1, "input-stale", "过期目标版本")
    after_first = runs.read_run(run_id)
    assert after_first["goal_revision"] == 2

    second = runs.add_input(run_id, 2, "input-2", "补充关注事项二")
    assert second["goal_revision"] == 3
    after_second = runs.read_run(run_id)
    assert after_second["goal_revision"] == 3

    ahead = dict(second)
    ahead["goal_revision"] = 4
    cases = [
        {"name": "first_current", "receipt": first, "current": after_first["goal_revision"], "expected": "CURRENT"},
        {"name": "first_history", "receipt": first, "current": after_second["goal_revision"], "expected": "HISTORY"},
        {"name": "second_current", "receipt": second, "current": after_second["goal_revision"], "expected": "CURRENT"},
        {"name": "ahead", "receipt": ahead, "current": after_second["goal_revision"], "expected": "AHEAD"},
        {"name": "unknown", "receipt": first, "current": None, "expected": "UNKNOWN"},
    ]
    result = subprocess.run(["node", str(ROOT / "app/tests/u2_09_input_receipt_state_check.cjs")],
                            input=json.dumps({"cases": cases, "duplicate_same": duplicate == first}, ensure_ascii=False),
                            text=True, capture_output=True, check=True, cwd=ROOT)
    actual = json.loads(result.stdout)
    assert actual["duplicate_receipt_same"] is True
    assert actual["cases"]["first_current"]["state"] == "CURRENT"
    assert actual["cases"]["first_history"]["state"] == "HISTORY"
    assert actual["cases"]["second_current"]["state"] == "CURRENT"
    assert actual["cases"]["ahead"]["state"] == "AHEAD"
    assert actual["cases"]["unknown"]["state"] == "UNKNOWN"
    (tmp_path / "result.json").write_text(json.dumps(actual, ensure_ascii=False), encoding="utf-8")
