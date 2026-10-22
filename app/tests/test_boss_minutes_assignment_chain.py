"""FR-05 -> FR-06 confirmed minute entry -> independently sent task integration.

All assertions exercise the actual ControlStore SQLite transaction, business
authorization, idempotency, and owner/maintainer role boundaries. No AI key,
external delivery, made-up task, or real contact account is involved.
"""
from __future__ import annotations

import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "validation"))
from boss_command_api import BossCommandAPI  # noqa: E402
from boss_page_api import BossPageAPI  # noqa: E402
from controls import ControlStore  # noqa: E402


@pytest.fixture
def app(tmp_path):
    store = ControlStore(tmp_path / "minutes-task.sqlite")
    store.initialize("ui-check")
    return BossCommandAPI(store), BossPageAPI(store)


def call(cmd, role, action, key, **values):
    return cmd.execute(role, action, {"client_request_id": key, **values})


def save_minutes(cmd, key="link-save-minutes-001"):
    return call(
        cmd, "BOSS", "boss.minutes.save", key,
        meeting_id="meeting-1", meeting_version="1",
        source_id="meeting-minutes", source_version="1",
        expected_version="0",
        entries=[
            {"kind": "OPINION", "text": "目前讨论中，没有授权执行",
             "source_anchor": "历史会议纪要"},
            {"kind": "ASSIGNMENT_DRAFT",
             "text": "候选交办：核查未完成经营材料",
             "source_anchor": "coordinator-1"},
        ],
    )


def confirm_minutes(cmd):
    return call(
        cmd, "BOSS", "boss.minutes.confirm", "link-confirm-minutes-001",
        meeting_id="meeting-1", expected_version="1",
        source_id="meeting-minutes", source_version="1",
    )


def create_payload(entry="entry-02", version="2"):
    return {
        "meeting_id": "meeting-1", "minute_version": version,
        "entry_id": entry, "purpose": "逐项核对原始经营材料并提交完整证据",
        "coordinator_id": "coordinator-1",
        "due_at": "2026-10-24T17:00:00+08:00",
        "timezone": "Asia/Shanghai",
        "evidence_requirements": ["经营原始明细"],
    }


def create_linked_task(cmd, key="link-task-owner-001", **changes):
    return call(
        cmd, "BOSS", "boss.minutes.assignment.create", key,
        **{**create_payload(), **changes},
    )


def minutes(page):
    return page.serve("BOSS", "/api/boss/ui/workspace/minutes")


def tasks(page):
    return page.serve("BOSS", "/api/boss/ui/tasks")


def test_before_confirmation_cannot_create_and_opinion_is_not_assignment(app):
    cmd, page = app
    assert create_linked_task(cmd)[0] == 404
    assert save_minutes(cmd)[0] == 200
    assert create_linked_task(cmd, "draft-not-confirmed")[0] == 409
    assert confirm_minutes(cmd)[0] == 200
    status, _ = create_linked_task(cmd, "opinion-is-not-task", entry_id="entry-01")
    assert status == 400
    assert call(
        cmd, "MAINTAINER", "boss.minutes.assignment.create",
        "maintenance-cannot-assign", **create_payload(),
    )[0] == 403
    with cmd.store.connect() as db:
        assert db.execute(
            "SELECT COUNT(*) FROM objects WHERE kind='task'"
        ).fetchone()[0] == 0


def test_explicit_confirmed_entry_creates_one_open_linked_task_not_message(app):
    cmd, page = app
    assert save_minutes(cmd)[0] == 200
    assert confirm_minutes(cmd)[0] == 200
    code, out = create_linked_task(cmd)
    assert code == 200, out
    assert out["status"] == "OPEN"
    assert out["minute_version"] == "2"
    assert out["entry_id"] == "entry-02"
    assert out["message_sent"] is False
    assert out["independent_send_required"] is True
    assert out["authorization_id"]
    code, minute = minutes(page)
    assert code == 200
    assert minute["task_created_by_minutes"] is True
    assert minute["message_sent_by_minutes"] is False
    assert minute["minute"]["state"] == "CONFIRMED"
    assert minute["minute"]["version"] == "2"  # immutable after task creation
    assert len(minute["linked_assignments"]) == 1
    link = minute["linked_assignments"][0]
    assert link["entry_id"] == "entry-02"
    assert link["task_id"] == out["task_id"]
    assert link["task_status"] == "OPEN"
    assert link["send_status"] == "NOT_SENT"
    code, task_view = tasks(page)
    assert code == 200
    assert len(task_view["tasks"]) == 1
    task = task_view["tasks"][0]
    assert task["origin_minute_id"] == "minutes:meeting-1"
    assert task["origin_minute_version"] == "2"
    assert task["origin_entry_id"] == "entry-02"
    assert task["origin_source_id"] == "meeting-minutes"
    assert task["origin_source_version"] == "1"
    with cmd.store.connect() as db:
        assert db.execute(
            "SELECT COUNT(*) FROM objects WHERE kind='outbox'"
        ).fetchone()[0] == 0
        assert db.execute(
            "SELECT COUNT(*) FROM objects WHERE kind='message_outbox'"
        ).fetchone()[0] == 0


def test_replay_and_other_id_can_never_duplicate_same_confirmed_entry(app):
    cmd, _ = app
    save_minutes(cmd)
    confirm_minutes(cmd)
    first = create_linked_task(cmd)
    assert first[0] == 200
    assert create_linked_task(cmd) == first
    assert create_linked_task(cmd, "second-attempt-same-entry")[0] == 409
    assert create_linked_task(cmd, "entry-stale-version", minute_version="1")[0] == 409
    assert create_linked_task(cmd, "bad-entry-id", entry_id="entry-99")[0] == 400
    changed = call(
        cmd, "BOSS", "boss.minutes.assignment.create",
        "link-task-owner-001", **{**create_payload(), "purpose": "不同目的"},
    )
    assert changed[0] == 409
    with cmd.store.connect() as db:
        assert db.execute(
            "SELECT COUNT(*) FROM objects WHERE kind='task'"
        ).fetchone()[0] == 1
        assert db.execute(
            "SELECT COUNT(*) FROM objects WHERE kind='minutes_assignment_link'"
        ).fetchone()[0] == 1


def test_draft_entry_and_finance_source_revocation_block_no_partial_writes(app):
    cmd, page = app
    save_minutes(cmd)
    confirm_minutes(cmd)
    cmd.store.control(
        "ui-check", "withdraw", {"source_id": "meeting-minutes", "version": "1"},
    )
    assert create_linked_task(cmd, "withdrawn-minute-entry")[0] == 403
    with cmd.store.connect() as db:
        assert db.execute(
            "SELECT COUNT(*) FROM objects WHERE kind='task'"
        ).fetchone()[0] == 0
        assert db.execute(
            "SELECT COUNT(*) FROM objects WHERE kind='minutes_assignment_link'"
        ).fetchone()[0] == 0


def test_business_source_withdrawn_blocks_linked_task_without_side_effect(app):
    cmd, page = app
    save_minutes(cmd)
    confirm_minutes(cmd)
    cmd.store.control(
        "ui-check", "withdraw", {"source_id": "finance-note", "version": "1"},
    )
    assert create_linked_task(cmd, "withdrawn-financial-evidence")[0] == 403
    with cmd.store.connect() as db:
        assert db.execute(
            "SELECT COUNT(*) FROM objects WHERE kind='task'"
        ).fetchone()[0] == 0


def test_link_stays_in_sync_after_independently_authorized_send(app):
    cmd, page = app
    save_minutes(cmd)
    confirm_minutes(cmd)
    result = create_linked_task(cmd)[1]
    code, sent = call(
        cmd, "BOSS", "boss.assignment.send", "link-task-send-owner-001",
        task_id=result["task_id"], task_version=result["version"],
        recipient_id="coordinator-1", body="请逐项核实资料、反馈进展并提交依据",
        content_version="1",
    )
    assert code == 200, sent
    code, minute = minutes(page)
    assert code == 200
    assert minute["message_sent_by_minutes"] is True
    link = minute["linked_assignments"][0]
    assert link["task_id"] == result["task_id"]
    assert link["task_status"] == "WAITING_FEEDBACK"
    assert link["send_status"] == "SENT_SIMULATED"
    assert link["sent_message_count"] == 1
    assert minute["minute"]["entries"][1]["task_created"] is False
    # Persisted confirmed minute is immutable; live task linkage is separate.
    with cmd.store.connect() as db:
        saved = cmd.store.get(db, "ui-check", "minutes", "meeting-1")
        assert saved["version"] == "2"
        assert saved["state"] == "CONFIRMED"


def test_concurrent_owner_confirmations_result_in_single_task_and_link(app):
    cmd, page = app
    save_minutes(cmd)
    confirm_minutes(cmd)
    def submit(_):
        return create_linked_task(cmd, "parallel-minute-task-owner")
    with ThreadPoolExecutor(max_workers=2) as ex:
        outcomes = list(ex.map(submit, range(2)))
    assert all(status == 200 for status, _ in outcomes), outcomes
    assert outcomes[0][1]["task_id"] == outcomes[1][1]["task_id"]
    with cmd.store.connect() as db:
        assert db.execute(
            "SELECT COUNT(*) FROM objects WHERE kind='minutes_assignment_link'"
        ).fetchone()[0] == 1
        assert db.execute(
            "SELECT COUNT(*) FROM objects WHERE kind='task'"
        ).fetchone()[0] == 1
        assert db.execute(
            "SELECT COUNT(*) FROM audit WHERE operation='boss.minutes.assignment.create'"
        ).fetchone()[0] == 1


def test_link_provenance_does_not_write_raw_minute_text_to_link_or_audit(app):
    cmd, page = app
    save_minutes(cmd)
    confirm_minutes(cmd)
    result = create_linked_task(cmd)[1]
    with cmd.store.connect() as db:
        link_rows = db.execute(
            "SELECT body FROM objects WHERE kind='minutes_assignment_link'"
        ).fetchall()
        assert len(link_rows) == 1
        assert "候选交办：核查未完成经营材料" not in link_rows[0][0]
        assert "entry_text_sha256" in link_rows[0][0]
        audit = db.execute(
            "SELECT input,output FROM audit WHERE operation='boss.minutes.assignment.create'"
        ).fetchall()
        assert len(audit) == 1
        assert "候选交办" not in str(audit)
        assert result["authorization_id"]
    assert page.serve("MAINTAINER", "/api/boss/ui/workspace/minutes")[0] == 403



def test_reconfirmed_new_minute_version_can_create_new_link_without_rewriting_old_task(app):
    cmd, page = app
    assert save_minutes(cmd)[0] == 200
    assert confirm_minutes(cmd)[0] == 200
    first = create_linked_task(cmd)[1]
    revised_entries = [
        {"kind": "OPINION", "text": "原讨论继续保留",
         "source_anchor": "历史会议纪要"},
        {"kind": "ASSIGNMENT_DRAFT",
         "text": "新版本明确需要独立查证另一批资料",
         "source_anchor": "coordinator-1"},
    ]
    revised = call(
        cmd, "BOSS", "boss.minutes.save", "new-minutes-version-001",
        meeting_id="meeting-1", meeting_version="1",
        source_id="meeting-minutes", source_version="1",
        expected_version="2", entries=revised_entries,
    )
    assert revised[0] == 200 and revised[1]["version"] == "3"
    assert create_linked_task(cmd, "cannot-create-unconfirmed-new-version",
                              minute_version="3")[0] == 409
    confirmed = call(
        cmd, "BOSS", "boss.minutes.confirm", "new-minutes-version-confirm",
        meeting_id="meeting-1", expected_version="3",
        source_id="meeting-minutes", source_version="1",
    )
    assert confirmed[0] == 200 and confirmed[1]["version"] == "4"
    newer = create_linked_task(
        cmd, "new-confirmed-version-task-001", minute_version="4",
        purpose="重新核查当前已确认纪要版本的独立任务",
    )
    assert newer[0] == 200, newer
    assert newer[1]["task_id"] != first["task_id"]
    code, view = minutes(page)
    assert code == 200
    assert len(view["linked_assignments"]) == 2
    versions = {
        x["task_id"]: x["minute_version"] for x in view["linked_assignments"]
    }
    assert versions[first["task_id"]] == "2"
    assert versions[newer[1]["task_id"]] == "4"
    assert view["minute"]["version"] == "4"
    with cmd.store.connect() as db:
        assert db.execute(
            "SELECT COUNT(*) FROM objects WHERE kind='task'"
        ).fetchone()[0] == 2
        assert db.execute(
            "SELECT COUNT(*) FROM objects WHERE kind='minutes_assignment_link'"
        ).fetchone()[0] == 2


def test_wrong_meeting_or_explicit_source_version_cannot_reuse_old_approval(app):
    cmd, page = app
    save_minutes(cmd)
    confirm_minutes(cmd)
    assert create_linked_task(
        cmd, "wrong-meeting-link", meeting_id="unknown-meeting",
    )[0] == 400
    assert create_linked_task(
        cmd, "wrong-minutes-version-link", minute_version="1",
    )[0] == 409
    status, page_body = minutes(page)
    assert status == 200
    assert page_body["linked_assignments"] == []
