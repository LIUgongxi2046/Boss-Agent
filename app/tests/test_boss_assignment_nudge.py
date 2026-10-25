"""PRD FR06 owner-authorized nudge after sending a task.

Real SQLite + role/idempotency/CAS/provenance tests. Synthetic only.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "validation"))
from boss_command_api import BossCommandAPI  # noqa: E402
from boss_page_api import BossPageAPI  # noqa: E402
from controls import ControlStore  # noqa: E402

PRIVATE_BODY = "仅模拟催办：请说明资料核查进度与预计完成时间。"


@pytest.fixture
def services(tmp_path):
    store = ControlStore(tmp_path / "nudge.sqlite")
    store.initialize("ui-check")
    return BossCommandAPI(store), BossPageAPI(store)


def command(api, role, action, key, **fields):
    return api.execute(role, action, {"client_request_id": key, **fields})


def create(api):
    status, result = command(
        api, "BOSS", "boss.assignment.create", "nudge-task-create",
        purpose="核查历史经营承诺的反馈来源",
        coordinator_id="coordinator-1",
        due_at="2026-10-26T17:00:00+08:00",
        timezone="Asia/Shanghai",
        evidence_requirements=["经营原始明细"],
        related_meeting_id="meeting-1",
        related_event_ids=["event-1"],
        source_refs=["finance-note"],
        content_version="1",
    )
    assert status == 200, result
    return result


def send(api, created):
    status, result = command(
        api, "BOSS", "boss.assignment.send", "nudge-first-send",
        task_id=created["task_id"], task_version=created["version"],
        recipient_id="coordinator-1", body="请核对经营原始资料",
        content_version="1",
    )
    assert status == 200, result
    return result


def nudge_input(created, version, **fields):
    return {
        "task_id": created["task_id"], "task_version": version,
        "recipient_id": "coordinator-1", "body": PRIVATE_BODY,
        **fields,
    }


def test_nudge_requires_original_task_send_not_open(services):
    api, pages = services
    created = create(api)
    code, _ = command(
        api, "BOSS", "boss.assignment.nudge", "nudge-before-send",
        **nudge_input(created, created["version"]),
    )
    assert code == 409
    assert pages.serve("BOSS", "/api/boss/ui/tasks")[1]["linked_messages"] == []


def test_nudge_is_role_bound_and_preserves_task_state(services):
    api, pages = services
    created = create(api)
    sent = send(api, created)
    args = nudge_input(created, sent["task_version"])
    assert command(api, "MAINTAINER", "boss.assignment.nudge",
                   "maintainer-denied-nudge", **args)[0] == 403
    status, result = command(api, "BOSS", "boss.assignment.nudge", "valid-nudge-01", **args)
    assert status == 200, result
    assert result["send_state"] == "SENT_SIMULATED"
    assert result["delivery_state"] == "NOT_VERIFIED"
    assert result["reply_state"] == "NOT_RECEIVED"
    assert result["task_status_changed"] is False
    assert result["external_channel_invoked"] is False
    assert result["status"] == "WAITING_FEEDBACK"
    assert command(api, "BOSS", "boss.assignment.nudge", "valid-nudge-01", **args) == (status, result)
    with api.store.connect() as db:
        task = api.store.get(db, "ui-check", "task", created["task_id"])
        assert task["version"] == sent["task_version"]
        assert task["status"] == "WAITING_FEEDBACK"
        out = db.execute("SELECT body FROM objects WHERE kind='assignment_nudge'").fetchall()
        assert len(out) == 1
        assert PRIVATE_BODY in out[0][0]
        auth = db.execute("SELECT body FROM objects WHERE kind='authorization'").fetchall()
        assert PRIVATE_BODY not in str(auth)
        assert result["authorization_id"]
        assert db.execute(
            "SELECT COUNT(*) FROM audit WHERE operation='boss.assignment.nudge'"
        ).fetchone()[0] == 1
    payload = pages.serve("BOSS", "/api/boss/ui/tasks")[1]
    nudge_row = next(m for m in payload["linked_messages"]
                     if m["type"] == "ASSIGNMENT_NUDGE")
    assert nudge_row["message_id"] == result["message_id"]
    assert nudge_row["task_id"] == created["task_id"]
    assert nudge_row["external_channel_invoked"] is False
    assert "body" not in nudge_row
    assert PRIVATE_BODY not in json.dumps(payload["linked_messages"])


def test_new_id_cannot_nudge_same_task_within_24h(services):
    api, _ = services
    created = create(api)
    sent = send(api, created)
    args = nudge_input(created, sent["task_version"])
    assert command(api, "BOSS", "boss.assignment.nudge", "nudge-first", **args)[0] == 200
    assert command(api, "BOSS", "boss.assignment.nudge", "nudge-second", **args)[0] == 409


def test_nudge_after_advancing_simulated_clock_is_distinct(services):
    api, pages = services
    created = create(api)
    sent = send(api, created)
    args = nudge_input(created, sent["task_version"])
    first = command(api, "BOSS", "boss.assignment.nudge", "nudge-d1", **args)
    assert first[0] == 200
    advanced = command(
        api, "MAINTAINER", "boss.simulation.clock.advance", "nudge-clock-d2",
        at="2026-10-24T11:00:00+08:00",
    )
    assert advanced[0] == 200, advanced
    second = command(api, "BOSS", "boss.assignment.nudge", "nudge-d2", **args)
    assert second[0] == 200, second
    assert first[1]["message_id"] != second[1]["message_id"]
    sent_rows = [row for row in pages.serve("BOSS", "/api/boss/ui/tasks")[1]["linked_messages"]
                 if row["type"] == "ASSIGNMENT_NUDGE"]
    assert len(sent_rows) == 2


@pytest.mark.parametrize("field,wrong,expected", [
    ("task_version", "999", 409),
    ("recipient_id", "contact-2", 403),
    ("body", "", 400),
])
def test_nudge_rejects_stale_version_wrong_recipient_or_empty_body(
        services, field, wrong, expected):
    api, _ = services
    created = create(api)
    sent = send(api, created)
    args = nudge_input(created, sent["task_version"], **{field: wrong})
    assert command(api, "BOSS", "boss.assignment.nudge",
                   "nudge-invalid-"+field, **args)[0] == expected
    with api.store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind='assignment_nudge'").fetchone()[0] == 0


def test_nudge_rejects_withdrawn_origin_and_regular_source(services):
    api, _ = services
    created = create(api)
    sent = send(api, created)
    api.store.control("ui-check", "withdraw", {"source_id": "finance-note", "version": "1"})
    assert command(api, "BOSS", "boss.assignment.nudge", "nudge-old-source",
                   **nudge_input(created, sent["task_version"]))[0] == 410


def test_nudge_rejects_result_submitted_without_changing_result(services):
    api, pages = services
    created = create(api)
    sent = send(api, created)
    status, feedback = command(
        api, "MAINTAINER", "boss.simulation.feedback", "nudge-result-feedback",
        task_id=created["task_id"], task_version=sent["task_version"],
        author_contact_id="coordinator-1", kind="RESULT_SUBMITTED",
        content="已有正式模拟结果及有效资料",
        evidence_refs=["finance-note"],
    )
    assert status == 200, feedback
    new_version = feedback["task"]["version"]
    result = command(api, "BOSS", "boss.assignment.nudge", "nudge-submitted",
                     **nudge_input(created, new_version))
    assert result[0] == 409
    task = next(t for t in pages.serve("BOSS", "/api/boss/ui/tasks")[1]["tasks"]
                if t["task_id"] == created["task_id"])
    assert task["status"] == "RESULT_SUBMITTED"


def test_nudge_follows_owner_and_original_message_role_boundaries(services):
    api, pages = services
    created = create(api)
    sent = send(api, created)
    args = nudge_input(created, sent["task_version"])
    assert command(api, "BOSS", "boss.assignment.nudge", "nudge-tamper",
                   **{**args, "owner_id": "other"})[0] == 400
    assert command(api, "BOSS", "boss.assignment.nudge", "nudge-tamper2",
                   **{**args, "authorization_id": "fake"})[0] == 400
    assert pages.serve("MAINTAINER", "/api/boss/ui/tasks")[0] == 403
