import json
import subprocess
from pathlib import Path

from agent_run_broker import RunBroker
from agent_run_store import RunStore
from controls import ControlStore


ROOT = Path(__file__).resolve().parents[2]


def test_cancel_requested_and_reconciling_states_reach_panel(tmp_path):
    store = ControlStore(tmp_path / "business.sqlite")
    store.initialize("ui-check")
    runs = RunStore(store.path)
    run_id = runs.create_run("technical-check", "ui-check", "cancel-state-check", "cancel-state-digest")
    row = runs.read_run(run_id)
    lease = runs.acquire_lease(run_id, row["revision"], "cancel-state-worker", 60)
    runs.transition(run_id, lease["revision"], "RUNNING", "cancel-state-worker", lease["epoch"])
    snapshots = []

    def snapshot():
        current = runs.read_run(run_id)
        snapshots.append({**current, "allowed_actions": RunBroker.allowed_actions(current)})

    snapshot()
    runs.cancel(run_id, runs.read_run(run_id)["revision"])
    snapshot()
    runs.transition(run_id, runs.read_run(run_id)["revision"], "RECONCILING", "cancel-state-worker", lease["epoch"])
    snapshot()
    runs.transition(run_id, runs.read_run(run_id)["revision"], "CANCELED", "cancel-state-worker", lease["epoch"], verified=True)
    snapshot()

    assert [item["status"] for item in snapshots] == ["RUNNING", "CANCEL_REQUESTED", "RECONCILING", "CANCELED"]
    assert snapshots[0]["cancel_requested_at"] is None
    assert all(item["cancel_requested_at"] for item in snapshots[1:])
    result = subprocess.run(["node", str(ROOT / "app/tests/u2_09_cancel_state_check.cjs")],
                            input=json.dumps({"runs": snapshots}, ensure_ascii=False),
                            text=True, capture_output=True, check=True, cwd=ROOT)
    actual = json.loads(result.stdout)
    assert actual["states"] == ["RUNNING", "CANCEL_REQUESTED", "RECONCILING", "CANCELED"]
    assert actual["observed"]["RUNNING"]["notice"] is False
    assert actual["observed"]["CANCEL_REQUESTED"] == {"notice": True, "cancel_disabled": True}
    assert actual["observed"]["RECONCILING"]["notice"] is True
    assert actual["observed"]["CANCELED"]["notice"] is True
    (tmp_path / "result.json").write_text(json.dumps(actual, ensure_ascii=False), encoding="utf-8")
