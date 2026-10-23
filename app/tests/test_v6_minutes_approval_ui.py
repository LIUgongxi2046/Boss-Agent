"""Reviewed Desktop v6 geometry and F05/F07 UI binding assertions.

Structural regression only. Pixel acceptance requires screenshots on macOS.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_real_minute_approval_routes_not_shell_placeholders():
    mapping = json.loads((ROOT / "specs/page-service-map.json").read_text(encoding="utf-8"))
    by_id = {item["page_id"]: item for item in mapping["pages"]}
    for id in ("F05", "F07"):
        assert by_id[id]["component_file"] == "app/webui/BossMeetingApproval.tsx"
        assert not by_id[id]["actual_e2e_verified"]
        assert not by_id[id]["visual_pixel_verified"]
    assert set(by_id["F05"]["code_wired_write_actions"]) == {
        "boss.minutes.save", "boss.minutes.confirm",
        "boss.minutes.assignment.create",
    }
    assert "boss.approval.decide" in by_id["F07"]["code_wired_write_actions"]
    assert {"boss.simulation.application.seed", "boss.simulation.application.revise"} <= set(
        by_id["A03"]["code_wired_write_actions"]
    )
    assert mapping["implemented_page_count"] == 72
    assert mapping["placeholder_page_count"] == 0


def test_workflow_component_respects_source_and_owner_boundaries():
    view = (ROOT / "app/webui/BossMeetingApproval.tsx").read_text(encoding="utf-8")
    domain = (ROOT / "validation/boss_meeting_approval.py").read_text(encoding="utf-8")
    overlay = (ROOT / "scripts/prepare_boss_webui.py").read_text(encoding="utf-8")
    assert "BossMeetingApprovalView" in view
    assert "MaintainerApplicationSeed" in view
    assert "boss.minutes.confirm" in view
    assert "boss.approval.decide" in view
    assert "DRAFT_REVIEW" in view
    assert "ASSIGNMENT_DRAFT" in view
    assert "funds_transferred" in domain
    assert "document_revision" in domain
    assert "BossMeetingApproval.tsx" in overlay
    assert "BossMinutesAssignmentActions.tsx" in overlay
    assert "BossMinutesAssignmentActions" in view
    assert "dangerouslySetInnerHTML" not in view
    assert "<iframe" not in view


def test_reviewed_desktop_v6_hero_sidebar_and_card_geometry():
    source = (ROOT / "app/webui/BossDesktop.tsx").read_text(encoding="utf-8")
    css = (ROOT / "app/webui/boss-v6.css").read_text(encoding="utf-8")
    for element in (
        "boss-hero-compact", "dapeng-think.png", "dapeng-execute.png",
        "BossMeetingApprovalView", "MaintainerApplicationSeed",
    ):
        assert element in source
    for element in (
        "min-height:64px;height:64px", "flex:0 0 146px", "flex-basis:122px",
        "grid-template-columns:minmax(0,1fr) 278px",
        "border-radius:20px", ".boss-minutes-tabs", ".boss-approval-decisions",
    ):
        assert element in css
    design_css = (ROOT / "Boss-Agent-Desktop-Complete-v6/design-v6.css").read_text(encoding="utf-8")
    assert "--v6-primary:#005BAC" in design_css
    assert "--v6-secondary:#5CA63B" in design_css
    assert "--boss-blue: #005BAC" in css
    assert "--boss-green: #5CA63B" in css



def test_f05_confirmed_minute_draft_has_separate_authorized_create_and_f06_link():
    editor = (ROOT / "app/webui/BossMinutesAssignmentActions.tsx").read_text()
    shell = (ROOT / "app/webui/BossDesktop.tsx").read_text()
    f06 = (ROOT / "app/webui/BossAssignmentFlow.tsx").read_text()
    backend = (ROOT / "validation/boss_meeting_approval.py").read_text()
    for marker in (
        "boss.minutes.assignment.create", "ASSIGNMENT_DRAFT",
        "CONFIRMED", "sourceCurrent", "editingUnsaved",
        "entry_id", "minute_version", "due_at", "evidence_requirements",
        "onTaskCreated", "独立", "client.requestMutation",
        "/api/boss/ui/operation-status",
    ):
        assert marker in editor
    assert "BossMinutesAssignmentActions" in (
        ROOT / "app/webui/BossMeetingApproval.tsx"
    ).read_text()
    assert "onTaskCreated={id=>{setSelectedTaskId(id);refresh();}}" in shell
    assert "origin_minute_id" in f06
    assert "origin_entry_id" in f06
    assert "minutes_assignment_link" in backend
    assert "message_sent_at_link" in backend
    assert 'task["status"]' not in editor  # no fake local task success
    assert "dangerouslySetInnerHTML" not in editor
    assert "iframe" not in editor


def test_f05_transaction_and_replay_are_represented_in_real_contract():
    source = (ROOT / "validation/boss_command_api.py").read_text()
    projection = (ROOT / "validation/boss_workspace_api.py").read_text()
    assert '"boss.minutes.assignment.create": "BOSS"' in source
    assert "minutes_assignment_create(self, db, data, payload, key)" in source
    assert '"task_created_by_minutes": bool(linked)' in projection
    assert '"message_sent_by_minutes": any(' in projection
    assert '"linked_assignments": linked' in projection



def test_f06_task_message_timeline_is_genuine_cross_page_readback():
    domain = (ROOT / "validation/boss_page_api.py").read_text()
    task_view = (ROOT / "app/webui/BossAssignmentFlow.tsx").read_text()
    shell = (ROOT / "app/webui/BossDesktop.tsx").read_text()
    assert '"linked_messages": linked_messages' in domain
    assert '"type": "ASSIGNMENT_SEND"' in domain
    assert '"type": "FOLLOWUP_MESSAGE"' in domain
    assert '"delivery_state": "NOT_VERIFIED"' in domain
    assert "external_channel_invoked" in domain
    assert "TaskLinkedMessage" in task_view
    assert "tasks?.linked_messages" in task_view
    assert "关联发件与回复状态" in task_view
    assert "onViewMessages()" not in task_view or "onViewMessages" in task_view
    assert 'onViewMessages={()=>navigate("F08")}' in shell
    assert "message.send_state" in task_view  # backend supplies actual simulated send state
    assert "message.delivery_state" in task_view
    assert "message.reply_state" in task_view



def test_f06_followup_draft_requires_existing_sent_task_and_separate_f08_send():
    flow=(ROOT/"app/webui/BossAssignmentFlow.tsx").read_text(encoding="utf-8")
    assert '"boss.message.draft.save"' in flow
    assert 'related_task_id:current.task_id' in flow
    assert 'recipient_id:current.coordinator_id' in flow
    assert '["WAITING_FEEDBACK","IN_PROGRESS"].includes(current.status)' in flow
    assert 'current.source_reference_state!=="CURRENT"' in flow
    assert 'visibility:"RECIPIENT_ONLY"' in flow
    assert 'draft_id:null,expected_version:"0"' in flow
    assert '只保存 F08 DRAFT，不会自动发送' in flow
    assert '保存关联催办草稿（F08）' in flow
    assert "onViewMessages" in flow
