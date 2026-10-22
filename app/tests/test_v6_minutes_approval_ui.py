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
    }
    assert "boss.approval.decide" in by_id["F07"]["code_wired_write_actions"]
    assert {"boss.simulation.application.seed", "boss.simulation.application.revise"} <= set(
        by_id["A03"]["code_wired_write_actions"]
    )
    assert mapping["implemented_page_count"] == 70
    assert mapping["placeholder_page_count"] == 2


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
