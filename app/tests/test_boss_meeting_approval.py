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


def test_today_tracks_current_application_state(services):
    from boss_today import TodayAPI
    api, pages = services
    assert api.execute("MAINTAINER", "boss.simulation.application.seed", seed_input())[0] == 200
    today = TodayAPI(api.store)
    assert any(item["object_id"] == "application-1" and item["category"] == "DECIDE" for item in today.read("BOSS")["items"])
    assert api.execute("BOSS", "boss.approval.decide", decide_input())[0] == 200
    assert not any(item["object_id"] == "application-1" for item in today.read("BOSS")["items"])


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
    })[0]==410
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
    status, history = reads.serve("BOSS", "/api/boss/ui/owner/decisions")
    assert status == 200, history
    record = next(row for row in history["records"] if row["authorization_id"] == out["authorization_id"])
    assert record["original_records"][0]["version"] == "1"
    assert record["original_records"][0]["content"] == "\n".join(row["text"] for row in minutes_input()["entries"])
    assert record["sources"][0]["source_id"] == "meeting-minutes" and record["sources"][0]["version"] == "1"
    assert "历史会议纪要" in record["sources"][0]["content"]
    with api.store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind='task'").fetchone()[0]==0
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind='outbox'").fetchone()[0]==0


def test_owner_decision_retains_original_attachment_after_revision(services):
    api, pages = services
    original = seed_input()
    assert api.execute("MAINTAINER", "boss.simulation.application.seed", original)[0] == 200
    status, decision = api.execute("BOSS", "boss.approval.decide", decide_input(decision="REQUEST_MORE"))
    assert status == 200, decision
    revised = {**seed_input("revise-history-source"), "expected_version": "2",
               "attachment_text": "SIMULATED：申请人补充当前报价说明，保留此前附件与本人决定供历史查询。"}
    status, result = api.execute("MAINTAINER", "boss.simulation.application.revise", revised)
    assert status == 200, result
    before = api.store.path.read_bytes()
    status, history = pages.serve("BOSS", "/api/boss/ui/owner/decisions")
    assert status == 200, history
    record = next(row for row in history["records"] if row["authorization_id"] == decision["authorization_id"])
    assert record["original_records"][0]["decision"] == "REQUEST_MORE"
    assert record["original_records"][0]["content"] == decide_input()["comment"]
    source = record["sources"][0]
    assert source["version"] == "1" and source["state"] == "HISTORICAL_VERSION"
    assert source["content"] == original["attachment_text"]
    assert source["current_evidence_eligible"] is False
    assert api.store.path.read_bytes() == before
    assert pages.serve("MAINTAINER", "/api/boss/ui/owner/decisions")[0] == 403


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
    maint=view(reads,"MAINTAINER","approval-admin")[1]
    assert maint["private_decision_comments_returned"] is False
    assert "本人已对照当前附件版本核查" not in json.dumps(maint)
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
        key="bad-approve-withdrawn"))[0]==410
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
    assert public["private_decision_comments_returned"] is False
    assert "本人已对照当前附件版本核查" not in json.dumps(public)
    assert "entries" not in json.dumps(public)


def test_request_more_revise_and_owner_reapprove_complete_a_real_version_chain(services):
    api, reads = services
    first = run(api, "MAINTAINER", "boss.simulation.application.seed", seed_input())
    assert first[0] == 200
    requested = run(api, "BOSS", "boss.approval.decide", decide_input(
        key="boss-request-more-101",
        decision="REQUEST_MORE",
        comment="请补充对应报价证明与适用范围",
    ))
    assert requested[0] == 200 and requested[1]["state"] == "WAITING_MATERIAL"

    revised = {
        "client_request_id": "maint-revise-app-101",
        "application_id": "application-1",
        "expected_version": "2",
        "applicant_contact_id": "finance-1",
        "amount_cny": "4200.00",
        "title": "合成内部采购审批申请（补充件）",
        "description": "模拟申请人明确更新金额与对应附件。",
        "attachment_text": "模拟申请新版本附件：新报价为4200元，设备数量和材料日期均由维护端显式输入，不代表真实采购。",
    }
    assert run(api, "BOSS", "boss.simulation.application.revise", revised)[0] == 403
    code, new_version = run(api, "MAINTAINER",
        "boss.simulation.application.revise", revised)
    assert code == 200, new_version
    assert new_version["version"] == "3"
    assert new_version["source_version"] == "2"
    assert new_version["state"] == "PENDING_DECISION"
    assert new_version["funds_transferred"] is False
    assert new_version["owner_authorization_created"] is False
    assert run(api, "MAINTAINER", "boss.simulation.application.revise",
               revised) == (code, new_version)
    assert run(api, "MAINTAINER", "boss.simulation.application.revise",
               {**revised, "client_request_id": "maint-repeat-revision"})[0] == 409

    assert run(api, "BOSS", "boss.approval.decide", decide_input(
        key="old-approval-should-fail"))[0] == 409
    assert run(api, "BOSS", "boss.approval.decide", decide_input(
        key="old-amount-fail", expected_version="3", source_version="2"))[0] == 409

    current=decide_input(key="owner-approve-updated", expected_version="3",
                         source_version="2", amount="4200.00")
    status, approved=run(api, "BOSS", "boss.approval.decide", current)
    assert status==200,approved
    assert approved["state"]=="APPROVED_RECORDED"
    assert approved["funds_transferred"] is False
    _, view_state=view(reads, "BOSS", "approvals")
    assert view_state["applications"][0]["version"]=="4"
    assert view_state["applications"][0]["amount"]=="4200.00"
    assert len(view_state["decisions"])==2
    with api.store.connect() as db:
        assert db.execute(
            "SELECT COUNT(*) FROM objects WHERE kind='document_revision'"
        ).fetchone()[0]==1
        assert db.execute(
            "SELECT COUNT(*) FROM objects WHERE kind='application_revision'"
        ).fetchone()[0]>=2
    c, evidence=reads.serve("BOSS","/api/boss/ui/evidence",
                           "source=application-1-attachment")
    assert c==200 and evidence["version"]=="2"
    assert "4200" in evidence["content"]


def test_revise_rejects_missing_owner_request_and_bad_contact(services):
    api, _ = services
    assert run(api, "MAINTAINER", "boss.simulation.application.seed",
               seed_input())[0]==200
    payload={
        "client_request_id":"maint-revise-no-request",
        "application_id":"application-1","expected_version":"1",
        "applicant_contact_id":"finance-1","amount_cny":"500.00",
        "title":"合成申请更新","description":"尚未经老板请求补充",
        "attachment_text":"测试申请附件：目前没有收到本人请求补充的意见。",
    }
    assert run(api, "MAINTAINER", "boss.simulation.application.revise",
               payload)[0]==409
    assert run(api, "BOSS", "boss.approval.decide", decide_input(
        key="request-more-first",decision="REQUEST_MORE"))[0]==200
    assert run(api, "MAINTAINER", "boss.simulation.application.revise",
               {**payload,"client_request_id":"bad-contact-revision",
                "expected_version":"2","applicant_contact_id":"coordinator-1"})[0]==400
    assert run(api, "MAINTAINER", "boss.simulation.application.revise",
               {**payload,"client_request_id":"bad-version-revision",
                "expected_version":"1"})[0]==409


def minute_assignment_input(key="from-minutes-task-001", **overrides):
    return {
        "client_request_id": key,
        "meeting_id": "meeting-1",
        "minute_version": "2",
        "entry_id": "entry-04",
        "purpose": "根据已确认纪要核对经营材料与差异",
        "coordinator_id": "coordinator-1",
        "due_at": "2026-10-24T17:00:00+08:00",
        "timezone": "Asia/Shanghai",
        "evidence_requirements": ["经营原始明细与结论依据"],
        **overrides,
    }


def confirmed_minute(services):
    api, _ = services
    assert run(api, "BOSS", "boss.minutes.save", minutes_input())[0] == 200
    confirmed = {
        "client_request_id": "minute-confirm-link",
        "meeting_id": "meeting-1", "expected_version": "1",
        "source_id": "meeting-minutes", "source_version": "1",
    }
    assert run(api, "BOSS", "boss.minutes.confirm", confirmed)[0] == 200
    return api


def test_confirmed_minute_entry_creates_one_traceable_open_task_without_send(services):
    api, reads = services
    confirmed_minute(services)
    result = run(api, "BOSS", "boss.minutes.assignment.create",
                 minute_assignment_input())
    assert result[0] == 200, result
    created = result[1]
    assert created["status"] == "OPEN"
    assert created["minute_version"] == "2"
    assert created["entry_id"] == "entry-04"
    assert not created["message_sent"]
    assert created["independent_send_required"]
    assert run(api, "BOSS", "boss.minutes.assignment.create",
               minute_assignment_input()) == result
    with api.store.connect() as db:
        task = api.store.get(db, "ui-check", "task", created["task_id"])
        assert task["origin_minute_id"] == "minutes:meeting-1"
        assert task["origin_minute_version"] == "2"
        assert task["origin_entry_id"] == "entry-04"
        assert task["origin_source_id"] == "meeting-minutes"
        assert task["origin_source_version"] == "1"
        assert task["message_ids"] == []
        assert db.execute(
            "SELECT COUNT(*) FROM objects WHERE kind='minutes_assignment_link'"
        ).fetchone()[0] == 1
        assert db.execute(
            "SELECT COUNT(*) FROM objects WHERE kind='outbox'"
        ).fetchone()[0] == 0
    _, minutes = view(reads, "BOSS", "minutes")
    linked = minutes["linked_assignments"]
    assert len(linked) == 1 and linked[0]["task_id"] == created["task_id"]
    assert linked[0]["task_status"] == "OPEN"
    assert linked[0]["send_status"] == "NOT_SENT"
    assert linked[0]["sent_message_count"] == 0
    assert minutes["task_created_by_minutes"] is True
    assert minutes["message_sent_by_minutes"] is False
    _, tasks = reads.serve("BOSS", "/api/boss/ui/tasks")
    task_read = next(t for t in tasks["tasks"] if t["task_id"] == created["task_id"])
    assert task_read["origin_minute_id"] == "minutes:meeting-1"
    assert task_read["origin_entry_id"] == "entry-04"


def test_linked_minute_requires_separate_boss_send_and_reads_consistent_state(services):
    api, reads = services
    confirmed_minute(services)
    created = run(api, "BOSS", "boss.minutes.assignment.create",
                  minute_assignment_input())[1]
    message = run(api, "BOSS", "boss.assignment.send", {
        "client_request_id": "send-minute-assignment-001",
        "task_id": created["task_id"], "task_version": created["version"],
        "recipient_id": "coordinator-1",
        "body": "请核对已确认纪要提及的业务资料", "content_version": "1",
    })
    assert message[0] == 200, message
    _, minutes = view(reads, "BOSS", "minutes")
    link = minutes["linked_assignments"][0]
    assert link["task_status"] == "WAITING_FEEDBACK"
    assert link["send_status"] == "SENT_SIMULATED"
    assert link["sent_message_count"] == 1
    assert minutes["message_sent_by_minutes"] is True
    _, tasks = reads.serve("BOSS", "/api/boss/ui/tasks")
    task = next(t for t in tasks["tasks"] if t["task_id"] == created["task_id"])
    assert task["status"] == "WAITING_FEEDBACK"
    assert len(task["message_ids"]) == 1


@pytest.mark.parametrize(("corrupt", "expected"), [
    ({"entry_id": "entry-01"}, 400),
    ({"entry_id": "entry-99"}, 400),
    ({"minute_version": "1"}, 409),
    ({"meeting_id": "another-meeting"}, 400),
    ({"coordinator_id": "finance-1"}, 400),
])
def test_minute_assignment_rejects_wrong_entry_role_version_and_contact(
        services, corrupt, expected):
    api, _ = services
    confirmed_minute(services)
    result = run(api, "BOSS", "boss.minutes.assignment.create",
                 minute_assignment_input(key="bad-link-" + next(iter(corrupt)), **corrupt))
    assert result[0] == expected, result
    with api.store.connect() as db:
        assert db.execute(
            "SELECT COUNT(*) FROM objects WHERE kind='task'"
        ).fetchone()[0] == 0
        assert db.execute(
            "SELECT COUNT(*) FROM objects WHERE kind='minutes_assignment_link'"
        ).fetchone()[0] == 0


def test_minute_assignment_requires_owner_confirmation_and_is_not_maintainer_action(services):
    api, _ = services
    assert run(api, "BOSS", "boss.minutes.assignment.create",
               minute_assignment_input())[0] == 404
    assert run(api, "BOSS", "boss.minutes.save", minutes_input())[0] == 200
    assert run(api, "BOSS", "boss.minutes.assignment.create",
               minute_assignment_input())[0] == 409
    confirmed_minute_after_save = {
        "client_request_id": "confirm-existing-minute",
        "meeting_id": "meeting-1", "expected_version": "1",
        "source_id": "meeting-minutes", "source_version": "1",
    }
    assert run(api, "BOSS", "boss.minutes.confirm", confirmed_minute_after_save)[0] == 200
    assert run(api, "MAINTAINER", "boss.minutes.assignment.create",
               minute_assignment_input())[0] == 403


def test_duplicate_minute_entry_with_new_request_key_cannot_create_second_task(services):
    api, _ = services
    confirmed_minute(services)
    assert run(api, "BOSS", "boss.minutes.assignment.create",
               minute_assignment_input())[0] == 200
    assert run(api, "BOSS", "boss.minutes.assignment.create",
               minute_assignment_input(key="second-request-for-same-entry"))[0] == 409
    with api.store.connect() as db:
        assert db.execute(
            "SELECT COUNT(*) FROM objects WHERE kind='task'"
        ).fetchone()[0] == 1


def test_withdrawn_minutes_source_blocks_new_linked_task(services):
    api, reads = services
    confirmed_minute(services)
    api.store.control("ui-check", "withdraw", {
        "source_id": "meeting-minutes", "version": "1",
    })
    assert run(api, "BOSS", "boss.minutes.assignment.create",
               minute_assignment_input())[0] == 410
    _, minutes = view(reads, "BOSS", "minutes")
    assert minutes["minute"]["source_reference_state"] == "NEEDS_REVIEW"
    assert not minutes["linked_assignments"]
    with api.store.connect() as db:
        assert db.execute(
            "SELECT COUNT(*) FROM objects WHERE kind='task'"
        ).fetchone()[0] == 0
