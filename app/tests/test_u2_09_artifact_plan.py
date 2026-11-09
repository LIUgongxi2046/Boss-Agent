import asyncio
import hashlib
import json
import os
import shutil
import socket
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from nanobot.bus.queue import MessageBus
from nanobot.channels.websocket.runtime import WebSocketChannel, WebSocketConfig
from nanobot.config.loader import set_config_path
from nanobot.webui.gateway_services import build_gateway_services
from aiohttp import web

from agent_artifact_formats import create_format, verify_format
from agent_artifacts import ArtifactPreparation, read_verified_file, store_exact_file
from agent_run_api import product_application
from agent_run_broker import RunBroker
from agent_run_scope import RunScopeService
from agent_run_store import RunStore
from boss_memory_sessions import MemorySessionManager
from boss_owner_plans import valid_plan_budget
from controls import ControlStore
from hermes_bridge import EngineEventSink, EngineRunConfig
from hermes_plan_routes import install_plan_execution
from hermes_product import install_closed_artifact_routes
from role_channel import RoleChannel


def test_artifact_sources_and_unbound_version(tmp_path):
    source_db = Path(os.environ["BOSS_U2_09_SIMULATION_DB"]).resolve(strict=True)
    database = tmp_path / "business.sqlite"
    shutil.copyfile(source_db, database)
    set_config_path(tmp_path / "config.json")
    business = ControlStore(database)
    runs = RunStore(database)
    run_id = runs.create_run("technical-check", "ui-check", "artifact-check", "artifact-digest")
    lease = runs.acquire_lease(run_id, 0, "artifact-worker", 60)
    runs.transition(run_id, lease["revision"], "RUNNING", "artifact-worker", lease["epoch"])
    sessions = MemorySessionManager(tmp_path / "workspace", business_store=business, sessions_root=tmp_path / "sessions")
    scope = RunScopeService(business, sessions, "ui-check")
    gate = EngineEventSink(runs, EngineRunConfig(run_id, lease["epoch"], "903230b1e23e0c496b28e5d2e8c4f2639cd506b6", "http://127.0.0.1:1234", 1), "artifact-worker")
    workspace = tmp_path / "artifacts"
    workspace.mkdir()
    service = ArtifactPreparation(business, workspace, run_gate=gate, scope_service=scope, max_files=1, max_bytes=200000)
    source_id = "simulation-meeting-material"
    with business.connect() as db:
        db.execute("BEGIN")
        _, refs, documents = service._sources(db, [source_id])
        auth_before = db.execute("SELECT count(*) FROM objects WHERE kind='authorization'").fetchone()[0]
    assert refs[0]["source_id"] == source_id and refs[0]["revision"] == "1"
    content = create_format("MARKDOWN", documents)
    key = str(uuid4()) + ".md"
    assert store_exact_file(workspace, key, content) == content
    digest = hashlib.sha256(content).hexdigest()
    assert store_exact_file(workspace, key, content) == content
    assert read_verified_file(workspace, key, len(content), digest) == content
    verify_format("MARKDOWN", content, documents)
    with pytest.raises(ValueError, match="前一版本"):
        service.create_meeting_brief(run_id, [source_id], request_key="version-check", expected_version=1)
    with pytest.raises(ValueError, match="主体"):
        service.create_meeting_brief(run_id, [source_id], request_key="unbound-check")
    with business.connect() as db:
        assert db.execute("SELECT count(*) FROM agent_artifacts").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM agent_file_reservations").fetchone()[0] == 0
    business.control("ui-check", "withdraw", {"source_id": source_id, "version": "1"})
    with business.connect() as db:
        db.execute("BEGIN")
        with pytest.raises(web.HTTPGone):
            service._sources(db, [source_id])
        assert db.execute("SELECT count(*) FROM objects WHERE kind='authorization'").fetchone()[0] == auth_before
    assert read_verified_file(workspace, key, len(content), digest) == content
    (workspace / key).write_bytes(content + b"x")
    with pytest.raises(ValueError, match="摘要或大小"):
        read_verified_file(workspace, key, len(content), digest)
    result = {"source_id": source_id, "source_version": refs[0]["revision"], "file_sha256": digest,
        "repeat_file_reused": True, "unbound_run_rejected": True, "invalid_previous_rejected": True,
        "withdrawn_source_rejected": True, "changed_file_rejected": True, "new_artifacts": 0}
    (tmp_path / "result.json").write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


def test_unauthenticated_plan_and_closed_artifact_routes(tmp_path):
    async def exercise():
        set_config_path(tmp_path / "config.json")
        business = ControlStore(tmp_path / "business.sqlite")
        business.initialize("ui-check")
        runs = RunStore(business.path)
        sessions = MemorySessionManager(tmp_path / "workspace", business_store=business, sessions_root=tmp_path / "sessions")
        scope = RunScopeService(business, sessions, "ui-check")
        broker = RunBroker(runs, scope_service=scope)
        bus, config = MessageBus(), WebSocketConfig()
        gateway = build_gateway_services(config=config, bus=bus, session_manager=sessions, static_dist_path=None,
            workspace_path=tmp_path, default_restrict_to_workspace=True, config_path=tmp_path / "config.json",
            runtime_model_name=None, runtime_surface="webui", runtime_capabilities_overrides=None)
        channel = RoleChannel(WebSocketChannel(config, bus, gateway=gateway), {}, tmp_path / "access.jsonl", business)
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(("127.0.0.1", 0))
        sock.listen()
        sock.setblocking(False)
        port = sock.getsockname()[1]
        origin = f"http://127.0.0.1:{port}"
        app = product_application(channel, broker)
        install_closed_artifact_routes(app, channel)
        install_plan_execution(app, channel, business, scope, public_port=port)
        runner = web.AppRunner(app)
        await runner.setup()
        await web.SockSite(runner, sock).start()
        budget = {"model_requests": 1, "rounds": 1, "tools": 1, "seconds": 1, "concurrency": 1,
                  "context_tokens": 1, "files": 1, "file_bytes": 1, "open_files": 16, "cpu_seconds": 1}
        assert valid_plan_budget(budget)
        assert not valid_plan_budget({key: value for key, value in budget.items() if key != "cpu_seconds"})
        try:
            async with httpx.AsyncClient(trust_env=False) as client:
                for path in ("/api/v2/owner-plans/execution-methods", "/api/v2/owner-plans/execution-preview", "/api/v2/owner-plans/execution-decision", "/api/v2/owner-plans/execution-binding"):
                    response = await client.post(origin + path, json={"budget": budget}, headers={"Origin": origin})
                    assert response.status_code == 401
                assert (await client.get(origin + "/api/v2/owner-plans/example/suppressed-history?version=1&event_id=example")).status_code == 401
                for path in ("/api/v2/runs/unknown/artifacts", "/api/v2/runs/unknown/artifact-pending-requests", "/api/v2/artifacts/unknown?version=1",
                             "/api/v2/artifacts/unknown/versions?version=1", "/api/v2/artifacts/unknown/file?version=1"):
                    assert (await client.get(origin + path)).status_code == 401
            with business.connect() as db:
                assert db.execute("SELECT count(*) FROM objects WHERE kind='authorization'").fetchone()[0] == 0
                assert db.execute("SELECT count(*) FROM agent_runs").fetchone()[0] == 0
            print(json.dumps({"plan_unauthenticated": 401, "closed_artifact_unauthenticated": 401,
                              "ten_budget_fields_validated": True, "new_runs": 0, "authorizations": 0}))
        finally:
            await runner.cleanup()

    asyncio.run(exercise())
