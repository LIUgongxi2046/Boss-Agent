import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "validation"))

from boss_command_api import BossCommandAPI
from controls import ControlStore
from test_boss_command_api import create_input, send_input, feedback_input


def test_canceled_task_accepts_late_feedback_as_history_without_reactivation(tmp_path):
    store = ControlStore(tmp_path / "late-feedback.sqlite")
    store.initialize("ui-check")
    api = BossCommandAPI(store)
    code, created = api.execute("BOSS", "boss.assignment.create", create_input())
    assert code == 200
    code, sent = api.execute("BOSS", "boss.assignment.send", send_input(created))
    assert code == 200
    code, canceled = api.execute("BOSS", "boss.assignment.cancel", {
        "client_request_id": "late-feedback-owner-cancel", "task_id": created["task_id"],
        "task_version": sent["task_version"], "reason": "停止后续交办",
    })
    assert code == 200
    payload = feedback_input({"task_id": created["task_id"], "version": canceled["version"]})
    payload.pop("client_request_id")
    result = store.control("ui-check", "feedback", payload)
    assert result["task"]["status"] == "CANCELED"
    assert result["feedback"]["historical_only"] is True
    with ControlStore(store.path).connect() as db:
        task = store.get(db, "ui-check", "task", created["task_id"])
        assert task["status"] == "CANCELED"
        assert task["feedback_ids"] == [result["feedback"]["feedback_id"]]
        assert store.get(db, "ui-check", "event", "task-due:" + task["task_id"])["state"] == "CANCELED"
        audit = db.execute("SELECT input,output FROM audit WHERE operation='feedback'").fetchall()
        assert payload["content"] not in json.dumps(audit, ensure_ascii=False)
