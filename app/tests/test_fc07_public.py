import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "validation"))

from boss_page_api import BossPageAPI
from test_boss_command_api import demo, create, send_input, feedback_input
from test_product_assignment import validate_public


def test_public_extension_decision_and_original_receipt(demo):
    task = create(demo)
    original_due = BossPageAPI(demo.store).serve("BOSS", "/api/boss/ui/tasks")[1]["tasks"][0]["due_at"]
    sent = demo.execute("BOSS", "boss.assignment.send", send_input(task))[1]
    payload = feedback_input({"task_id": task["task_id"], "version": sent["task_version"]}, kind="EXTENSION_REQUEST")
    payload["proposed_due_at"] = "2026-10-26T17:00:00+08:00"
    code, feedback = demo.execute("MAINTAINER", "boss.simulation.feedback", payload)
    assert code == 200, feedback
    decision = {"client_request_id": "fc07-public-reject-extension", "task_id": task["task_id"], "task_version": feedback["task"]["version"],
        "feedback_id": feedback["feedback_id"], "decision": "REJECT", "due_at": None, "reason": "保留本人已经确认的当前期限"}
    code, result = demo.execute("BOSS", "boss.assignment.extension.decide", decision)
    assert code == 200, result
    assert result["due_at"] == original_due and result["old_due_at"] == original_due and result["decision"] == "REJECT"
    assert demo.execute("BOSS", "boss.assignment.extension.decide", decision) == (200, result)
    pages = BossPageAPI(demo.store)
    code, history = pages.serve("BOSS", "/api/boss/ui/assignment-extensions", "task_id=" + task["task_id"])
    assert code == 200 and len(history["decisions"]) == 1
    validate_public("ExtensionHistory", history)
    assert history["decisions"][0]["reason"] == decision["reason"]
    code, receipt = pages.serve("BOSS", "/api/boss/ui/operation-status", "action=boss.assignment.extension.decide&client_request_id=" + decision["client_request_id"])
    assert code == 200 and receipt["outcome"] == "RECORDED" and receipt["result"] == result
    assert demo.execute("MAINTAINER", "boss.assignment.extension.decide", decision)[0] == 403
    assert pages.serve("MAINTAINER", "/api/boss/ui/assignment-extensions", "task_id=" + task["task_id"])[0] == 403
    assert pages.serve("BOSS", "/api/boss/ui/assignment-extensions", "task_id=" + task["task_id"] + "&task_id=other")[0] == 400


def test_task_projection_preserves_feedback_versions_and_canceled_history(demo):
    task = create(demo)
    sent = demo.execute("BOSS", "boss.assignment.send", send_input(task))[1]
    code, canceled = demo.execute("BOSS", "boss.assignment.cancel", {"client_request_id": "fc07-public-cancel", "task_id": task["task_id"], "task_version": sent["task_version"], "reason": "本人结束当前协调"})
    assert code == 200
    code, feedback = demo.execute("MAINTAINER", "boss.simulation.feedback", feedback_input({"task_id": task["task_id"], "version": canceled["version"]}))
    assert code == 200 and feedback["historical_only"] is True
    code, current = BossPageAPI(demo.store).serve("BOSS", "/api/boss/ui/tasks")
    assert code == 200 and current["tasks"][0]["status"] == "CANCELED"
    item = next(item for item in current["feedback"] if item["feedback_id"] == feedback["feedback_id"])
    assert item["historical_only"] is True and item["task_version"] == canceled["version"]
    assert item["evidence_versions"] == {"finance-note": "1"} and item["evidence_states"] == {"finance-note": "VALID"}
    assert len(current["linked_messages"]) == 1 and current["tasks"][0]["source_versions"] == {"finance-note": "1"}
