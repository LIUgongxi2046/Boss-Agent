"""Actual SQLite integration checks for Boss Agent FR-06/FR-28 mutations.

They test one authorized BOSS, one MAINTAINER feedback author, business
versioning, idempotency and evidence requirements. No model/network required.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "validation"))
from boss_command_api import BossCommandAPI  # noqa: E402
from controls import ControlStore  # noqa: E402


@pytest.fixture
def demo(tmp_path):
    store = ControlStore(tmp_path / "boss.sqlite")
    store.initialize("ui-check")
    return BossCommandAPI(store)


def create_input(key="owner-created-001", **changes):
    return {
        "client_request_id": key,
        "purpose": "核查饲料外销经营明细并准备会议",
        "coordinator_id": "coordinator-1",
        "due_at": "2026-10-24T17:00:00+08:00",
        "timezone": "Asia/Shanghai",
        "evidence_requirements": ["经营原始明细"],
        "related_meeting_id": "meeting-1",
        "related_event_ids": ["event-1"],
        "source_refs": ["finance-note"],
        "content_version": "1",
        **changes,
    }


def create(demo, key="owner-created-001"):
    code, out = demo.execute("BOSS", "boss.assignment.create", create_input(key))
    assert code == 200, out
    return out


def send_input(created, key="owner-send-00001"):
    return {
        "client_request_id": key,
        "task_id": created["task_id"],
        "task_version": created["version"],
        "recipient_id": "coordinator-1",
        "body": "请核查经营数据并提供来源证据",
        "content_version": "1",
    }


def feedback_input(created, kind="RESULT_SUBMITTED", key="sim-feedback-0001", evidence=None):
    return {
        "client_request_id": key,
        "task_id": created["task_id"],
        "task_version": created["version"],
        "author_contact_id": "coordinator-1",
        "kind": kind,
        "content": "已按要求提供核查结果与原始明细",
        "evidence_refs": evidence if evidence is not None else ["finance-note"],
    }


def test_create_is_atomic_authorized_versioned_and_deduplicated(demo):
    data = create_input()
    c1, result1 = demo.execute("BOSS", "boss.assignment.create", data)
    c2, result2 = demo.execute("BOSS", "boss.assignment.create", data)
    assert c1 == c2 == 200
    assert result1 == result2
    assert result1["source_type"] == "SIMULATED"
    assert result1["status"] == "OPEN"
    with demo.store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind='task'").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind='authorization'").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM audit WHERE operation='boss.assignment.create'").fetchone()[0] == 1


def test_conflicting_key_cannot_create_second_assignment(demo):
    create(demo)
    status, body = demo.execute("BOSS", "boss.assignment.create",
                                create_input(purpose="变更后的内容"))
    assert status == 409
    assert body["error"] == "VERSION_OR_IDEMPOTENCY_CONFLICT"
    with demo.store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind='task'").fetchone()[0] == 1


def test_other_roles_cannot_issue_boss_writes(demo):
    for role in (None, "MAINTAINER", "OTHER"):
        code, _ = demo.execute(role, "boss.assignment.create", create_input())
        assert code in (401, 403)
    assert demo.execute("BOSS", "boss.simulation.feedback", {})[0] == 403
    with demo.store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind='task'").fetchone()[0] == 0


def test_no_identity_or_dataset_override_from_browser(demo):
    for field, value in [("owner_id", "other"), ("authorization_id", "owner-fake"),
                         ("execution_namespace", "another-space"),
                         ("dataset_id", "another-dataset")]:
        code, _ = demo.execute("BOSS", "boss.assignment.create",
                               create_input("new-key-" + field, **{field: value}))
        assert code == 400


def test_invalid_reference_and_outdated_source_never_create(demo):
    for key, changed in [
        ("invalid-coordinator", {"coordinator_id": "contact-2"}),
        ("invalid-meeting", {"related_meeting_id": "unknown"}),
        ("invalid-timezone", {"timezone": "Europe/Paris"}),
        ("invalid-evidence", {"evidence_requirements": []}),
        ("invalid-expiry", {"due_at": "2026-10-20T08:00:00+08:00"}),
    ]:
        code, _ = demo.execute("BOSS", "boss.assignment.create", create_input(key, **changed))
        assert code == 400, key
    demo.store.control("ui-check", "withdraw", {"source_id": "finance-note", "version": "1"})
    assert demo.execute("BOSS", "boss.assignment.create", create_input("after-withdraw"))[0] == 403
    with demo.store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind='task'").fetchone()[0] == 0


def test_send_is_simulated_not_real_external_delivery(demo):
    task = create(demo)
    payload = send_input(task)
    code, result = demo.execute("BOSS", "boss.assignment.send", payload)
    assert code == 200, result
    assert result["source_type"] == "SIMULATED"
    assert result["message_status"] == "SENT"
    assert result["task_status"] == "WAITING_FEEDBACK"
    assert demo.execute("BOSS", "boss.assignment.send", payload)[1] == result
    with demo.store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind='outbox'").fetchone()[0] == 1


def test_send_rejects_changed_version_wrong_recipient(demo):
    task = create(demo)
    bad = send_input(task)
    bad["recipient_id"] = "contact-2"
    assert demo.execute("BOSS", "boss.assignment.send", bad)[0] == 403
    bad2 = send_input(task, "owner-send-00002")
    bad2["task_version"] = "99"
    assert demo.execute("BOSS", "boss.assignment.send", bad2)[0] == 409


def test_maintainer_feedback_is_not_owner_completion(demo):
    created = create(demo)
    send = demo.execute("BOSS", "boss.assignment.send", send_input(created))[1]
    feedback = feedback_input({
        "task_id": created["task_id"], "version": send["task_version"]
    })
    code, result = demo.execute("MAINTAINER", "boss.simulation.feedback", feedback)
    assert code == 200, result
    assert result["task"]["status"] == "RESULT_SUBMITTED"
    assert demo.execute("MAINTAINER", "boss.simulation.feedback", feedback)[1] == result
    # Owner never confirmed the completion yet.
    with demo.store.connect() as db:
        task = demo.store.get(db, "ui-check", "task", created["task_id"])
        assert task["status"] == "RESULT_SUBMITTED"


def test_complete_requires_feedback_evidence_and_explicit_owner(demo):
    created = create(demo)
    sent = demo.execute("BOSS", "boss.assignment.send", send_input(created))[1]
    no_feedback = {
        "client_request_id": "complete-before-feedback",
        "task_id": created["task_id"],
        "task_version": sent["task_version"],
        "feedback_id": "unknown",
    }
    assert demo.execute("BOSS", "boss.assignment.complete", no_feedback)[0] == 404
    simulated = demo.execute("MAINTAINER", "boss.simulation.feedback",
        feedback_input({"task_id": created["task_id"], "version": sent["task_version"]}))[1]
    complete = {
        "client_request_id": "complete-owner-001",
        "task_id": created["task_id"],
        "task_version": simulated["task"]["version"],
        "feedback_id": simulated["feedback_id"],
    }
    code, completed = demo.execute("BOSS", "boss.assignment.complete", complete)
    assert code == 200, completed
    assert completed["status"] == "COMPLETED_CONFIRMED"
    assert demo.execute("BOSS", "boss.assignment.complete", complete)[1] == completed
    with demo.store.connect() as db:
        task = demo.store.get(db, "ui-check", "task", created["task_id"])
        assert task["completion_authorization_id"] == completed["authorization_id"]


def test_cancel_preserves_sent_message_and_blocks_late_feedback(demo):
    created = create(demo)
    sent = demo.execute("BOSS", "boss.assignment.send", send_input(created))[1]
    status, canceled = demo.execute("BOSS", "boss.assignment.cancel", {
        "client_request_id": "owner-cancel-001",
        "task_id": created["task_id"],
        "task_version": sent["task_version"],
        "reason": "该交办不再继续",
    })
    assert status == 200, canceled
    assert canceled["status"] == "CANCELED"
    assert canceled["previous_message_ids"] == [sent["message_id"]]
    assert demo.execute("MAINTAINER", "boss.simulation.feedback", feedback_input({
        "task_id": created["task_id"], "version": canceled["version"]
    }))[0] == 409
    with demo.store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind='outbox'").fetchone()[0] == 1


def test_progress_and_extension_request_do_not_change_due_automatically(demo):
    created = create(demo)
    sent = demo.execute("BOSS", "boss.assignment.send", send_input(created))[1]
    fb = feedback_input({"task_id": created["task_id"], "version": sent["task_version"]},
                        "EXTENSION_REQUEST", "feedback-extension-001", evidence=[])
    status, response = demo.execute("MAINTAINER", "boss.simulation.feedback", fb)
    assert status == 200, response
    with demo.store.connect() as db:
        task = demo.store.get(db, "ui-check", "task", created["task_id"])
        assert task["due_at"] == "2026-10-24T17:00:00+08:00"
    code, ext = demo.execute("BOSS", "boss.assignment.extend", {
        "client_request_id": "owner-extend-001",
        "task_id": created["task_id"],
        "task_version": response["task"]["version"],
        "feedback_id": response["feedback_id"],
        "due_at": "2026-10-26T17:00:00+08:00",
    })
    assert code == 200, ext
    assert ext["due_at"] == "2026-10-26T17:00:00+08:00"
    assert demo.execute("BOSS", "boss.assignment.extend", {
        "client_request_id": "owner-extend-001",
        "task_id": created["task_id"],
        "task_version": response["task"]["version"],
        "feedback_id": response["feedback_id"],
        "due_at": "2026-10-26T17:00:00+08:00",
    })[1] == ext


def test_unknown_action_and_bad_content_return_safe_error(demo):
    assert demo.execute("BOSS", "boss.root", {})[0] == 404
    assert demo.execute("BOSS", "boss.assignment.create", None)[0] == 400
    assert demo.execute("BOSS", "boss.assignment.create", create_input(key="x"))[0] == 400
    code, result = demo.execute("BOSS", "boss.assignment.create",
        create_input("bad-timezone-001", due_at="not-a-date"))
    assert code == 400
    assert "Traceback" not in str(result)
