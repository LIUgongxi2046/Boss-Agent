"""Desktop v6 F09 source-first research UI/contract regressions (not pixel QA)."""
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]


def test_f09_real_ui_binds_approved_visual_sections_and_business_contract():
    cat=json.loads((ROOT/"Boss-Agent-Desktop-Complete-v6/meta/页面配置.json").read_text())
    mapping=json.loads((ROOT/"specs/page-service-map.json").read_text())
    page=next(p for p in mapping["pages"] if p["page_id"]=="F09")
    assert cat["F09"]["title"]=="专题研究"
    assert cat["F09"]["filters"]==["研究问题","期间","国别","业务关系"]
    assert cat["F09"]["sections"]==["可核查事实","作者意见","模型推断","待验证问题"]
    assert page["render_status"]=="PARTIAL_VERSIONED_RESEARCH_WITH_SOURCE_VALIDITY"
    assert page["component_file"]=="app/webui/BossResearchView.tsx"
    assert not page["actual_e2e_verified"]
    assert not page["visual_pixel_verified"]
    assert set(page["code_wired_write_actions"])=={
        "boss.research.prepare","boss.message.draft.save",
    }


def test_f09_source_open_highlights_exact_citation_only_after_version_check():
    view=(ROOT/"app/webui/BossResearchView.tsx").read_text()
    detail=(ROOT/"app/webui/BossDesktop.tsx").read_text()
    css=(ROOT/"app/webui/boss-v6.css").read_text()
    assert "quote_start" in view and "quote_end" in view
    assert "onViewSource(row.source_id,{version:row.version,start:row.quote_start,end:row.quote_end})" in view
    assert "sourceAnchor" in detail
    assert "evidence.version===sourceAnchor.version" in detail
    assert "evidence.content.slice(sourceAnchor.start,sourceAnchor.end)" in detail
    assert "boss-source-highlight" in css
    assert 'page === "F09" ? <BossResearchView' in detail


def test_f09_is_not_static_only_and_never_claims_unverified_model_completion():
    ui=(ROOT/"app/webui/BossResearchView.tsx").read_text()
    workflow=(ROOT/"scripts/prepare_boss_webui.py").read_text()
    service=(ROOT/"validation/boss_research.py").read_text()
    for item in (
        "boss.research.prepare","boss.message.draft.save",
        "client.requestMutation","source_changed","UNVERIFIED_SOURCE_EXCERPT",
        "未分类","FACT","INFERENCE","MISSING","原文引用",
        "核查原请求回执",
    ):
        assert item in (ui+service)
    assert 'BossResearchView.tsx' in workflow
    assert "source_text_is_untrusted_instruction" in service
    assert '"facts_confirmed":[]' in service
    assert '"model_inferences":[]' in service
    assert '"public_web_search_performed":False' in service
    assert "dangerouslySetInnerHTML" not in ui
    assert "localStorage" not in ui
    assert "api_key" not in ui
