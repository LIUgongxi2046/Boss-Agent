"""F04/Desktop v6 source-grounded integration contract, not pixel acceptance."""
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]


def test_f04_is_a_real_business_component_not_a_generic_readonly_page():
    catalog=json.loads((ROOT/"Boss-Agent-Desktop-Complete-v6/meta/页面配置.json").read_text())
    mapped=json.loads((ROOT/"specs/page-service-map.json").read_text())
    page=next(x for x in mapped["pages"] if x["page_id"]=="F04")
    assert catalog["F04"]["title"]=="会前材料"
    assert page["component_file"]=="app/webui/BossMeetingBrief.tsx"
    assert page["role_gate"]=="BOSS"
    assert page["render_status"]=="PARTIAL_VERSIONED_MEETING_BRIEF_AND_F08_DRAFT"
    assert set(page["code_wired_write_actions"])=={
        "boss.meeting.brief.prepare","boss.message.draft.save",
    }
    assert "meeting_brief.prepare" not in page["operations_not_yet_implemented"]
    assert page["actual_e2e_verified"] is False
    assert page["visual_pixel_verified"] is False


def test_f04_uses_authenticated_mutation_and_source_version_ui():
    view=(ROOT/"app/webui/BossMeetingBrief.tsx").read_text()
    shell=(ROOT/"app/webui/BossDesktop.tsx").read_text()
    build=(ROOT/"scripts/prepare_boss_webui.py").read_text()
    for required in [
        "boss.meeting.brief.prepare","boss.message.draft.save",
        "client.requestMutation","/api/boss/ui/operation-status",
        "needs_review","source_changed","business_changed",
        "finance-note","F05","F06","F08","READY_FOR_REVIEW",
    ]:
        if required=="READY_FOR_REVIEW":
            # State comes from the actual backend and is presented as data.
            assert required in (ROOT/"validation/boss_meeting_brief.py").read_text()
        elif required=="finance-note":
            assert required in (ROOT/"validation/boss_meeting_brief.py").read_text()
        else:
            assert required in view
    assert "BossMeetingBrief" in shell
    assert '"BossMeetingBrief.tsx"' in build
    assert "dangerouslySetInnerHTML" not in view
    assert "localStorage" not in view
    assert "eval(" not in view


def test_briefing_never_sends_a_message_or_marks_meeting_held():
    domain=(ROOT/"validation/boss_meeting_brief.py").read_text()
    assert '"message_sent":False' in domain
    assert '"meeting_occurred":False' in domain
    assert '"reviewed_by_owner":False' in domain
    assert '"source_type":"SIMULATED"' in domain
    assert '"READY_FOR_REVIEW"' in domain
    assert '"NEEDS_REVIEW"' in domain
    assert "meeting_brief_revision" in domain
    assert ' "meeting_id"' in domain or '"meeting_id"' in domain
    assert "meeting_calendar" not in domain
