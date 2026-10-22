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



def test_f06_detail_reads_task_due_state_from_same_sqlite_source(context):
    api, pages = context
    created = create(api)[1]
    tasks_before = pages.serve("BOSS", "/api/boss/ui/tasks")[1]
    assert tasks_before["task_due_events"] == []

    sent = send(api, created["task_id"])
    assert sent[0] == 200
    status, tasks_after = pages.serve("BOSS", "/api/boss/ui/tasks")
    assert status == 200
    task_due = tasks_after["task_due_events"]
    assert len(task_due) == 1
    assert task_due[0]["task_id"] == created["task_id"]
    assert task_due[0]["event_id"] == "task-due:" + created["task_id"]
    assert task_due[0]["event_state"] == "OPEN"
    assert task_due[0]["dispatch_state"] == "NOT_DISPATCHED"
    assert task_due[0]["external_delivery_verified"] is False
    assert pages.serve("MAINTAINER", "/api/boss/ui/tasks")[0] == 403

    ended = act(
        api, "BOSS", "boss.assignment.cancel", "cancel-task-for-readback",
        task_id=created["task_id"], task_version="2",
        reason="已终止此交办任务，不再催办",
    )
    assert ended[0] == 200
    _, post = pages.serve("BOSS", "/api/boss/ui/tasks")
    assert post["task_due_events"][0]["event_state"] == "CANCELED"
    assert post["task_due_events"][0]["event_version"] == "2"
    assert post["tasks"][0]["status"] == "CANCELED"


def test_task_due_events_are_metadata_only_not_owner_message_bodies(context):
    api, pages = context
    created = create(api)[1]
    status, send_result = act(
        api, "BOSS", "boss.assignment.send", "send-private-text-task",
        task_id=created["task_id"], task_version="1",
        recipient_id="coordinator-1",
        body="ONLY_OWNER_PRIVATE_MESSAGE_MUST_NOT_BE_IN_EVENT",
        content_version="1",
    )
    assert status == 200, send_result
    _, response = pages.serve("BOSS", "/api/boss/ui/tasks")
    assert "ONLY_OWNER_PRIVATE_MESSAGE_MUST_NOT_BE_IN_EVENT" not in json.dumps(
        response["task_due_events"]
    )
    with api.store.connect() as db:
        event = current(db, created["task_id"])
        assert "ONLY_OWNER_PRIVATE_MESSAGE_MUST_NOT_BE_IN_EVENT" not in json.dumps(event)



def test_approved_extension_feedback_cannot_be_reused_for_another_deadline(context):
    api, pages = context
    task = create(api)[1]
    assert send(api, task["task_id"])[0] == 200
    request = act(
        api, "MAINTAINER", "boss.simulation.feedback",
        "one-extension-feedback", task_id=task["task_id"], task_version="2",
        author_contact_id="coordinator-1", kind="EXTENSION_REQUEST",
        content="请允许调整交办截止时间", evidence_refs=[],
        proposed_due_at="2026-10-26T17:00:00+08:00",
    )
    assert request[0] == 200, request
    grant = act(
        api, "BOSS", "boss.assignment.extend", "grant-once-task-extension",
        task_id=task["task_id"], task_version=request[1]["task"]["version"],
        feedback_id=request[1]["feedback_id"], due_at="2026-10-26T17:00:00+08:00",
    )
    assert grant[0] == 200, grant
    event = due(api, task["task_id"])
    repeated = act(
        api, "BOSS", "boss.assignment.extend",
        "bad-repeat-approval-with-new-request-id",
        task_id=task["task_id"], task_version=grant[1]["version"],
        feedback_id=request[1]["feedback_id"], due_at="2026-10-28T17:00:00+08:00",
    )
    assert repeated[0] == 409
    assert due(api, task["task_id"]) == event
    with api.store.connect() as db:
        current_task = api.store.get(db, "ui-check", "task", task["task_id"])
        assert current_task["accepted_extension_feedback_ids"] == [request[1]["feedback_id"]]
        assert current_task["due_at"] == "2026-10-26T17:00:00+08:00"
        assert db.execute(
            "SELECT COUNT(*) FROM audit WHERE operation='boss.assignment.extend'"
        ).fetchone()[0] == 1
