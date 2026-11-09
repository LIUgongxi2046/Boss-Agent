import pytest
import sqlite3
from aiohttp import web

from agent_run_memory_guard import require_current_run_memory_in_transaction
from controls import ControlStore
from hermes_memory_adapter import HermesMemoryAdapter
from test_agent_run_result import setup_result


def test_recorded_memory_change_blocks_result_and_event_access(tmp_path):
    store, runs, results, sink = setup_result(tmp_path)
    memory = HermesMemoryAdapter(store, results.scope, run_gate=sink)
    adopted = memory.read()
    event = results.record(sink, "memory-result", 1, "模拟业务资料记录。", [{"source_id": "finance-note", "locator": "经营明细"}])
    with runs.connect() as db:
        db.execute("BEGIN")
        require_current_run_memory_in_transaction(db, store, sink.config.run_id)
        assert runs.result_in_transaction(db, sink.config.run_id, 1) == event
        original = store.get(db, "ui-check", "memory", "current")
        db.row_factory = sqlite3.Row
        require_current_run_memory_in_transaction(db, store, sink.config.run_id)
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute("DELETE FROM objects WHERE namespace=? AND kind='memory' AND id='current'", ("ui-check",))
    with runs.connect() as db:
        db.execute("BEGIN")
        with pytest.raises(web.HTTPConflict):
            require_current_run_memory_in_transaction(db, store, sink.config.run_id)
    with pytest.raises(web.HTTPConflict):
        results.record(sink, "memory-result", 1, "模拟业务资料记录。", [{"source_id": "finance-note", "locator": "经营明细"}])
    results.scope.sources.sessions.reconcile_memory()
    with runs.connect() as db:
        db.execute("BEGIN")
        with pytest.raises(web.HTTPConflict):
            require_current_run_memory_in_transaction(db, store, sink.config.run_id)
    with store.connect() as db:
        store.put(db, "ui-check", "memory", "current", original)
    reopened = ControlStore(store.path)
    with reopened.connect() as db:
        db.execute("BEGIN")
        with pytest.raises(web.HTTPConflict):
            require_current_run_memory_in_transaction(db, reopened, sink.config.run_id)
    assert adopted["reference"]["memory_reference"]["eligible"] is True


def test_withdrawn_source_rejects_result_replay(tmp_path):
    store, runs, results, sink = setup_result(tmp_path)
    results.record(sink, "source-result", 1, "模拟业务资料记录。", [{"source_id": "finance-note", "locator": "经营明细"}])
    store.control("ui-check", "withdraw", {"source_id": "finance-note", "version": "1"})
    with pytest.raises(ValueError):
        results.record(sink, "source-result", 1, "模拟业务资料记录。", [{"source_id": "finance-note", "locator": "经营明细"}])
