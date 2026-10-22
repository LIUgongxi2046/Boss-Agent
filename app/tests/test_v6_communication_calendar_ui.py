"""Desktop v6 FR-08/FR-12 implementation contracts.

Static code checks only. Browser visual similarity requires real Mac capture.
"""
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]


def test_real_message_calendar_pages_not_generic_placeholders():
    mapdata=json.loads((ROOT/"specs/page-service-map.json").read_text(encoding="utf-8"))
    by={row["page_id"]:row for row in mapdata["pages"]}
    for page in ("F08","F12"):
        p=by[page]
        assert p["component_file"]=="app/webui/BossCommunicationCalendar.tsx"
        assert not p["actual_e2e_verified"]
        assert not p["visual_pixel_verified"]
        assert p["external_delivery_verified"] is False
    assert set(by["F08"]["code_wired_write_actions"])=={
        "boss.message.draft.save","boss.message.send",
    }
    assert set(by["F12"]["code_wired_write_actions"])=={
        "boss.calendar.save","boss.calendar.share",
        "boss.calendar.share.revoke","boss.calendar.delete",
    }
    assert "boss.simulation.message.reply" in by["A04"]["code_wired_write_actions"]


def test_client_uses_native_auth_socket_without_fake_results():
    v=(ROOT/"app/webui/BossCommunicationCalendar.tsx").read_text(encoding="utf-8")
    a=(ROOT/"app/webui/MaintainerMessageReply.tsx").read_text(encoding="utf-8")
    shell=(ROOT/"app/webui/BossDesktop.tsx").read_text(encoding="utf-8")
    script=(ROOT/"scripts/prepare_boss_webui.py").read_text(encoding="utf-8")
    for action in (
        "boss.message.draft.save","boss.message.send",
        "boss.calendar.save","boss.calendar.share",
        "boss.calendar.share.revoke","boss.calendar.delete",
    ):
        assert action in v
    assert "boss.simulation.message.reply" in a
    assert "client.requestMutation" in v
    assert "client.requestMutation" in a
    assert "crypto.randomUUID()" in v
    assert "draft.content_sha256" in v
    assert "message_id" in a
    assert "body" not in a.split("type Row =",1)[1].split("type Listing",1)[0]
    assert "BossCommunicationCalendar" in shell
    assert "MaintainerMessageReply" in shell
    assert "BossCommunicationCalendar.tsx" in script
    assert "MaintainerMessageReply.tsx" in script
    assert "dangerouslySetInnerHTML" not in v
    assert "localStorage" not in v


def test_private_contents_cannot_enter_authorization_or_technical_projection():
    domain=(ROOT/"validation/boss_message_calendar.py").read_text(encoding="utf-8")
    api=(ROOT/"validation/boss_workspace_api.py").read_text(encoding="utf-8")
    assert 'checksum({' in domain
    assert '"body": body' in domain  # Stored under owner-only SQLite business object.
    assert 'share["revoked"] = True' in domain
    assert '"busy": True' in domain
    assert '"private_body"' not in domain.split('def calendar_share(',1)[1].split('def calendar_revoke(',1)[0]
    assert '"raw_message_text_returned": False' in api
    assert 'if key == "message-admin"' in api
    assert '"visibility": "BOSS_ONLY"' in api
    assert "physical_secure_erasure_verified" in api
