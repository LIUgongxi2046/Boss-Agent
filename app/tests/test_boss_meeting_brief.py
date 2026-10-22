"""FR-04 meeting briefing integration with approved fixed data and versioning."""
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
def service(tmp_path):
    store=ControlStore(tmp_path/"brief.sqlite")
    store.initialize("ui-check")
    return BossCommandAPI(store),BossPageAPI(store)


def prepare(cmd,key="brief-prep-001",version="0"):
    return cmd.execute("BOSS","boss.meeting.brief.prepare",{
        "client_request_id":key,"meeting_id":"meeting-1",
        "meeting_version":"1","expected_version":version,
    })


def briefing(pages,role="BOSS"):
    return pages.serve(role,"/api/boss/ui/workspace/briefing")


def test_preparation_uses_real_sources_metrics_and_commitment(service):
    cmd,pages=service
    code,initial=briefing(pages)
    assert code==200 and not initial["saved"]
    assert initial["current_status"]=="NOT_PREPARED"
    assert [x["source_id"] for x in initial["current"]["sources"]]==[
        "finance-note","meeting-minutes"
    ]
    assert initial["current"]["commitments"][0]["task_id"]=="historical-1"
    assert initial["current"]["commitments"][0]["status"]=="IN_PROGRESS"
    metrics=initial["current"]["metrics"]
    assert metrics["available"]
    assert [x["metrics"]["revenue"]["value"] for x in metrics["values"]]==[
        "40000000","48000000"
    ]
    assert [x["metrics"]["gross_margin"]["value"] for x in metrics["values"]]==[
        "10.0","8.00"
    ]
    result=prepare(cmd)
    assert result[0]==200,result
    assert result[1]["state"]=="READY_FOR_REVIEW"
    assert result[1]["source_count"]==2
    assert result[1]["message_sent"] is False
    assert result[1]["meeting_occurred"] is False
    status,current=briefing(pages)
    assert status==200
    assert current["saved"] and current["current_status"]=="READY_FOR_REVIEW"
    assert current["saved_brief"]["version"]=="1"
    assert current["saved_brief"]["reviewed_by_owner"] is False
    with cmd.store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind='message_outbox'").fetchone()[0]==0
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind='task'").fetchone()[0]==0


def test_preparation_replay_cas_and_other_roles(service):
    cmd,pages=service
    assert cmd.execute("MAINTAINER","boss.meeting.brief.prepare",{
        "client_request_id":"maint-brief-001","meeting_id":"meeting-1",
        "meeting_version":"1","expected_version":"0"
    })[0]==403
    assert briefing(pages,"MAINTAINER")[0]==403
    first=prepare(cmd)
    assert prepare(cmd)==first
    assert prepare(cmd,"brief-other-key",version="0")[0]==409
    assert prepare(cmd,"brief-prep-001",version="1")[0]==409
    assert cmd.execute("BOSS","boss.meeting.brief.prepare",{
        "client_request_id":"brief-wrong-meeting","meeting_id":"other",
        "meeting_version":"1","expected_version":"1",
    })[0]==409


def test_source_withdrawn_keeps_history_but_invalidates_ready(service):
    cmd,pages=service
    assert prepare(cmd)[0]==200
    cmd.store.control("ui-check","withdraw",{"source_id":"finance-note","version":"1"})
    _,state=briefing(pages)
    assert state["saved_brief"]["state"]=="READY_FOR_REVIEW" # immutable historical snapshot
    assert state["current_status"]=="NEEDS_REVIEW"
    assert state["source_changed"]
    assert state["current"]["metrics"]["available"] is False
    assert "finance-note" in state["current"]["missing_items"]
    assert "metric:finance-note" in state["current"]["missing_items"]
    assert next(x for x in state["current"]["sources"]
                if x["source_id"]=="finance-note")["excerpt"] is None
    refreshed=prepare(cmd,"brief-regenerate-002",version="1")
    assert refreshed[0]==200
    assert refreshed[1]["state"]=="NEEDS_REVIEW"
    assert refreshed[1]["missing_count"]>=1
    _,updated=briefing(pages)
    assert updated["saved_brief"]["version"]=="2"
    assert updated["revisions"][0]["version"]=="1"


def test_task_progress_changes_live_brief_status_without_rewriting_history(service):
    cmd,pages=service
    assert prepare(cmd)[0]==200
    created=cmd.execute("BOSS","boss.assignment.create",{
        "client_request_id":"brief-related-task-001",
        "purpose":"会前核查原始经营资料",
        "coordinator_id":"coordinator-1","due_at":"2026-10-24T17:00:00+08:00",
        "timezone":"Asia/Shanghai","evidence_requirements":["经营原始明细"],
        "related_meeting_id":"meeting-1","related_event_ids":["event-1"],
        "source_refs":["finance-note"],"content_version":"1",
    })
    assert created[0]==200,created
    _,state=briefing(pages)
    assert state["current_status"]=="NEEDS_REVIEW"
    assert state["business_changed"]
    assert any(x["task_id"]==created[1]["task_id"]
               for x in state["current"]["commitments"])
    assert state["saved_brief"]["version"]=="1"


def test_authorized_source_and_contact_expiration_do_not_fabricate_readiness(service):
    cmd,pages=service
    advanced=cmd.execute("MAINTAINER","boss.simulation.clock.advance",{
        "client_request_id":"brief-clock-expired","at":"2027-02-01T09:00:00+08:00"
    })
    assert advanced[0]==200,advanced
    _,current=briefing(pages)
    assert current["current"]["needs_review"]
    assert "participant:coordinator-1" in current["current"]["missing_items"]
    assert prepare(cmd)[1]["state"]=="NEEDS_REVIEW"
    assert all(row["status"]=="EXPIRED" for row in current["current"]["participants"])



def test_f04_missing_material_request_becomes_f08_draft_not_sent(service):
    cmd,pages=service
    assert prepare(cmd)[0]==200
    cmd.store.control("ui-check","withdraw",{
        "source_id":"meeting-minutes","version":"1",
    })
    _,brief=briefing(pages)
    missing=brief["current"]["missing_items"]
    assert "meeting-minutes" in missing
    body=("关于会议 meeting-1，请补充以下待核查资料："+ "；".join(missing)
          +"。请说明有效来源版本和预计提供时间。")
    status,draft=cmd.execute("BOSS","boss.message.draft.save",{
        "client_request_id":"brief-request-draft-001",
        "draft_id":None,"expected_version":"0",
        "recipient_id":"coordinator-1","related_task_id":None,
        "body":body,"attachment_refs":[],
        "visibility":"RECIPIENT_ONLY",
    })
    assert status==200,draft
    assert draft["status"]=="DRAFT"
    assert draft["message_sent"] is False
    _,outbox=pages.serve("BOSS","/api/boss/ui/workspace/outbox")
    assert len(outbox["drafts"])==1
    assert outbox["drafts"][0]["recipient_id"]=="coordinator-1"
    assert outbox["drafts"][0]["body"]==body
    assert outbox["sent_messages"]==[]
    with cmd.store.connect() as db:
        assert db.execute(
            "SELECT COUNT(*) FROM objects WHERE kind='message_outbox'"
        ).fetchone()[0]==0


def test_f04_preparation_receipt_recovery_does_not_leak_source_excerpt(service):
    cmd,pages=service
    status,result=prepare(cmd)
    assert status==200,result
    from urllib.parse import urlencode
    status,receipt=pages.serve("BOSS","/api/boss/ui/operation-status",
        urlencode({
            "action":"boss.meeting.brief.prepare",
            "client_request_id":"brief-prep-001",
        }))
    assert status==200,receipt
    assert receipt["outcome"]=="RECORDED"
    assert receipt["result"]["state"]=="READY_FOR_REVIEW"
    assert receipt["result"]["version"]=="1"
    assert "source_id" not in receipt["result"]
    assert "合成水产饲料外销" not in json.dumps(receipt)
    assert pages.serve("MAINTAINER","/api/boss/ui/operation-status",
        urlencode({
            "action":"boss.meeting.brief.prepare",
            "client_request_id":"brief-prep-001",
        }))[0]==403
