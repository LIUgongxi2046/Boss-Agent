"""FR-11 real SQLite lifecycle, timezone, conflict, role and F04 freshness tests.

All test travel is SIMULATED; no booking or external calendar exists.
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "validation"))

from boss_command_api import BossCommandAPI
from boss_page_api import BossPageAPI
from controls import ControlStore


@pytest.fixture
def app(tmp_path):
    store = ControlStore(tmp_path / "travel.sqlite")
    store.initialize("ui-check")
    return BossCommandAPI(store), BossPageAPI(store)


def action(cmd, name, key, role="BOSS", **payload):
    return cmd.execute(role, name, {"client_request_id": key, **payload})


def review_input(**changes):
    return {
        "travel_id": None, "expected_version": "0",
        "origin": "模拟总部", "destination": "区域会议场地",
        "starts_at": "2026-10-23T08:00:00+08:00",
        "ends_at": "2026-10-23T11:00:00+08:00",
        "timezone": "Asia/Shanghai", "host_contact_id": "coordinator-1",
        "buffer_minutes": 30, "transport_refs": [],
        **changes,
    }


def read(pages, role="BOSS"):
    return pages.serve(role, "/api/boss/ui/workspace/travel")


def confirm_input(review_result, **changes):
    return {
        "travel_id": review_result["travel_id"],
        "expected_version": review_result["version"],
        "review_sha256": review_result["review_sha256"],
        "acknowledge_conflicts": True,
        "acknowledge_missing_transport": True,
        **changes,
    }


def test_review_then_separate_owner_confirmation_persist_and_f04_invalidation(app):
    cmd, pages = app
    ready = action(cmd, "boss.meeting.brief.prepare", "initial-f04-for-trip",
                   meeting_id="meeting-1", meeting_version="1", expected_version="0")
    assert ready[0] == 200 and ready[1]["state"] == "READY_FOR_REVIEW"

    code, draft = action(cmd, "boss.travel.review", "travel-review-first", **review_input())
    assert code == 200, draft
    assert draft["status"] == "DRAFT_REVIEWED"
    assert draft["external_booking_created"] is False
    assert draft["impact"]["meeting"]["start_overlap"] is True
    assert draft["impact"]["meeting"]["end_known"] is False
    assert draft["impact"]["transport_missing"] is True
    assert draft["impact"]["conflicts_need_acknowledgement"]

    code, state = read(pages)
    assert code == 200 and state["projection"] == "travel"
    assert state["source_type"] == "SIMULATED"
    assert len(state["plans"]) == 1
    assert state["plans"][0]["pending_is_current"] is True
    assert state["plans"][0]["current"] is None

    # Reviewing a draft does not alter the work meeting or mark it completed.
    _, f04 = pages.serve("BOSS", "/api/boss/ui/workspace/briefing")
    assert f04["current_status"] == "READY_FOR_REVIEW"

    assert action(cmd, "boss.travel.confirm", "travel-no-conflict-ack",
                  **confirm_input(draft, acknowledge_conflicts=False))[0] == 409
    assert action(cmd, "boss.travel.confirm", "travel-no-transport-ack",
                  **confirm_input(draft, acknowledge_missing_transport=False))[0] == 409
    code, result = action(cmd, "boss.travel.confirm", "travel-owner-confirm",
                          **confirm_input(draft))
    assert code == 200, result
    assert result["status"] == "CONFIRMED" and result["version"] == "2"
    assert result["authorization_id"]
    assert result["external_booking_created"] is False
    assert result["external_calendar_updated"] is False
    assert action(cmd, "boss.travel.confirm", "travel-owner-confirm",
                  **confirm_input(draft)) == (code, result)
    assert action(cmd, "boss.travel.confirm", "travel-confirm-fresh",
                  **confirm_input(draft))[0] == 409

    _, saved = read(pages)
    trip = saved["plans"][0]
    assert trip["status"] == "CONFIRMED" and trip["pending"] is None
    assert trip["current"]["starts_at_utc"] == "2026-10-23T00:00:00+00:00"
    _, f04 = pages.serve("BOSS", "/api/boss/ui/workspace/briefing")
    assert f04["business_changed"] and f04["current_status"] == "NEEDS_REVIEW"
    assert f04["current"]["travel_impacts"][0]["travel_id"] == result["travel_id"]
    assert f04["saved_brief"]["version"] == "1"
    with cmd.store.connect() as db:
        assert db.execute("SELECT count(*) FROM objects WHERE kind='travel_plan'").fetchone()[0] == 1
        assert db.execute("SELECT count(*) FROM objects WHERE kind='authorization'").fetchone()[0] == 1
        assert db.execute("SELECT count(*) FROM objects WHERE kind='message_outbox'").fetchone()[0] == 0


def test_private_calendar_and_task_due_are_checked_not_hidden_or_guessed(app):
    cmd, pages = app
    code, draft = action(cmd, "boss.travel.review", "travel-private-overlap", **review_input(
        starts_at="2026-10-24T16:45:00+08:00",
        ends_at="2026-10-24T19:15:00+08:00",
    ))
    assert code == 200, draft
    impact = draft["impact"]
    assert impact["private_calendar"]["conflict"] is True
    assert impact["private_calendar"]["private_body_exposed"] is False
    assert [x["task_id"] for x in impact["task_deadlines"]] == ["historical-1"]
    assert impact["meeting"]["start_overlap"] is False
    assert impact["meeting"]["end_known"] is False
    assert "private_body" not in json.dumps(impact)
    assert action(cmd, "boss.travel.confirm", "trip-missing-ack",
                  **confirm_input(draft, acknowledge_conflicts=False))[0] == 409
    assert action(cmd, "boss.travel.confirm", "trip-valid-ack",
                  **confirm_input(draft))[0] == 200
    assert read(pages)[1]["plans"][0]["current"]["destination"] == "区域会议场地"


def test_two_stage_revision_keeps_confirmed_schedule_until_owner_confirmation(app):
    cmd, pages = app
    created = action(cmd, "boss.travel.review", "travel-versioned-first", **review_input())[1]
    saved = action(cmd, "boss.travel.confirm", "travel-versioned-confirm", **confirm_input(created))[1]
    code, draft = action(cmd, "boss.travel.review", "travel-versioned-edit",
                         **review_input(travel_id=saved["travel_id"],
                                        expected_version=saved["version"],
                                        destination="变更后的会面场地"))
    assert code == 200
    assert draft["status"] == "CONFIRMED" and draft["version"] == "3"
    state = read(pages)[1]["plans"][0]
    assert state["current"]["destination"] == "区域会议场地"
    assert state["pending"]["details"]["destination"] == "变更后的会面场地"
    assert action(cmd, "boss.travel.confirm", "travel-stale-version",
                  **confirm_input(created))[0] == 409
    applied = action(cmd, "boss.travel.confirm", "travel-versioned-apply",
                     **confirm_input(draft))
    assert applied[0] == 200 and applied[1]["version"] == "4"
    assert read(pages)[1]["plans"][0]["current"]["destination"] == "变更后的会面场地"
    with cmd.store.connect() as db:
        assert db.execute("SELECT count(*) FROM objects WHERE kind='travel_revision'").fetchone()[0] >= 3
    assert action(cmd, "boss.travel.cancel", "travel-cancel",
                  travel_id=saved["travel_id"], expected_version="4",
                  reason="接待人员报告计划改变")[0] == 200
    canceled = read(pages)[1]["plans"][0]
    assert canceled["status"] == "CANCELED" and canceled["version"] == "5"
    assert canceled["current"]["destination"] == "变更后的会面场地"
    assert action(cmd, "boss.travel.review", "travel-reopen-canceled",
                  **review_input(travel_id=saved["travel_id"], expected_version="5"))[0] == 409
    assert action(cmd, "boss.travel.cancel", "travel-repeat-cancel",
                  travel_id=saved["travel_id"], expected_version="5",
                  reason="不能重复取消")[0] == 409


@pytest.mark.parametrize("start,end,zone", [
    ("2026-11-01T01:30:00", "2026-11-01T03:00:00-08:00", "America/Los_Angeles"),
    ("2027-03-14T02:30:00-07:00", "2027-03-14T04:00:00-07:00", "America/Los_Angeles"),
    ("2026-11-01T01:30:00+08:00", "2026-11-01T02:00:00+08:00", "America/Los_Angeles"),
    ("2026-10-23T08:00:00+08:00", "2026-10-23T07:00:00+08:00", "Asia/Shanghai"),
])
def test_ambiguous_missing_nonexistent_or_invalid_time_rejected(app, start, end, zone):
    cmd, _ = app
    code, _ = action(cmd, "boss.travel.review", "trip-invalid-time-001",
                     **review_input(starts_at=start, ends_at=end, timezone=zone))
    assert code == 400


def test_dst_overlap_with_explicit_offsets_maps_to_unambiguous_utc(app):
    cmd, pages = app
    code, draft = action(cmd, "boss.travel.review", "trip-dst-explicit", **review_input(
        starts_at="2026-11-01T01:30:00-07:00",
        ends_at="2026-11-01T01:30:00-08:00",
        timezone="America/Los_Angeles",
    ))
    assert code == 200, draft
    assert read(pages)[1]["plans"][0]["pending"]["details"]["starts_at_utc"] == "2026-11-01T08:30:00+00:00"
    assert read(pages)[1]["plans"][0]["pending"]["details"]["ends_at_utc"] == "2026-11-01T09:30:00+00:00"


def test_role_scope_same_name_client_payload_and_no_ghost_booking(app):
    cmd, pages = app
    input = review_input()
    assert action(cmd, "boss.travel.review", "trip-maint-denied",
                  role="MAINTAINER", **input)[0] == 403
    assert read(pages, "MAINTAINER")[0] == 403
    assert read(pages, "GUEST")[0] == 401
    assert action(cmd, "boss.travel.review", "trip-owner-injected",
                  **{**input, "owner_id": "some-other-owner"})[0] == 400
    assert action(cmd, "boss.travel.review", "trip-contact-unknown",
                  **review_input(host_contact_id="unknown-name"))[0] == 400
    # Two contacts share the same name; only the stable ID is allowed.
    code, result = action(cmd, "boss.travel.review", "trip-contact-stable",
                          **review_input(host_contact_id="contact-2"))
    assert code == 200 and result["status"] == "DRAFT_REVIEWED"
    assert read(pages)[1]["real_transport_bookings"] is False


def test_source_and_private_calendar_change_invalidate_stale_review(app):
    cmd, pages = app
    code, draft = action(cmd, "boss.travel.review", "trip-source-preview",
                         **review_input(transport_refs=[{
                             "source_id": "finance-note", "version": "1",
                         }]))
    assert code == 200, draft
    assert draft["impact"]["transport_missing"] is False
    cmd.store.control("ui-check", "withdraw", {"source_id": "finance-note", "version": "1"})
    _, workspace = read(pages)
    assert workspace["plans"][0]["pending_is_current"] is False
    assert action(cmd, "boss.travel.confirm", "trip-revoked-sources",
                  **confirm_input(draft))[0] in (403, 409)

    other = action(cmd, "boss.travel.review", "trip-private-preview",
                   **review_input(starts_at="2026-10-24T12:00:00+08:00",
                                  ends_at="2026-10-24T13:00:00+08:00"))[1]
    changed = action(cmd, "boss.calendar.save", "trip-change-private", **{
        "expected_version": "1",
        "starts_at": "2026-10-24T12:15:00+08:00",
        "ends_at": "2026-10-24T12:45:00+08:00",
        "timezone": "Asia/Shanghai", "title": "私人活动",
        "private_body": "不能外泄的私人内容",
        "location": "仅本人可见", "attachment_refs": [],
        "acknowledge_conflict": False,
    })
    assert changed[0] == 200, changed
    assert read(pages)[1]["plans"][1]["pending_is_current"] is False
    assert action(cmd, "boss.travel.confirm", "trip-calendar-changed",
                  **confirm_input(other))[0] == 409


def test_contact_expiry_and_no_unapproved_external_send(app):
    cmd, pages = app
    moved = action(cmd, "boss.simulation.clock.advance", "trip-clock-expiry",
                   role="MAINTAINER", at="2027-02-01T09:00:00+08:00")
    assert moved[0] == 200, moved
    assert action(cmd, "boss.travel.review", "trip-expired-host",
                  **review_input(starts_at="2027-03-02T09:00:00+08:00",
                                 ends_at="2027-03-02T10:00:00+08:00"))[0] == 403
    assert read(pages)[1]["plans"] == []
    with cmd.store.connect() as db:
        assert db.execute("SELECT count(*) FROM objects WHERE kind='message_outbox'").fetchone()[0] == 0
