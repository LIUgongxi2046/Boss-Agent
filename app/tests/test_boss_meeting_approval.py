"""SQLite integration of PRD FR-05 meeting minutes / FR-07 approval decisions.

No external messages, financial transfers or provider credentials are used.
Tests cover role, document/version staleness, classifications, source revocation,
transactional idempotency and separation of real task-send operations.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"validation"))
from boss_command_api import BossCommandAPI  # noqa: E402
from boss_page_api import BossPageAPI  # noqa: E402
from controls import ControlStore  # noqa: E402


@pytest.fixture
def services(tmp_path):
    store=ControlStore(tmp_path/"minutes-approval.sqlite")
    store.initialize("ui-check")
    return BossCommandAPI(store),BossPageAPI(store)


def minutes_input(key="save-minutes-001",expected_version="0"):
    return {
        "client_request_id":key,
        "meeting_id":"meeting-1","meeting_version":"1",
        "source_id":"meeting-minutes","source_version":"1",
        "expected_version":expected_version,
        "entries":[
            {"kind":"OPINION","text":"资料作者说明尚有争议","source_anchor":"历史会议纪要"},
            {"kind":"SUGGESTION","text":"建议补齐经营明细","source_anchor":"经营原始明细"},
            {"kind":"DECISION","text":"本人要求核查证据后才考虑关闭事项","source_anchor":"尚未收到本人完成决定"},
            {"kind":"ASSIGNMENT_DRAFT","text":"候选交办，负责人和期限须单独确认","source_anchor":"coordinator-1"},
        ],
    }


def seed_input(key="maint-seed-app-001",amount="3000.00",**rest):
    return {
        "client_request_id":key,"application_id":"application-1",
        "applicant_contact_id":"finance-1","amount_cny":amount,
        "title":"合成内部采购审批申请","description":"模拟试用申请，需要老板核查附件与金额",
        "attachment_text":"模拟申请附件：拟采购设备及报价项目，附件仅供当前演示审批，不涉及实际采购或付款。",
        **rest,
    }


def decide_input(key="boss-approve-001",decision="APPROVE",**rest):
    return {
        "client_request_id":key, "application_id":"application-1",
        "expected_version":"1", "source_id":"application-1-attachment",
        "source_version":"1","amount":"3000.00","currency":"CNY",
        "decision":decision,"comment":"本人已对照当前附件版本核查",
        **rest,
    }


def run(api,role,action,payload):
    return api.execute(role,action,payload)


def view(projection,role,page):
    return projection.serve(role,"/api/boss/ui/workspace/"+page)


def test_meeting_draft_contains_classifications_but_no_decision_or_task(services):
    api,reads=services
    code,out=run(api,"BOSS","boss.minutes.save",minutes_input())
    assert code==200,out
    assert out["state"]=="DRAFT_REVIEW" and out["entry_count"]==4
    assert out["decision_count_confirmed"]==0
    assert out["tasks_created"]==0 and out["messages_sent"]==0
    assert view(reads,"MAINTAINER","minutes")[0]==403
    status,content=view(reads,"BOSS","minutes")
    assert status==200
    assert [item["kind"] for item in content["minute"]["entries"]]==[
        "OPINION","SUGGESTION","DECISION","ASSIGNMENT_DRAFT",
    ]
    assert content["minute"]["state"]=="DRAFT_REVIEW"
    with api.store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind='task'").fetchone()[0]==0
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind='outbox'").fetchone()[0]==0


def test_minutes_save_idempotent_and_stale_source_rejected(services):
    api,reads=services
    payload=minutes_input()
    first=run(api,"BOSS","boss.minutes.save",payload)
    assert first[0]==200
    assert run(api,"BOSS","boss.minutes.save",payload)==first
    assert run(api,"BOSS","boss.minutes.save",minutes_input(
        key="save-minutes-002",expected_version="0"))[0]==409
    changed=minutes_input()
    changed["entries"][0]["text"]="同一幂等编号但内容被修改"
    assert run(api,"BOSS","boss.minutes.save",changed)[0]==409
    revoked=api.store.control("ui-check","withdraw",
                               {"source_id":"meeting-minutes","version":"1"})
    assert revoked["withdrawn"]
    assert run(api,"BOSS","boss.minutes.confirm",{
        "client_request_id":"confirm-after-withdraw",
        "meeting_id":"meeting-1","expected_version":"1",
        "source_id":"meeting-minutes","source_version":"1",
    })[0]==403
    assert view(reads,"BOSS","minutes")[1]["minute"]["state"]=="DRAFT_REVIEW"


def test_minutes_reject_fabricated_source_anchor_and_unknown_meeting(services):
    api,_=services
    fake=minutes_input("bad-position-001")
    fake["entries"][0]["source_anchor"]="这个位置在模拟原文中不存在"
    assert run(api,"BOSS","boss.minutes.save",fake)[0]==400
    fake=minutes_input("bad-meeting-001")
    fake["meeting_id"]="meeting-999"
    assert run(api,"BOSS","boss.minutes.save",fake)[0]==409
    assert run(api,"MAINTAINER","boss.minutes.save",minutes_input())[0]==403


def test_minutes_confirm_produces_separate_authorization_and_snapshots(services):
    api,reads=services
    assert run(api,"BOSS","boss.minutes.save",minutes_input())[0]==200
    confirmation={
        "client_request_id":"confirm-minutes-001",
        "meeting_id":"meeting-1","expected_version":"1",
        "source_id":"meeting-minutes","source_version":"1",
    }
    code,out=run(api,"BOSS","boss.minutes.confirm",confirmation)
    assert code==200,out
    assert out["state"]=="CONFIRMED" and out["version"]=="2"
    assert out["decision_count_confirmed"]==1
    assert out["tasks_created"]==out["messages_sent"]==0
    assert run(api,"BOSS","boss.minutes.confirm",confirmation)==(code,out)
    assert run(api,"BOSS","boss.minutes.confirm",{
        **confirmation,"client_request_id":"confirm-minutes-stale"
    })[0]==409
    saved=view(reads,"BOSS","minutes")[1]
    assert saved["minute"]["confirmation_authorization_id"]==out["authorization_id"]
    assert any(row["version"]=="1" for row in saved["revisions"])
    with api.store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind='task'").fetchone()[0]==0
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind='outbox'").fetchone()[0]==0


def test_application_does_not_exist_before_maintenance_simulation(services):
    api,reads=services
    code,overview=view(reads,"BOSS","approvals")
    assert code==200
    assert overview["applications"]==[]
    assert run(api,"BOSS","boss.simulation.application.seed",seed_input())[0]==403
    assert run(api,"MAINTAINER","boss.approval.decide",decide_input())[0]==403
    assert run(api,"BOSS","boss.approval.decide",decide_input())[0]==404


def test_seed_application_creates_only_simulated_record_and_versioned_attachment(services):
    api,reads=services
    req=seed_input()
    first=run(api,"MAINTAINER","boss.simulation.application.seed",req)
    assert first[0]==200,first
    assert first[1]["funds_transferred"] is False
    assert first[1]["owner_authorization_created"] is False
    assert run(api,"MAINTAINER","boss.simulation.application.seed",req)==first
    assert run(api,"MAINTAINER","boss.simulation.application.seed",seed_input(
        key="maint-app-other-seed"))[0]==409
    owner=view(reads,"BOSS","approvals")[1]
    application=owner["applications"][0]
    assert application["state"]=="PENDING_DECISION"
    assert application["amount"]=="3000.00" and application["currency"]=="CNY"
    assert application["attachment_status"]=="CURRENT"
    source_code,source=reads.serve("BOSS","/api/boss/ui/evidence",
                                 "source=application-1-attachment")
    assert source_code==200
    assert source["source_type"]=="SIMULATED"
    assert "模拟申请附件" in source["content"]
    assert reads.serve("MAINTAINER","/api/boss/ui/evidence",
                       "source=application-1-attachment")[0]==403
    admin=view(reads,"MAINTAINER","approval-admin")[1]
    assert "attachment_text" not in json.dumps(admin)
    assert "description" not in json.dumps(admin)
    assert "owner_authorization_created" not in json.dumps(admin)
    with api.store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind='authorization'").fetchone()[0]==0
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind='outbox'").fetchone()[0]==0


@pytest.mark.parametrize("value",["0","-1","1e3","abc","1.234","NaN",""])
def test_invalid_application_amount_rejected_without_side_effect(services,value):
    api,_=services
    status,_=run(api,"MAINTAINER","boss.simulation.application.seed",
                 seed_input("bad-amount-seed",amount=value))
    assert status==400
    with api.store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind='application'").fetchone()[0]==0


def test_application_draft_is_authorized_only_by_owner_and_never_transfers_funds(services):
    api,reads=services
    run(api,"MAINTAINER","boss.simulation.application.seed",seed_input())
    payload=decide_input()
    code,decision=run(api,"BOSS","boss.approval.decide",payload)
    assert code==200,decision
    assert decision["state"]=="APPROVED_RECORDED"
    assert decision["funds_transferred"] is False
    assert decision["professional_release_issued"] is False
    assert run(api,"BOSS","boss.approval.decide",payload)==(code,decision)
    assert run(api,"BOSS","boss.approval.decide",decide_input(
        key="new-decision-id",decision="REJECT"))[0]==409
    after=view(reads,"BOSS","approvals")[1]
    assert after["applications"][0]["state"]=="APPROVED_RECORDED"
    assert after["decisions"][0]["authorization_id"]==decision["authorization_id"]
    assert "comment" not in json.dumps(view(reads,"MAINTAINER","approval-admin")[1])
    with api.store.connect() as db:
        auths=db.execute("SELECT body FROM objects WHERE kind='authorization'").fetchall()
        assert len(auths)==1
        assert "本人已对照当前附件版本核查" not in auths[0][0]


def test_application_amount_or_attachment_conflict_rejected_before_authorization(services):
    api,reads=services
    run(api,"MAINTAINER","boss.simulation.application.seed",seed_input())
    for i,changed in enumerate([
        {"amount":"3001.00"},{"currency":"USD"},{"source_version":"2"},
        {"expected_version":"0"},{"source_id":"finance-note"},
        {"decision":"TRANSFER_FUNDS"},
    ]):
        code,_=run(api,"BOSS","boss.approval.decide",decide_input(
            key=f"wrong-version-{i}",**changed))
        assert code in (400,409),changed
    with api.store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind='authorization'").fetchone()[0]==0
    assert view(reads,"BOSS","approvals")[1]["decisions"]==[]


def test_withdrawn_application_attachment_blocks_approve_but_can_request_more(services):
    api,reads=services
    run(api,"MAINTAINER","boss.simulation.application.seed",seed_input())
    assert api.store.control("ui-check","withdraw",{
        "source_id":"application-1-attachment","version":"1",
    })["withdrawn"] is True
    assert run(api,"BOSS","boss.approval.decide",decide_input(
        key="bad-approve-withdrawn"))[0]==403
    more=run(api,"BOSS","boss.approval.decide",decide_input(
        key="more-after-withdrawn",decision="REQUEST_MORE",
        comment="附件已撤销，请提供当前有效证明"))
    assert more[0]==200,more
    assert more[1]["state"]=="WAITING_MATERIAL"
    assert more[1]["funds_transferred"] is False
    assert reads.serve("BOSS","/api/boss/ui/evidence",
                       "source=application-1-attachment")[0]==410
    with api.store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind='authorization'").fetchone()[0]==1


def test_maintainer_cannot_read_owner_minutes_or_approval_comments(services):
    api,reads=services
    run(api,"BOSS","boss.minutes.save",minutes_input())
    run(api,"MAINTAINER","boss.simulation.application.seed",seed_input())
    run(api,"BOSS","boss.approval.decide",decide_input())
    for path in ("minutes","approvals"):
        assert view(reads,"MAINTAINER",path)[0]==403
    public=view(reads,"MAINTAINER","approval-admin")[1]
    assert "comment" not in json.dumps(public)
    assert "entries" not in json.dumps(public)
