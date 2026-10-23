"""FR-28 / N10: owner revocation never undoes earlier business state.

These are SQLite role/CAS tests, not actual Mac UI or external delivery.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from datetime import datetime, timedelta, timezone

import pytest
from aiohttp import web

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"validation"))
from boss_command_api import BossCommandAPI
from boss_page_api import BossPageAPI
from controls import ControlStore
from business import initial_materials
from test_boss_command_api import create_input


@pytest.fixture
def app(tmp_path):
    store=ControlStore(tmp_path/"auth-revocation.sqlite")
    store.initialize("ui-check")
    return BossCommandAPI(store),BossPageAPI(store)


def call(api,role,action,key,**fields):
    return api.execute(role,action,{"client_request_id":key,**fields})


def create_authorization(api):
    code,result=call(api,"BOSS","boss.memory.confirm","owner-auth-memory-confirm",
                     expected_version="1",text="本次本人明确允许的合成设置")
    assert code==200,result
    return result["authorization_id"]


def read(pages,role="BOSS"):
    return pages.serve(role,"/api/boss/ui/workspace/authorizations")


def revoke_payload(identifier,version="1",reason="本人终止对未来该授权的继续使用"):
    return {
        "authorization_id":identifier,
        "expected_version":version,
        "reason":reason,
    }


def test_revocation_is_versioned_and_not_retroactive(app):
    cmd,pages=app
    identifier=create_authorization(cmd)
    before=read(pages)[1]["authorizations"]
    target=next(x for x in before if x["authorization_id"]==identifier)
    assert target["can_revoke"] and target["version"]=="1" and not target["revoked"]
    payload=revoke_payload(identifier)
    code,result=call(cmd,"BOSS","boss.authorization.revoke",
                     "owner-auth-revoke-current",**payload)
    assert code==200,result
    assert result["authorization_id"]==identifier
    assert result["version"]=="2"
    assert result["revoked"] is True
    assert result["future_authorization_use_blocked"] is True
    assert result["historical_business_actions_undone"] is False
    assert result["external_delivery_recalled"] is False
    assert result["revocation_authorization_id"] != identifier
    assert call(cmd,"BOSS","boss.authorization.revoke",
                "owner-auth-revoke-current",**payload)==(code,result)
    newer=next(x for x in read(pages)[1]["authorizations"]
               if x["authorization_id"]==identifier)
    assert newer["revoked"] is True and newer["version"]=="2"
    assert newer["can_revoke"] is False
    assert newer["revoked_at"]
    assert call(cmd,"BOSS","boss.authorization.revoke",
                "owner-auth-double-revoke",**revoke_payload(identifier,"2"))[0]==409
    with cmd.store.connect() as db:
        original=cmd.store.get(db,"ui-check","authorization",identifier)
        assert original["revoked"] is True
        assert original["revocation_authorization_id"]==result["revocation_authorization_id"]
        memory=cmd.store.get(db,"ui-check","memory","current")
        assert memory["confirmation_state"]=="CONFIRMED"
        assert memory["version"]=="2"  # past decision not undone
        stored=db.execute("SELECT result FROM idempotency WHERE operation='boss.authorization.revoke'").fetchall()
        assert len(stored)==1


def test_owner_only_and_no_foreign_or_unverified_permissions(app):
    cmd,pages=app
    identifier=create_authorization(cmd)
    payload=revoke_payload(identifier)
    assert call(cmd,"MAINTAINER","boss.authorization.revoke","maint-revoke-denied",
                **payload)[0]==403
    assert call(cmd,"OTHER","boss.authorization.revoke","unknown-role-denied",
                **payload)[0]==401
    assert read(pages,"MAINTAINER")[0]==403
    assert read(pages,"ANONYMOUS")[0]==401
    assert call(cmd,"BOSS","boss.authorization.revoke","forged-overrides",
                **{**payload,"owner_id":"other-person"})[0]==400
    assert call(cmd,"BOSS","boss.authorization.revoke","wrong-version",
                **revoke_payload(identifier,version="0"))[0]==409
    assert call(cmd,"BOSS","boss.authorization.revoke","unknown-authorization",
                **revoke_payload("missing-authorization"))[0]==404
    with cmd.store.connect() as db:
        current=cmd.store.get(db,"ui-check","authorization",identifier)
        assert current["revoked"] is False


def test_expired_single_action_authorization_cannot_be_revoked_with_false_success(app):
    cmd,pages=app
    status, task = cmd.execute("BOSS", "boss.assignment.create", create_input())
    assert status == 200
    identifier = task["authorization_id"]
    with cmd.store.connect() as db:
        current=cmd.store.get(db,"ui-check","authorization",identifier)
        current["valid_until"]=(datetime.now(timezone.utc)-timedelta(minutes=1)).isoformat()
        cmd.store.put(db,"ui-check","authorization",identifier,current)
    record=next(x for x in read(pages)[1]["authorizations"]
                if x["authorization_id"]==identifier)
    assert not record["can_revoke"]
    assert call(cmd,"BOSS","boss.authorization.revoke","expired-revocation",
                **revoke_payload(identifier))[0]==409


@pytest.mark.parametrize("kind", ["memory", "goals", "notice", "plan", "plan_resume", "share"])
def test_continuing_use_can_be_revoked_after_confirmation_window(app, kind):
    from test_boss_owner_preferences import goals, notice, confirm_input
    from test_boss_owner_plans import create
    from boss_owner_plans import OwnerPlansAPI
    cmd, _ = app
    if kind == "memory":
        status, authorized = call(cmd, "BOSS", "boss.memory.confirm", "continuing-memory-confirm", expected_version="1", text=initial_materials()["memory"]["text"])
        assert status == 200
    elif kind in ("goals", "notice"):
        status, draft = call(cmd, "BOSS", "boss.owner." + kind + ".save", "continuing-setting-save", **(goals() if kind == "goals" else notice()))
        assert status == 200
        status, authorized = call(cmd, "BOSS", "boss.owner." + kind + ".confirm", "continuing-setting-confirm", **confirm_input(draft))
        assert status == 200
    elif kind in ("plan", "plan_resume"):
        assert call(cmd, "MAINTAINER", "boss.simulation.event.seed", "continuing-plan-event", event_id="event-1")[0] == 200
        plans = OwnerPlansAPI(cmd.store)
        authorized = create(plans)
        if kind == "plan_resume":
            paused = plans.execute("BOSS", "pause", {"client_request_id": "continuing-plan-pause", "plan_id": authorized["plan_id"], "expected_version": authorized["version"]})
            authorized = plans.execute("BOSS", "resume", {"client_request_id": "continuing-plan-resume", "plan_id": authorized["plan_id"], "expected_version": paused["version"]})
    else:
        assert kind == "share"
        status, authorized = call(cmd, "BOSS", "boss.calendar.share", "continuing-share-confirm", expected_version="1", recipient_id="coordinator-1",
            purpose=initial_materials()["memory"]["text"], expires_at=initial_materials()["private_calendar"]["ends_at"], fields=["busy", "starts_at", "ends_at", "timezone"])
        assert status == 200
    identifier = authorized["authorization_id"]
    with cmd.store.connect() as db:
        current = cmd.store.get(db, "ui-check", "authorization", identifier)
        current["valid_until"] = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
        cmd.store.put(db, "ui-check", "authorization", identifier, current)
    status, result = call(cmd, "BOSS", "boss.authorization.revoke", "continuing-use-revoke", **revoke_payload(identifier))
    assert status == 200, result
    assert result["revoked"] is True
    if kind == "memory":
        assert ControlStore(cmd.store.path).context("ui-check")["memory"] is None


def test_cross_owner_and_maintainer_issued_grants_cannot_be_revoked(app):
    cmd,pages=app
    identifier=create_authorization(cmd)
    with cmd.store.connect() as db:
        other=cmd.store.get(db,"ui-check","authorization",identifier)
        other.update(authorization_id="other-owner-auth",owner_id="boss-other")
        cmd.store.put(db,"ui-check","authorization","other-owner-auth",other)
        technical=dict(other)
        technical.update(authorization_id="technical-issued-auth",
                         owner_id="boss-1",issuer_identity="MAINTAINER")
        cmd.store.put(db,"ui-check","authorization","technical-issued-auth",technical)
    assert call(cmd,"BOSS","boss.authorization.revoke","other-owner-denied",
                **revoke_payload("other-owner-auth"))[0]==403
    assert call(cmd,"BOSS","boss.authorization.revoke","maint-issued-denied",
                **revoke_payload("technical-issued-auth"))[0]==403
    projection=read(pages)[1]["authorizations"]
    assert not any(x["can_revoke"] for x in projection
                   if x["authorization_id"] in ("other-owner-auth","technical-issued-auth"))


def test_reason_is_not_persisted_in_audit_or_authorization_metadata(app):
    cmd,pages=app
    identifier=create_authorization(cmd)
    private="私人理由，仅用于我本次撤销确认"
    code,_=call(cmd,"BOSS","boss.authorization.revoke","auth-private-reason",
                **revoke_payload(identifier,reason=private))
    assert code==200
    projected=read(pages)[1]
    assert private not in json.dumps(projected,ensure_ascii=False)
    with cmd.store.connect() as db:
        audit=db.execute("SELECT input,output FROM audit").fetchall()
        auth=db.execute("SELECT body FROM objects WHERE kind='authorization'").fetchall()
        receipts=db.execute("SELECT result FROM idempotency").fetchall()
    assert private not in str(audit)
    assert all(private not in row[0] for row in auth)
    assert all(private not in row[0] for row in receipts)
