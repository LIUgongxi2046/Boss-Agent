"""Design-contract checks for the reviewed Desktop v6 implementation baseline.

These are static structural checks, *not* screenshots or pixel-diff results.
Runtime, domain and Mac visual acceptance stay separate.
"""
from __future__ import annotations

import json
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
