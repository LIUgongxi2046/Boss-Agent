from boss_command_api import BossCommandAPI
from test_menu_n03_meeting_preparation import ready_meeting, preparation
from test_menu_n03_overview import snapshot


def test_public_scoped_meeting_uses_exact_current_materials_metrics_and_readonly_state(ready_meeting):
    store, overview, bridge, task, confirmed, selection = ready_meeting
    api = BossCommandAPI(store)
    before = snapshot(store)
    status, current = api.execute("BOSS", "boss.business_overview.preparation", selection)
    assert status == 200 and current["current_use_verified"]
    payload = {"selection": selection, "context_sha256": current["context_sha256"]}
    status, result = api.execute("BOSS", "boss.business.meeting.prepare", payload)
    assert status == 200, result
    assert result["preparation"] == current["meeting_preparation"]
    assert result["preparation"]["task"]["task_id"] == task["id"]
    assert result["preparation"]["meeting"]["version"] == confirmed["version"]
    assert result["preparation"]["applied_scope"] == selection["applied_scope"]
    assert result["preparation"]["metrics"] == overview.read("BOSS", selection["applied_scope"])["metrics"]
    assert api.execute("BOSS", "boss.business.meeting.prepare", payload)[1]["preparation"] == result["preparation"]
    assert snapshot(store) == before
    for role, expected in ((None, 401), ("MAINTAINER", 403)):
        assert api.execute(role, "boss.business.meeting.prepare", payload)[0] == expected
    for field in ("owner_id", "sources", "confirmed", "meeting_id"):
        assert api.execute("BOSS", "boss.business.meeting.prepare", {**payload, field: "injected"})[0] == 400
    assert api.execute("BOSS", "boss.business.meeting.prepare", {**payload, "context_sha256": "0" * 64})[0] == 409
    assert snapshot(store) == before
    store.control("ui-check", "withdraw", {"source_id": "finance-note", "version": "1"})
    assert api.execute("BOSS", "boss.business.meeting.prepare", payload)[0] == 409
    assert result["preparation"]["materials"][0]["source_reference"]["version"] == "1"
