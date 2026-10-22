"""Task-due lifecycle: no draft alerts; owner-approved state owns dispatch.

Uses real sqlite and ControlStore.dispatch_due, not mock scheduler metrics.
This simulates time in the already-approved fixed selection namespace only.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from datetime import datetime, timedelta

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "validation"))
from boss_command_api import BossCommandAPI
from boss_page_api import BossPageAPI
from boss_task_reminders import current
from controls import ControlStore


@pytest.fixture
def context(tmp_path):
    store = ControlStore(tmp_path / "task-due.sqlite")
    store.initialize("ui-check")
    return BossCommandAPI(store), BossPageAPI(store)


def act(api, role, action, key, **args):
    return api.execute(role, action, {"client_request_id": key, **args})


def create(api, key="create-task-reminder"):
    return act(
        api, "BOSS", "boss.assignment.create", key,
        purpose="独立审核历史经营材料", coordinator_id="coordinator-1",
        due_at="2026-10-24T17:00:00+08:00", timezone="Asia/Shanghai",
        evidence_requirements=["经营原始明细"],
        related_meeting_id="meeting-1", related_event_ids=["event-1"],
        source_refs=["finance-note"], content_version="1",
    )


def send(api, task_id, version="1", key="send-task-reminder"):
    return act(
        api, "BOSS", "boss.assignment.send", key,
        task_id=task_id, task_version=version, recipient_id="coordinator-1",
        body="请核查事实并回复证据，不自动完成", content_version="1",
    )


def due(api, task_id):
    with api.store.connect() as db:
        return current(db, task_id)


def register_rules(api):
    return act(
        api, "MAINTAINER", "boss.simulation.event.seed",
        "seed-event-for-task-reminders", event_id="event-1",
    )


def test_open_task_has_no_reminder_before_independent_owner_send(context):
    api, pages = context
    code, task = create(api)
    assert code == 200, task
    assert due(api, task["task_id"]) is None
    assert pages.serve("BOSS", "/api/boss/ui/workspace/notifications")[1]["events"] == []
    status, _ = act(
        api, "MAINTAINER", "boss.simulation.feedback",
        "feedback-before-authorization", task_id=task["task_id"],
        task_version="1", author_contact_id="coordinator-1",
        kind="PROGRESS", content="不可以通过维护侧触发任务", evidence_refs=[],
    )
    assert status == 409
    assert due(api, task["task_id"]) is None


def test_send_installs_one_durable_task_due_event_and_is_idempotent(context):
    api, pages = context
    task = create(api)[1]
    status, result = send(api, task["task_id"])
    assert status == 200, result
    event = due(api, task["task_id"])
    assert event["event_id"] == "task-due:" + task["task_id"]
    assert event["due_at"] == "2026-10-24T17:00:00+08:00"
    assert event["task_id"] == task["task_id"]
    assert event["version"] == "1"
    assert event["state"] == "OPEN"
    assert event["automatic_external_delivery"] is False
    assert result["task_due_event"]["cron_dispatch_claimed"] is False
    assert send(api, task["task_id"]) == (status, result)
    with api.store.connect() as db:
        assert db.execute(
            "SELECT COUNT(*) FROM objects WHERE kind='event' AND id LIKE 'task-due:%'"
        ).fetchone()[0] == 1
    assert pages.serve("MAINTAINER", "/api/boss/ui/workspace/notifications")[0] == 403


def test_owner_cancel_stops_future_due_dispatch_without_deleting_history(context):
    api, pages = context
    task = create(api)[1]
    assert send(api, task["task_id"])[0] == 200
    status, canceled = act(
        api, "BOSS", "boss.assignment.cancel", "owner-cancel-task-before-due",
        task_id=task["task_id"], task_version="2",
        reason="已经明确终止，无需继续催办",
    )
    assert status == 200, canceled
    assert canceled["task_due_event"]["event_state"] == "CANCELED"
    assert due(api, task["task_id"])["state"] == "CANCELED"
    assert due(api, task["task_id"])["version"] == "2"
    assert canceled["previous_message_ids"]
    assert register_rules(api)[0] == 200
    assert act(
        api, "MAINTAINER", "boss.simulation.clock.advance",
        "advance-after-task-cancel", at="2026-10-25T09:00:00+08:00",
    )[0] == 200
    dispatched = api.store.dispatch_due("ui-check")
    task_outcome = next(x for x in dispatched
                        if x["event_id"] == "task-due:" + task["task_id"])
    assert task_outcome["state"] == "SUPPRESSED"
    assert task_outcome["reason"] in ("SOURCE_CANCELED", "TASK_ENDED")
    with api.store.connect() as db:
        assert db.execute(
            "SELECT COUNT(*) FROM objects WHERE kind='delivery' AND id=?",
            ("task-due:" + task["task_id"],)
        ).fetchone()[0] == 0
    assert pages.serve("BOSS", "/api/boss/ui/tasks")[1]["tasks"][0]["status"] == "CANCELED"


def test_canceling_open_unsent_draft_does_not_create_false_event(context):
    api, _ = context
    task = create(api)[1]
    canceled = act(
        api, "BOSS", "boss.assignment.cancel", "cancel-before-send",
        task_id=task["task_id"], task_version="1",
        reason="该交办草稿不再需要",
    )
    assert canceled[0] == 200
    assert canceled[1]["task_due_event"] is None
    assert due(api, task["task_id"]) is None


def test_extension_updates_due_atomically_only_after_owner_confirm(context):
    api, _ = context
    task = create(api)[1]
    assert send(api, task["task_id"])[0] == 200
    request = act(
        api, "MAINTAINER", "boss.simulation.feedback", "request-delay",
        task_id=task["task_id"], task_version="2",
        author_contact_id="coordinator-1", kind="EXTENSION_REQUEST",
        content="申请补充真实来源后延期",
        evidence_refs=[], proposed_due_at="2026-10-26T17:00:00+08:00",
    )
    assert request[0] == 200, request
    assert due(api, task["task_id"])["version"] == "1"
    assert due(api, task["task_id"])["due_at"] == "2026-10-24T17:00:00+08:00"
    change = act(
        api, "BOSS", "boss.assignment.extend", "owner-grant-extension",
        task_id=task["task_id"], task_version=request[1]["task"]["version"],
        feedback_id=request[1]["feedback_id"], due_at="2026-10-26T17:00:00+08:00",
    )
    assert change[0] == 200, change
    event = due(api, task["task_id"])
    assert event["due_at"] == "2026-10-26T17:00:00+08:00"
    assert event["version"] == "2"
    assert event["state"] == "OPEN"
    assert change[1]["task_due_event"]["event_version"] == "2"
    assert act(
        api, "BOSS", "boss.assignment.extend", "owner-grant-extension",
        task_id=task["task_id"], task_version=request[1]["task"]["version"],
        feedback_id=request[1]["feedback_id"], due_at="2026-10-26T17:00:00+08:00",
    ) == change


def test_owner_completion_revokes_due_event_after_valid_evidence(context):
    api, pages = context
    task = create(api)[1]
    assert send(api, task["task_id"])[0] == 200
    result = act(
        api, "MAINTAINER", "boss.simulation.feedback", "submit-task-result",
        task_id=task["task_id"], task_version="2",
        author_contact_id="coordinator-1", kind="RESULT_SUBMITTED",
        content="已提交核查结果及其来源",
        evidence_refs=["finance-note"],
    )
    assert result[0] == 200, result
    assert due(api, task["task_id"])["state"] == "OPEN"
    completed = act(
        api, "BOSS", "boss.assignment.complete", "owner-confirm-completion",
        task_id=task["task_id"],
        task_version=result[1]["task"]["version"],
        feedback_id=result[1]["feedback_id"],
    )
    assert completed[0] == 200, completed
    assert completed[1]["status"] == "COMPLETED_CONFIRMED"
    assert due(api, task["task_id"])["state"] == "CANCELED"
    assert due(api, task["task_id"])["version"] == "2"
    assert pages.serve("BOSS", "/api/boss/ui/tasks")[1]["tasks"][0]["status"] == "COMPLETED_CONFIRMED"
