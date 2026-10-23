"""A13 persisted technical scheduler: draft -> validate -> activate lifecycle.

Synthetic SQLite only. No approval, personal-content access or real Cron
runtime pass is asserted by these unit tests.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/"validation"))
from controls import ControlStore  # noqa: E402
from boss_page_api import BossPageAPI  # noqa: E402
from boss_command_api import BossCommandAPI  # noqa: E402


@pytest.fixture
def services(tmp_path):
    store = ControlStore(tmp_path/"scheduler.sqlite")
    store.initialize("ui-check")
    return BossCommandAPI(store),BossPageAPI(store)


def cmd(api,role,action,key,**fields):
    return api.execute(role,action,{"client_request_id":key,**fields})


def config(**overrides):
    return {
        "expected_version":"0",
        "trigger":"EVENT_OR_TIME",
        "timezone":"Asia/Shanghai",
        "quiet_start":22,
        "quiet_end":7,
        "cooldown_seconds":3600,
        "important_escalation":False,
        **overrides,
    }


def read(pages,role="MAINTAINER"):
    return pages.serve(role,"/api/boss/ui/workspace/scheduler")


def save_validate(api):
    saved=cmd(api,"MAINTAINER","boss.scheduler.draft.save",
              "scheduler-draft-save-001",**config())
    assert saved[0]==200,saved
    checked=cmd(api,"MAINTAINER","boss.scheduler.draft.validate",
                "scheduler-draft-validate-001",expected_version="1")
    assert checked[0]==200,checked
    assert checked[1]["version"]=="2"
    return saved,checked


def test_draft_save_and_validate_do_not_change_live_schedule(services):
    api,pages=services
    original=read(pages)[1]
    assert original["draft"] is None
    assert original["schedule"]["version"]=="1"
    assert original["rules"] is None
    saved,checked=save_validate(api)
    assert saved[1]["validation_state"]=="DRAFT"
    assert saved[1]["schedule_activated"] is False
    assert checked[1]["validation_state"]=="VALIDATED"
    assert checked[1]["schedule_activated"] is False
    observed=read(pages)[1]
    assert observed["draft"]["version"]=="2"
    assert observed["draft"]["validation_state"]=="VALIDATED"
    assert observed["schedule"]==original["schedule"]
    assert observed["rules"] is None
    assert read(pages,"BOSS")[0]==403
    with api.store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind='authorization'").fetchone()[0]==0


def test_activation_is_cas_and_updates_actual_rule_version(services):
    api,pages=services
    save_validate(api)
    action={
        "expected_draft_version":"2",
        "expected_schedule_version":"1",
        "expected_rules_version":"0",
    }
    code,activated=cmd(api,"MAINTAINER","boss.scheduler.activate",
                       "scheduler-activate-001",**action)
    assert code==200,activated
    assert activated["version"]=="2"
    assert activated["rules_version"]=="1"
    assert activated["validation_state"]=="ACTIVE"
    assert activated["external_message_sent"] is False
    assert activated["manual_dispatch_executed"] is False
    assert activated["owner_authorization_granted"] is False
    assert cmd(api,"MAINTAINER","boss.scheduler.activate",
               "scheduler-activate-001",**action)==(code,activated)
    assert cmd(api,"MAINTAINER","boss.scheduler.activate",
               "scheduler-activate-again",**action)[0]==409
    observed=read(pages)[1]
    assert observed["schedule"]["version"]=="2"
    assert observed["schedule"]["active_draft_version"]=="2"
    assert observed["rules"]["quiet_start"]==22
    assert observed["rules"]["cooldown_seconds"]==3600
    assert observed["draft"]["validation_state"]=="ACTIVE"
    assert observed["cron_runtime_verified_here"] is False
    assert observed["manual_dispatch_supported_here"] is True  # simulated only
    assert observed["next_run_time"] is None
    with api.store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind='authorization'").fetchone()[0]==0


def test_pause_and_resume_change_real_live_toggle_version_and_never_owner_permission(services):
    api,pages=services
    save_validate(api)
    cmd(api,"MAINTAINER","boss.scheduler.activate",
        "scheduler-activate-pause",
        expected_draft_version="2",expected_schedule_version="1",
        expected_rules_version="0")
    status,paused=cmd(api,"MAINTAINER","boss.scheduler.pause",
                      "scheduler-pause-001",expected_version="2")
    assert status==200,paused
    assert paused["enabled"] is False
    assert paused["canceled"] is False
    assert paused["version"]=="3"
    assert cmd(api,"MAINTAINER","boss.scheduler.pause",
               "scheduler-pause-001",expected_version="2")==(status,paused)
    assert cmd(api,"MAINTAINER","boss.scheduler.pause",
               "scheduler-pause-stale",expected_version="2")[0]==409
    status,resumed=cmd(api,"MAINTAINER","boss.scheduler.resume",
                       "scheduler-resume-001",expected_version="3")
    assert status==200,resumed
    assert resumed["version"]=="4" and resumed["enabled"] is True
    assert resumed["owner_authorization_granted"] is False
    assert read(pages)[1]["schedule"]["enabled"] is True


def test_cancel_blocks_reenable_same_execution_namespace(services):
    api,pages=services
    code,canceled=cmd(api,"MAINTAINER","boss.scheduler.cancel",
                      "scheduler-cancel-001",expected_version="1")
    assert code==200,canceled
    assert canceled["canceled"] is True
    assert canceled["enabled"] is False
    assert cmd(api,"MAINTAINER","boss.scheduler.resume",
               "scheduler-cancel-resume",expected_version="2")[0]==409
    assert cmd(api,"MAINTAINER","boss.scheduler.pause",
               "scheduler-cancel-pause",expected_version="2")[0]==409
    assert cmd(api,"MAINTAINER","boss.scheduler.cancel",
               "scheduler-cancel-retry-new-id",expected_version="2")[0]==409
    assert read(pages)[1]["schedule"]["canceled"] is True
    assert cmd(api,"MAINTAINER","boss.scheduler.draft.save",
               "scheduler-save-after-cancel",**config())[0]==200
    assert cmd(api,"MAINTAINER","boss.scheduler.draft.validate",
               "scheduler-validate-after-cancel",expected_version="1")[0]==409


@pytest.mark.parametrize("mutation",[
    {"trigger":"WRONG_EVENT"},
    {"timezone":"Europe/London"},
    {"quiet_start":24},
    {"quiet_end":-1},
    {"cooldown_seconds":86401},
    {"important_escalation":"no"},
    {"expected_version":"bad-version"},
])
def test_bad_configuration_rejected_without_side_effect(services,mutation):
    api,pages=services
    status,_=cmd(api,"MAINTAINER","boss.scheduler.draft.save",
                 "scheduler-bad-" + list(mutation)[0],**config(**mutation))
    assert status==400
    state=read(pages)[1]
    assert state["draft"] is None
    assert state["schedule"]["version"]=="1"


def test_owner_cannot_modify_technical_schedule_but_can_read_own_tasks(services):
    api,pages=services
    assert cmd(api,"BOSS","boss.scheduler.draft.save",
               "owner-denied-scheduler",**config())[0]==403
    assert cmd(api,"BOSS","boss.scheduler.pause",
               "owner-denied-pause",expected_version="1")[0]==403
    assert read(pages,"BOSS")[0]==403
    assert pages.serve("BOSS","/api/boss/ui/tasks")[0]==200
    assert pages.serve("MAINTAINER","/api/boss/ui/tasks")[0]==403


def test_validation_is_invalidated_after_independent_schedule_update(services):
    api,pages=services
    save_validate(api)
    assert cmd(api,"MAINTAINER","boss.scheduler.pause",
               "scheduler-concurrent-pause",expected_version="1")[0]==200
    assert cmd(api,"MAINTAINER","boss.scheduler.activate",
               "scheduler-stale-activate",
               expected_draft_version="2",expected_schedule_version="2",
               expected_rules_version="0")[0]==409
    result=read(pages)[1]
    assert result["draft"]["validation_state"]=="VALIDATED"
    assert result["schedule"]["version"]=="2"


def test_paused_scheduler_suppresses_real_due_event_dispatch(services):
    api,pages=services
    # The normal simulation editor injects a test event and rules.
    planted=cmd(api,"MAINTAINER","boss.simulation.event.seed",
                "scheduler-seed-event",event_id="event-1")
    assert planted[0]==200,planted
    paused=cmd(api,"MAINTAINER","boss.scheduler.pause",
               "scheduler-paused-event",expected_version="1")
    assert paused[0]==200
    assert cmd(api,"MAINTAINER","boss.simulation.clock.advance",
               "scheduler-advance-due",at="2026-10-30T09:00:00+08:00")[0]==200
    emitted=api.store.dispatch_due("ui-check")
    assert emitted
    assert all(x["state"]=="SUPPRESSED" for x in emitted)
    assert any(x["reason"]=="PLAN_PAUSED_OR_CANCELED" for x in emitted)
    with api.store.connect() as db:
        assert db.execute(
            "SELECT COUNT(*) FROM objects WHERE kind='delivery'"
        ).fetchone()[0]==0
    assert read(pages)[1]["schedule"]["enabled"] is False



def activate_fixture(api):
    seeded = cmd(api, "MAINTAINER", "boss.simulation.event.seed",
                 "scheduler-manual-event", event_id="event-1")
    assert seeded[0] == 200, seeded
    saved = cmd(api, "MAINTAINER", "boss.scheduler.draft.save",
                "scheduler-manual-draft", **config(expected_version="0"))
    assert saved[0] == 200, saved
    checked = cmd(api, "MAINTAINER", "boss.scheduler.draft.validate",
                  "scheduler-manual-validate", expected_version="1")
    assert checked[0] == 200, checked
    activated = cmd(api, "MAINTAINER", "boss.scheduler.activate",
                    "scheduler-manual-activate",
                    expected_draft_version="2", expected_schedule_version="1",
                    expected_rules_version="1")
    assert activated[0] == 200, activated
    return activated[1]


def manual_args(version):
    return {
        "event_id": "event-1", "event_version": "1",
        "expected_schedule_version": version,
        "expected_rules_version": "2",
    }


def test_manual_simulated_run_reuses_cron_business_rules_and_has_no_external_effect(services):
    api, pages = services
    activated = activate_fixture(api)
    pending = cmd(api, "MAINTAINER", "boss.scheduler.manual_run",
                  "manual-not-due-001", **manual_args(activated["version"]))
    assert pending[0] == 200, pending
    assert pending[1]["dispatch_state"] == "NOT_DUE"
    assert pending[1]["dispatch_reason"] == "EVENT_NOT_YET_DUE"
    assert pending[1]["manual_dispatch_executed"] is True
    assert pending[1]["external_delivery_verified"] is False
    with api.store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind='delivery'").fetchone()[0] == 0
    advanced = cmd(api, "MAINTAINER", "boss.simulation.clock.advance",
                   "scheduler-manual-time", at="2026-10-30T09:00:00+08:00")
    assert advanced[0] == 200, advanced
    actual = cmd(api, "MAINTAINER", "boss.scheduler.manual_run",
                 "manual-after-due-001", **manual_args(activated["version"]))
    assert actual[0] == 200, actual
    assert actual[1]["dispatch_state"] == "DELIVERED"
    assert actual[1]["dispatch_reason"] is None
    assert actual[1]["external_message_sent"] is False
    assert actual[1]["owner_business_authorization_granted"] is False
    _, workspace = read(pages)
    assert any(row["event_id"] == "event-1"
               for row in workspace["recent_dispatches"])
    with api.store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind='delivery'").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind='notification'").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind='authorization'").fetchone()[0] == 0


def test_manual_dispatch_concurrent_intent_has_one_persisted_delivery(services):
    api, pages = services
    activated = activate_fixture(api)
    assert cmd(api, "MAINTAINER", "boss.simulation.clock.advance",
               "scheduler-manual-repeat-time", at="2026-10-30T09:00:00+08:00")[0] == 200
    a = cmd(api, "MAINTAINER", "boss.scheduler.manual_run",
            "scheduler-manual-first", **manual_args(activated["version"]))
    assert a[0] == 200 and a[1]["dispatch_state"] == "DELIVERED"
    replay = cmd(api, "MAINTAINER", "boss.scheduler.manual_run",
                 "scheduler-manual-first", **manual_args(activated["version"]))
    assert replay == a
    new_key = cmd(api, "MAINTAINER", "boss.scheduler.manual_run",
                  "scheduler-manual-second", **manual_args(activated["version"]))
    assert new_key[0] == 200
    assert new_key[1]["dispatch_state"] == "SUPPRESSED"
    assert new_key[1]["dispatch_reason"] == "DUPLICATE_EVENT"
    with api.store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind='delivery'").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind='notification'").fetchone()[0] == 1


def test_manual_run_requires_validated_active_plan_and_correct_event_scope(services):
    api, pages = services
    planted = cmd(api, "MAINTAINER", "boss.simulation.event.seed",
                  "manual-scope-event", event_id="event-1")
    assert planted[0] == 200
    no_active = {
        "event_id": "event-1", "event_version": "1",
        "expected_schedule_version": "1", "expected_rules_version": "1",
    }
    assert cmd(api, "MAINTAINER", "boss.scheduler.manual_run",
               "not-activated-manual", **no_active)[0] == 409
    assert cmd(api, "BOSS", "boss.scheduler.manual_run",
               "owner-not-technical", **no_active)[0] == 403
    # Event ID must be in the actual approved dataset, not supplied scope.
    invalid = cmd(api, "MAINTAINER", "boss.scheduler.manual_run",
                  "bad-event-manual", **{**no_active, "event_id": "../other-space"})
    assert invalid[0] in (404,409)
