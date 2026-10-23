import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from aiohttp import web

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "validation"))

from boss_command_api import BossCommandAPI
from boss_page_api import BossPageAPI
from business import initial_materials
from controls import ControlStore
from test_boss_meeting_brief import prepare, briefing
from test_boss_command_api import create_input
from test_boss_api_spec import SPEC, OPERATIONS
from jsonschema import Draft202012Validator, FormatChecker


def test_briefing_reads_current_persisted_meeting_and_marks_original_version_for_review(tmp_path):
    store = ControlStore(tmp_path / "meeting-current.sqlite")
    store.initialize("ui-check")
    commands, pages = BossCommandAPI(store), BossPageAPI(store)
    assert prepare(commands)[0] == 200
    original = initial_materials()["meeting"]
    with store.connect() as db:
        store.put(db, "ui-check", "meeting", original["meeting_id"], {**original, "version": "2"})
    status, result = briefing(pages)
    assert status == 200
    assert result["current"]["meeting"]["version"] == "2"
    assert result["saved_brief"]["compiled"]["meeting"]["version"] == "1"
    assert result["current_status"] == "NEEDS_REVIEW"
    assert result["meeting_changed"] is True
    with store.connect() as db:
        assert store.get(db, "ui-check", "initial", "snapshot")["meeting"] == original


def arrangement(tmp_path):
    from boss_meetings import MeetingAPI
    store = ControlStore(tmp_path / "meeting-arrangement.sqlite")
    store.initialize("ui-check")
    return store, MeetingAPI(store)


def checked_meeting(api, action, payload):
    operation = OPERATIONS["boss.meeting." + action]
    Draft202012Validator({"components": SPEC["components"], "$ref": operation["input"]}, format_checker=FormatChecker()).validate(payload)
    result = api.execute("BOSS", action, payload)
    Draft202012Validator({"components": SPEC["components"], "$ref": operation["output"]}, format_checker=FormatChecker()).validate(result)
    assert set(operation["result_required"]) <= set(result)
    return result


def draft_input(**changes):
    data = initial_materials()
    calendar = data["private_calendar"]
    return {"client_request_id": "meeting-draft-save", "meeting_id": data["meeting"]["meeting_id"],
            "meeting_version": "1", "expected_version": "0", "purpose": create_input()["purpose"],
            "starts_at": calendar["starts_at"], "ends_at": calendar["ends_at"], "timezone": calendar["timezone"],
            "preparation_due_at": None, "participant_ids": data["meeting"]["participant_ids"],
            "source_refs": [{"source_id": item["source_id"], "version": item["version"]} for item in data["documents"]],
            **changes}


def confirmation(saved, **changes):
    return {"client_request_id": "meeting-owner-confirm", "meeting_id": saved["meeting_id"],
            "meeting_version": saved["meeting_version"], "draft_version": saved["version"],
            "review_sha256": saved["review_sha256"], "acknowledge_conflict": True, **changes}


def test_draft_and_owner_confirmation_preserve_initial_and_invalidate_old_brief(tmp_path):
    store, api = arrangement(tmp_path)
    assert prepare(BossCommandAPI(store))[0] == 200
    initial = api.read("BOSS")["meeting"]
    assert initial["state"] == "DRAFT" and initial["ends_at"] is None
    saved = checked_meeting(api, "draft.save", draft_input())
    assert api.read("BOSS")["meeting"] == initial
    assert saved["meeting_changed"] is False
    assert api.read("BOSS")["draft"]["impact"]["private_calendar"]["conflict"] is True
    with pytest.raises(web.HTTPConflict):
        api.execute("BOSS", "confirm", confirmation(saved, acknowledge_conflict=False))
    result = checked_meeting(api, "confirm", confirmation(saved))
    assert result["state"] == "SCHEDULED" and result["version"] == "2"
    assert result["invitation_sent"] is False
    assert api.execute("BOSS", "confirm", confirmation(saved)) == result
    status, live = briefing(BossPageAPI(ControlStore(store.path)))
    assert status == 200 and live["meeting_changed"] is True
    assert live["current"]["meeting"]["ends_at"] == draft_input()["ends_at"]
    assert live["saved_brief"]["compiled"]["meeting"]["version"] == "1"
    with store.connect() as db:
        assert store.get(db, "ui-check", "initial", "snapshot") == initial_materials()
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind='message_outbox'").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind='meeting_revision'").fetchone()[0] == 1
        audit = json_audit(db)
        assert draft_input()["purpose"] not in audit


def json_audit(db):
    return json.dumps(db.execute("SELECT input,output FROM audit").fetchall(), ensure_ascii=False)


def test_source_change_requires_new_review(tmp_path):
    store, api = arrangement(tmp_path)
    saved = api.execute("BOSS", "draft.save", draft_input())
    store.control("ui-check", "withdraw", {"source_id": "finance-note", "version": "1"})
    assert api.read("BOSS")["draft"]["review_current"] is False
    with pytest.raises(web.HTTPConflict):
        api.execute("BOSS", "confirm", confirmation(saved))
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind='authorization'").fetchone()[0] == 0
    assert api.read("BOSS")["meeting"]["version"] == "1"


def test_calendar_version_change_invalidates_saved_meeting_review(tmp_path):
    from test_boss_message_calendar import calendar_input
    store, api = arrangement(tmp_path)
    saved = api.execute("BOSS", "draft.save", draft_input())
    status, _ = BossCommandAPI(store).execute("BOSS", "boss.calendar.save", {"client_request_id": "meeting-private-change", **calendar_input()})
    assert status == 200
    assert api.read("BOSS")["draft"]["review_current"] is False
    with pytest.raises(web.HTTPConflict):
        api.execute("BOSS", "confirm", confirmation(saved))


def test_meeting_review_includes_confirmed_travel_buffer(tmp_path):
    from test_boss_travel import review_input, confirm_input
    store, api = arrangement(tmp_path)
    commands = BossCommandAPI(store)
    travel = review_input()
    status, reviewed = commands.execute("BOSS", "boss.travel.review", {"client_request_id": "meeting-buffer-trip", **travel})
    assert status == 200
    status, confirmed = commands.execute("BOSS", "boss.travel.confirm", {"client_request_id": "meeting-buffer-confirm", **confirm_input(reviewed)})
    assert status == 200
    api.execute("BOSS", "draft.save", draft_input(starts_at=travel["ends_at"]))
    assert api.read("BOSS")["draft"]["impact"]["overlapping_travel_ids"] == [confirmed["travel_id"]]


def test_rescheduling_preserves_current_until_separate_confirmation(tmp_path):
    from test_boss_travel import review_input
    store, api = arrangement(tmp_path)
    saved = api.execute("BOSS", "draft.save", draft_input())
    first = api.execute("BOSS", "confirm", confirmation(saved))
    current = api.read("BOSS")["meeting"]
    times = review_input()
    revised = api.execute("BOSS", "draft.save", draft_input(client_request_id="meeting-draft-revise", meeting_version=first["version"],
        expected_version=saved["version"], starts_at=times["starts_at"], ends_at=times["ends_at"]))
    assert api.read("BOSS")["meeting"] == current
    second = api.execute("BOSS", "confirm", confirmation(revised, client_request_id="meeting-owner-reschedule"))
    assert second["version"] == "3"
    assert api.read("BOSS")["meeting"]["starts_at"] == times["starts_at"]
    assert api.execute("BOSS", "confirm", confirmation(saved)) == first
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind='meeting_revision'").fetchone()[0] == 2


def test_meeting_change_rejects_old_minutes_people_and_travel_confirmation(tmp_path):
    from test_boss_meeting_approval import minutes_input
    from test_boss_people import draft, attach_input
    from test_boss_travel import review_input, confirm_input
    store, api = arrangement(tmp_path)
    commands, pages = BossCommandAPI(store), BossPageAPI(store)
    status, minute = commands.execute("BOSS", "boss.minutes.save", minutes_input())
    assert status == 200
    status, person = commands.execute("BOSS", "boss.people.prepare", {"client_request_id": "meeting-person-draft", **draft()})
    assert status == 200
    person_row = pages.serve("BOSS", "/api/boss/ui/workspace/people")[1]["briefs"][0]
    status, travel = commands.execute("BOSS", "boss.travel.review", {"client_request_id": "meeting-trip-review", **review_input()})
    assert status == 200
    saved = api.execute("BOSS", "draft.save", draft_input())
    api.execute("BOSS", "confirm", confirmation(saved))
    assert commands.execute("BOSS", "boss.minutes.confirm", {"client_request_id": "meeting-old-minutes", "meeting_id": "meeting-1",
        "expected_version": minute["version"], "source_id": "meeting-minutes", "source_version": "1"})[0] == 409
    assert commands.execute("BOSS", "boss.people.attach", {"client_request_id": "meeting-old-person", **attach_input(person, person_row["compiled_sha256"])})[0] == 409
    assert commands.execute("BOSS", "boss.travel.confirm", {"client_request_id": "meeting-old-trip", **confirm_input(travel)})[0] == 409
    people = pages.serve("BOSS", "/api/boss/ui/workspace/people")[1]
    assert people["meeting"]["version"] == "2"
    assert people["briefs"][0]["live_evidence_current"] is False


def test_calendar_preflight_uses_confirmed_meeting_end_and_cancellation(tmp_path):
    from boss_recovery_api import BossRecoveryAPI
    from test_boss_message_calendar import calendar_input
    store, api = arrangement(tmp_path)
    saved = api.execute("BOSS", "draft.save", draft_input())
    confirmed = api.execute("BOSS", "confirm", confirmation(saved))
    query = "starts_at=2026-10-24T18%3A00%3A00%2B08%3A00&ends_at=2026-10-24T19%3A00%3A00%2B08%3A00&timezone=Asia%2FShanghai"
    recovery = BossRecoveryAPI(store)
    status, overlap = recovery.serve("BOSS", "/api/boss/ui/calendar-conflict", query)
    assert status == 200
    assert overlap["meeting_version"] == confirmed["version"]
    assert overlap["meeting_end_known"] is True
    assert overlap["requires_owner_acknowledgement"] is True
    commands = BossCommandAPI(store)
    status, _ = commands.execute("BOSS", "boss.calendar.save", {"client_request_id": "meeting-calendar-overlap", **calendar_input()})
    assert status == 409
    api.execute("BOSS", "cancel", {"client_request_id": "meeting-cancel-calendar", "meeting_id": "meeting-1", "expected_version": confirmed["version"], "reason": create_input()["purpose"]})
    status, no_overlap = recovery.serve("BOSS", "/api/boss/ui/calendar-conflict", query)
    assert status == 200
    assert no_overlap["status"] == "MEETING_INACTIVE"
    assert no_overlap["requires_owner_acknowledgement"] is False


def test_cancel_is_terminal_without_canceling_independent_task(tmp_path):
    store, api = arrangement(tmp_path)
    status, task = BossCommandAPI(store).execute("BOSS", "boss.assignment.create", create_input())
    assert status == 200
    canceled = checked_meeting(api, "cancel", {"client_request_id": "meeting-cancel-current", "meeting_id": "meeting-1", "expected_version": "1", "reason": create_input()["purpose"]})
    assert canceled["state"] == "CANCELED"
    assert api.read("BOSS")["meeting"]["state"] == "CANCELED"
    assert briefing(BossPageAPI(store))[1]["current"]["needs_review"] is True
    with pytest.raises(web.HTTPConflict):
        api.execute("BOSS", "draft.save", draft_input(meeting_version=canceled["version"]))
    with store.connect() as db:
        assert store.get(db, "ui-check", "task", task["task_id"])["status"] == "OPEN"
    from boss_today import TodayAPI
    assert all(row["item_id"] != "meeting:meeting-1" for row in TodayAPI(store).read("BOSS")["items"])


def test_held_requires_scheduled_meeting_and_business_start_time(tmp_path):
    store, api = arrangement(tmp_path)
    saved = api.execute("BOSS", "draft.save", draft_input())
    confirmed = api.execute("BOSS", "confirm", confirmation(saved))
    payload = {"client_request_id": "meeting-held-current", "meeting_id": "meeting-1", "expected_version": confirmed["version"], "reason": create_input()["purpose"]}
    with pytest.raises(web.HTTPConflict):
        api.execute("BOSS", "held", payload)
    store.control("ui-check", "clock", {"at": draft_input()["starts_at"]})
    held = checked_meeting(api, "held", payload)
    assert held["state"] == "HELD"
    assert api.read("BOSS")["meeting"]["state"] == "HELD"
    assert briefing(BossPageAPI(store))[1]["meeting_occurred"] is True
    with pytest.raises(web.HTTPConflict):
        api.execute("BOSS", "cancel", {**payload, "client_request_id": "meeting-cancel-held", "expected_version": held["version"]})


def test_simultaneous_same_confirmation_has_one_authorization(tmp_path):
    store, api = arrangement(tmp_path)
    saved = api.execute("BOSS", "draft.save", draft_input())
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: api.execute("BOSS", "confirm", confirmation(saved)), range(2)))
    assert results[0] == results[1]
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind='authorization'").fetchone()[0] == 1
    with pytest.raises(web.HTTPConflict):
        api.execute("BOSS", "confirm", confirmation(saved, client_request_id="meeting-other-confirm"))


def test_maintainer_and_unverified_participant_scope_are_rejected(tmp_path):
    store, api = arrangement(tmp_path)
    with pytest.raises(web.HTTPForbidden):
        api.read("MAINTAINER")
    with pytest.raises(web.HTTPUnauthorized):
        api.read(None)
    with pytest.raises(web.HTTPForbidden):
        api.execute("MAINTAINER", "draft.save", draft_input())
    with pytest.raises(web.HTTPBadRequest):
        api.execute("BOSS", "draft.save", draft_input(participant_ids=["coordinator-1", "coordinator-1"]))
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind='meeting_draft'").fetchone()[0] == 0
