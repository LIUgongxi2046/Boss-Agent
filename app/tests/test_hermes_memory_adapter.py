import pytest
from aiohttp import web

from agent_run_scope import RunScopeService
from agent_run_broker import RunBroker, RunIdentity
from agent_run_store import RunStore
from boss_memory_runtime import memory_adoption
from boss_memory_sessions import MemorySessionManager
from controls import ControlStore
from business import checksum
from hermes_bridge import EngineEventSink, EngineRunConfig
from hermes_memory_adapter import HermesMemoryAdapter, hermes_memory_settings


def test_memory_configuration_limits_toolsets():
    assert hermes_memory_settings(["boss_domain"]) == {
        "enabled_toolsets": ["boss_domain"], "disabled_toolsets": ["memory"],
        "skip_memory": True, "skip_context_files": True, "load_soul_identity": False,
        "checkpoints_enabled": False, "save_trajectories": False,
    }
    for toolsets in (None, ["memory"], ["boss_domain", "memory"], ["boss_domain", "boss_domain"]):
        with pytest.raises(ValueError):
            hermes_memory_settings(toolsets)


def test_unbound_run_cannot_read_persisted_memory(tmp_path):
    store = ControlStore(tmp_path / "business.sqlite")
    store.initialize("ui-check")
    sessions = MemorySessionManager(tmp_path / "workspace", business_store=store, sessions_root=tmp_path / "sessions")
    scope = RunScopeService(store, sessions, "ui-check")
    runs = RunStore(store.path)
    run_id = runs.create_run("boss-1", "ui-check", "memory-check", "memory-check")
    lease = runs.acquire_lease(run_id, 0, "memory-check", 60)
    runs.transition(run_id, lease["revision"], "RUNNING", "memory-check", lease["epoch"])
    config = EngineRunConfig(run_id, lease["epoch"], "903230b1e23e0c496b28e5d2e8c4f2639cd506b6", "http://127.0.0.1:1234", 1)
    adapter = HermesMemoryAdapter(store, scope, run_gate=EngineEventSink(runs, config, "memory-check"))
    with store.connect() as db:
        before, memory = memory_adoption(store, db, "ui-check")
        assert memory is not None and before["eligible"] is True
    with pytest.raises(ValueError, match="会话范围"):
        adapter.read()
    with pytest.raises(ValueError, match="会话范围"):
        adapter.require_current({})
    with ControlStore(store.path).connect() as db:
        after, reread = memory_adoption(store, db, "ui-check")
    assert (after, reread) == (before, memory)


def test_persisted_reference_blocks_deleted_memory_in_parent_and_child(tmp_path):
    store = ControlStore(tmp_path / "business.sqlite")
    store.initialize("ui-check")
    sessions = MemorySessionManager(tmp_path / "workspace", business_store=store, sessions_root=tmp_path / "sessions")
    sessions.save(sessions.get_or_create("websocket:memory-check"), fsync=True)
    scope = RunScopeService(store, sessions, "ui-check")
    runs = RunStore(store.path)
    identity = RunIdentity("boss-1", "ui-check", "BOSS", frozenset({"memory-check"}), frozenset())
    run_id = RunBroker(runs, scope_service=scope).create(identity, {"conversation_id": "memory-check", "goal": "读取已有模拟记忆", "selected_refs": [], "request_key": "memory-read"})["run_id"]
    lease = runs.acquire_lease(run_id, 0, "parent-worker", 60)
    runs.transition(run_id, lease["revision"], "RUNNING", "parent-worker", lease["epoch"])

    def adapter_for(identifier, epoch, owner):
        config = EngineRunConfig(identifier, epoch, "903230b1e23e0c496b28e5d2e8c4f2639cd506b6", "http://127.0.0.1:1234", 1)
        return HermesMemoryAdapter(store, scope, run_gate=EngineEventSink(runs, config, owner))

    parent = adapter_for(run_id, lease["epoch"], "parent-worker")
    child_id = runs.create_child_run(run_id, "parent-worker", lease["epoch"], "child-request", "child-content")
    child_lease = runs.acquire_lease(child_id, 0, "child-worker", 60)
    runs.transition(child_id, child_lease["revision"], "RUNNING", "child-worker", child_lease["epoch"])
    child = adapter_for(child_id, child_lease["epoch"], "child-worker")
    with pytest.raises(ValueError, match="记忆引用缺少"):
        parent.require_current({})
    with pytest.raises(ValueError, match="记忆引用缺少"):
        child.read()
    result = parent.read()
    assert result["memory"] is not None
    parent.require_current(result["reference"])
    assert child.read() == result
    child.require_current(result["reference"])
    session = sessions.get_or_create("websocket:memory-check")
    session.add_message("user", result["memory"]["text"])
    session.commit_summary_checkpoint(result["memory"]["text"])
    sessions.save(session, fsync=True)
    with store.connect() as db:
        original = store.get(db, "ui-check", "memory", "current")
        db.execute("DELETE FROM objects WHERE namespace=? AND kind='memory' AND id='current'", ("ui-check",))
    reopened = ControlStore(store.path)
    with reopened.connect() as db:
        assert memory_adoption(reopened, db, "ui-check") == (None, None)
    reread_sessions = MemorySessionManager(tmp_path / "workspace", business_store=reopened, sessions_root=tmp_path / "sessions")
    reread = reread_sessions.get_or_create("websocket:memory-check")
    assert "_last_summary" not in reread.metadata
    assert reread.get_history() == []
    with reopened.connect() as db:
        invalidated = db.execute("SELECT id FROM objects WHERE namespace=? AND kind='hermes_memory_invalidation' ORDER BY id", ("ui-check",)).fetchall()
        assert {row[0] for row in invalidated} == {run_id, child_id}
    for adapter in (parent, child):
        with pytest.raises(ValueError, match="记忆引用"):
            adapter.require_current(result["reference"])
        with pytest.raises(ValueError, match="记忆引用"):
            adapter.read()
    with reopened.connect() as db:
        reopened.put(db, "ui-check", "memory", "current", original)
    for adapter in (parent, child):
        with pytest.raises(ValueError, match="已经失效"):
            adapter.require_current(result["reference"])


def test_empty_session_checkpoint_is_cleared_after_memory_change(tmp_path):
    store = ControlStore(tmp_path / "business.sqlite")
    store.initialize("ui-check")
    sessions = MemorySessionManager(tmp_path / "workspace", business_store=store, sessions_root=tmp_path / "sessions")
    session = sessions.get_or_create("websocket:checkpoint-check")
    sessions.save(session, fsync=True)
    with store.connect() as db:
        original = store.get(db, "ui-check", "memory", "current")
    session.metadata["runtime_checkpoint"] = {"memory": original["text"]}
    sessions.save_runtime_checkpoint(session)
    checkpoint = sessions._jsonl_store.get_runtime_checkpoint_path(session.key)
    assert checkpoint.is_file()
    with store.connect() as db:
        db.execute("DELETE FROM objects WHERE namespace=? AND kind='memory' AND id='current'", ("ui-check",))
    first = MemorySessionManager(tmp_path / "workspace", business_store=store, sessions_root=tmp_path / "sessions").get_or_create(session.key)
    assert "runtime_checkpoint" not in first.metadata
    assert not checkpoint.exists()
    second = MemorySessionManager(tmp_path / "workspace", business_store=store, sessions_root=tmp_path / "sessions").get_or_create(session.key)
    assert "runtime_checkpoint" not in second.metadata


def test_withdrawn_source_invalidates_bound_parent_child_and_session(tmp_path):
    store = ControlStore(tmp_path / "business.sqlite")
    store.initialize("ui-check")
    sessions = MemorySessionManager(tmp_path / "workspace", business_store=store, sessions_root=tmp_path / "sessions")
    session = sessions.get_or_create("websocket:source-check")
    with store.connect() as db:
        initial = store.get(db, "ui-check", "initial", "snapshot")
        document = store.get(db, "ui-check", "document", "finance-note")
    session.add_message("user", document["content"])
    session.commit_summary_checkpoint(document["content"])
    sessions.save(session, fsync=True)
    source = {"source_id": document["source_id"], "version": document["version"]}
    binding = {"namespace": "ui-check", "owner_id": initial["owner_id"], "dataset_id": initial["dataset_id"],
               "dataset_version": initial["dataset_version"], "chat_id": "source-check", "session_id": session.key,
               "native_session_created_at": session.created_at.isoformat(), "binding_id": "source-selection-test",
               "context_version": "1", "source_refs": [source],
               "source_pins": [{**source, "content_sha256": checksum(document)}]}
    with store.connect() as db:
        store.put(db, "ui-check", "conversation_source_binding", session.key, binding)
    scope = RunScopeService(store, sessions, "ui-check")
    runs = RunStore(store.path)
    identity = RunIdentity("boss-1", "ui-check", "BOSS", frozenset({"source-check"}), frozenset({"finance-note"}))
    run_id = RunBroker(runs, scope_service=scope).create(identity, {"conversation_id": "source-check", "goal": "读取获准模拟资料", "selected_refs": ["finance-note"], "request_key": "source-run"})["run_id"]
    lease = runs.acquire_lease(run_id, 0, "parent-worker", 60)
    runs.transition(run_id, lease["revision"], "RUNNING", "parent-worker", lease["epoch"])
    child_id = runs.create_child_run(run_id, "parent-worker", lease["epoch"], "child-source", "child-source")
    child_lease = runs.acquire_lease(child_id, 0, "child-worker", 60)
    runs.transition(child_id, child_lease["revision"], "RUNNING", "child-worker", child_lease["epoch"])

    def adapter_for(identifier, epoch, owner):
        config = EngineRunConfig(identifier, epoch, "903230b1e23e0c496b28e5d2e8c4f2639cd506b6", "http://127.0.0.1:1234", 1)
        return HermesMemoryAdapter(store, scope, run_gate=EngineEventSink(runs, config, owner))

    parent = adapter_for(run_id, lease["epoch"], "parent-worker")
    child = adapter_for(child_id, child_lease["epoch"], "child-worker")
    reference = parent.read()["reference"]
    child.read()
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        with pytest.raises(ValueError, match="未撤销"):
            sessions.source_withdrawn_in_transaction(db, "finance-note")
        store.control_withdraw(db, "ui-check", source)
        sessions.source_withdrawn_in_transaction(db, "finance-note")
        rows = db.execute("SELECT id FROM objects WHERE namespace=? AND kind='hermes_memory_invalidation'", ("ui-check",)).fetchall()
        assert {row[0] for row in rows} == {run_id, child_id}
        db.rollback()
    parent.require_current(reference)
    child.require_current(reference)
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        store.control_withdraw(db, "ui-check", source)
        sessions.source_withdrawn_in_transaction(db, "finance-note")
    sessions.source_withdrawn("finance-note")
    reopened = MemorySessionManager(tmp_path / "workspace", business_store=ControlStore(store.path), sessions_root=tmp_path / "sessions")
    restored = reopened.get_or_create(session.key)
    assert "_last_summary" not in restored.metadata
    assert restored.get_history() == []
    for adapter in (parent, child):
        with pytest.raises(web.HTTPGone):
            adapter.require_current(reference)
