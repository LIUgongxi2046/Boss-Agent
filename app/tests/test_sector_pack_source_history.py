import json
from dataclasses import asdict
from datetime import datetime, timedelta

import pytest
from aiohttp import web

from agent_source_history import AgentSourceHistory
from boss_sector_pack import ensure_sector_pack
from business import checksum
from test_agent_run_result import setup_result


def refresh(store, db, snapshot):
    db.execute("DELETE FROM objects WHERE namespace=? AND kind=? AND id=?", ("ui-check", "sector_pack", "current"))
    return ensure_sector_pack(store, db, snapshot)


def bind(store, results, sink, document):
    session_id = results.scope.sources.sessions.get_or_create("websocket:result-check").key
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        binding = store.get(db, "ui-check", "conversation_source_binding", session_id)
        selection = {"source_id": document["source_id"], "version": document["version"]}
        binding["source_refs"] = [selection]
        binding["source_pins"] = [{**selection, "content_sha256": checksum(document)}]
        store.put(db, "ui-check", "conversation_source_binding", session_id, binding)


def test_sector_version_history_and_transaction(tmp_path):
    store, runs, results, sink = setup_result(tmp_path)
    with store.connect() as db:
        snapshot = store.get(db, "ui-check", "initial", "snapshot")
        with pytest.raises(ValueError, match="同一数据库事务"):
            ensure_sector_pack(store, db, snapshot)
        db.execute("BEGIN IMMEDIATE")
        ensure_sector_pack(store, db, snapshot)
        original = store.get(db, "ui-check", "document", "sector-f14-a")
        refresh(store, db, snapshot)
        assert store.get(db, "ui-check", "document", original["source_id"]) == original
        assert db.execute("SELECT 1 FROM objects WHERE namespace=? AND kind=?", ("ui-check", "document_revision")).fetchone() is None
    bind(store, results, sink, original)
    proof = results.scope.prove("result-check", [original["source_id"]])
    with runs.connect() as db:
        db.execute("UPDATE agent_runs SET selected_refs=?,scope_proof=? WHERE run_id=?", (json.dumps([original["source_id"]]), json.dumps(asdict(proof)), sink.config.run_id))
    event = results.record(sink, "sector-result", 1, "专题资料技术记录", [{"source_id": original["source_id"], "locator": "模拟资料"}])
    next_clock = (datetime.fromisoformat(snapshot["business_clock"]) + timedelta(days=1)).isoformat()
    store.control("ui-check", "clock", {"at": next_clock})
    updated_snapshot = {**snapshot, "business_clock": next_clock}
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        refresh(store, db, updated_snapshot)
        assert store.get(db, "ui-check", "document", original["source_id"])["version"] == "2"
        assert store.get(db, "ui-check", "document_revision", original["source_id"] + ":v1") == original
        db.rollback()
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        assert store.get(db, "ui-check", "document", original["source_id"]) == original
        refresh(store, db, updated_snapshot)
        current = store.get(db, "ui-check", "document", original["source_id"])
        assert current["version"] == "2"
        refresh(store, db, updated_snapshot)
        assert store.get(db, "ui-check", "document", original["source_id"]) == current
    bind(store, results, sink, current)
    history = AgentSourceHistory(runs, results.scope)
    with runs.connect() as db:
        db.execute("BEGIN")
        read = history.read_in_transaction(db, sink.config.run_id, event["event_id"], original["source_id"], "1")
        assert read["historical"] is True and read["current_version"] == "2"
        assert read["content"] == original["content"] and read["sha256"] == checksum(original)
    store.hermes_source_sessions = results.scope.sources.sessions
    store.control("ui-check", "withdraw", {"source_id": original["source_id"], "version": "2"})
    with runs.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        with pytest.raises((web.HTTPGone, web.HTTPConflict)):
            history.read_in_transaction(db, sink.config.run_id, event["event_id"], original["source_id"], "1")
        with pytest.raises(ValueError, match="撤销或清理"):
            refresh(store, db, updated_snapshot)
        db.rollback()


def test_sector_update_rejects_conflicting_history_without_partial_writes(tmp_path):
    store, _, _, _ = setup_result(tmp_path)
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        snapshot = store.get(db, "ui-check", "initial", "snapshot")
        ensure_sector_pack(store, db, snapshot)
        original = store.get(db, "ui-check", "document", "sector-f14-a")
        store.put(db, "ui-check", "document_history", original["source_id"] + ":1", {**original, "content": original["content"] + "历史记录"})
        next_clock = (datetime.fromisoformat(snapshot["business_clock"]) + timedelta(days=1)).isoformat()
        with pytest.raises(ValueError, match="历史版本内容不一致"):
            refresh(store, db, {**snapshot, "business_clock": next_clock})
        assert store.get(db, "ui-check", "document", original["source_id"]) == original
        assert db.execute("SELECT 1 FROM objects WHERE namespace=? AND kind=?", ("ui-check", "document_revision")).fetchone() is None
        db.rollback()
