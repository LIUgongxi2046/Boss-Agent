import json
from dataclasses import asdict

import pytest

from agent_legacy_inventory import AgentLegacyInventory
from agent_legacy_run_link import AgentLegacyRunLink
from agent_run_broker import RunBroker
from agent_run_scope import RunScopeService
from agent_run_store import RunStore, utc_now
from boss_memory_sessions import MemorySessionManager
from controls import ControlStore
from hermes_legacy_routes import load_legacy_inventory, verify_legacy_link_in_transaction
from hermes_source_invalidation import begin_source_cleanup


def recorded_link(tmp_path):
    store = ControlStore(tmp_path / "business.sqlite")
    store.initialize("ui-check")
    runs = RunStore(store.path)
    sessions = MemorySessionManager(tmp_path / "workspace", business_store=store, sessions_root=tmp_path / "sessions")
    session = sessions.get_or_create("websocket:legacy-check")
    session.add_message("user", "核查会议资料")
    sessions.save(session, fsync=True)
    scope = RunScopeService(store, sessions, "ui-check")
    inventory = AgentLegacyInventory(store, scope, allow_migration=True)
    AgentLegacyRunLink(inventory, RunBroker(runs, scope_service=scope), allow_migration=True)
    proof = scope.prove("legacy-check", [])
    run_id = runs.create_run(proof.owner_id, proof.namespace, "run-create", "run-digest")
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        source = inventory.session_in_transaction(db, "legacy-check", [])
        db.execute("UPDATE agent_runs SET conversation_id=?,selected_refs=?,scope_proof=? WHERE run_id=?", (proof.chat_id, "[]", json.dumps(asdict(proof)), run_id))
        db.execute("INSERT INTO agent_api_requests VALUES (?,?,?,?,?,?,?)", (proof.owner_id, proof.namespace, "create-request", "create-digest", run_id, "create", json.dumps({"run_id": run_id})))
        db.execute("INSERT INTO agent_legacy_run_links VALUES (?,?,?,?,?,?)", (run_id, proof.namespace, "SESSION", proof.session_id, source["source_digest"], utc_now().isoformat()))
    return store, sessions, scope, inventory, proof, run_id


def verify(store, inventory, proof, run_id):
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        return verify_legacy_link_in_transaction(db, inventory, run_id, proof)


def test_link_rechecks_actual_session_and_repeated_reads(tmp_path):
    store, sessions, scope, inventory, proof, run_id = recorded_link(tmp_path)
    assert load_legacy_inventory(scope) is not None
    first = verify(store, inventory, proof, run_id)
    assert first["run_id"] == run_id and first["session_id"] == proof.session_id
    assert verify(store, inventory, proof, run_id) == first
    session = sessions.get_or_create(proof.session_id)
    session.add_message("user", "继续核查会议资料")
    sessions.save(session, fsync=True)
    with pytest.raises(ValueError, match="当前范围已经变化"):
        verify(store, inventory, proof, run_id)


def test_link_rejects_changed_memory_and_source_cleanup(tmp_path):
    memory_path = tmp_path / "memory"
    memory_path.mkdir()
    store, _, _, inventory, proof, run_id = recorded_link(memory_path)
    with store.connect() as db:
        db.execute("DELETE FROM objects WHERE namespace=? AND kind='memory' AND id='current'", ("ui-check",))
    with pytest.raises(ValueError, match="当前范围已经变化"):
        verify(store, inventory, proof, run_id)
    source_path = tmp_path / "source"
    source_path.mkdir()
    store, _, _, inventory, proof, run_id = recorded_link(source_path)
    begin_source_cleanup(store, "ui-check", "finance-note", "1")
    with pytest.raises(ValueError, match="当前范围已经变化"):
        verify(store, inventory, proof, run_id)


def test_absent_link_does_not_create_inventory(tmp_path):
    store, _, _, inventory, proof, _ = recorded_link(tmp_path)
    runs = RunStore(store.path, allow_migration=False)
    run_id = runs.create_run(proof.owner_id, proof.namespace, "other-run", "other-digest")
    assert verify(store, inventory, proof, run_id) is None
    with store.connect() as db:
        assert db.execute("SELECT count(*) FROM agent_legacy_run_links").fetchone() == (1,)
