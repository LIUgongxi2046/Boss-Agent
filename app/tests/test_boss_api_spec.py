import sys
import json
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "validation"))

from boss_command_api import BossCommandAPI
from boss_page_api import BossPageAPI
from controls import ControlStore
from business import initial_materials
from test_boss_command_api import create_input, send_input, feedback_input
from test_boss_meeting_approval import seed_input, decide_input, minutes_input
from test_boss_message_calendar import msg_input, calendar_input
from test_boss_owner_preferences import goals, notice, confirm_input
from test_boss_travel import review_input, confirm_input as confirm_travel

SPEC = yaml.safe_load((ROOT / "specs/openapi.yaml").read_text())
OPERATIONS = {operation["action"]: operation for operation in SPEC["x-websocket-operations"]}
VALIDATED_ACTIONS = set()


@pytest.fixture
def services(tmp_path):
    store = ControlStore(tmp_path / "api-schema.sqlite")
    store.initialize("ui-check")
    return BossCommandAPI(store), BossPageAPI(store)


def checked(api, action, payload):
    operation = OPERATIONS[action]
    schema = {"components": SPEC["components"], "$ref": operation["input"]}
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(payload)
    status, result = api.execute(operation["role"], action, payload)
    assert status == 200, {"action": action, "status": status}
    schema = {"components": SPEC["components"], "$ref": operation["output"]}
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(result)
    assert set(operation["result_required"]) <= set(result)
    VALIDATED_ACTIONS.add(action)
    return result


def test_assignment_feedback_complete_uses_declared_input_and_result(services):
    api, pages = services
    created = checked(api, "boss.assignment.create", create_input())
    sent = checked(api, "boss.assignment.send", send_input(created))
    feedback = checked(api, "boss.simulation.feedback", feedback_input({"task_id": created["task_id"], "version": sent["task_version"]}))
    checked(api, "boss.assignment.complete", {
        "client_request_id": "schema-complete-original", "task_id": created["task_id"],
        "task_version": feedback["task"]["version"], "feedback_id": feedback["feedback_id"],
    })
    assert pages.serve("BOSS", "/api/boss/ui/tasks")[1]["tasks"][0]["status"] == "COMPLETED_CONFIRMED"


def test_minutes_and_approval_match_declared_fields(services):
    api, _ = services
    minute = checked(api, "boss.minutes.save", minutes_input())
    checked(api, "boss.minutes.confirm", {
        "client_request_id": "schema-minutes-confirm", "meeting_id": "meeting-1",
        "expected_version": minute["version"], "source_id": "meeting-minutes", "source_version": "1",
    })
    checked(api, "boss.simulation.application.seed", seed_input())
    decided = checked(api, "boss.approval.decide", decide_input())
    assert decided["funds_transferred"] is False


def test_message_calendar_and_travel_match_declared_fields(services):
    api, pages = services
    saved = checked(api, "boss.message.draft.save", {"client_request_id": "schema-message-save", **msg_input()})
    draft = pages.serve("BOSS", "/api/boss/ui/workspace/outbox")[1]["drafts"][0]
    checked(api, "boss.message.send", {
        "client_request_id": "schema-message-send", "draft_id": saved["draft_id"], "expected_version": saved["version"],
        "recipient_id": draft["recipient_id"], "expected_content_sha256": draft["content_sha256"],
    })
    calendar = checked(api, "boss.calendar.save", {"client_request_id": "schema-calendar-save", **calendar_input()})
    checked(api, "boss.calendar.delete", {"client_request_id": "schema-calendar-delete", "expected_version": calendar["version"]})
    reviewed = checked(api, "boss.travel.review", {"client_request_id": "schema-travel-review", **review_input()})
    checked(api, "boss.travel.confirm", {"client_request_id": "schema-travel-confirm", **confirm_travel(reviewed)})


@pytest.mark.parametrize("domain,values", [("goals", goals()), ("notice", notice())])
def test_owner_setting_input_and_confirmation_are_separate(services, domain, values):
    api, _ = services
    prepared = checked(api, "boss.owner." + domain + ".save", {"client_request_id": "schema-setting-save", **values})
    active = checked(api, "boss.owner." + domain + ".confirm", {"client_request_id": "schema-setting-confirm", **confirm_input(prepared)})
    revoked = checked(api, "boss.authorization.revoke", {
        "client_request_id": "schema-setting-revoke", "authorization_id": active["authorization_id"],
        "expected_version": "1", "reason": "停止后续采用",
    })
    assert revoked["future_authorization_use_blocked"] is True


def test_actual_tool_evidence_does_not_copy_source_body_into_general_audit(services):
    api, pages = services
    status, response = pages.serve("BOSS", "/api/boss/ui/metrics")
    assert status == 200
    query = response["result"]
    evidence = api.store.invoke("read_evidence", {
        "envelope": query["envelope"], "query_id": query["query_id"],
        "source_ids": ["finance-note"], "detail_refs": query["detail_refs"],
    })
    assert evidence["original_records"]
    with api.store.connect() as db:
        document = api.store.get(db, "ui-check", "document", "finance-note")
        audits = db.execute("SELECT input,output FROM audit").fetchall()
    assert document["content"] not in json.dumps(audits, ensure_ascii=False)


def test_assignment_nudge_extension_and_cancel_match_declared_input(services):
    from test_boss_assignment_nudge import nudge_input
    api, _ = services
    task = checked(api, "boss.assignment.create", create_input())
    sent = checked(api, "boss.assignment.send", send_input(task))
    checked(api, "boss.assignment.nudge", {"client_request_id": "schema-task-nudge", **nudge_input(task, sent["task_version"])})
    response = feedback_input({"task_id": task["task_id"], "version": sent["task_version"]}, "EXTENSION_REQUEST")
    response["proposed_due_at"] = "2026-10-26T17:00:00+08:00"
    feedback = checked(api, "boss.simulation.feedback", response)
    extended = checked(api, "boss.assignment.extend", {"client_request_id": "schema-task-extend", "task_id": task["task_id"],
        "task_version": feedback["task"]["version"], "feedback_id": feedback["feedback_id"], "due_at": response["proposed_due_at"]})
    checked(api, "boss.assignment.cancel", {"client_request_id": "schema-task-cancel", "task_id": task["task_id"],
        "task_version": extended["version"], "reason": create_input()["purpose"]})


def test_scheduler_lifecycle_and_actual_manual_dispatch_match_declared_input(services):
    from test_boss_scheduler_config import config, manual_args
    api, _ = services
    checked(api, "boss.simulation.event.seed", {"client_request_id": "schema-event-seed", "event_id": "event-1"})
    saved = checked(api, "boss.scheduler.draft.save", {"client_request_id": "schema-schedule-save", **config()})
    validated = checked(api, "boss.scheduler.draft.validate", {"client_request_id": "schema-schedule-validate", "expected_version": saved["version"]})
    active = checked(api, "boss.scheduler.activate", {"client_request_id": "schema-schedule-activate", "expected_draft_version": validated["version"],
        "expected_schedule_version": "1", "expected_rules_version": "1"})
    checked(api, "boss.simulation.clock.advance", {"client_request_id": "schema-clock-advance", "at": initial_materials()["event"]["due_at"]})
    dispatched = checked(api, "boss.scheduler.manual_run", {"client_request_id": "schema-manual-dispatch", **manual_args(active["version"])})
    assert dispatched["external_delivery_verified"] is False
    paused = checked(api, "boss.scheduler.pause", {"client_request_id": "schema-schedule-pause", "expected_version": active["version"]})
    resumed = checked(api, "boss.scheduler.resume", {"client_request_id": "schema-schedule-resume", "expected_version": paused["version"]})
    checked(api, "boss.scheduler.cancel", {"client_request_id": "schema-schedule-cancel", "expected_version": resumed["version"]})


def test_reminder_ack_snooze_close_preserve_source_event_and_declared_versions(services):
    api, _ = services
    checked(api, "boss.simulation.event.seed", {"client_request_id": "schema-reminder-event", "event_id": "event-1"})
    acknowledged = checked(api, "boss.reminder.ack", {"client_request_id": "schema-reminder-ack", "event_id": "event-1", "event_version": "1", "reminder_version": "0"})
    snoozed = checked(api, "boss.reminder.snooze", {"client_request_id": "schema-reminder-snooze", "event_id": "event-1", "event_version": "1",
        "reminder_version": acknowledged["version"], "until": initial_materials()["event"]["due_at"]})
    closed = checked(api, "boss.reminder.close", {"client_request_id": "schema-reminder-close", "event_id": "event-1", "event_version": "1", "reminder_version": snoozed["version"]})
    assert closed["state"] == "CLOSED"
    with api.store.connect() as db:
        assert api.store.get(db, "ui-check", "event", "event-1")["state"] == "OPEN"


def test_memory_confirm_delete_and_owner_commitments_match_declared_input(services):
    api, _ = services
    data = initial_materials()
    confirmed = checked(api, "boss.memory.confirm", {"client_request_id": "schema-memory-confirm", "expected_version": "1", "text": data["memory"]["text"]})
    checked(api, "boss.memory.delete", {"client_request_id": "schema-memory-delete", "expected_version": confirmed["version"]})
    fields = {"purpose": create_input()["purpose"], "due_at": data["historical_task"]["due_at"], "timezone": data["private_calendar"]["timezone"],
        "importance": "NORMAL", "evidence_requirements": data["historical_task"]["evidence_requirements"], "source_refs": []}
    commitment = checked(api, "boss.commitment.create", {"client_request_id": "schema-commitment-create", **fields})
    extended = checked(api, "boss.commitment.extend", {"client_request_id": "schema-commitment-extend", "commitment_id": commitment["commitment_id"],
        "expected_version": commitment["version"], "due_at": data["private_calendar"]["ends_at"], "reason": data["memory"]["text"]})
    checked(api, "boss.commitment.complete", {"client_request_id": "schema-commitment-complete", "commitment_id": commitment["commitment_id"],
        "expected_version": extended["version"], "evidence_refs": [{"source_id": "finance-note", "version": "1"}]})
    another = checked(api, "boss.commitment.create", {"client_request_id": "schema-commitment-another", **fields})
    checked(api, "boss.commitment.cancel", {"client_request_id": "schema-commitment-cancel", "commitment_id": another["commitment_id"],
        "expected_version": another["version"], "reason": data["memory"]["text"]})


def test_meeting_preparation_research_and_minute_assignment_match_declared_input(services):
    from test_boss_minutes_assignment_chain import create_payload
    api, _ = services
    data = initial_materials()
    checked(api, "boss.meeting.brief.prepare", {"client_request_id": "schema-brief-prepare", "meeting_id": "meeting-1", "meeting_version": "1", "expected_version": "0"})
    checked(api, "boss.research.prepare", {"client_request_id": "schema-research-prepare", "expected_version": "0", "question": "合成水产饲料外销明细",
        "period": "", "country": "", "business_relation": "", "cutoff_date": data["private_calendar"]["starts_at"][:10]})
    minute = checked(api, "boss.minutes.save", minutes_input())
    confirmed = checked(api, "boss.minutes.confirm", {"client_request_id": "schema-minute-task-confirm", "meeting_id": "meeting-1",
        "expected_version": minute["version"], "source_id": "meeting-minutes", "source_version": "1"})
    checked(api, "boss.minutes.assignment.create", {"client_request_id": "schema-minute-task-create", **create_payload(entry="entry-04", version=confirmed["version"])})


def test_message_reply_calendar_share_and_revoke_match_declared_input(services):
    api, pages = services
    draft = checked(api, "boss.message.draft.save", {"client_request_id": "schema-reply-draft", **msg_input()})
    row = pages.serve("BOSS", "/api/boss/ui/workspace/outbox")[1]["drafts"][0]
    sent = checked(api, "boss.message.send", {"client_request_id": "schema-reply-send", "draft_id": draft["draft_id"], "expected_version": draft["version"],
        "recipient_id": row["recipient_id"], "expected_content_sha256": row["content_sha256"]})
    checked(api, "boss.simulation.message.reply", {"client_request_id": "schema-message-reply", "message_id": sent["message_id"],
        "author_contact_id": row["recipient_id"], "text": initial_materials()["memory"]["text"]})
    shared = checked(api, "boss.calendar.share", {"client_request_id": "schema-calendar-share", "expected_version": "1", "recipient_id": row["recipient_id"],
        "purpose": initial_materials()["memory"]["text"], "expires_at": initial_materials()["private_calendar"]["ends_at"], "fields": ["busy", "starts_at", "ends_at", "timezone"]})
    checked(api, "boss.calendar.share.revoke", {"client_request_id": "schema-calendar-share-revoke", "share_id": shared["share_id"], "expected_version": "1"})


def test_people_attach_detach_and_trip_cancel_match_declared_input(services):
    from test_boss_people import draft, attach_input
    api, pages = services
    prepared = checked(api, "boss.people.prepare", {"client_request_id": "schema-people-prepare", **draft()})
    row = pages.serve("BOSS", "/api/boss/ui/workspace/people")[1]["briefs"][0]
    attached = checked(api, "boss.people.attach", {"client_request_id": "schema-people-attach", **attach_input(prepared, row["compiled_sha256"])})
    checked(api, "boss.people.detach", {"client_request_id": "schema-people-detach", "brief_id": prepared["brief_id"], "expected_version": attached["version"],
        "reason": initial_materials()["memory"]["text"]})
    reviewed = checked(api, "boss.travel.review", {"client_request_id": "schema-trip-review-cancel", **review_input()})
    checked(api, "boss.travel.cancel", {"client_request_id": "schema-trip-cancel", "travel_id": reviewed["travel_id"], "expected_version": reviewed["version"], "reason": initial_materials()["memory"]["text"]})


def test_existing_approved_source_copy_lifecycle_matches_declared_input(services):
    from test_boss_knowledge_ingestion import create_input as source_input
    api, _ = services
    source = initial_materials()["documents"][0]
    values = source_input(title=source["source_id"], content=source["content"])
    created = checked(api, "boss.knowledge.source.create", values)
    revised = checked(api, "boss.knowledge.source.revise", {**values, "client_request_id": "schema-source-revise", "expected_version": created["version"]})
    checked(api, "boss.knowledge.source.withdraw", {"client_request_id": "schema-source-withdraw", "source_id": created["source_id"], "expected_version": revised["version"]})


def test_technical_prompt_lifecycle_matches_declared_input(services):
    api, _ = services
    saved = checked(api, "boss.prompt.save", {"client_request_id": "schema-prompt-save", "prompt_id": None, "expected_version": "0", "kind": "SECRETARY_ROLE",
        "title": "合成的秘书职责指引", "instruction_text": "仅对当前获准的模拟业务资料提供有来源的阅读说明；不修改任何老板授权，也不自行发送消息。",
        "change_note": "检查技术提示在下一会话的加载记录", "source_ids": ["finance-note"]})
    validated = checked(api, "boss.prompt.validate", {"client_request_id": "schema-prompt-validate", "prompt_id": saved["prompt_id"], "expected_version": saved["version"], "expected_content_sha256": saved["content_sha256"]})
    active = checked(api, "boss.prompt.activate", {"client_request_id": "schema-prompt-activate", "prompt_id": saved["prompt_id"], "expected_version": validated["version"],
        "expected_content_sha256": saved["content_sha256"], "expected_active_version": "0"})
    checked(api, "boss.prompt.deactivate", {"client_request_id": "schema-prompt-deactivate", "kind": "SECRETARY_ROLE", "expected_active_version": active["active_version"]})


def test_existing_application_revision_matches_declared_input(services):
    api, _ = services
    values = seed_input()
    created = checked(api, "boss.simulation.application.seed", values)
    requested = checked(api, "boss.approval.decide", decide_input(key="schema-application-more", decision="REQUEST_MORE", expected_version=created["version"]))
    checked(api, "boss.simulation.application.revise", {**values, "client_request_id": "schema-application-revise", "expected_version": requested["version"]})
