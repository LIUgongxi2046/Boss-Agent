import json
import multiprocessing
import os
import sqlite3

import pytest

from agent_run_action_drafts import RunActionDrafts
from agent_run_requirements import RunRequirements
from agent_run_result import AgentRunResult
from agent_run_store import RunStore
from agent_run_tool_budget import RunToolBudget
from agent_run_scope import RunScopeService
from boss_meetings import MeetingAPI
from boss_memory_sessions import MemorySessionManager
from business import checksum
from controls import ControlStore
from hermes_bridge import EngineEventSink, EngineRunConfig
from hermes_domain_intents import draft_result_event_in_transaction, save_meeting_draft_in_transaction, save_minutes_draft_in_transaction
from test_agent_run_result import setup_result


def prepare_draft(db, store, results, sink, budget, kind, params, key, tool_name=None):
    cursor = db.cursor()
    cursor.row_factory = sqlite3.Row
    run = cursor.execute("SELECT * FROM agent_runs WHERE run_id=?", (sink.config.run_id,)).fetchone()
    tool = tool_name if tool_name is not None else "save_meeting_draft" if kind == "meeting" else "save_minutes_draft"
    digest = checksum({"goal_revision": run["goal_revision"], "scope_proof": json.loads(run["scope_proof"]), "params": params})
    reserved = budget.reserve_in_transaction(db, run["run_id"], sink.lease_owner, sink.config.lease_epoch, key, digest, tool)
    save = save_meeting_draft_in_transaction if kind == "meeting" else save_minutes_draft_in_transaction
    result = save(db, store, results.scope, run, params, key)
    payload = draft_result_event_in_transaction(db, store, run["run_id"], run["goal_revision"], key, kind, result, tool_name=tool)
    if reserved:
        sink.store._record_event(db, run["run_id"], "TOOL_STARTED", {"tool_id": tool, "call_id": key}, sink.config.lease_epoch, tool + ":start:" + key)
        sink.store._record_event(db, run["run_id"], "TOOL_FINISHED", payload, sink.config.lease_epoch, tool + ":finish:" + key)
        db.execute("UPDATE agent_runs SET revision=revision+1 WHERE run_id=?", (run["run_id"],))
    return result


def interrupt_draft(path, run_id, owner, epoch, kind, params, tool_name):
    store = ControlStore(path / "business.sqlite")
    runs = RunStore(store.path, allow_migration=False)
    sessions = MemorySessionManager(path / "workspace", business_store=store, sessions_root=path / "sessions")
    scope = RunScopeService(store, sessions, "ui-check")
    results = AgentRunResult(runs, scope)
    sink = EngineEventSink(runs, EngineRunConfig(run_id, epoch, "903230b1e23e0c496b28e5d2e8c4f2639cd506b6", "http://127.0.0.1:1234", 1), owner)
    budget = RunToolBudget(runs)
    db = runs.connect()
    db.execute("BEGIN IMMEDIATE")
    prepare_draft(db, store, results, sink, budget, kind, params, "technical-draft", tool_name)
    os._exit(19)


@pytest.mark.parametrize("kind,tool_name", [("meeting", "save_meeting_draft"), ("meeting", "meetingDraftSave"), ("minutes", "save_minutes_draft")])
def test_current_action_draft_is_bound_to_goal_and_source(tmp_path, kind, tool_name):
    store, runs, results, sink = setup_result(tmp_path)
    RunRequirements(runs, allow_migration=True)
    budget = RunToolBudget(runs, allow_migration=True)
    budget.configure(sink.config.run_id, sink.lease_owner, sink.config.lease_epoch, 3)
    with runs.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        RunRequirements.save_in_transaction(db, sink.config.run_id, 1, "technical-outputs", ["ACTION_DRAFT"])
        meeting = MeetingAPI(store)._data(db)["meeting"]
        source = store.get(db, "ui-check", "document", "finance-note")
    if kind == "meeting":
        params = {"meeting_id": meeting["meeting_id"], "meeting_version": meeting["version"], "expected_version": "0", "purpose": "核查模拟会议材料", "starts_at": meeting["starts_at"], "ends_at": "2026-10-23T10:00:00+08:00", "timezone": "Asia/Shanghai", "preparation_due_at": "2026-10-22T17:00:00+08:00", "participant_ids": ["coordinator-1"], "source_refs": [{"source_id": source["source_id"], "version": source["version"]}]}
    else:
        params = {"meeting_id": meeting["meeting_id"], "meeting_version": meeting["version"], "expected_version": "0", "source_id": source["source_id"], "source_version": source["version"], "entries": [{"kind": "ASSIGNMENT_DRAFT", "text": "核查会议资料", "source_anchor": source["content"][:10]}]}
    process = multiprocessing.get_context("spawn").Process(target=interrupt_draft, args=(tmp_path, sink.config.run_id, sink.lease_owner, sink.config.lease_epoch, kind, params, tool_name))
    process.start()
    process.join(20)
    assert process.exitcode == 19
    with runs.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        prepare_draft(db, store, results, sink, budget, kind, params, "technical-draft", tool_name)
        db.rollback()
    with runs.connect() as db:
        assert db.execute("SELECT count(*) FROM agent_tool_reservations").fetchone() == (0,)
        assert db.execute("SELECT count(*) FROM idempotency WHERE operation IN ('boss.meeting.draft.save','boss.minutes.save')").fetchone() == (0,)
    with runs.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        saved = prepare_draft(db, store, results, sink, budget, kind, params, "technical-draft", tool_name)
        assert prepare_draft(db, store, results, sink, budget, kind, params, "technical-draft", tool_name) == saved
    result = results.record(sink, "technical-result", 1, "草稿内容等待本人审阅。", [{"source_id": source["source_id"], "locator": "模拟材料"}])
    finish = sink.emit("technical-finish", "RUN_FINISHED", {"outcome": "TECHNICAL"})
    revision = runs.read_run(sink.config.run_id)["revision"]
    checked = results.inspect_completion(sink, revision, result["event_id"], finish["event_id"], "draft-check")
    assert checked["output_checks"] == [{"type": "ACTION_DRAFT", "state": "RECORD_PRESENT"}]
    assert checked["action_draft_inspection"] == {"state": "RECORD_PRESENT", "count": 1}
    assert checked["completion_state"] == "BLOCKED"
    assert results.inspect_completion(sink, revision, result["event_id"], finish["event_id"], "draft-check") == checked
    reopened = AgentRunResult(RunStore(store.path, allow_migration=False), results.scope)
    assert reopened.inspect_completion(sink, revision, result["event_id"], finish["event_id"], "draft-check") == checked
    with runs.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        object_kind = "meeting_draft" if kind == "meeting" else "minutes"
        current = store.get(db, "ui-check", object_kind, meeting["meeting_id"])
        current["version"] = str(int(current["version"]) + 1)
        store.put(db, "ui-check", object_kind, meeting["meeting_id"], current)
        db.commit()
    changed = results.inspect_completion(sink, revision, result["event_id"], finish["event_id"], "changed-draft")
    assert changed["action_draft_inspection"] == {"state": "NOT_VERIFIED", "count": 0}
    assert changed["output_checks"] == [{"type": "ACTION_DRAFT", "state": "NOT_VERIFIED"}]
    runs.add_input(sink.config.run_id, 1, "technical-input", "补充核查要求")
    with runs.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        RunRequirements.save_in_transaction(db, sink.config.run_id, 2, "technical-outputs-2", ["ACTION_DRAFT"])
    runs.apply_input(sink.config.run_id, 1, sink.lease_owner, sink.config.lease_epoch)
    next_result = results.record(sink, "technical-result-2", 2, "补充要求等待处理。", [])
    next_finish = sink.emit("technical-finish-2", "RUN_FINISHED", {"outcome": "TECHNICAL"})
    next_revision = runs.read_run(sink.config.run_id)["revision"]
    next_checked = results.inspect_completion(sink, next_revision, next_result["event_id"], next_finish["event_id"], "next-goal")
    assert next_checked["action_draft_inspection"] == {"state": "NOT_VERIFIED", "count": 0}
    store.control("ui-check", "withdraw", {"source_id": source["source_id"], "version": source["version"]})
    with pytest.raises(ValueError):
        results.inspect_completion(sink, revision, result["event_id"], finish["event_id"], "draft-check")
