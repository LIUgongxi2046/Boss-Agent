import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "validation"))

from boss_page_api import BossPageAPI
from boss_command_api import BossCommandAPI
from controls import ControlStore
from test_boss_command_api import demo


def test_current_business_alert_public_input_and_role_scoped_projection(demo):
    payload = {"client_request_id": "fc04-public-source-load", "expected_version": "0", "mode": "SIMULATED", "definition_version": "FC04-ALERT-1", "seed": 20261024, "frame": "RESOURCE_SHORTAGE"}
    code, loaded = demo.execute("MAINTAINER", "boss.simulation.alert.load", payload)
    assert code == 200, loaded
    assert demo.execute("MAINTAINER", "boss.simulation.alert.load", payload) == (200, loaded)
    assert demo.execute("BOSS", "boss.simulation.alert.load", payload)[0] == 403
    pages = BossPageAPI(demo.store)
    code, projection = pages.serve("BOSS", "/api/boss/ui/business-alerts")
    assert code == 200, projection
    assert len(projection["items"]) == 1
    current = projection["items"][0]
    assert current["event_id"] == loaded["event_id"] and current["adoption_state"] == "CURRENT"
    assert current["facts"] is not None and current["documents"]
    for role, status in ((None, 401), ("MAINTAINER", 403)):
        assert pages.serve(role, "/api/boss/ui/business-alerts")[0] == status
    assert pages.serve("BOSS", "/api/boss/ui/business-alerts", "owner_id=boss-1")[0] == 400
    assert pages.serve("BOSS", "/api/boss/ui/business-alerts", "event_id=" + loaded["event_id"] + "&event_id=" + loaded["event_id"])[0] == 400
    code, workspace = pages.serve("BOSS", "/api/boss/ui/workspace/notifications")
    assert code == 200 and workspace["business_alerts"]["items"][0]["event_id"] == current["event_id"]
    assert all(row["event_id"] != current["event_id"] for row in workspace["events"])


def public_ready(demo):
    pages = BossPageAPI(demo.store)
    def command(role, action, payload):
        code, result = demo.execute(role, action, payload)
        assert code == 200, (action, result)
        return result
    command("MAINTAINER", "boss.simulation.event.seed", {"client_request_id": "fc04-public-approved-seed", "event_id": "event-1"})
    code, catalog = pages.serve("MAINTAINER", "/api/boss/ui/business-alert-rules")
    assert code == 200
    configuration = catalog["definition"]["configuration"]
    saved = command("MAINTAINER", "boss.scheduler.draft.save", {"client_request_id": "fc04-public-technical-save", "expected_version": "0", "trigger": "EVENT_OR_TIME", **{field: configuration[field] for field in ("timezone", "quiet_start", "quiet_end", "cooldown_seconds", "important_escalation")}})
    checked = command("MAINTAINER", "boss.scheduler.draft.validate", {"client_request_id": "fc04-public-technical-check", "expected_version": saved["version"]})
    code, schedule = pages.serve("MAINTAINER", "/api/boss/ui/workspace/scheduler")
    assert code == 200
    command("MAINTAINER", "boss.scheduler.activate", {"client_request_id": "fc04-public-technical-enable", "expected_draft_version": checked["version"], "expected_schedule_version": schedule["schedule"]["version"], "expected_rules_version": schedule["rules"]["version"]})
    saved = command("MAINTAINER", "boss.simulation.alert.rule.save", {"client_request_id": "fc04-public-rule-save", "expected_version": "0", "configuration": configuration})
    assert pages.serve("BOSS", "/api/boss/ui/business-alert-rules")[1]["active"] is None
    checked = command("MAINTAINER", "boss.simulation.alert.rule.validate", {"client_request_id": "fc04-public-rule-check", "expected_version": saved["version"]})
    command("MAINTAINER", "boss.simulation.alert.rule.activate", {"client_request_id": "fc04-public-rule-enable", "expected_version": checked["version"], "expected_active_version": "0"})
    for minute in (0, 5, 10):
        command("MAINTAINER", "boss.simulation.clock.advance", {"client_request_id": "fc04-public-clock-" + str(minute), "at": f"2026-10-22T09:{minute:02}:00+08:00"})
        catalog = pages.serve("MAINTAINER", "/api/boss/ui/admin/business-alert-input")[1]
        command("MAINTAINER", "boss.simulation.alert.load", {"client_request_id": "fc04-public-observation-" + str(minute), "expected_version": catalog["event_version"], "mode": "SIMULATED", "definition_version": "FC04-ALERT-1", "seed": 20261024, "frame": "MARGIN_DROP"})
        demo.store.dispatch_due("ui-check")
    return pages, command


def current(pages):
    code, result = pages.serve("BOSS", "/api/boss/ui/business-alerts")
    assert code == 200
    return result["items"][0]


def decision(pages, key):
    item = current(pages)
    return {"client_request_id": key, "event_id": item["event_id"], "event_version": item["event_version"], "expected_version": item["reminder_version"], "review_sha256": item["review_sha256"]}


def test_public_owner_decisions_current_source_review_receipt_and_independent_tasks(demo):
    pages, command = public_ready(demo)
    item = current(pages)
    assert item["evaluation"]["duration_seconds"] == 600 and item["notification"]["state"] == "DELIVERED"
    assert item["data_as_of"] == "2026-10-10T23:59:59+08:00" and item["observed_at"] == "2026-10-22T09:10:00+08:00"
    native = "event_id=" + item["event_id"] + "&event_version=" + item["event_version"]
    assert pages.serve("BOSS", "/api/boss/ui/notification-target", native)[0] == 200
    assert demo.execute("BOSS", "boss.reminder.close", {"client_request_id": "fc04-public-legacy-bypass", "event_id": item["event_id"], "event_version": item["event_version"], "reminder_version": item["reminder_version"]})[0] == 409
    payload = decision(pages, "fc04-public-owner-ack")
    assert demo.execute("MAINTAINER", "boss.alert.ack", payload)[0] == 403
    for extra in ({"owner_id": "boss-1"}, {"confirmed": True}, {"authorization_id": "self-issued"}):
        assert demo.execute("BOSS", "boss.alert.ack", {**payload, **extra})[0] == 400
    acknowledged = command("BOSS", "boss.alert.ack", payload)
    assert command("BOSS", "boss.alert.ack", payload) == acknowledged
    assert demo.execute("BOSS", "boss.alert.ack", {**payload, "event_version": "999"})[0] == 409
    code, receipt = pages.serve("BOSS", "/api/boss/ui/operation-status", "action=boss.alert.ack&client_request_id=" + payload["client_request_id"])
    assert code == 200 and receipt["write_performed_by_lookup"] is False and receipt["result"] == acknowledged
    item = current(pages)
    linked = command("BOSS", "boss.alert.meeting.link", {**decision(pages, "fc04-public-owner-meeting"), "meeting_id": item["meeting_reference"]["meeting_id"], "meeting_version": item["meeting_reference"]["version"]})
    assert linked["meeting_arranged"] is False
    assignment = command("BOSS", "boss.alert.assignment.create", {**decision(pages, "fc04-public-owner-assignment"), "purpose": "复核当前经营提醒及来源", "coordinator_id": item["facts"]["handler_id"], "due_at": "2026-10-23T17:00:00+08:00", "timezone": "Asia/Shanghai", "evidence_requirements": ["当前来源与处理结果"]})
    assert assignment["task_status"] == "OPEN" and assignment["external_message_sent"] is False
    item = current(pages)
    assert any(reference["task_id"] == assignment["task_id"] for reference in item["assignment_references"])
    snooze = command("BOSS", "boss.alert.snooze", {**decision(pages, "fc04-public-owner-snooze"), "until": "2026-10-22T09:40:00+08:00"})
    assert snooze["state"] == "SNOOZED" and pages.serve("BOSS", "/api/boss/ui/notification-target", native)[0] == 409
    assert demo.execute("BOSS", "boss.alert.snooze", {**decision(pages, "fc04-public-owner-invalid-snooze"), "until": "2026-10-22T09:00:00+08:00"})[0] == 400
    old = decision(pages, "fc04-public-owner-old-review")
    demo.store.control("ui-check", "withdraw", {"source_id": "finance-note", "version": "1"})
    invalid = current(pages)
    assert invalid["adoption_state"] == "NEEDS_REVIEW" and invalid["facts"] is None and invalid["documents"] == []
    assert demo.execute("BOSS", "boss.alert.close", old)[0] == 409
    closed = command("BOSS", "boss.alert.close", decision(pages, "fc04-public-owner-close"))
    assert closed["state"] == "CLOSED"
    reopened = BossPageAPI(ControlStore(demo.store.path))
    assert current(reopened)["reminder"]["state"] == "CLOSED"
    task = next(task for task in reopened.serve("BOSS", "/api/boss/ui/tasks")[1]["tasks"] if task["task_id"] == assignment["task_id"])
    assert task["status"] == "OPEN" and task["due_at"] == "2026-10-23T17:00:00+08:00"
    assert current(reopened)["state"] == item["state"]
