import asyncio
import json
import os
import secrets
import socket
from dataclasses import asdict

import httpx
import pytest
from aiohttp import web

from agent_run_scope import RunScopeService
from agent_run_store import RunStore
from boss_memory_sessions import MemorySessionManager
from business import checksum
from controls import ControlStore
from hermes_bridge import EngineEventSink, EngineRunConfig
from hermes_memory_adapter import HermesMemoryAdapter
from service import STORE_KEY, application


def test_service_retries_failed_session_cleanup(tmp_path):
    async def exercise():
        store = ControlStore(tmp_path / "business.sqlite")
        store.initialize("ui-check")
        sessions = MemorySessionManager(tmp_path / "workspace", business_store=store, sessions_root=tmp_path / "sessions")
        session = sessions.get_or_create("websocket:control-check")
        with store.connect() as db:
            initial = store.get(db, "ui-check", "initial", "snapshot")
            document = store.get(db, "ui-check", "document", "finance-note")
            source = {"source_id": document["source_id"], "version": document["version"]}
            binding = {"namespace": "ui-check", "owner_id": initial["owner_id"], "dataset_id": initial["dataset_id"], "dataset_version": initial["dataset_version"], "chat_id": "control-check", "session_id": session.key, "native_session_created_at": session.created_at.isoformat(), "binding_id": "control-selection", "context_version": "1", "source_refs": [source], "source_pins": [{**source, "content_sha256": checksum(document)}]}
            store.put(db, "ui-check", "conversation_source_binding", session.key, binding)
        session.add_message("user", document["content"])
        session.commit_summary_checkpoint(document["content"])
        sessions.save(session, fsync=True)
        scope = RunScopeService(store, sessions, "ui-check")
        proof = scope.prove("control-check", ["finance-note"])
        runs = RunStore(store.path)
        run_id = runs.create_run(proof.owner_id, proof.namespace, "control-run", "control-digest")
        with runs.connect() as db:
            db.execute("UPDATE agent_runs SET goal=?,conversation_id=?,selected_refs=?,scope_proof=? WHERE run_id=?", ("核查资料", proof.chat_id, json.dumps(["finance-note"]), json.dumps(asdict(proof)), run_id))
        lease = runs.acquire_lease(run_id, 0, "worker", 60)
        runs.transition(run_id, lease["revision"], "RUNNING", "worker", lease["epoch"])
        config = EngineRunConfig(run_id, lease["epoch"], "903230b1e23e0c496b28e5d2e8c4f2639cd506b6", "http://127.0.0.1:1234", 1)
        HermesMemoryAdapter(store, scope, run_gate=EngineEventSink(runs, config, "worker")).read()
        app = application(store.path, execution_namespace="ui-check", business_store=store, session_manager=sessions)
        assert app[STORE_KEY] is store
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        listener.setblocking(False)
        endpoint = "http://127.0.0.1:" + str(listener.getsockname()[1])
        runner = web.AppRunner(app)
        await runner.setup()
        await web.SockSite(runner, listener).start()
        try:
            async with httpx.AsyncClient(trust_env=False) as client:
                rejected = await client.post(endpoint + "/spaces/ui-check/controls/withdraw", json=source)
                assert rejected.status_code == 401
            sessions.sessions_dir.chmod(0o500)
            try:
                with pytest.raises(PermissionError):
                    store.control("ui-check", "withdraw", source)
            finally:
                sessions.sessions_dir.chmod(0o700)
            with store.connect() as db:
                marker = store.get(db, "ui-check", "hermes_source_cleanup", "finance-note")
                assert marker["state"] == "COMPLETED" and marker["session_state"] == "FAILED"
                assert store.get(db, "ui-check", "document", "finance-note")["withdrawn"] is True
                assert db.execute("SELECT 1 FROM objects WHERE namespace=? AND kind='hermes_memory_invalidation' AND id=?", ("ui-check", run_id)).fetchone() is not None
            recovery_app = application(store.path, execution_namespace="ui-check", session_workspace=tmp_path / "workspace", sessions_root=tmp_path / "sessions")
            assert recovery_app[STORE_KEY] is not store and recovery_app[STORE_KEY].path == store.path
            recovery = web.AppRunner(recovery_app)
            await recovery.setup()
            await recovery.cleanup()
            with store.connect() as db:
                assert store.get(db, "ui-check", "hermes_source_cleanup", "finance-note")["session_state"] == "COMPLETED"
            saved = sessions.read_session_snapshot(session.key)
            assert saved.get_history() == [] and "_last_summary" not in saved.metadata
            store.control("ui-check", "withdraw", source)
            restored = MemorySessionManager(tmp_path / "workspace", business_store=store, sessions_root=tmp_path / "sessions").get_or_create(session.key)
            assert restored.get_history() == [] and "_last_summary" not in restored.metadata
        finally:
            await runner.cleanup()

    previous = {name: os.environ.get(name) for name in ("BOSS_PROBE_TOKEN", "MAINTAINER_PROBE_TOKEN")}
    os.environ["BOSS_PROBE_TOKEN"] = secrets.token_urlsafe(32)
    os.environ["MAINTAINER_PROBE_TOKEN"] = secrets.token_urlsafe(32)
    try:
        asyncio.run(exercise())
    finally:
        for name, value in previous.items():
            if value is None:
                del os.environ[name]
            else:
                os.environ[name] = value
