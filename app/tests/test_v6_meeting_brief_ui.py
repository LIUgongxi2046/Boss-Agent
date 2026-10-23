"""F04/Desktop v6 source-grounded integration contract, not pixel acceptance."""
import json
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "validation"))

from boss_command_api import BossCommandAPI
from boss_meetings import MeetingAPI
from controls import ControlStore
from test_boss_meeting_changes import draft_input, confirmation


def test_f04_is_a_real_business_component_not_a_generic_readonly_page():
    catalog=json.loads((ROOT/"Boss-Agent-Desktop-Complete-v6/meta/页面配置.json").read_text())
    mapped=json.loads((ROOT/"specs/page-service-map.json").read_text())
    page=next(x for x in mapped["pages"] if x["page_id"]=="F04")
    assert catalog["F04"]["title"]=="会前材料"
    assert page["component_file"]=="app/webui/BossMeetingBrief.tsx"
    assert page["role_gate"]=="BOSS"
    assert page["render_status"]=="PARTIAL_OWNER_MEETING_LIFECYCLE_BRIEF_AND_F08_DRAFT"
    assert page["additional_component_files"]==["app/webui/BossMeetingArrangement.tsx"]
    assert set(page["code_wired_write_actions"])=={
        "boss.meeting.brief.prepare","boss.message.draft.save",
        "boss.meeting.draft.save","boss.meeting.confirm","boss.meeting.cancel","boss.meeting.held",
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
    assert '"BossMeetingArrangement.tsx"' in build
    assert 'read<MeetingArrangementProjection>("/api/boss/ui/meeting-arrangement"' in shell
    assert "dangerouslySetInnerHTML" not in view
    assert "localStorage" not in view
    assert "eval(" not in view


def test_briefing_never_sends_a_message_or_marks_meeting_held(tmp_path):
    store = ControlStore(tmp_path / "briefing-state.sqlite")
    store.initialize("ui-check")
    commands = BossCommandAPI(store)
    status, prepared = commands.execute("BOSS", "boss.meeting.brief.prepare", {
        "client_request_id": "briefing-initial-state", "meeting_id": "meeting-1", "meeting_version": "1", "expected_version": "0",
    })
    assert status == 200 and prepared["meeting_occurred"] is False
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind='meeting'").fetchone()[0] == 0
    meetings = MeetingAPI(store)
    draft = meetings.execute("BOSS", "draft.save", draft_input())
    confirmed = meetings.execute("BOSS", "confirm", confirmation(draft))
    store.control("ui-check", "clock", {"at": draft_input()["starts_at"]})
    held = meetings.execute("BOSS", "held", {"client_request_id": "briefing-owner-held", "meeting_id": "meeting-1",
        "expected_version": confirmed["version"], "reason": draft_input()["purpose"]})
    current = meetings.read("BOSS")["meeting"]
    status, refreshed = commands.execute("BOSS", "boss.meeting.brief.prepare", {
        "client_request_id": "briefing-held-state", "meeting_id": "meeting-1", "meeting_version": held["version"], "expected_version": prepared["version"],
    })
    assert status == 200 and refreshed["meeting_occurred"] is True
    assert refreshed["message_sent"] is False
    assert meetings.read("BOSS")["meeting"] == current
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind IN ('outbox','message_outbox')").fetchone()[0] == 0
