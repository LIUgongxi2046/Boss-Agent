"""PRD AC-04/05/06/08/09 cross-page business process integration.

All steps execute *actual* SQLite transactions through the authenticated
command API and role-scoped readers with the fixed approved SIMULATED fixture.
No live AI, external delivery, or Mac browser execution is claimed.
"""
import json
import sys
from pathlib import Path

import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"validation"))
from boss_command_api import BossCommandAPI
from boss_page_api import BossPageAPI
from controls import ControlStore


@pytest.fixture
def scenario(tmp_path):
    store=ControlStore(tmp_path/"full-owner-flow.sqlite")
    store.initialize("ui-check")
    return BossCommandAPI(store),BossPageAPI(store)


def execute(cmd,role,action,key,**payload):
    code,result=cmd.execute(role,action,{"client_request_id":key,**payload})
    assert code==200, (role,action,code,result)
    return result


def read(page,key,role="BOSS"):
    code,body=page.serve(role,"/api/boss/ui/workspace/"+key)
    assert code==200,(key,code,body)
    return body


def test_f04_f05_f06_f08_f09_owner_flow_is_persisted_and_not_autosent(scenario):
    cmd,page=scenario

    # F04: meeting/source snapshot, no automatic meeting or notification.
    brief=execute(cmd,"BOSS","boss.meeting.brief.prepare","e2e-brief-001",
        meeting_id="meeting-1",meeting_version="1",expected_version="0")
    assert brief["state"]=="READY_FOR_REVIEW"
    assert brief["message_sent"] is False
    assert read(page,"briefing")["saved_brief"]["version"]=="1"

    # F09: source-scoped question. Quotes are sources, NOT confirmed facts.
    study=execute(cmd,"BOSS","boss.research.prepare","e2e-research-001",
        expected_version="0",question="毛利率",
        period="2026-10",country="",business_relation="经营变化核查",
        cutoff_date="2026-10-22")
    assert study["state"]=="SOURCE_REVIEW_REQUIRED"
    research=read(page,"research")["report"]
    assert research["matched_sources"][0]["source_id"]=="finance-note"
    assert research["facts_confirmed"]==[]
    assert research["model_inferences"]==[]
    assert research["external_message_sent"] is False

    # F05: separate draft save and confirmation, never a side-effectful task.
    minutes=execute(cmd,"BOSS","boss.minutes.save","e2e-minutes-save-001",
        meeting_id="meeting-1",meeting_version="1",
        source_id="meeting-minutes",source_version="1",expected_version="0",
        entries=[
            {"kind":"OPINION","text":"该材料仍在讨论中，没有本人执行授权",
             "source_anchor":"历史会议纪要"},
            {"kind":"ASSIGNMENT_DRAFT",
             "text":"请负责人核查已关联经营事项的原始明细",
             "source_anchor":"coordinator-1"},
        ])
    assert minutes["tasks_created"]==0
    assert minutes["messages_sent"]==0
    confirmed=execute(cmd,"BOSS","boss.minutes.confirm","e2e-minutes-confirm-001",
        meeting_id="meeting-1",expected_version="1",
        source_id="meeting-minutes",source_version="1")
    assert confirmed["state"]=="CONFIRMED"
    assert confirmed["tasks_created"]==0

    # F05 -> F06: owner separately creates exactly ONE linked task.
    linked=execute(cmd,"BOSS","boss.minutes.assignment.create","e2e-link-001",
        meeting_id="meeting-1",minute_version="2",entry_id="entry-02",
        purpose="核查关联经营原始明细与证明",
        coordinator_id="coordinator-1",
        due_at="2026-10-24T17:00:00+08:00",timezone="Asia/Shanghai",
        evidence_requirements=["经营原始明细"])
    assert linked["status"]=="OPEN"
    assert linked["message_sent"] is False
    task_id=linked["task_id"]
    details=read(page,"minutes")
    assert details["linked_assignments"][0]["task_id"]==task_id
    assert details["message_sent_by_minutes"] is False
    assert cmd.execute("BOSS","boss.minutes.assignment.create",{
        "client_request_id":"e2e-new-intent-same-entry",
        "meeting_id":"meeting-1","minute_version":"2","entry_id":"entry-02",
        "purpose":"重试同一个已创建的原文条目",
        "coordinator_id":"coordinator-1","due_at":"2026-10-24T17:00:00+08:00",
        "timezone":"Asia/Shanghai","evidence_requirements":["经营原始明细"],
    })[0]==409

    # F06 must independently authorize a send before any F08 linked message.
    sent=execute(cmd,"BOSS","boss.assignment.send","e2e-assign-send-001",
        task_id=task_id,task_version="1",recipient_id="coordinator-1",
        body="请核实原始明细后汇报结果",content_version="1")
    assert sent["task_status"]=="WAITING_FEEDBACK"
    again=read(page,"minutes")
    assert again["linked_assignments"][0]["send_status"]=="SENT_SIMULATED"
    assert again["linked_assignments"][0]["task_status"]=="WAITING_FEEDBACK"

    # F08: save first, then send via stable contact and exact SHA.
    draft=execute(cmd,"BOSS","boss.message.draft.save","e2e-followup-draft-001",
        draft_id=None,expected_version="0",recipient_id="coordinator-1",
        related_task_id=task_id,body="请更新本次经营核查的进展",
        attachment_refs=[],visibility="RECIPIENT_ONLY")
    assert draft["message_sent"] is False
    saved=next(x for x in read(page,"outbox")["drafts"]
               if x["draft_id"]==draft["draft_id"])
    message=execute(cmd,"BOSS","boss.message.send","e2e-followup-send-001",
        draft_id=saved["draft_id"],expected_version=saved["version"],
        recipient_id=saved["recipient_id"],
        expected_content_sha256=saved["content_sha256"])
    assert message["delivery_state"]=="NOT_VERIFIED"
    assert message["external_channel_invoked"] is False
    reply=execute(cmd,"MAINTAINER","boss.simulation.message.reply",
        "e2e-contact-reply-001",message_id=message["message_id"],
        author_contact_id="coordinator-1",
        text="模拟反馈：核查进行中，尚未形成可确认结果")
    assert reply["task_status_after_reply"]=="IN_PROGRESS"
    assert reply["task_completion_confirmed"] is False

    # Genuine result submission (with approved reference) is different from
    # OWNER acknowledgement of completion.
    current=next(x for x in page.serve("BOSS","/api/boss/ui/tasks")[1]["tasks"]
                 if x["task_id"]==task_id)
    result=execute(cmd,"MAINTAINER","boss.simulation.feedback",
        "e2e-submit-result-001",task_id=task_id,task_version=current["version"],
        author_contact_id="coordinator-1",kind="RESULT_SUBMITTED",
        content="提交核查结果及获准财务原始证明",
        evidence_refs=["finance-note"])
    assert result["task"]["status"]=="RESULT_SUBMITTED"
    completed=execute(cmd,"BOSS","boss.assignment.complete","e2e-owner-confirm-001",
        task_id=task_id,task_version=result["task"]["version"],
        feedback_id=result["feedback_id"])
    assert completed["status"]=="COMPLETED_CONFIRMED"
    after=page.serve("BOSS","/api/boss/ui/tasks")[1]
    assert after["tasks"][0]["status"]=="COMPLETED_CONFIRMED"
    assert read(page,"minutes")["linked_assignments"][0]["task_status"]=="COMPLETED_CONFIRMED"
    assert read(page,"briefing")["current_status"]=="NEEDS_REVIEW"
    assert read(page,"research")["report"]["published_conclusions"] is False

    # Every artifact remains traceable in the same underlying SQLite store.
    with cmd.store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind='task'").fetchone()[0]==1
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind='minutes_assignment_link'").fetchone()[0]==1
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind='message_outbox'").fetchone()[0]==1
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind='outbox'").fetchone()[0]==1
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind='research'").fetchone()[0]==1
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind='meeting_brief'").fetchone()[0]==1
