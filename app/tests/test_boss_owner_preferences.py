"""N07/N08: actual SQLite owner preference adoption and canonical notification tests.

This does not assert physical Mac, model compliance, real delivery or pixel QA.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "validation"))

from boss_command_api import BossCommandAPI
from boss_page_api import BossPageAPI
from boss_owner_preferences import record_runtime_goal_context_load
from controls import ControlStore

SECRET = "仅老板设置的私密示例：请优先核查本人签发的工作事项"


@pytest.fixture
def app(tmp_path):
    store = ControlStore(tmp_path / "owner-preferences.sqlite")
    store.initialize("ui-check")
    return BossCommandAPI(store), BossPageAPI(store)


def act(api, action, key, role="BOSS", **kwargs):
    return api.execute(role, action, {"client_request_id": key, **kwargs})


def goals(**kwargs):
    return {
        "expected_version": "0",
        "goals": ["及时处理本人待决定事项", "核实真实来源"],
        "topics": ["任务", "决策"],
        "reading_requirement": SECRET,
        "scope": "OWNER_WORKSPACE",
        "valid_until": None,
        **kwargs,
    }


def notice(**kwargs):
    return {
        "expected_version": "0",
        "timezone": "Asia/Shanghai",
        "quiet_start": 22, "quiet_end": 7,
        "notifications_enabled": True,
        "important_during_quiet": False,
        "reading_format": "ACTIONS_FIRST",
        "visibility": "BOSS_ONLY",
        "calendar_share_limit": "BUSY_ONLY",
        "valid_until": None,
        **kwargs,
    }


def confirm_input(prepared, expected_active_version="0"):
    return {
        "expected_draft_version": prepared["version"],
        "expected_active_version": expected_active_version,
        "content_sha256": prepared["content_sha256"],
    }


def view(pages, suffix, role="BOSS"):
    return pages.serve(role, "/api/boss/ui/workspace/" + suffix)


def seed(api):
    return act(api, "boss.simulation.event.seed", "owner-notice-event-seed",
               role="MAINTAINER", event_id="event-1")


def clock(api, at="2026-10-24T18:00:00+08:00"):
    return act(api, "boss.simulation.clock.advance", "owner-notice-clock-advance",
               role="MAINTAINER", at=at)


@pytest.mark.parametrize("domain,fields", [("goals", goals()), ("notice", notice())])
def test_revoked_confirmation_stops_future_setting_adoption(app, domain, fields):
    api, pages = app
    code, prepared = act(api, "boss.owner." + domain + ".save", "revocation-setting-save", **fields)
    assert code == 200, prepared
    code, confirmed = act(api, "boss.owner." + domain + ".confirm", "revocation-setting-confirm", **confirm_input(prepared))
    assert code == 200, confirmed
    route = "owner-goals" if domain == "goals" else "owner-notice"
    assert view(pages, route)[1]["active_is_effective"]
    code, result = act(api, "boss.authorization.revoke", "revoke-setting-confirmation",
                       authorization_id=confirmed["authorization_id"], expected_version="1", reason="停止后续采用")
    assert code == 200, result
    observed = view(BossPageAPI(ControlStore(api.store.path)), route)[1]
    assert observed["active"]["state"] == "CONFIRMED"
    assert not observed["active_is_effective"]
    if domain == "goals":
        assert record_runtime_goal_context_load(api.store) is None


def test_goal_draft_does_not_override_current_context_or_f01(app):
    api, pages = app
    status, initial = view(pages, "owner-goals")
    assert status == 200
    assert initial["active"] is None and initial["draft"] is None
    assert not initial["fixture_goals_are_owner_confirmed"]
    assert pages.serve("BOSS", "/api/boss/ui/dashboard")[1]["profile"]["owner_confirmation"] == "NOT_CONFIRMED"
    code, prepared = act(api, "boss.owner.goals.save", "owner-goal-save-first", **goals())
    assert code == 200, prepared
    assert prepared["state"] == "DRAFT_NOT_EFFECTIVE"
    assert prepared["active_unchanged"] and not prepared["authorization_created"]
    assert act(api, "boss.owner.goals.save", "owner-goal-save-first",
               **goals()) == (code, prepared)
    _, saved = view(pages, "owner-goals")
    assert saved["draft"]["content"]["reading_requirement"] == SECRET
    assert saved["active"] is None and not saved["active_is_effective"]
    assert record_runtime_goal_context_load(api.store) is None
    assert pages.serve("BOSS", "/api/boss/ui/dashboard")[1]["profile"]["goals"] == []
    with api.store.connect() as db:
        assert db.execute("SELECT count(*) FROM objects WHERE kind='authorization'").fetchone()[0] == 0


def test_confirmed_goal_is_read_by_f01_f04_people_and_runtime_provider(app):
    api, pages = app
    assert act(api, "boss.meeting.brief.prepare", "owner-before-f04",
               meeting_id="meeting-1", meeting_version="1",
               expected_version="0")[0] == 200
    draft = act(api, "boss.owner.goals.save", "owner-goal-saving", **goals())[1]
    denied = act(api, "boss.owner.goals.confirm", "owner-goal-maint-forbidden",
                 role="MAINTAINER", **confirm_input(draft))
    assert denied[0] == 403
    code, confirmed = act(api, "boss.owner.goals.confirm", "owner-goal-confirming",
                          **confirm_input(draft))
    assert code == 200, confirmed
    assert confirmed["state"] == "CONFIRMED" and confirmed["version"] == "1"
    assert confirmed["active_adoptable"] and confirmed["authorization_id"]
    assert act(api, "boss.owner.goals.confirm", "owner-goal-confirming",
               **confirm_input(draft)) == (code, confirmed)
    assert act(api, "boss.owner.goals.confirm", "owner-goal-double",
               **confirm_input(draft))[0] == 409
    dashboard = pages.serve("BOSS", "/api/boss/ui/dashboard")[1]
    assert dashboard["profile"]["goals"] == goals()["goals"]
    assert dashboard["profile"]["reading_requirement"] == SECRET
    assert dashboard["profile"]["active_version"] == "1"
    _, briefing = view(pages, "briefing")
    assert briefing["current_status"] == "NEEDS_REVIEW"
    assert briefing["business_changed"]
    assert briefing["current"]["owner_goal_reference"]["active_version"] == "1"
    assert briefing["saved_brief"]["version"] == "1"
    _, initial = view(pages, "owner-goals")
    assert initial["runtime_context_observation"]["context_load_count"] == 0
    context = record_runtime_goal_context_load(api.store)
    assert context["version"] == "1"
    assert context["reading_requirement"] == SECRET
    _, updated = view(pages, "owner-goals")
    assert updated["runtime_context_observation"]["context_load_count"] == 1
    assert updated["runtime_context_observation"]["actual_model_compliance_verified"] is False
    with api.store.connect() as db:
        audit = db.execute("SELECT input, output FROM audit").fetchall()
        assert all(SECRET not in str(row) for row in audit)
        auth = db.execute("SELECT body FROM objects WHERE kind='authorization'").fetchall()
        assert all(SECRET not in row[0] for row in auth)
        receipts = db.execute("SELECT result FROM idempotency").fetchall()
        assert all(SECRET not in row[0] for row in receipts)


def test_setting_drafts_preserve_previous_confirmed_version_until_reconfirmed(app):
    api, pages = app
    draft = act(api, "boss.owner.goals.save", "goals-version-base", **goals())[1]
    first = act(api, "boss.owner.goals.confirm", "goals-version-confirm",
                **confirm_input(draft))[1]
    newer = act(api, "boss.owner.goals.save", "goals-version-edit",
                **goals(expected_version="1", goals=["新的本人工作目标"]))[1]
    assert newer["version"] == "2"
    assert view(pages, "owner-goals")[1]["active"]["version"] == "1"
    assert pages.serve("BOSS", "/api/boss/ui/dashboard")[1]["profile"]["goals"] == goals()["goals"]
    assert act(api, "boss.owner.goals.confirm", "goals-version-stale",
               **confirm_input(newer))[0] == 409
    confirmed = act(api, "boss.owner.goals.confirm", "goals-version-apply",
                    **confirm_input(newer, first["version"]))
    assert confirmed[0] == 200 and confirmed[1]["version"] == "2"
    assert pages.serve("BOSS", "/api/boss/ui/dashboard")[1]["profile"]["goals"] == ["新的本人工作目标"]
    assert view(pages, "owner-goals")[1]["history"][0]["version"] == "1"
    assert act(api, "boss.owner.goals.save", "goals-version-stale-save",
               **goals(expected_version="1"))[0] == 409


@pytest.mark.parametrize("overrides", [
    {"scope": "ALL_ROLES"},
    {"goals": []},
    {"goals": ["重复", "重复"]},
    {"reading_requirement": ""},
    {"valid_until": "2026-10-20T09:00:00+08:00"},
    {"valid_until": "2027-12-01T09:00:00+08:00"},
])
def test_goals_reject_invalid_input(app, overrides):
    api, _ = app
    assert act(api, "boss.owner.goals.save", "goal-invalid-unique",
               **goals(**overrides))[0] == 400


def test_goal_expiry_stops_later_adoption_but_does_not_delete_history(app):
    api, pages = app
    prepared = act(api, "boss.owner.goals.save", "expiry-prep-goal",
                   **goals(valid_until="2026-10-23T10:00:00+08:00"))[1]
    assert act(api, "boss.owner.goals.confirm", "expiry-confirm-goal",
               **confirm_input(prepared))[0] == 200
    assert record_runtime_goal_context_load(api.store) is not None
    assert act(api, "boss.simulation.clock.advance", "expiry-advance-goal",
               role="MAINTAINER", at="2026-10-24T09:00:00+08:00")[0] == 200
    assert pages.serve("BOSS", "/api/boss/ui/dashboard")[1]["profile"]["owner_confirmation"] == "NOT_CONFIRMED"
    assert record_runtime_goal_context_load(api.store) is None
    projected = view(pages, "owner-goals")[1]
    assert not projected["active_is_effective"]
    assert projected["active"]["version"] == "1"


def test_notice_draft_requires_owner_confirm_and_cannot_expand_visibility(app):
    api, pages = app
    initial = view(pages, "owner-notice")[1]
    assert initial["active"] is None
    assert act(api, "boss.owner.notice.save", "notice-impersonate",
               role="MAINTAINER", **notice())[0] == 403
    assert view(pages, "owner-notice", "MAINTAINER")[0] == 403
    assert view(pages, "owner-notice", "ANONYMOUS")[0] == 401
    for invalid in [
        {"timezone":"not-a-timezone"},
        {"quiet_start":24},
        {"important_during_quiet":"true"},
        {"visibility":"CONTACTS"},
        {"calendar_share_limit":"FULL_PRIVATE"},
    ]:
        key = "notice-invalid-"+str(len(str(invalid)))
        assert act(api, "boss.owner.notice.save", key,
                   **notice(**invalid))[0] in (400,403)
    code, prepared = act(api, "boss.owner.notice.save", "notice-save-draft",
                         **notice(notifications_enabled=False))
    assert code == 200 and prepared["state"] == "DRAFT_NOT_EFFECTIVE"
    assert view(pages, "owner-notice")[1]["active"] is None
    assert prepared["authorization_created"] is False
    with api.store.connect() as db:
        assert db.execute("SELECT count(*) FROM objects WHERE kind='authorization'").fetchone()[0] == 0


def test_confirmed_notice_pause_reaches_real_canonical_dispatcher(app):
    api, pages = app
    draft = act(api, "boss.owner.notice.save", "notice-paused-save",
                **notice(notifications_enabled=False))[1]
    confirmation = act(api, "boss.owner.notice.confirm", "notice-paused-confirm",
                       **confirm_input(draft))
    assert confirmation[0] == 200
    assert seed(api)[0] == 200
    assert clock(api)[0] == 200
    result = api.store.dispatch_due("ui-check")
    assert result[0]["state"] == "SUPPRESSED"
    assert result[0]["reason"] == "OWNER_NOTIFICATIONS_PAUSED"
    assert result[0]["owner_notice_version"] == "1"
    notice_read = view(pages, "owner-notice")[1]
    assert notice_read["active_is_effective"]
    assert notice_read["active"]["content"]["notifications_enabled"] is False
    notifications = view(pages, "notifications")[1]
    assert notifications["notifications"] == []
    assert notifications["deliveries"] == []
    with api.store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind='notification'").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind='event'").fetchone()[0] == 1


def test_confirmed_notice_quiet_in_iana_timezone_and_tech_only_stricter(app):
    api, pages = app
    draft = act(api, "boss.owner.notice.save", "notice-shanghai-saved",
                **notice(quiet_start=8,quiet_end=12))[1]
    assert act(api, "boss.owner.notice.confirm", "notice-shanghai-confirm",
               **confirm_input(draft))[0] == 200
    assert seed(api)[0] == 200
    assert clock(api, at="2026-10-25T09:00:00+08:00")[0] == 200
    result = api.store.dispatch_due("ui-check")[0]
    assert result["state"] == "SUPPRESSED"
    assert result["reason"] == "OWNER_QUIET_HOURS"
    assert result["owner_notice_version"] == "1"
    assert view(pages, "notifications")[1]["notifications"] == []


def test_only_draft_notice_does_not_suppress_notifications(app):
    api, pages = app
    assert act(api, "boss.owner.notice.save", "notice-only-draft",
               **notice(notifications_enabled=False))[0] == 200
    assert seed(api)[0] == 200
    assert clock(api)[0] == 200
    result = api.store.dispatch_due("ui-check")[0]
    assert result["state"] == "DELIVERED"
    assert result["reason"] is None
    assert "owner_notice_version" not in result
    assert len(view(pages, "notifications")[1]["notifications"]) == 1


def test_technical_pause_always_stronger_than_owner_preference(app):
    api, pages = app
    d = act(api, "boss.owner.notice.save", "notice-tech-saved",
            **notice(important_during_quiet=True))[1]
    assert act(api, "boss.owner.notice.confirm", "notice-tech-confirm",
               **confirm_input(d))[0] == 200
    assert seed(api)[0] == 200
    assert act(api, "boss.scheduler.pause", "notice-tech-paused",
               role="MAINTAINER", expected_version="1")[0] == 200
    assert clock(api)[0] == 200
    result = api.store.dispatch_due("ui-check")[0]
    assert result["reason"] == "PLAN_PAUSED_OR_CANCELED"
    assert result["state"] == "SUPPRESSED"


def test_owner_version_race_is_rejected_and_no_private_text_is_shared(app):
    api, pages = app
    draft = act(api, "boss.owner.goals.save", "owner-goals-race-draft",
                **goals())[1]
    assert act(api, "boss.owner.goals.confirm", "owner-goals-race-confirm",
               **confirm_input(draft, expected_active_version="91"))[0] == 409
    assert view(pages, "owner-goals", "MAINTAINER")[0] == 403
    assert pages.serve("MAINTAINER", "/api/boss/ui/dashboard")[0] == 403
    with api.store.connect() as db:
        assert db.execute("SELECT count(*) FROM objects WHERE kind='authorization'").fetchone()[0] == 0


def test_scoped_goals_are_not_silently_injected_into_unrelated_chat(app):
    api, pages = app
    draft = act(api, "boss.owner.goals.save", "goals-meeting-scope-draft",
                **goals(scope="MEETING_PREP"))[1]
    assert act(api, "boss.owner.goals.confirm", "goals-meeting-scope-confirm",
               **confirm_input(draft))[0] == 200
    assert record_runtime_goal_context_load(api.store) is None
    assert pages.serve("BOSS", "/api/boss/ui/dashboard")[1]["profile"]["goals"] == []
    _, f04 = view(pages, "briefing")
    assert f04["current"]["owner_goal_reference"]["active_version"] == "1"
    assert f04["current"]["owner_goal_reference"]["scope"] == "MEETING_PREP"
    assert view(pages, "owner-goals")[1]["runtime_context_observation"]["context_load_count"] == 0


def test_daily_brief_goals_do_not_inject_unrelated_runtime_context_or_meeting(app):
    api, pages = app
    draft = act(api, "boss.owner.goals.save", "goals-daily-scope-draft",
                **goals(scope="DAILY_BRIEF"))[1]
    assert act(api, "boss.owner.goals.confirm", "goals-daily-scope-confirm",
               **confirm_input(draft))[0] == 200
    assert record_runtime_goal_context_load(api.store) is None
    assert pages.serve("BOSS", "/api/boss/ui/dashboard")[1]["profile"]["goals"] == goals()["goals"]
    assert view(pages, "briefing")[1]["current"]["owner_goal_reference"]["active_version"] is None


def test_notification_projection_discloses_applied_policy_version_not_owner_goal_text(app):
    api, pages = app
    g = act(api, "boss.owner.goals.save", "goal-for-notice-projection", **goals())[1]
    assert act(api, "boss.owner.goals.confirm", "goal-notice-projection-confirm",
               **confirm_input(g))[0] == 200
    n = act(api, "boss.owner.notice.save", "notice-projection-save",
            **notice(notifications_enabled=False))[1]
    assert act(api, "boss.owner.notice.confirm", "notice-projection-confirm",
               **confirm_input(n))[0] == 200
    assert seed(api)[0] == 200
    assert clock(api)[0] == 200
    api.store.dispatch_due("ui-check")
    body = view(pages, "notifications")[1]
    prefs = body["owner_notification_preferences"]
    assert prefs["version"] == "1"
    assert prefs["notifications_enabled"] is False
    assert prefs["reading_format"] == "ACTIONS_FIRST"
    assert body["dispatches"][0]["reason"] == "OWNER_NOTIFICATIONS_PAUSED"
    assert body["dispatches"][0]["owner_notice_version"] == "1"
    assert SECRET not in json.dumps(body, ensure_ascii=False)
