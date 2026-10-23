"""FR06 own promises; independent from external assignment and owner-only."""
from __future__ import annotations

import json
import sys
from pathlib import Path
import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"validation"))
from controls import ControlStore
from boss_command_api import BossCommandAPI
from boss_page_api import BossPageAPI


@pytest.fixture
def services(tmp_path):
    store=ControlStore(tmp_path/"owner-commitment.sqlite")
    store.initialize("ui-check")
    return BossCommandAPI(store),BossPageAPI(store)


def action(cmd,role,name,key,**data):
    return cmd.execute(role,name,{"client_request_id":key,**data})


def create(cmd,key="owner-commitment-create-001",**override):
    fields={
        "purpose":"本人核对本周经营证据",
        "due_at":"2026-10-24T18:00:00+08:00",
        "timezone":"Asia/Shanghai",
        "importance":"NORMAL",
        "evidence_requirements":["带版本的原始财务凭证"],
        "source_refs":[],
        **override,
    }
    return action(cmd,"BOSS","boss.commitment.create",key,**fields)


def read(pages,role="BOSS"):
    return pages.serve(role,"/api/boss/ui/tasks")


def test_owner_creates_independent_commitment_without_sending_to_employee(services):
    cmd,pages=services
    code,created=create(cmd)
    assert code==200,created
    assert created["status"]=="ACTIVE"
    assert created["external_message_sent"] is False
    assert created["due_event"]["state"]=="OPEN"
    assert created["due_event"]["automatic_external_delivery"] is False
    assert create(cmd)==(code,created)  # same idempotent result
    status,view=read(pages)
    assert status==200
    assert view["tasks"]==[]             # no delegated task created
    assert view["linked_messages"]==[]
    assert view["self_commitments"][0]["commitment_id"]==created["commitment_id"]
    assert view["self_commitments"][0]["status"]=="ACTIVE"
    assert view["self_due_events"][0]["event_state"]=="OPEN"
    assert read(pages,"MAINTAINER")[0]==403
    assert action(cmd,"MAINTAINER","boss.commitment.create",
                  "maint-create-denied",purpose="无权操作",due_at="2026-10-24T18:00:00+08:00",
                  timezone="Asia/Shanghai",importance="NORMAL",
                  evidence_requirements=["原始资料"],source_refs=[])[0]==403


def test_owner_can_complete_only_with_current_versioned_evidence(services):
    cmd,pages=services
    created=create(cmd)[1]
    ident=created["commitment_id"]
    fields={"commitment_id":ident,"expected_version":"1"}
    assert action(cmd,"BOSS","boss.commitment.complete","empty-proof-invalid",
                  **fields,evidence_refs=[])[0]==400
    evidence=[{"source_id":"finance-note","version":"1"}]
    code,done=action(cmd,"BOSS","boss.commitment.complete",
                     "owner-proof-complete-001",**fields,evidence_refs=evidence)
    assert code==200,done
    assert done["status"]=="COMPLETED_CONFIRMED"
    assert done["due_event"]["state"]=="CANCELED"
    assert action(cmd,"BOSS","boss.commitment.complete",
                  "owner-proof-complete-001",**fields,evidence_refs=evidence)==(code,done)
    _,view=read(pages)
    assert view["self_commitments"][0]["completion_evidence"]==evidence
    assert view["self_commitments"][0]["version"]=="2"
    assert view["self_due_events"][0]["event_state"]=="CANCELED"
    assert action(cmd,"BOSS","boss.commitment.complete",
                  "owner-proof-again-002",**fields,evidence_refs=evidence)[0]==409
    assert action(cmd,"BOSS","boss.commitment.cancel",
                  "owner-cancel-completed",commitment_id=ident,
                  expected_version="2",reason="无需继续")[0]==409


def test_source_withdrawal_blocks_owner_completion_and_leaves_active(services):
    cmd,pages=services
    ident=create(cmd)[1]["commitment_id"]
    cmd.store.control("ui-check","withdraw",{"source_id":"finance-note","version":"1"})
    status,_=action(cmd,"BOSS","boss.commitment.complete",
                    "bad-withdrawn-proof",commitment_id=ident,
                    expected_version="1",
                    evidence_refs=[{"source_id":"finance-note","version":"1"}])
    assert status==410
    assert read(pages)[1]["self_commitments"][0]["status"]=="ACTIVE"
    with cmd.store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind='authorization'").fetchone()[0]==1


def test_owner_explicit_extension_updates_event_and_history_once(services):
    cmd,pages=services
    ident=create(cmd)[1]["commitment_id"]
    code,result=action(cmd,"BOSS","boss.commitment.extend",
        "owner-extend-001",commitment_id=ident,expected_version="1",
        due_at="2026-10-25T18:00:00+08:00",reason="待补齐原始凭证")
    assert code==200,result
    assert result["version"]=="2"
    assert result["due_event"]["event_version"]=="2"
    assert result["due_event"]["state"]=="OPEN"
    assert action(cmd,"BOSS","boss.commitment.extend","owner-extend-001",
        commitment_id=ident,expected_version="1",
        due_at="2026-10-25T18:00:00+08:00",reason="待补齐原始凭证")==(code,result)
    assert action(cmd,"BOSS","boss.commitment.extend","owner-extend-stale",
        commitment_id=ident,expected_version="1",
        due_at="2026-10-26T18:00:00+08:00",reason="不能旧版延期")[0]==409
    with cmd.store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind='self_commitment_revision'").fetchone()[0]==1
    assert read(pages)[1]["self_commitments"][0]["due_at"]=="2026-10-25T18:00:00+08:00"


def test_owner_cancel_closes_reminder_without_erasing_history(services):
    cmd,pages=services
    ident=create(cmd)[1]["commitment_id"]
    status,res=action(cmd,"BOSS","boss.commitment.cancel",
        "owner-self-cancel-001",commitment_id=ident,
        expected_version="1",reason="业务优先级发生变化")
    assert status==200,res
    assert res["status"]=="CANCELED"
    assert res["due_event"]["state"]=="CANCELED"
    assert read(pages)[1]["self_commitments"][0]["status"]=="CANCELED"
    assert read(pages)[1]["self_due_events"][0]["event_state"]=="CANCELED"
    assert action(cmd,"BOSS","boss.commitment.extend","owner-cancel-then-extend",
        commitment_id=ident,expected_version="2",
        due_at="2026-10-26T18:00:00+08:00",reason="重复活动")[0]==409


def test_owner_commitment_due_dispatch_does_not_send_external_notifications(services):
    cmd,pages=services
    ident=create(cmd)[1]["commitment_id"]
    register=action(cmd,"MAINTAINER","boss.simulation.event.seed",
        "owner-self-rules-seed-001",event_id="event-1")
    assert register[0]==200
    advance=action(cmd,"MAINTAINER","boss.simulation.clock.advance",
        "owner-self-clock-after",at="2026-10-25T09:00:00+08:00")
    assert advance[0]==200
    statuses=cmd.store.dispatch_due("ui-check")
    matched=next(row for row in statuses if row["event_id"]=="owner-due:"+ident)
    assert matched["state"] in ("DELIVERED","SUPPRESSED")
    # DELIVERED here is only the internal simulated notification object.
    assert read(pages)[1]["self_due_events"][0]["external_delivery_verified"] is False
    assert read(pages)[1]["self_commitments"][0]["status"]=="ACTIVE"
    assert read(pages)[1]["tasks"]==[]


@pytest.mark.parametrize("bad",[
    {"due_at":"2026-10-20T08:00:00+08:00"},
    {"importance":"URGENT_EXTERNAL_ESCALATION"},
    {"source_refs":[{"source_id":"finance-note","version":"2"}]},
    {"evidence_requirements":[]},
])
def test_invalid_self_commitment_never_creates_task_or_authorization(services,bad):
    cmd,_=services
    status,_=create(cmd,key="invalid-owner-commitment",**bad)
    assert status in (400,409)
    with cmd.store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind='self_commitment'").fetchone()[0]==0
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind='authorization'").fetchone()[0]==0


def test_commitment_recovery_receipt_contains_no_private_task_text(services):
    from urllib.parse import urlencode
    cmd,pages=services
    code,created=create(cmd)
    assert code==200
    status,record=pages.serve("BOSS","/api/boss/ui/operation-status",
        urlencode({"action":"boss.commitment.create",
                   "client_request_id":"owner-commitment-create-001"}))
    assert status==200,record
    assert record["outcome"]=="RECORDED"
    assert "本人核对本周经营证据" not in json.dumps(record)
    assert "due_event" not in record.get("result",{})
    assert pages.serve("MAINTAINER","/api/boss/ui/operation-status",
        urlencode({"action":"boss.commitment.create",
                   "client_request_id":"owner-commitment-create-001"}))[0]==403



def test_self_commitment_source_revision_requires_review(services):
    cmd,pages=services
    code,new=create(cmd,key="owner-ref-pinned-new",
        source_refs=[{"source_id":"finance-note","version":"1"}])
    assert code==200,new
    assert read(pages)[1]["self_commitments"][0]["source_reference_state"]=="CURRENT"
    assert cmd.store.control("ui-check","withdraw",{
        "source_id":"finance-note","version":"1"})["withdrawn"]
    _,current=read(pages)
    assert current["self_commitments"][0]["source_reference_state"]=="NEEDS_REVIEW"
    assert current["self_commitments"][0]["status"]=="ACTIVE"


def test_historical_completion_evidence_revoked_is_not_trusted(services):
    cmd,pages=services
    created=create(cmd,key="owner-completion-history-new")[1]
    code,done=action(cmd,"BOSS","boss.commitment.complete",
        "owner-completion-history-confirm",
        commitment_id=created["commitment_id"],expected_version="1",
        evidence_refs=[{"source_id":"finance-note","version":"1"}])
    assert code==200,done
    assert read(pages)[1]["self_commitments"][0]["source_reference_state"]=="CURRENT"
    assert cmd.store.control("ui-check","withdraw",{
        "source_id":"finance-note","version":"1"})["withdrawn"]
    _,record=read(pages)
    assert record["self_commitments"][0]["status"]=="COMPLETED_CONFIRMED"
    assert record["self_commitments"][0]["source_reference_state"]=="NEEDS_REVIEW"
    assert record["self_commitments"][0]["completion_evidence"][0]["source_id"]=="finance-note"
