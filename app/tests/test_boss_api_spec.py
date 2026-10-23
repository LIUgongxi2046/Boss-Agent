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
from test_boss_command_api import create_input, send_input, feedback_input
from test_boss_meeting_approval import seed_input, decide_input, minutes_input
from test_boss_message_calendar import msg_input, calendar_input
from test_boss_owner_preferences import goals, notice, confirm_input
from test_boss_travel import review_input, confirm_input as confirm_travel

SPEC = yaml.safe_load((ROOT / "specs/openapi.yaml").read_text())
OPERATIONS = {operation["action"]: operation for operation in SPEC["x-websocket-operations"]}


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
