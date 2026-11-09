import sqlite3

import pytest
from aiohttp import web

from agent_run_business_receipts import RunBusinessReceipts
from agent_run_requirements import RunRequirements
from boss_meetings import MeetingAPI
from hermes_domain_intents import preview_domain_intent, save_meeting_draft_in_transaction
from test_agent_run_result import setup_result


def test_meeting_draft_transaction_result_and_source_withdrawal(tmp_path):
    store, runs, results, sink = setup_result(tmp_path)
    RunRequirements(runs, allow_migration=True)
    receipts = RunBusinessReceipts(runs, results.scope, allow_migration=True)
    with runs.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        RunRequirements.save_in_transaction(db, sink.config.run_id, 1, "technical-outputs", ["ACTION_DRAFT", "BUSINESS_RECEIPT"])
        meeting = MeetingAPI(store)._data(db)["meeting"]
        params = {"meeting_id": meeting["meeting_id"], "meeting_version": meeting["version"], "expected_version": "0", "purpose": "核查模拟会议材料", "starts_at": meeting["starts_at"], "ends_at": "2026-10-23T10:00:00+08:00", "timezone": "Asia/Shanghai", "preparation_due_at": "2026-10-22T17:00:00+08:00", "participant_ids": ["coordinator-1"], "source_refs": [{"source_id": "finance-note", "version": "1"}]}
    with runs.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        db.row_factory = sqlite3.Row
        run = db.execute("SELECT * FROM agent_runs WHERE run_id=?", (sink.config.run_id,)).fetchone()
        saved = save_meeting_draft_in_transaction(db, store, results.scope, run, params, "technical-meeting-draft")
        assert saved["status"] == "DRAFT"
        assert save_meeting_draft_in_transaction(db, store, results.scope, run, params, "technical-meeting-draft") == saved
        db.rollback()
    with runs.connect() as db:
        assert db.execute("SELECT count(*) FROM objects WHERE kind='meeting_draft'").fetchone() == (0,)
        assert db.execute("SELECT count(*) FROM idempotency WHERE operation='boss.meeting.draft.save'").fetchone() == (0,)
        assert db.execute("SELECT count(*) FROM audit WHERE operation='boss.meeting.draft.save'").fetchone() == (0,)
    with runs.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        db.row_factory = sqlite3.Row
        run = db.execute("SELECT * FROM agent_runs WHERE run_id=?", (sink.config.run_id,)).fetchone()
        original_auth = db.execute("SELECT count(*) FROM objects WHERE kind='authorization'").fetchone()[0]
        saved = save_meeting_draft_in_transaction(db, store, results.scope, run, params, "technical-meeting-draft")
        assert save_meeting_draft_in_transaction(db, store, results.scope, run, params, "technical-meeting-draft") == saved
        with pytest.raises(web.HTTPConflict):
            save_meeting_draft_in_transaction(db, store, results.scope, run, {**params, "purpose": "核查当前模拟会议材料"}, "technical-meeting-draft")
        preview = preview_domain_intent(db, store, results.scope, run, "boss.meeting.confirm", saved["confirmation_parameters"])
        assert preview["owner_decision_required"] is True and preview["business_authority_granted"] is False
        assert db.execute("SELECT count(*) FROM objects WHERE kind='authorization'").fetchone()[0] == original_auth
    result = results.record(sink, "meeting-draft-result", 1, "模拟会议草稿等待本人审阅。", [{"source_id": "finance-note", "locator": "经营明细"}])
    finish = sink.emit("meeting-draft-finish", "RUN_FINISHED", {"outcome": "TECHNICAL"})
    revision = runs.read_run(sink.config.run_id)["revision"]
    checked = results.inspect_completion(sink, revision, result["event_id"], finish["event_id"], "meeting-draft-check", business_receipts=receipts)
    assert checked["output_checks"] == [{"type": "ACTION_DRAFT", "state": "NOT_VERIFIED"}, {"type": "BUSINESS_RECEIPT", "state": "NOT_VERIFIED"}]
    assert checked["business_receipt_inspection"] == {"state": "NOT_VERIFIED", "count": 0}
    assert checked["completion_state"] == "BLOCKED"
    assert results.inspect_completion(sink, revision, result["event_id"], finish["event_id"], "meeting-draft-check", business_receipts=receipts) == checked
    store.control("ui-check", "withdraw", {"source_id": "finance-note", "version": "1"})
    with pytest.raises(ValueError):
        results.inspect_completion(sink, revision, result["event_id"], finish["event_id"], "meeting-draft-check", business_receipts=receipts)
