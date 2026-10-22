"""PRD FR-08/FR-12/E01-E06: receipt reconciliation and busy-share validity.

Domain objects are persisted in actual SQLite. No DeepSeek call or fake
external delivery. The receipt route is read-only, authenticated and
whitelisted; missing receipt never proves an operation was not delivered.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from urllib.parse import urlencode

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "validation"))
from boss_command_api import BossCommandAPI  # noqa: E402
from boss_page_api import BossPageAPI  # noqa: E402
from controls import ControlStore  # noqa: E402


@pytest.fixture
def context(tmp_path):
    store = ControlStore(tmp_path / "recovery.sqlite")
    store.initialize("ui-check")
    return BossCommandAPI(store), BossPageAPI(store)


def act(commands, role, action, key, **params):
    return commands.execute(role, action, {"client_request_id": key, **params})


def receipt(page_api, role, action, key):
    return page_api.serve(
        role, "/api/boss/ui/operation-status",
        urlencode({"action": action, "client_request_id": key}),
    )


def save_private(commands, key="calendar-recovery-save"):
    return act(
        commands, "BOSS", "boss.calendar.save", key,
        expected_version="1",
        starts_at="2026-10-24T18:00:00+08:00",
        ends_at="2026-10-24T19:00:00+08:00",
        timezone="Asia/Shanghai", title="隐私标题",
        private_body="OWNER_CALENDAR_SECRET_NOT_FOR_TECHNICAL_READ",
        location="私人地点", attachment_refs=[],
        acknowledge_conflict=False,
    )


def share_busy(commands, version="2", key="calendar-recovery-share"):
    return act(
        commands, "BOSS", "boss.calendar.share", key,
        expected_version=version, recipient_id="coordinator-1",
        purpose="BUSY_PURPOSE_SECRET_NOT_FOR_RECIPIENT",
        expires_at="2026-10-25T08:00:00+08:00",
        fields=["busy", "starts_at", "ends_at", "timezone"],
    )


def draft(commands, key="draft-recovery-create", refs=None):
    return act(
        commands, "BOSS", "boss.message.draft.save", key,
        draft_id=None, expected_version="0",
        recipient_id="coordinator-1", related_task_id=None,
        body="OWNER_DRAFT_PRIVATE_CONTENT", attachment_refs=refs or [],
        visibility="RECIPIENT_ONLY",
    )


def test_uncertain_mutation_can_check_original_receipt_without_side_effect(context):
    commands, pages = context
    _, absent = receipt(pages, "BOSS", "boss.message.draft.save", "draft-recovery-create")
    assert absent["outcome"] == "NOT_FOUND_IN_CURRENT_STORE"
    assert absent["not_proof_of_failed_delivery"]
    assert absent["safe_same_key_retry"]
    code, created = draft(commands)
    assert code == 200, created
    with commands.store.connect() as db:
        before = db.execute("SELECT COUNT(*) FROM idempotency").fetchone()[0]
    status, found = receipt(pages, "BOSS", "boss.message.draft.save", "draft-recovery-create")
    assert status == 200
    assert found["outcome"] == "RECORDED"
    assert found["result"]["draft_id"] == created["draft_id"]
    assert found["result"]["status"] == "DRAFT"
    assert found["write_performed_by_lookup"] is False
    assert "OWNER_DRAFT_PRIVATE_CONTENT" not in json.dumps(found)
    with commands.store.connect() as db:
        after = db.execute("SELECT COUNT(*) FROM idempotency").fetchone()[0]
    assert before == after


def test_cross_role_and_unknown_receipt_queries_fail_closed(context):
    commands, pages = context
    assert draft(commands)[0] == 200
    assert receipt(pages, "MAINTAINER", "boss.message.draft.save",
                   "draft-recovery-create")[0] == 403
    assert receipt(pages, None, "boss.message.draft.save",
                   "draft-recovery-create")[0] == 401
    assert receipt(pages, "BOSS", "boss.no.such.action", "draft-recovery-create")[0] == 404
    assert pages.serve("BOSS", "/api/boss/ui/operation-status",
                       "action=boss.message.draft.save&client_request_id=x")[0] == 400
    assert pages.serve("BOSS", "/api/boss/ui/operation-status",
                       "action=boss.message.draft.save&client_request_id=valid-id-100"
                       "&client_request_id=valid-id-200")[0] == 400
    assert pages.serve("MAINTAINER", "/api/boss/ui/calendar-share-preview",
                       "share_id=busy-share-invalid")[0] == 403


def test_message_send_reconciliation_retains_accepted_receipt_without_replay(context):
    commands, pages = context
    code, created = draft(commands)
    assert code == 200
    outbox = pages.serve("BOSS", "/api/boss/ui/workspace/outbox")[1]
    item = next(row for row in outbox["drafts"] if row["draft_id"] == created["draft_id"])
    sent = act(
        commands, "BOSS", "boss.message.send", "message-send-original-001",
        draft_id=created["draft_id"], expected_version="1",
        recipient_id="coordinator-1", expected_content_sha256=item["content_sha256"],
    )
    assert sent[0] == 200
    status, outcome = receipt(pages, "BOSS", "boss.message.send", "message-send-original-001")
    assert status == 200
    assert outcome["result"]["message_id"] == sent[1]["message_id"]
    assert outcome["result"]["delivery_state"] == "NOT_VERIFIED"
    assert outcome["result"]["external_channel_invoked"] is False
    with commands.store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind='message_outbox'").fetchone()[0] == 1
    again = act(
        commands, "BOSS", "boss.message.send", "message-send-original-001",
        draft_id=created["draft_id"], expected_version="1",
        recipient_id="coordinator-1", expected_content_sha256=item["content_sha256"],
    )
    assert again == sent


def test_duplicate_attachment_ids_and_mismatched_versions_rejected(context):
    commands, _ = context
    refs = [
        {"source_id": "finance-note", "version": "1"},
        {"source_id": "finance-note", "version": "2"},
    ]
    assert draft(commands, "dup-source-refs", refs=refs)[0] == 400
    assert draft(commands, "bad-source-version",
                 refs=[{"source_id": "finance-note", "version": "2"}])[0] == 409
    with commands.store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind='message_draft'").fetchone()[0] == 0


def test_busy_preview_is_private_content_free_and_role_restricted(context):
    commands, pages = context
    assert save_private(commands)[0] == 200
    code, share = share_busy(commands)
    assert code == 200, share
    path = "share_id=" + share["share_id"]
    status, preview = pages.serve("BOSS", "/api/boss/ui/calendar-share-preview", path)
    assert status == 200, preview
    assert preview["share_status"] == "ACTIVE_SIMULATED"
    assert preview["preview_only_not_external_access"] is True
    assert preview["external_delivery_created"] is False
    assert set(preview["fields"]) == {"busy", "starts_at", "ends_at", "timezone"}
    assert "OWNER_CALENDAR_SECRET_NOT_FOR_TECHNICAL_READ" not in json.dumps(preview)
    assert "BUSY_PURPOSE_SECRET_NOT_FOR_RECIPIENT" not in json.dumps(preview)
    assert "私人地点" not in json.dumps(preview)
    assert pages.serve("MAINTAINER", "/api/boss/ui/calendar-share-preview", path)[0] == 403


def test_expired_share_disappears_from_effective_preview_but_keeps_history(context):
    commands, pages = context
    assert save_private(commands)[0] == 200
    sh = share_busy(commands)[1]
    status, current = pages.serve("BOSS", "/api/boss/ui/workspace/calendar")
    assert status == 200
    assert current["shares"][0]["effective_state"] == "ACTIVE_SIMULATED"
    clock = act(
        commands, "MAINTAINER", "boss.simulation.clock.advance",
        "simulate-future-001", at="2026-10-25T09:00:00+08:00",
    )
    assert clock[0] == 200, clock
    after = pages.serve("BOSS", "/api/boss/ui/workspace/calendar")[1]
    assert after["shares"][0]["effective_state"] == "EXPIRED"
    stat, body = pages.serve("BOSS", "/api/boss/ui/calendar-share-preview",
                             "share_id=" + sh["share_id"])
    assert stat == 410 and body["share_status"] == "EXPIRED"
    assert "busy" not in body


def test_calendar_new_version_and_revocation_invalidate_preview(context):
    commands, pages = context
    assert save_private(commands)[0] == 200
    sh = share_busy(commands)[1]
    revoke = act(
        commands, "BOSS", "boss.calendar.share.revoke", "revoke-private-001",
        share_id=sh["share_id"], expected_version="2",
    )
    assert revoke[0] == 200
    status, body = pages.serve("BOSS", "/api/boss/ui/calendar-share-preview",
                               "share_id=" + sh["share_id"])
    assert status == 410 and body["share_status"] == "REVOKED"

    sh2 = share_busy(commands, key="calendar-recovery-share-second")[1]
    edit = act(
        commands, "BOSS", "boss.calendar.save", "calendar-recovery-edit-001",
        expected_version="2",
        starts_at="2026-10-24T18:00:00+08:00",
        ends_at="2026-10-24T19:00:00+08:00",
        timezone="Asia/Shanghai", title="修改后私人标题",
        private_body="PRIVATE_REPLACED", location="", attachment_refs=[],
        acknowledge_conflict=False,
    )
    assert edit[0] == 200, edit
    stat, body = pages.serve("BOSS", "/api/boss/ui/calendar-share-preview",
                             "share_id=" + sh2["share_id"])
    assert stat == 410
    assert body["share_status"] in ("REVOKED", "OUTDATED")


@pytest.mark.parametrize("expiry",[
    "2026-10-21T12:00:00+08:00",
    "2028-10-25T09:00:00+08:00",
])
def test_calendar_share_requires_future_and_bounded_expiry(context, expiry):
    commands, _ = context
    assert save_private(commands)[0] == 200
    status, _ = act(
        commands, "BOSS", "boss.calendar.share", "invalid-expiry-001",
        expected_version="2", recipient_id="coordinator-1",
        purpose="只共享忙碌", expires_at=expiry,
        fields=["busy", "starts_at", "ends_at", "timezone"],
    )
    assert status == 400
    with commands.store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind='calendar_share'").fetchone()[0] == 0



def test_owner_cannot_use_message_reply_to_bypass_assignment_send(context):
    commands, pages = context
    status, task = act(
        commands, "BOSS", "boss.assignment.create", "guard-task-create-001",
        purpose="核查经营原始凭证", coordinator_id="coordinator-1",
        due_at="2026-10-24T17:00:00+08:00", timezone="Asia/Shanghai",
        evidence_requirements=["经营原始明细"],
        related_meeting_id="meeting-1", related_event_ids=["event-1"],
        source_refs=["finance-note"], content_version="1",
    )
    assert status == 200, task
    created = act(
        commands, "BOSS", "boss.message.draft.save", "guard-msg-draft-001",
        draft_id=None, expected_version="0", recipient_id="coordinator-1",
        related_task_id=task["task_id"], body="请确认交办已经到达",
        attachment_refs=[], visibility="RECIPIENT_ONLY",
    )
    assert created[0] == 200, created
    message = pages.serve("BOSS", "/api/boss/ui/workspace/outbox")[1]["drafts"][0]
    status, _ = act(
        commands, "BOSS", "boss.message.send", "guard-msg-send-001",
        draft_id=message["draft_id"], expected_version="1",
        recipient_id="coordinator-1",
        expected_content_sha256=message["content_sha256"],
    )
    assert status == 409
    with commands.store.connect() as db:
        task_after = commands.store.get(db, "ui-check", "task", task["task_id"])
        assert task_after["status"] == "OPEN"
        assert db.execute(
            "SELECT COUNT(*) FROM objects WHERE kind='message_outbox'"
        ).fetchone()[0] == 0
        assert db.execute(
            "SELECT COUNT(*) FROM objects WHERE kind='feedback'"
        ).fetchone()[0] == 0


def test_f06_owner_can_reconcile_actual_saved_assignment(context):
    commands, pages = context
    created = act(
        commands, "BOSS", "boss.assignment.create", "recover-assignment-owner",
        purpose="核实业务情况", coordinator_id="coordinator-1",
        due_at="2026-10-24T17:00:00+08:00", timezone="Asia/Shanghai",
        evidence_requirements=["经营原始明细"],
        related_meeting_id="meeting-1", related_event_ids=["event-1"],
        source_refs=["finance-note"], content_version="1",
    )
    assert created[0] == 200
    status, result = receipt(
        pages, "BOSS", "boss.assignment.create", "recover-assignment-owner"
    )
    assert status == 200
    assert result["result"]["task_id"] == created[1]["task_id"]
    assert result["outcome"] == "RECORDED"
    assert "purpose" not in json.dumps(result)
    assert receipt(
        pages, "MAINTAINER", "boss.assignment.create", "recover-assignment-owner"
    )[0] == 403


def test_parallel_same_request_id_does_not_create_two_simulated_messages(context):
    from concurrent.futures import ThreadPoolExecutor
    commands, pages = context
    assert draft(commands, "parallel-draft-owner")[0] == 200
    entry = pages.serve("BOSS", "/api/boss/ui/workspace/outbox")[1]["drafts"][0]
    params = {
        "draft_id": entry["draft_id"], "expected_version": entry["version"],
        "recipient_id": "coordinator-1",
        "expected_content_sha256": entry["content_sha256"],
    }
    def submit():
        return act(
            commands, "BOSS", "boss.message.send", "parallel-message-owner", **params
        )
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: submit(), range(2)))
    assert all(status == 200 for status, _ in results), results
    assert results[0][1]["message_id"] == results[1][1]["message_id"]
    with commands.store.connect() as db:
        assert db.execute(
            "SELECT COUNT(*) FROM objects WHERE kind='message_outbox'"
        ).fetchone()[0] == 1
        assert db.execute(
            "SELECT COUNT(*) FROM audit WHERE operation='boss.message.send'"
        ).fetchone()[0] == 1



def test_contact_validity_uses_current_simulated_time_not_old_meeting_date(context):
    commands, pages = context
    assert save_private(commands)[0] == 200
    code, clock = act(
        commands, "MAINTAINER", "boss.simulation.clock.advance",
        "advance-beyond-contact-001", at="2027-02-01T09:00:00+08:00",
    )
    assert code == 200, clock
    expired_draft = draft(commands, "draft-contact-expired-001")
    assert expired_draft[0] == 403
    assert act(
        commands, "BOSS", "boss.calendar.share", "calendar-contact-expired",
        expected_version="2", recipient_id="coordinator-1",
        purpose="现在联系人资料已过期", expires_at="2027-02-05T08:00:00+08:00",
        fields=["busy", "starts_at", "ends_at", "timezone"],
    )[0] == 403
    with commands.store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind='message_draft'").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind='calendar_share'").fetchone()[0] == 0
