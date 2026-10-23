"""Static Desktop v6 wiring contract only; not a screenshot or GUI E2E test."""
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
DESKTOP=(ROOT/"app/webui/BossDesktop.tsx").read_text(encoding="utf-8")
PREFS=(ROOT/"app/webui/BossOwnerPreferences.tsx").read_text(encoding="utf-8")
HUB=(ROOT/"app/webui/BossSettingsHub.tsx").read_text(encoding="utf-8")
WORKSPACE=(ROOT/"app/webui/BossWorkspaceView.tsx").read_text(encoding="utf-8")
BRIEF=(ROOT/"app/webui/BossMeetingBrief.tsx").read_text(encoding="utf-8")
BUILD=(ROOT/"scripts/prepare_boss_webui.py").read_text(encoding="utf-8")
MAPPING=json.loads((ROOT/"specs/page-service-map.json").read_text(encoding="utf-8"))
PAGES={x["page_id"]:x for x in MAPPING["pages"]}


def test_owner_settings_keep_v6_assets_and_real_routes():
    assert 'import "./boss-v6.css"' in DESKTOP
    assert "boss-brand" in DESKTOP and "dapeng" in DESKTOP.lower()
    assert "BossOwnerPreferences" in DESKTOP
    assert "BossSettingsHub" in DESKTOP
    assert 'page === "N07" || page === "N08"' in DESKTOP
    assert 'page === "F26"' in DESKTOP
    assert 'pageId={page}' in DESKTOP
    assert 'onDirtyChange={setSettingsDirty}' in DESKTOP
    assert '"N07","N08"' in DESKTOP
    assert "setPendingNavigation" in DESKTOP
    for name in ("BossOwnerPreferences.tsx", "BossSettingsHub.tsx"):
        assert name in BUILD
    for page in ("N07", "N08", "F26"):
        assert PAGES[page]["render_status"].startswith("PARTIAL_")
        assert PAGES[page]["actual_e2e_verified"] is False
        assert PAGES[page]["visual_pixel_verified"] is False
    route_map=WORKSPACE.split("export const WORKSPACE_PAGE_ROUTES",1)[1].split("type Role",1)[0]
    assert 'N07: "' not in route_map
    assert 'N08: "' not in route_map
    assert 'F26: "' not in route_map


def test_owner_preference_draft_confirm_and_receipt_are_separate_ui_actions():
    for action in (
        "boss.owner.goals.save", "boss.owner.goals.confirm",
        "boss.owner.notice.save", "boss.owner.notice.confirm",
    ):
        assert action in PREFS
    for route in ("owner-goals","owner-notice"):
        assert route in PREFS
    assert "client.requestMutation" in PREFS
    assert "client_request_id" in PREFS
    assert "/api/boss/ui/operation-status" in PREFS
    assert 'outcome==="RECORDED"' in PREFS
    assert "expected_active_version" in PREFS
    assert "expected_draft_version" in PREFS
    assert "content_sha256" in PREFS
    assert "dirty" in PREFS and "beforeunload" in PREFS
    assert "boss-confirm-backdrop" in PREFS
    assert 'role="dialog"' in PREFS
    assert 'aria-modal="true"' in PREFS
    assert 'ShieldCheck' in PREFS
    assert "localStorage.setItem" not in PREFS
    assert "dangerouslySetInnerHTML" not in PREFS


def test_f26_links_owner_settings_and_uses_native_logout():
    for route in ("N07","N08","F13","N09","N10","N11","F12","F01"):
        assert f'onNavigate("{route}")' in HUB
    assert "onLogout" in HUB
    assert "active_is_effective" in HUB
    assert "BOSS_ONLY" in HUB
    assert "MAINTAINER" in HUB
    assert "app/webui/BossSettingsHub.tsx" == PAGES["F26"]["component_file"]


def test_current_owner_versions_render_without_fabricating_model_adoption():
    assert "profile.active_version" in DESKTOP
    assert "profile.owner_confirmation" in DESKTOP
    assert "profile.goals" in DESKTOP
    assert "owner_goal_reference" in BRIEF
    assert 'onNavigate("N07")' in BRIEF
    assert "actual_model_compliance_verified" in PREFS
    assert "owner_notification_preferences" in WORKSPACE
    assert "owner_notice_version" in WORKSPACE
    assert 'onNavigate("N08")' in WORKSPACE
    assert "BUSY_ONLY" in PREFS
    assert "BOSS_ONLY" in PREFS
    assert "external_message_sent" not in PREFS
