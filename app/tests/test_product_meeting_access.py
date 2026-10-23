import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "validation"))

from boss_command_api import BossCommandAPI
from boss_page_api import BossPageAPI
from controls import ControlStore
from test_boss_meeting_changes import draft_input, confirmation
from test_boss_command_api import create_input, send_input, feedback_input


def test_public_meeting_confirmation_updates_all_current_projections(tmp_path):
    store = ControlStore(tmp_path / "public-meeting.sqlite")
    store.initialize("ui-check")
    commands, pages = BossCommandAPI(store), BossPageAPI(store)
    status, initial = pages.serve("BOSS", "/api/boss/ui/meeting-arrangement")
    assert status == 200
    assert initial["meeting"]["state"] == "DRAFT"
    assert pages.serve("MAINTAINER", "/api/boss/ui/meeting-arrangement")[0] == 403
    assert pages.serve(None, "/api/boss/ui/meeting-arrangement")[0] == 401
    assert pages.serve("BOSS", "/api/boss/ui/meeting-arrangement", "namespace=ui-check")[0] == 400
    payload = draft_input()
    assert commands.execute("MAINTAINER", "boss.meeting.draft.save", payload)[0] == 403
    status, saved = commands.execute("BOSS", "boss.meeting.draft.save", payload)
    assert status == 200
    assert commands.execute("BOSS", "boss.meeting.draft.save", payload) == (200, saved)
    assert pages.serve("BOSS", "/api/boss/ui/meeting-arrangement")[1]["meeting"] == initial["meeting"]
    approval = confirmation(saved)
    status, scheduled = commands.execute("BOSS", "boss.meeting.confirm", approval)
    assert status == 200 and scheduled["state"] == "SCHEDULED"
    assert commands.execute("BOSS", "boss.meeting.confirm", approval) == (200, scheduled)
    assert pages.serve("BOSS", "/api/boss/ui/dashboard")[1]["meeting"]["version"] == scheduled["version"]
    assert pages.serve("BOSS", "/api/boss/ui/meetings")[1]["meeting"]["ends_at"] == payload["ends_at"]
    assert pages.serve("BOSS", "/api/boss/ui/workspace/briefing")[1]["current"]["meeting"]["version"] == scheduled["version"]
    calendar = pages.serve("BOSS", "/api/boss/ui/workspace/calendar")[1]
    assert calendar["meeting"]["ends_at"] == payload["ends_at"]
    assert calendar["meeting"]["end_is_known"] is True
    query = "action=boss.meeting.confirm&client_request_id=" + approval["client_request_id"]
    receipt = pages.serve("BOSS", "/api/boss/ui/operation-status", query)[1]
    assert receipt["outcome"] == "RECORDED"
    assert receipt["result"]["invitation_sent"] is False
    reopened = BossPageAPI(ControlStore(store.path))
    assert reopened.serve("BOSS", "/api/boss/ui/meeting-arrangement")[1]["meeting"]["version"] == scheduled["version"]


def test_public_late_feedback_preserves_canceled_task_and_event(tmp_path):
    store = ControlStore(tmp_path / "public-history.sqlite")
    store.initialize("ui-check")
    commands = BossCommandAPI(store)
    status, created = commands.execute("BOSS", "boss.assignment.create", create_input())
    assert status == 200
    status, sent = commands.execute("BOSS", "boss.assignment.send", send_input(created))
    assert status == 200
    status, canceled = commands.execute("BOSS", "boss.assignment.cancel", {
        "client_request_id": "public-late-owner-cancel", "task_id": created["task_id"],
        "task_version": sent["task_version"], "reason": "停止后续交办",
    })
    assert status == 200
    payload = feedback_input({"task_id": created["task_id"], "version": canceled["version"]})
    status, result = commands.execute("MAINTAINER", "boss.simulation.feedback", payload)
    assert status == 200
    assert result["historical_only"] is True
    assert result["task"]["status"] == "CANCELED"
    assert commands.execute("MAINTAINER", "boss.simulation.feedback", payload) == (200, result)
    with ControlStore(store.path).connect() as db:
        assert store.get(db, "ui-check", "event", "task-due:" + created["task_id"])["state"] == "CANCELED"
