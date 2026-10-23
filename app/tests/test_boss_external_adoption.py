import sys
from pathlib import Path

import pytest
from aiohttp import web

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "validation"))

from boss_command_api import BossCommandAPI
from boss_meeting_brief import briefing_projection
from boss_meetings import MeetingAPI
from boss_people import projection as people_projection
from controls import ControlStore
from test_boss_meeting_changes import draft_input, confirmation
from test_boss_people import draft as people_input
from test_boss_supply_quality import imported, update_record
from test_boss_travel import review_input as travel_input
from test_boss_message_calendar import msg_input, calendar_input

SOURCE = "sim-business:production_event:sim-production-event-1"
REFERENCES = [{"source_id": SOURCE, "version": "1"}]


@pytest.fixture
def services(tmp_path):
    store = ControlStore(tmp_path / "external-adoption.sqlite")
    store.initialize("ui-check")
    external, _ = imported(store)
    return store, external, BossCommandAPI(store), MeetingAPI(store)


def change_dependencies(external):
    return update_record(external, "professional_record", "sim-quality-review-1", {"state": "PROFESSIONALLY_CONFIRMED", "conclusion": "PASS_REPORTED"})


def schedule(meetings):
    draft = meetings.execute("BOSS", "draft.save", draft_input(source_refs=REFERENCES))
    return meetings.execute("BOSS", "confirm", confirmation(draft))


def test_current_meeting_preparation_excludes_external_material_with_changed_dependencies(services):
    store, external, commands, meetings = services
    scheduled = schedule(meetings)
    assert commands.execute("BOSS", "boss.meeting.brief.prepare", {"client_request_id": "external-brief-prepare", "meeting_id": "meeting-1", "meeting_version": scheduled["version"], "expected_version": "0"})[0] == 200
    change_dependencies(external)
    with store.connect() as db:
        view = briefing_projection(db, store.get(db, "ui-check", "initial", "snapshot"))
    source = next(row for row in view["current"]["sources"] if row["source_id"] == SOURCE)
    assert source["excerpt"] is None and source["status"] == "NEEDS_REVIEW"
    assert SOURCE in view["current"]["missing_items"] and view["source_changed"] is True
    saved = next(row for row in view["saved_brief"]["compiled"]["sources"] if row["source_id"] == SOURCE)
    assert saved["excerpt"] is None


def test_pending_meeting_draft_reflects_dependency_change_and_rejects_owner_confirmation(services):
    store, external, _, meetings = services
    saved = meetings.execute("BOSS", "draft.save", draft_input(source_refs=REFERENCES))
    change_dependencies(external)
    assert meetings.read("BOSS")["draft"]["review_current"] is False
    with pytest.raises(web.HTTPConflict):
        meetings.execute("BOSS", "confirm", confirmation(saved))
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind='authorization'").fetchone()[0] == 0
        assert store.get(db, "ui-check", "initial", "snapshot")["meeting"]["version"] == "1"


@pytest.mark.parametrize("consumer", ["meeting", "people", "travel"])
def test_new_business_preparation_rejects_noncurrent_external_adoption(services, consumer):
    store, external, commands, meetings = services
    change_dependencies(external)
    if consumer == "meeting":
        with pytest.raises(web.HTTPConflict):
            meetings.execute("BOSS", "draft.save", draft_input(source_refs=REFERENCES))
    else:
        action = "boss.people.prepare" if consumer == "people" else "boss.travel.review"
        payload = people_input(source_refs=REFERENCES) if consumer == "people" else travel_input(transport_refs=REFERENCES)
        status, result = commands.execute("BOSS", action, {"client_request_id": "external-reject-" + consumer, **payload})
        assert status == 409, result
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind IN ('authorization','meeting_draft','person_brief','travel_plan')").fetchone()[0] == 0


def test_saved_people_preparation_stops_serving_external_excerpt_after_dependency_change(services):
    store, external, commands, _ = services
    status, _ = commands.execute("BOSS", "boss.people.prepare", {"client_request_id": "external-people-current", **people_input(source_refs=REFERENCES)})
    assert status == 200
    change_dependencies(external)
    with store.connect() as db:
        view = people_projection(commands, db, store.get(db, "ui-check", "initial", "snapshot"))
    assert view["briefs"][0]["live_evidence_current"] is False
    assert all(row["excerpt"] is None for row in view["briefs"][0]["compiled"]["sources"])


def test_minutes_confirmation_rejects_external_dependency_changes_without_authorization(services):
    store, external, commands, meetings = services
    scheduled = schedule(meetings)
    status, saved = commands.execute("BOSS", "boss.minutes.save", {"client_request_id": "external-minutes-save", "meeting_id": "meeting-1", "meeting_version": scheduled["version"], "source_id": SOURCE, "source_version": "1", "expected_version": "0", "entries": [{"kind": "OPINION", "text": "核查当前模拟批次资料", "source_anchor": "SIMULATED"}]})
    assert status == 200, saved
    with store.connect() as db:
        before = db.execute("SELECT COUNT(*) FROM objects WHERE kind='authorization'").fetchone()[0]
    change_dependencies(external)
    status, result = commands.execute("BOSS", "boss.minutes.confirm", {"client_request_id": "external-minutes-confirm", "meeting_id": "meeting-1", "expected_version": saved["version"], "source_id": SOURCE, "source_version": "1"})
    assert status == 409, result
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind='authorization'").fetchone()[0] == before


def test_explicit_reimport_allows_new_owner_preparation_with_current_source_version(services):
    _, external, commands, meetings = services
    change_dependencies(external)
    update_record(external, "production_event", "sim-production-event-1", {"description": "SIMULATED：明确重新核查当前批次及专业记录。"}, key="external-current-event-reimport")
    references = [{"source_id": SOURCE, "version": "2"}]
    saved = meetings.execute("BOSS", "draft.save", draft_input(source_refs=references))
    assert meetings.read("BOSS")["draft"]["review_current"] is True
    assert meetings.execute("BOSS", "confirm", confirmation(saved))["state"] == "SCHEDULED"
    status, people = commands.execute("BOSS", "boss.people.prepare", {"client_request_id": "external-current-people-reimport", **people_input(source_refs=references)})
    assert status == 200 and people["state"] == "READY_FOR_REVIEW"


def test_ordinary_meeting_draft_digest_remains_current_after_reopening(services):
    store, external, _, meetings = services
    saved = meetings.execute("BOSS", "draft.save", draft_input())
    change_dependencies(external)
    reopened = MeetingAPI(ControlStore(store.path))
    assert reopened.read("BOSS")["draft"]["review_current"] is True
    assert reopened.execute("BOSS", "confirm", confirmation(saved))["state"] == "SCHEDULED"


@pytest.mark.parametrize("consumer", ["message", "calendar"])
def test_message_and_private_calendar_reject_noncurrent_external_attachments(services, consumer):
    store, external, commands, _ = services
    change_dependencies(external)
    action = "boss.message.draft.save" if consumer == "message" else "boss.calendar.save"
    payload = msg_input(attachment_refs=REFERENCES) if consumer == "message" else calendar_input(attachment_refs=REFERENCES)
    status, result = commands.execute("BOSS", action, {"client_request_id": "external-attachment-" + consumer, **payload})
    assert status == 409, result
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind IN ('authorization','private_calendar','message_draft')").fetchone()[0] == 0


def test_message_send_rechecks_external_attachment_before_saving_authorization(services):
    store, external, commands, _ = services
    status, saved = commands.execute("BOSS", "boss.message.draft.save", {"client_request_id": "external-message-current", **msg_input(attachment_refs=REFERENCES)})
    assert status == 200
    with store.connect() as db:
        draft = store.get(db, "ui-check", "message_draft", saved["draft_id"])
    change_dependencies(external)
    status, result = commands.execute("BOSS", "boss.message.send", {"client_request_id": "external-message-stale-send", "draft_id": saved["draft_id"], "expected_version": saved["version"], "recipient_id": "coordinator-1", "expected_content_sha256": draft["content_sha256"]})
    assert status == 409, result
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind IN ('authorization','message_outbox')").fetchone()[0] == 0
        assert store.get(db, "ui-check", "message_draft", saved["draft_id"])["status"] == "DRAFT"


def test_tool_created_task_uses_public_send_and_nudge_rechecks_external_adoption(services):
    store, external, commands, _ = services
    content = {"content_version": "1", "purpose": "汇总当前明确的模拟外部资料", "coordinator_id": "coordinator-1", "due_at": "2026-10-24T17:00:00+08:00", "timezone": "Asia/Shanghai", "evidence_requirements": ["当前明确的模拟来源"], "related_meeting_id": None, "related_event_ids": [], "source_refs": [SOURCE]}
    authorization_id = store.authorize("ui-check", "create_assignment", content)
    created = store.invoke("create_assignment", {**content, "authorization_id": authorization_id, "idempotency_key": "external-tool-task-create", "envelope": {"request_id": "external-tool-create-request", "session_id": "external-tool-create-session", "owner_id": "boss-1", "execution_namespace": "ui-check", "dataset_id": "selection", "dataset_version": "1"}})
    with store.connect() as db:
        task = store.get(db, "ui-check", "task", created["task_id"])
    assert task.get("source_versions") == {SOURCE: "1"}
    status, sent = commands.execute("BOSS", "boss.assignment.send", {"client_request_id": "external-tool-task-send", "task_id": created["task_id"], "task_version": created["version"], "recipient_id": "coordinator-1", "body": "请汇总当前模拟资料", "content_version": "1"})
    assert status == 200, sent
    change_dependencies(external)
    with store.connect() as db:
        before = db.execute("SELECT COUNT(*) FROM objects WHERE kind='authorization'").fetchone()[0]
    status, result = commands.execute("BOSS", "boss.assignment.nudge", {"client_request_id": "external-tool-task-nudge", "task_id": created["task_id"], "task_version": sent["task_version"], "recipient_id": "coordinator-1", "body": "请补充当前核查进展"})
    assert status == 409, result
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind='authorization'").fetchone()[0] == before
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind='assignment_nudge'").fetchone()[0] == 0
