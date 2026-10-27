"""N05 actual task index and original Desktop v6 UI contract.

No mock records: the task index is server-owned, role-checked, uses simulated
business time and exposes only the statuses persisted by prior transactions.
"""
from __future__ import annotations

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
def system(tmp_path):
    store=ControlStore(tmp_path/"task-center.sqlite")
    store.initialize("ui-check")
    return BossCommandAPI(store),BossPageAPI(store)


def _create(api):
    return api.execute("BOSS","boss.assignment.create",{
        "client_request_id":"n05-task-create-001",
        "purpose":"核查经营资料范围",
        "coordinator_id":"coordinator-1",
        "due_at":"2026-10-24T17:00:00+08:00",
        "timezone":"Asia/Shanghai",
        "evidence_requirements":["经营原始明细"],
        "related_meeting_id":"meeting-1",
        "related_event_ids":["event-1"],
        "source_refs":["finance-note"],"content_version":"1",
    })


def test_task_center_has_only_actual_objects_and_simulated_clock(system):
    command,api=system
    code,empty=api.serve("BOSS","/api/boss/ui/tasks")
    assert code==200
    assert empty["source_type"]=="SIMULATED"
    assert empty["tasks"]==[]
    assert empty["historical_commitment"]["task_id"]=="historical-1"
    assert empty["business_clock"].startswith("2026")
    assert api.serve("MAINTAINER","/api/boss/ui/tasks")[0]==403
    created=_create(command)
    assert created[0]==200,created
    code,loaded=api.serve("BOSS","/api/boss/ui/tasks")
    assert code==200
    assert len(loaded["tasks"])==1
    task=loaded["tasks"][0]
    assert task["task_id"]==created[1]["task_id"]
    assert task["related_meeting_id"]=="meeting-1"
    assert task["coordinator_id"]=="coordinator-1"
    assert task["source_reference_state"]=="CURRENT"
    assert loaded["linked_messages"]==[]
    assert loaded["task_due_events"]==[] # draft task has no dispatch


def test_task_center_reconciles_authorized_send_and_source_withdrawal(system):
    command,api=system
    created=_create(command)[1]
    sent=command.execute("BOSS","boss.assignment.send",{
        "client_request_id":"n05-task-send-001",
        "task_id":created["task_id"],"task_version":"1",
        "recipient_id":"coordinator-1",
        "body":"请核查当前经营证据",
        "content_version":"1",
    })
    assert sent[0]==200,sent
    _,record=api.serve("BOSS","/api/boss/ui/tasks")
    assert record["tasks"][0]["status"]=="WAITING_FEEDBACK"
    assert record["linked_messages"][0]["task_id"]==created["task_id"]
    assert record["linked_messages"][0]["delivery_state"]=="NOT_VERIFIED"
    assert record["linked_messages"][0]["external_channel_invoked"] is False
    assert record["task_due_events"][0]["event_state"]=="OPEN"
    assert command.store.control("ui-check","withdraw",{
        "source_id":"finance-note","version":"1",
    })["withdrawn"]
    _,after=api.serve("BOSS","/api/boss/ui/tasks")
    assert after["tasks"][0]["source_reference_state"]=="NEEDS_REVIEW"
    assert "SOURCE_UNAVAILABLE" in after["tasks"][0]["source_reference_reasons"]
    assert after["linked_messages"][0]["message_id"]==sent[1]["message_id"]
    assert after["linked_messages"][0]["delivery_state"]=="NOT_VERIFIED"


def test_current_clock_change_affects_task_due_classification_without_forged_result(system):
    command,api=system
    _create(command)
    old=api.serve("BOSS","/api/boss/ui/tasks")[1]["business_clock"]
    status,result=command.execute("MAINTAINER","boss.simulation.clock.advance",{
        "client_request_id":"n05-clock-advance-001",
        "at":"2026-10-25T09:00:00+08:00",
    })
    assert status==200,result
    new=api.serve("BOSS","/api/boss/ui/tasks")[1]
    assert new["business_clock"]!=old
    assert new["business_clock"]=="2026-10-25T09:00:00+08:00"
    assert new["tasks"][0]["status"]=="OPEN"
    assert new["tasks"][0]["due_at"]=="2026-10-24T17:00:00+08:00"
    assert new["task_due_events"]==[]


def test_original_v6_n05_filters_layout_links_real_task_detail():
    page=json.loads((ROOT/"Boss-Agent-Desktop-Complete-v6/meta/页面配置.json").read_text())["N05"]
    view=(ROOT/"app/webui/BossTaskCenter.tsx").read_text()
    desktop=(ROOT/"app/webui/BossDesktop.tsx").read_text()
    overlay=(ROOT/"scripts/prepare_boss_webui.py").read_text()
    assert page["tabs"]==["本人承诺","他人交办","等待反馈","待核查结果"]
    assert page["filters"]==["负责人","有效期限","任务状态","关联会议"]
    for label in ["全部","我的承诺","我交办的"]+page["filters"]:
        assert label in view
    assert "business_clock" in view and "Date.parse" in view
    assert "source_reference_state" in view
    assert "linked_messages" in view and "task_due_events" in view
    assert "onOpenTask(selected.task_id)" in view
    assert 'page === "N05" ? <BossTaskCenter' in desktop
    assert '"BossTaskCenter.tsx"' in overlay
    assert "dangerouslySetInnerHTML" not in view
    assert "localStorage" not in view


def test_cross_page_draft_focus_requires_original_persisted_id_no_auto_send():
    brief=(ROOT/"app/webui/BossMeetingBrief.tsx").read_text()
    assignment=(ROOT/"app/webui/BossAssignmentFlow.tsx").read_text()
    communication=(ROOT/"app/webui/BossCommunicationCalendar.tsx").read_text()
    desktop=(ROOT/"app/webui/BossDesktop.tsx").read_text()
    assert "onMessageDraftCreated(r.draft_id)" in brief
    assert 'pending.action==="boss.message.draft.save"' in brief
    assert 'pending.action === "boss.message.draft.save"' in assignment
    assert "onMessageDraftCreated?.(result.draft_id)" in assignment
    assert "onMessageDraftCreated={setDraftToReview}" in desktop
    assert "focusDraftId={draftToReview}" in desktop
    assert "focusDraftId" in communication
    assert "data as Outbox" in communication
    assert "onFocusDraftConsumed?.()" in communication
    # Selection is local UI only; sending is still a separate explicit action.
    assert "boss.message.send" in communication
    assert "checked" in communication
