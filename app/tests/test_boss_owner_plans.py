import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from aiohttp import web

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "validation"))

from boss_command_api import BossCommandAPI
from controls import ControlStore
from boss_owner_plans import OwnerPlansAPI


@pytest.fixture
def services(tmp_path):
    store = ControlStore(tmp_path / "plans.sqlite")
    store.initialize("ui-check")
    commands = BossCommandAPI(store)
    status, result = commands.execute("MAINTAINER", "boss.simulation.event.seed", {
        "client_request_id": "approved-event-seed", "event_id": "event-1",
    })
    assert status == 200, result
    return store, commands, OwnerPlansAPI(store)


def create(plans):
    return plans.execute("BOSS", "save", {
        "client_request_id": "owner-plan-create", "plan_id": "", "expected_version": "0",
        "purpose": "本人承诺", "event_ids": ["event-1"], "timezone": "Asia/Shanghai",
        "not_before": "2026-10-24T17:00:00+08:00",
    })


def test_owner_plan_cas_receipt_restart_and_single_dispatch(services):
    store, commands, plans = services
    saved = create(plans)
    assert create(plans) == saved
    assert plans.read("BOSS")["plans"][0]["plan_id"] == saved["plan_id"]
    reopened = OwnerPlansAPI(ControlStore(store.path))
    assert reopened.read("BOSS") == plans.read("BOSS")
    fields = {"client_request_id": "owner-plan-pause", "plan_id": saved["plan_id"], "expected_version": "1"}
    paused = plans.execute("BOSS", "pause", fields)
    assert paused["state"] == "PAUSED"
    assert plans.execute("BOSS", "pause", fields) == paused
    with pytest.raises(web.HTTPConflict):
        plans.execute("BOSS", "resume", {**fields, "client_request_id": "stale-resume"})
    status, result = commands.execute("MAINTAINER", "boss.simulation.clock.advance", {
        "client_request_id": "owner-plan-clock", "at": "2026-10-30T09:00:00+08:00",
    })
    assert status == 200, result
    assert store.dispatch_due("ui-check")[0]["reason"] == "OWNER_PLAN_PAUSED"
    resumed = plans.execute("BOSS", "resume", {**fields, "client_request_id": "owner-plan-resume", "expected_version": "2"})
    assert resumed["state"] == "ACTIVE"
    assert store.dispatch_due("ui-check")[0]["state"] == "DELIVERED"
    assert store.dispatch_due("ui-check")[0]["reason"] == "DUPLICATE_EVENT"
    assert len(reopened.read("BOSS")["results"]) == 1


def test_cancel_is_terminal_and_revocation_stops_future_dispatch(services):
    store, commands, plans = services
    saved = create(plans)
    status, result = commands.execute("BOSS", "boss.authorization.revoke", {
        "client_request_id": "owner-plan-revoke", "authorization_id": saved["authorization_id"],
        "expected_version": "1", "reason": "取消后续采用",
    })
    assert status == 200, result
    commands.execute("MAINTAINER", "boss.simulation.clock.advance", {
        "client_request_id": "revoked-plan-clock", "at": "2026-10-30T09:00:00+08:00",
    })
    assert store.dispatch_due("ui-check")[0]["reason"] == "OWNER_PLAN_AUTHORIZATION_REVOKED"
    canceled = plans.execute("BOSS", "cancel", {
        "client_request_id": "owner-plan-cancel", "plan_id": saved["plan_id"], "expected_version": "1",
    })
    assert canceled["state"] == "CANCELED"
    with pytest.raises(web.HTTPConflict):
        plans.execute("BOSS", "resume", {
            "client_request_id": "cancel-resume-denied", "plan_id": saved["plan_id"], "expected_version": "2",
        })


def test_roles_and_scope_validation_have_no_side_effects(services):
    store, _, plans = services
    for role, error in [(None, web.HTTPUnauthorized), ("MAINTAINER", web.HTTPForbidden), ("coordinator-1", web.HTTPUnauthorized)]:
        with pytest.raises(error):
            plans.read(role)
        with pytest.raises(error):
            plans.execute(role, "save", {})
    assert plans.read("BOSS")["plans"] == []
    saved = create(plans)
    with pytest.raises(web.HTTPConflict):
        plans.execute("BOSS", "save", {
            "client_request_id": "conflicting-plan", "plan_id": "", "expected_version": "0",
            "purpose": "本人承诺", "event_ids": ["event-1"], "timezone": "Asia/Shanghai",
            "not_before": "2026-10-24T17:00:00+08:00",
        })
    assert len(plans.read("BOSS")["plans"]) == 1
    assert plans.read("BOSS")["plans"][0]["plan_id"] == saved["plan_id"]


def test_event_update_retains_plan_binding_and_requires_current_source_confirmation(services):
    store, commands, plans = services
    saved = create(plans)
    with store.connect() as db:
        event = store.get(db, "ui-check", "event", "event-1")
    fields = {key: event[key] for key in ("event_id", "version", "state", "impact", "due_at")}
    fields["version"] = "2"
    updated = store.control("ui-check", "event", fields)
    assert updated["owner_plan_id"] == saved["plan_id"]
    status, result = commands.execute("MAINTAINER", "boss.simulation.clock.advance", {
        "client_request_id": "updated-plan-clock", "at": "2026-10-30T09:00:00+08:00",
    })
    assert status == 200, result
    assert store.dispatch_due("ui-check")[0]["reason"] == "OWNER_PLAN_SOURCE_CHANGED"


def test_same_event_version_cannot_change_authorized_content(services):
    store, _, plans = services
    saved = create(plans)
    with store.connect() as db:
        event = store.get(db, "ui-check", "event", "event-1")
    fields = {key: event[key] for key in ("event_id", "version", "state", "impact", "due_at")}
    assert store.control("ui-check", "event", fields)["owner_plan_id"] == saved["plan_id"]
    with pytest.raises(web.HTTPConflict):
        store.control("ui-check", "event", {**fields, "impact": "IMPORTANT"})


def test_concurrent_same_request_has_one_authorization_and_receipt(services):
    store, _, plans = services
    saved = create(plans)
    payload = {"client_request_id": "concurrent-plan-pause", "plan_id": saved["plan_id"], "expected_version": "1"}
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(plans.execute, "BOSS", "pause", payload) for _ in range(2)]
        results = [future.result() for future in futures]
    assert results[0] == results[1]
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM idempotency WHERE operation='boss.owner.plan.pause'").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind='authorization'").fetchone()[0] == 2


def test_concurrent_distinct_requests_enforce_cas(services):
    _, _, plans = services
    saved = create(plans)
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(plans.execute, "BOSS", "pause", {
            "client_request_id": "concurrent-plan-distinct-" + str(index),
            "plan_id": saved["plan_id"], "expected_version": "1",
        }) for index in range(2)]
        errors = [future.exception() for future in futures]
        assert sum(error is None for error in errors) == 1
        assert sum(isinstance(error, web.HTTPConflict) for error in errors) == 1
    assert plans.read("BOSS")["plans"][0]["version"] == "2"


def test_concurrent_cancel_and_dispatch_preserve_terminal_state(services):
    store, commands, plans = services
    saved = create(plans)
    assert commands.execute("MAINTAINER", "boss.simulation.clock.advance", {
        "client_request_id": "concurrent-plan-clock", "at": "2026-10-30T09:00:00+08:00",
    })[0] == 200
    with ThreadPoolExecutor(max_workers=2) as executor:
        canceled = executor.submit(plans.execute, "BOSS", "cancel", {
            "client_request_id": "concurrent-plan-cancel", "plan_id": saved["plan_id"], "expected_version": "1",
        })
        dispatched = executor.submit(store.dispatch_due, "ui-check")
        assert canceled.result()["state"] == "CANCELED"
        assert dispatched.result()
    assert store.dispatch_due("ui-check")[0]["reason"] == "OWNER_PLAN_CANCELED"
    assert len(plans.read("BOSS")["results"]) <= 1
