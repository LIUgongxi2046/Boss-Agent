import asyncio
import json
import socket
import subprocess
import sys
from pathlib import Path

import httpx
import pytest
from aiohttp import web
from nanobot.bus.queue import MessageBus
from nanobot.channels.websocket.runtime import WebSocketChannel, WebSocketConfig
from nanobot.webui.gateway_services import build_gateway_services

from agent_run_store import RunStore
from agent_chat_budget import AgentChatBudget
from agent_run_concurrency import RunConcurrencyBudget
from agent_run_scope import RunScopeService
from agent_run_object_scope import AgentRunObjectScope
from agent_artifacts import ArtifactPreparation
from agent_artifact_workspace import ArtifactWorkspace
from agent_artifact_routes import require_artifact_read_boundary
from boss_memory_sessions import MemorySessionManager
from controls import ControlStore
from hermes_product import DISPATCHER_KEY, SERVICES_KEY, hermes_product_application
from hermes_process_evidence import HermesProcessEvidence
from hermes_artifact_transport import HermesArtifactTransport
from hermes_bridge import EngineEventSink, EngineProcessSupervisor, EngineRunConfig
from hermes_run_authority import HermesRunAuthority
from role_channel import RoleChannel


@pytest.mark.parametrize("workspace_configured", [False, True])
def test_product_assembly_uses_current_services_and_rejects_unauthenticated(tmp_path, workspace_configured):
    async def exercise():
        store = ControlStore(tmp_path / "business.sqlite")
        store.initialize("ui-check")
        run_store = RunStore(store.path)
        sessions = MemorySessionManager(tmp_path / "workspace", business_store=store, sessions_root=tmp_path / "sessions")
        config = WebSocketConfig()
        gateway = build_gateway_services(config=config, bus=MessageBus(), session_manager=sessions,
            static_dist_path=None, workspace_path=tmp_path, default_restrict_to_workspace=True,
            config_path=tmp_path / "config.json", runtime_model_name=None,
            runtime_surface="webui", runtime_capabilities_overrides=None)
        channel = RoleChannel(WebSocketChannel(config, MessageBus(), gateway=gateway), {}, tmp_path / "access.jsonl", store)
        with pytest.raises(ValueError, match="预算迁移尚未安装"):
            hermes_product_application(channel, store, sessions, "ui-check", public_port=1234, upstream_port=1235, chat_budget_enabled=True)
        scope = RunScopeService(store, sessions, "ui-check")
        if workspace_configured:
            AgentRunObjectScope(run_store, scope, allow_migration=True)
        AgentChatBudget(run_store, channel, scope, allow_migration=True)
        RunConcurrencyBudget(run_store, allow_migration=True)
        evidence = HermesProcessEvidence(run_store, allow_migration=True)
        other_sessions = MemorySessionManager(tmp_path / "other-workspace", business_store=store, sessions_root=tmp_path / "other-sessions")
        with pytest.raises(ValueError):
            hermes_product_application(channel, store, other_sessions, "ui-check", public_port=1234, upstream_port=1235)
        with pytest.raises(ValueError):
            hermes_product_application(channel, store, sessions, "other-space", public_port=1234, upstream_port=1235)
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        sock.listen()
        sock.setblocking(False)
        port = sock.getsockname()[1]
        mapping = ArtifactWorkspace(tmp_path.resolve()) if workspace_configured else None
        app = hermes_product_application(channel, store, sessions, "ui-check", public_port=port, upstream_port=port + 1, artifact_workspace=mapping, chat_budget_enabled=True)
        services = app[SERVICES_KEY]
        assert services.artifact_workspace is mapping
        assert services.store.path == store.path
        assert services.scope.store is store
        assert services.broker.scope_service is services.scope
        assert (services.broker.object_scope is not None) == workspace_configured
        if workspace_configured:
            assert services.broker.object_scope.scope is services.scope
        assert services.bridge._store is store
        assert services.chat_budget.store is services.store
        assert services.chat_budget.scope is services.scope
        assert app[DISPATCHER_KEY].services is services
        config = EngineRunConfig("unbound-run", 1, "903230b1e23e0c496b28e5d2e8c4f2639cd506b6", "http://127.0.0.1:1234", 1)
        sink = EngineEventSink(services.store, config, "worker")
        with pytest.raises(web.HTTPServiceUnavailable):
            services.require_selected_meeting_method(sink)
        async def attempt_start(request):
            services.start(request, sink, {}, None)
            return web.Response()
        app.router.add_get("/test-start", attempt_start)
        async def attempt_registration(request):
            services.register_process_start(request, evidence, "unbound-run", "worker", 1, "digest", {}, "request", "digest")
            return web.Response()
        app.router.add_get("/test-registration", attempt_registration)
        async def attempt_artifact(request):
            preparation = ArtifactPreparation(store, tmp_path, run_gate=sink, scope_service=services.scope, max_files=1, max_bytes=1024)
            HermesArtifactTransport(preparation, request, channel).authorize()
            return web.Response()
        app.router.add_get("/test-artifact-start", attempt_artifact)
        async def attempt_authority(request):
            authority = HermesRunAuthority(services, request, sink, "technical-digest", {})
            authority.require()
            return web.Response()
        app.router.add_get("/test-authority", attempt_authority)
        async def attempt_cancelled_usage_authority(request):
            authority = HermesRunAuthority(services, request, sink, "technical-digest", {})
            with services.store.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                authority.require_cancelled_usage_in_transaction(db)
            return web.Response()
        app.router.add_get("/test-cancelled-usage-authority", attempt_cancelled_usage_authority)
        async def attempt_meeting_context(request):
            authority = HermesRunAuthority(services, request, sink, "technical-digest", {})
            services.assemble_meeting_context(authority)
            return web.Response()
        app.router.add_get("/test-meeting-context", attempt_meeting_context)
        async def attempt_supervision(request):
            authority = HermesRunAuthority(services, request, sink, "technical-digest", {})
            probe = Path(__file__).with_name("hermes_lifecycle_probe.py")
            process = subprocess.Popen([sys.executable, str(probe), "child", "30"], start_new_session=True,
                                       stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                supervisor = EngineProcessSupervisor(sink, process, process_group=True, authority=authority)
                with pytest.raises(web.HTTPUnauthorized):
                    supervisor.step()
                assert process.wait(timeout=10) == -9
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=10)
            return web.Response(status=401)
        app.router.add_get("/test-supervision", attempt_supervision)
        runner = web.AppRunner(app)
        await runner.setup()
        await web.SockSite(runner, sock).start()
        try:
            async with httpx.AsyncClient(trust_env=False) as client:
                response = await client.get(f"http://127.0.0.1:{port}/test-start")
                assert response.status_code == 401
                response = await client.get(f"http://127.0.0.1:{port}/test-registration")
                assert response.status_code == 401
                response = await client.get(f"http://127.0.0.1:{port}/test-artifact-start")
                assert response.status_code == 401
                response = await client.get(f"http://127.0.0.1:{port}/test-authority")
                assert response.status_code == 401
                response = await client.get(f"http://127.0.0.1:{port}/test-cancelled-usage-authority")
                assert response.status_code == 401
                response = await client.get(f"http://127.0.0.1:{port}/test-meeting-context")
                assert response.status_code == 401
                expired_token = gateway.tokens.issue_api_token(0)
                response = await client.get(f"http://127.0.0.1:{port}/test-authority", headers={"Authorization": "Bearer " + expired_token})
                assert response.status_code == 401
                response = await client.get(f"http://127.0.0.1:{port}/test-supervision")
                assert response.status_code == 401
                response = await client.post(f"http://127.0.0.1:{port}/api/v2/runs", json={"conversation_id": "scope-check", "goal": "检查运行", "selected_refs": [], "request_key": "assembly"})
                assert response.status_code == 401
                assert response.json()["code"] == "UNAUTHENTICATED"
                origin = f"http://127.0.0.1:{port}"
                endpoints = [
                    ("GET", "/api/v2/skill-candidates"),
                    ("GET", "/api/v2/settings/chat-run-budget"),
                    ("PUT", "/api/v2/settings/chat-run-budget"),
                    ("GET", "/api/v2/skill-candidates/check"),
                    ("GET", "/api/v2/skill-candidates/check/maintenance"),
                    ("POST", "/api/v2/skill-candidates/check/decision"),
                    ("GET", "/api/v2/skill-candidates/check/decisions/check"),
                    ("POST", "/api/v2/skill-candidates/check/validation"),
                    ("POST", "/api/v2/skill-candidates/check/publish"),
                    ("GET", "/api/v2/skill-candidates/check/publications/check"),
                    ("POST", "/api/v2/skills/disable"),
                    ("POST", "/api/v2/skills/recover"),
                    ("POST", "/api/v2/skills/cancel"),
                    ("POST", "/api/v2/owner-plans/execution-preview"),
                    ("POST", "/api/v2/run-method-catalog"),
                    ("POST", "/api/v2/owner-plans/execution-decision"),
                    ("POST", "/api/v2/owner-plans/execution-binding"),
                    ("GET", "/api/v2/owner-plans/plan-check/execution-receipts/decision/request-check"),
                    ("GET", "/api/v2/owner-plans/plan-check/execution-receipts/binding/request-check"),
                    ("GET", "/api/v2/runs/run-check/artifacts"),
                    ("GET", "/api/v2/runs/run-check/artifact-requests/request-check"),
                    ("GET", "/api/v2/runs/run-check/legacy-link"),
                    ("GET", "/api/v2/hermes/isolation"),
                    ("POST", "/api/v2/runs/run-check/legacy-link"),
                    ("GET", "/api/v2/runs/00000000-0000-0000-0000-000000000000/resume-status"),
                    ("GET", "/api/v2/runs/00000000-0000-0000-0000-000000000000/source-history/00000000-0000-0000-0000-000000000000?source_id=finance-note&version=1"),
                    ("GET", "/api/v2/runs/00000000-0000-0000-0000-000000000000/artifacts/00000000-0000-0000-0000-000000000000/source-history?source_id=finance-note&version=1&artifact_version=1"),
                    ("GET", "/api/v2/runs/00000000-0000-0000-0000-000000000000/resume-requests/request-check"),
                    ("POST", "/api/v2/runs/00000000-0000-0000-0000-000000000000/resume"),
                    ("POST", "/api/v2/runs/00000000-0000-0000-0000-000000000000/object-scope"),
                    ("POST", "/api/v2/runs/00000000-0000-0000-0000-000000000000/dispatch"),
                    ("GET", "/api/v2/runs/00000000-0000-0000-0000-000000000000/dispatch-requests/check"),
                    ("GET", "/api/v2/runs/00000000-0000-0000-0000-000000000000/dispatch-requests/check/inspection"),
                    ("GET", "/api/v2/artifacts/artifact-check?version=1"),
                    ("GET", "/api/v2/artifacts/artifact-check/file?version=1"),
                    ("GET", "/api/v2/artifacts/artifact-check/versions?version=1"),
                ]
                for method, path in endpoints:
                    response = await client.request(method, origin + path, headers={"Origin": origin}, json={} if method in {"POST", "PUT"} else None)
                    assert response.status_code == 401
                    response = await client.request(method, origin + path, headers={"Origin": "http://example.com"})
                    assert response.status_code == 403
                history_path = "/api/v2/runs/00000000-0000-0000-0000-000000000000/artifacts/00000000-0000-0000-0000-000000000000/source-history?source_id=finance-note&version=1&artifact_version=1"
                dispatch_path = "/api/v2/runs/00000000-0000-0000-0000-000000000000/dispatch"
                assert (await client.get(origin + dispatch_path)).status_code == 405
                assert (await client.post(origin + dispatch_path, headers={"Host": "example.invalid"}, json={"expected_revision": 0})).status_code == 403
                assert (await client.post(origin + dispatch_path, headers={"Sec-Fetch-Site": "cross-site"}, json={"expected_revision": 0})).status_code == 403
                assert (await client.get(origin + history_path, headers={"X-Boss-Role": "BOSS"})).status_code == 401
                assert (await client.get(origin + history_path, headers={"Host": "example.invalid"})).status_code == 403
                assert (await client.get(origin + history_path, headers={"Sec-Fetch-Site": "cross-site"})).status_code == 403
                artifact_paths = ["/api/v2/runs/00000000-0000-0000-0000-000000000000/artifacts", "/api/v2/runs/00000000-0000-0000-0000-000000000000/artifact-requests/request-check", "/api/v2/artifacts/00000000-0000-0000-0000-000000000000?version=1", "/api/v2/artifacts/00000000-0000-0000-0000-000000000000/file?version=1", "/api/v2/artifacts/00000000-0000-0000-0000-000000000000/versions?version=1"]
                for path in artifact_paths:
                    response = await client.get(origin + path)
                    assert response.status_code == 401 and response.json()["code"] == "UNAUTHENTICATED"
                    assert (await client.get(origin + path, headers={"X-Boss-Role": "BOSS"})).status_code == 401
                    assert (await client.get(origin + path, headers={"Host": "example.invalid"})).status_code == 403
                    assert (await client.get(origin + path, headers={"Sec-Fetch-Site": "cross-site"})).status_code == 403
                    assert (await client.post(origin + path)).status_code == 405
            with services.store.connect() as db:
                assert db.execute("SELECT count(*) FROM agent_runs").fetchone()[0] == 0
                assert db.execute("SELECT count(*) FROM hermes_process_evidence").fetchone()[0] == 0
                assert db.execute("SELECT count(*) FROM agent_chat_budget_configs").fetchone()[0] == 0
        finally:
            await runner.cleanup()

    asyncio.run(exercise())


def test_product_assembly_requires_current_run_migration(tmp_path):
    store = ControlStore(tmp_path / "business.sqlite")
    store.initialize("ui-check")
    sessions = MemorySessionManager(tmp_path / "workspace", business_store=store, sessions_root=tmp_path / "sessions")
    with pytest.raises(ValueError):
        hermes_product_application(None, store, sessions, "ui-check", public_port=1234, upstream_port=1235)


def test_artifact_read_boundary_reports_unavailable():
    with pytest.raises(web.HTTPServiceUnavailable) as unavailable:
        require_artifact_read_boundary()
    assert json.loads(unavailable.value.text)["code"] == "SERVICE_NOT_READY"
    assert json.loads(unavailable.value.text)["recovery_action"] == "NONE"
