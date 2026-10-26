import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "validation"))

from boss_page_api import BossPageAPI
from test_boss_command_api import demo, create, send_input, feedback_input
from test_product_reminders import validate_public


def test_original_reminder_receipt_preserves_current_event_without_reexecution(demo):
    assert demo.execute("MAINTAINER", "boss.simulation.event.seed", {"client_request_id": "fc04-receipt-event-seed", "event_id": "event-1"})[0] == 200
    payload = {"client_request_id": "fc04-receipt-ack", "event_id": "event-1", "event_version": "1", "reminder_version": "0"}
    code, result = demo.execute("BOSS", "boss.reminder.ack", payload)
    assert code == 200, result
    with demo.store.connect() as db:
        before = db.execute("SELECT count(*) FROM objects WHERE kind='authorization'").fetchone()[0]
    code, receipt = BossPageAPI(demo.store).serve("BOSS", "/api/boss/ui/operation-status", "action=boss.reminder.ack&client_request_id=" + payload["client_request_id"])
    assert code == 200 and receipt["outcome"] == "RECORDED"
    assert receipt["result"] == result
    with demo.store.connect() as db:
        assert db.execute("SELECT count(*) FROM objects WHERE kind='authorization'").fetchone()[0] == before


def test_feedback_original_receipt_preserves_task_target_without_body(demo):
    task = create(demo)
    code, sent = demo.execute("BOSS", "boss.assignment.send", send_input(task))
    assert code == 200, sent
    payload = feedback_input({"task_id": task["task_id"], "version": sent["task_version"]}, kind="PROGRESS", key="fc04-shared-feedback-receipt")
    code, feedback = demo.execute("MAINTAINER", "boss.simulation.feedback", payload)
    assert code == 200, feedback
    code, receipt = BossPageAPI(demo.store).serve("MAINTAINER", "/api/boss/ui/operation-status", "action=boss.simulation.feedback&client_request_id=" + payload["client_request_id"])
    assert code == 200 and receipt["outcome"] == "RECORDED"
    assert receipt["result"]["task_id"] == task["task_id"]
    assert receipt["result"]["task_version"] == feedback["task"]["version"]
    assert payload["content"] not in json.dumps(receipt, ensure_ascii=False)


def test_native_notification_target_is_current_owner_only_and_readonly(demo):
    code, result = demo.execute("MAINTAINER", "boss.simulation.event.seed", {"client_request_id": "fc04-target-event-seed", "event_id": "event-1"})
    assert code == 200, result
    code, result = demo.execute("MAINTAINER", "boss.simulation.clock.advance", {"client_request_id": "fc04-target-clock", "at": "2026-10-24T17:00:00+08:00"})
    assert code == 200, result
    assert demo.store.dispatch_due("ui-check")[0]["state"] == "DELIVERED"
    pages = BossPageAPI(demo.store)
    query = "event_id=event-1&event_version=1"
    with demo.store.connect() as db:
        before = db.execute("SELECT count(*) FROM objects").fetchone()[0]
    code, target = pages.serve("BOSS", "/api/boss/ui/notification-target", query)
    assert code == 200, target
    validate_public("NotificationTarget", target)
    assert target == {"source_type": "SIMULATED", "execution_namespace": "ui-check", "event_id": "event-1", "event_version": "1", "category": "经营提醒", "page_id": "F02", "notification_saved": True, "system_delivery_verified": False}
    for role, status in ((None, 401), ("MAINTAINER", 403)):
        assert pages.serve(role, "/api/boss/ui/notification-target", query)[0] == status
    for suffix in ("&owner_id=boss-1", "&event_id=event-1", "&confirmed=true"):
        assert pages.serve("BOSS", "/api/boss/ui/notification-target", query + suffix)[0] == 400
    assert pages.serve("BOSS", "/api/boss/ui/notification-target", "event_id=event-1&event_version=2")[0] == 409
    assert pages.serve("BOSS", "/api/boss/ui/notification-target", "event_id=private-1&event_version=1")[0] == 404
    with demo.store.connect() as db:
        assert db.execute("SELECT count(*) FROM objects").fetchone()[0] == before
    code, result = demo.execute("BOSS", "boss.reminder.close", {"client_request_id": "fc04-target-close", "event_id": "event-1", "event_version": "1", "reminder_version": "0"})
    assert code == 200, result
    assert pages.serve("BOSS", "/api/boss/ui/notification-target", query)[0] == 409
