import pytest
import sqlite3
from aiohttp import web

from agent_run_scope import RunScopeService
from agent_run_store import RunStore
from boss_memory_sessions import MemorySessionManager
from boss_source_access import require_current_business_source
from controls import ControlStore


def test_scope_uses_persisted_session_and_official_sources(tmp_path):
    store = ControlStore(tmp_path / "business.sqlite")
    store.initialize("ui-check")
    sessions = MemorySessionManager(tmp_path / "workspace", business_store=store, sessions_root=tmp_path / "sessions")
    scope = RunScopeService(store, sessions, "ui-check")
    with pytest.raises(web.HTTPNotFound):
        scope.prove("scope-check", [])
    session = sessions.get_or_create("websocket:scope-check")
    sessions.save(session, fsync=True)
    proof = scope.prove("scope-check", [])
    assert proof.owner_id == "boss-1" and proof.namespace == "ui-check"
    assert proof.session_id == "websocket:scope-check" and proof.source_pins == ()
    assert proof.native_session_created_at == session.created_at.isoformat()
    with store.connect() as db:
        db.execute("BEGIN")
        assert scope.prove_in_transaction(db, "scope-check", []) == proof
    with sqlite3.connect(tmp_path / "other.sqlite") as db:
        db.execute("BEGIN")
        with pytest.raises(web.HTTPForbidden):
            scope.prove_in_transaction(db, "scope-check", [])
    with store.connect() as db:
        db.execute("BEGIN")
        document = require_current_business_source(store, db, "ui-check", "boss-1", "finance-note")
        assert document["source_id"] == "finance-note" and document["version"] == "1"
    with pytest.raises(web.HTTPForbidden):
        scope.prove("scope-check", ["finance-note"])


def test_scope_rejects_other_execution_namespace(tmp_path):
    store = ControlStore(tmp_path / "business.sqlite")
    store.initialize("ui-check")
    sessions = MemorySessionManager(tmp_path / "workspace", business_store=store, sessions_root=tmp_path / "sessions")
    sessions.save(sessions.get_or_create("websocket:scope-check"), fsync=True)
    with pytest.raises(web.HTTPForbidden):
        RunScopeService(store, sessions, "another-space").prove("scope-check", [])


def test_transactional_source_read_requires_saved_scope(tmp_path):
    store = ControlStore(tmp_path / "business.sqlite")
    store.initialize("ui-check")
    sessions = MemorySessionManager(tmp_path / "workspace", business_store=store, sessions_root=tmp_path / "sessions")
    scope = RunScopeService(store, sessions, "ui-check")
    runs = RunStore(store.path)
    run_id = runs.create_run("boss-1", "ui-check", "source-read", "source-digest")
    lease = runs.acquire_lease(run_id, 0, "source-worker", 60)
    runs.transition(run_id, lease["revision"], "RUNNING", "source-worker", lease["epoch"])
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        with pytest.raises(web.HTTPForbidden):
            scope.read_source_in_transaction(db, runs, run_id, "source-worker", lease["epoch"], "finance-note")
