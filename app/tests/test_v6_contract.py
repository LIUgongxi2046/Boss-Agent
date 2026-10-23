"""Design-contract checks for the reviewed Desktop v6 implementation baseline.

These are static structural checks, *not* screenshots or pixel-diff results.
Runtime, domain and Mac visual acceptance stay separate.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DESIGN = ROOT / "Boss-Agent-Desktop-Complete-v6"
CSS = (ROOT / "app/webui/boss-v6.css").read_text(encoding="utf-8")
REACT = (ROOT / "app/webui/BossDesktop.tsx").read_text(encoding="utf-8")
PREPARE = (ROOT / "scripts/prepare_boss_webui.py").read_text(encoding="utf-8")
BASELINE = json.loads((ROOT / "specs/hld-72-page-map.json").read_text(encoding="utf-8"))
PAGES = json.loads((DESIGN / "meta/页面配置.json").read_text(encoding="utf-8"))
STATES = json.loads((DESIGN / "meta/v6-状态关联.json").read_text(encoding="utf-8"))


def test_all_72_page_routes_are_linked_to_original_design_and_prd():
    assert len(PAGES) == len(BASELINE["pages"]) == 72
    assert set(PAGES) == {item["page_id"] for item in BASELINE["pages"]}
    assert len({item["logical_route"] for item in BASELINE["pages"]}) == 72
    assert len(STATES) == 561
    for item in BASELINE["pages"]:
        page_id, title = item["page_id"], item["title"]
        assert PAGES[page_id]["title"] == title
        assert (ROOT / item["design_html"]).is_file()
        assert item["fr_ids"]
        assert item["upstream_reuse_anchor_ids"]
        assert item["role_gate"]
        assert item["route_is_implemented"] is False  # T08 has not signed off.
        assert item["component_is_implemented"] is False


def test_design_state_index_truthfulness():
    indexed = {row["page_id"] for row in STATES}
    assert len(indexed) == 51
    assert {x["page_id"] for x in BASELINE["pages"] if x["design_state_ids"]} == indexed
    for page_id in indexed:
        assert len([row for row in STATES if row["page_id"] == page_id]) == 11
    assert len(set(PAGES) - indexed) == 21  # N/D inherit common states.


def test_exact_brand_palette_and_accessible_controls():
    tokens = json.loads((DESIGN / "design-tokens.json").read_text(encoding="utf-8"))
    for key in ("brandBlue", "deepBlue", "brandGreen", "actionBlue", "focus"):
        assert tokens["colors"][key].lower() in CSS.lower(), key
    assert "PingFang SC" in CSS
    assert "Noto Sans CJK SC" in CSS
    assert "min-height:44px" in CSS
    assert "prefers-reduced-motion" in CSS
    assert ":focus-visible" in CSS
    assert "@media(max-width:1020px)" in CSS


def test_real_branded_media_all_present():
    for name in (
        "boss-logo-from-reference.png", "dapeng-front.png",
        "dapeng-side.png", "dapeng-think.png", "dapeng-execute.png"
    ):
        assert (DESIGN / "assets" / name).is_file(), name
    for i, label in enumerate(("待机悬浮", "语音倾听", "思考分析", "执行推进", "完成确认", "通知提醒"), 1):
        assert (DESIGN / "animation" / f"{i:02d}-{label}.webp").is_file()


def test_ui_stays_authenticated_and_does_not_fake_business_actions():
    assert '"/api/boss/identity"' in REACT
    assert '"/api/boss/ui/dashboard"' in REACT
    assert '"/api/boss/ui/metrics?products="' in REACT
    assert "onStartChat(question.trim())" in REACT
    assert "PROJECT" not in REACT  # No second product/project-wide identity.
    assert "dangerouslySetInnerHTML" not in REACT
    assert "<iframe" not in REACT
    assert "已映射 · 未实现" in REACT


def test_upstream_revision_and_non_destructive_overlay():
    commit = "1bb712d3488915ca4ed9ccc1a93067ff722f5ab9"
    assert commit in PREPARE
    assert "HEAD:webui/src/App.tsx" in PREPARE
    assert "src/App.tsx" in PREPARE
    assert "shutil.copy2" in PREPARE
    assert "git" in PREPARE


def test_page_service_map_is_explicit_about_partial_runtime():
    service_map = json.loads((ROOT / "specs/page-service-map.json").read_text(encoding="utf-8"))
    assert service_map["page_count"] == 72
    assert len(service_map["pages"]) == 72
    assert service_map["implemented_page_count"] == 72
    assert service_map["placeholder_page_count"] == 0
    assert all(page["actual_e2e_verified"] is False for page in service_map["pages"])
    assert all(page["visual_pixel_verified"] is False for page in service_map["pages"])
    by_id = {item["page_id"]: item for item in service_map["pages"]}
    assert set(by_id) == set(PAGES)
    assert set(by_id["F06"]["code_wired_write_actions"]) == {
        "boss.assignment.create", "boss.assignment.send",
        "boss.assignment.complete", "boss.assignment.extend", "boss.assignment.cancel",
        "boss.assignment.nudge", "boss.assignment.sources.confirm",
    }
    assert set(by_id["A04"]["code_wired_write_actions"]) == {"boss.simulation.feedback", "boss.simulation.event.seed", "boss.simulation.clock.advance", "boss.simulation.message.reply"}
    assert by_id["F24"]["verified_http_read_routes"] == ["GET /api/boss/ui/model-health"]
    assert by_id["A15"]["verified_http_read_routes"] == [
        "GET /api/boss/ui/model-usage", "GET /api/boss/ui/runtime-records",
        "GET /api/boss/ui/runtime-records/task", "GET /api/boss/ui/maintenance",
    ]
    for item in service_map["pages"]:
        assert item["component_file"]
        assert item["role_gate"] == next(p["role_gate"] for p in BASELINE["pages"] if p["page_id"] == item["page_id"])
        if item["render_status"] == "DESIGN_PLACEHOLDER_ONLY":
            assert not item["code_wired_write_actions"]


def test_boss_websocket_writes_are_never_literal_http_or_client_storage():
    role_channel = (ROOT / "validation/role_channel.py").read_text(encoding="utf-8")
    command_api = (ROOT / "validation/boss_command_api.py").read_text(encoding="utf-8")
    flow = (ROOT / "app/webui/BossAssignmentFlow.tsx").read_text(encoding="utf-8")
    assert "self.connection_roles.get(connection)" in role_channel
    assert "self.boss_commands.execute(role, action" in role_channel
    assert "client.requestMutation" in flow
    assert "client_request_id" in flow
    assert "BEGIN IMMEDIATE" in command_api
    assert "authorization_id" in command_api
    assert "idempotency" in command_api
    assert "localStorage.setItem" not in flow
    assert "dangerouslySetInnerHTML" not in flow


def test_real_workspace_and_sector_routing_coverage_is_not_faked():
    mapping = json.loads((ROOT / "specs/page-service-map.json").read_text(encoding="utf-8"))
    by_id = {row["page_id"]: row for row in mapping["pages"]}
    workspace_source = (ROOT / "app/webui/BossWorkspaceView.tsx").read_text(encoding="utf-8")
    part = workspace_source.split("export const WORKSPACE_PAGE_ROUTES", 1)[1].split("type Role", 1)[0]
    workplace_ids = re.findall(r"\b([FAND]\d{2}(?:-[A-Z]+)?):\s*\"", part)
    assert len(workplace_ids) == 23  # F10/F11 and F26/N07/N08 use dedicated v6 components
    for page_id in workplace_ids:
        dedicated = {"N09": "app/webui/BossOwnerPlans.tsx", "A12": "app/webui/MaintainerMemoryStatus.tsx"}
        expected = dedicated[page_id] if page_id in dedicated else "app/webui/BossWorkspaceView.tsx"
        assert by_id[page_id]["component_file"] == expected
        if page_id == "A12":
            assert "app/webui/BossWorkspaceView.tsx" in by_id[page_id]["additional_component_files"]
        assert by_id[page_id]["render_status"] != "DESIGN_PLACEHOLDER_ONLY"
        assert any("/api/boss/ui/workspace/" in endpoint
                   for endpoint in by_id[page_id]["verified_http_read_routes"])
    sector_source = (ROOT / "app/webui/BossSectorView.tsx").read_text(encoding="utf-8")
    sector_part = sector_source.split("export const SECTOR_PAGE_IDS", 1)[1].split("] as const;", 1)[0]
    sector_ids = re.findall(r'\"(F\d{2}|V19-[A-Z]+)\"', sector_part)
    assert len(sector_ids) == 13
    for page_id in sector_ids:
        assert by_id[page_id]["component_file"] == "app/webui/BossSectorView.tsx"
        assert by_id[page_id]["render_status"] == "PARTIAL_AGRICULTURE_SOURCE_COVERAGE_NO_KPI_DATA"
        assert by_id[page_id]["metrics_are_real"] is False
        assert by_id[page_id]["actual_e2e_verified"] is False
    assert len(mapping["not_yet_built_page_ids"]) == 0
    assert set(mapping["not_yet_built_page_ids"]) == {
        id for id, row in by_id.items() if row["render_status"] == "DESIGN_PLACEHOLDER_ONLY"
    }


def test_memory_and_notification_commands_are_owner_bound():
    mapping = json.loads((ROOT / "specs/page-service-map.json").read_text(encoding="utf-8"))
    by_id = {row["page_id"]: row for row in mapping["pages"]}
    assert set(by_id["F13"]["code_wired_write_actions"]) == {
        "boss.memory.confirm", "boss.memory.delete",
    }
    assert {"boss.reminder.ack", "boss.reminder.close", "boss.reminder.snooze"} <= set(
        by_id["N06"]["code_wired_write_actions"]
    )
    assert by_id["F14"]["metrics_are_real"] is False
    assert by_id["N01"]["component_file"] == "app/webui/BossLogin.tsx"
    assert by_id["D08"]["component_file"] == "app/webui/BossLogin.tsx"
    assert by_id["F31"]["verified_http_read_routes"] == ["GET /api/boss/ui/workspace/evaluation"]
    assert by_id["A06"]["render_status"] == "PARTIAL_NATIVE_SKILLS_HANDOFF"



def test_f27_voice_capture_requires_real_upstream_transcription_and_owner_review():
    voice = (ROOT / "app/webui/BossVoiceAssignment.tsx").read_text(encoding="utf-8")
    mapping = json.loads((ROOT / "specs/page-service-map.json").read_text(encoding="utf-8"))
    by_id = {row["page_id"]: row for row in mapping["pages"]}
    assert by_id["F27"]["render_status"].startswith("PARTIAL_")
    assert by_id["F27"]["actual_e2e_verified"] is False
    assert "client.transcribeAudio" in voice
    assert "getUserMedia({ audio: true })" in voice
    assert 'action: "request_microphone"' in voice
    assert "onSubmit(draft.trim())" in voice
    assert "MAX_AUDIO_BYTES" in voice and "MAX_DURATION_MS" in voice
    assert "URL.revokeObjectURL" in voice
    assert "MediaRecorder" in voice
    assert "transcription" not in voice or "尚未启用" in voice or "当前固定开发配置默认关闭" in voice
    assert "BossVoiceAssignment.tsx" in PREPARE
    assert set(mapping["not_yet_built_page_ids"]) == set()
    for page_id in ("D04", "D05", "D06", "D07"):
        assert by_id[page_id]["render_status"].startswith("PARTIAL_")
