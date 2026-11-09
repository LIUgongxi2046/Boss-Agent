import asyncio
import socket
from uuid import uuid4

import httpx
import pytest
from aiohttp import web
from nanobot.bus.queue import MessageBus
from nanobot.channels.websocket.runtime import WebSocketChannel, WebSocketConfig
from nanobot.webui.gateway_services import build_gateway_services

from agent_artifact_routes import install_artifact_read_routes
from agent_artifact_workspace import ArtifactWorkspace
from agent_run_scope import RunScopeService
from boss_memory_sessions import MemorySessionManager
from boss_source_access import require_current_business_source
from controls import ControlStore
from role_channel import RoleChannel


@pytest.mark.parametrize("mapped", [False, True])
def test_artifact_routes_reject_unauthenticated_and_cross_origin(tmp_path, mapped):
    store = ControlStore(tmp_path / "business.sqlite")
    store.initialize("ui-check")
    workspace = tmp_path / "artifacts"
    workspace.mkdir()
    if mapped:
        workspace = ArtifactWorkspace(workspace.resolve())
    sessions = MemorySessionManager(tmp_path / "workspace", business_store=store, sessions_root=tmp_path / "sessions")
    scope = RunScopeService(store, sessions, "ui-check")
    store.control("ui-check", "withdraw", {"source_id": "finance-note", "version": "1"})
    with store.connect() as db:
        db.execute("BEGIN")
        with pytest.raises(web.HTTPGone):
            require_current_business_source(store, db, "ui-check", "boss-1", "finance-note")

    async def exercise():
        bus, config = MessageBus(), WebSocketConfig()
        gateway = build_gateway_services(config=config, bus=bus, session_manager=sessions,
            static_dist_path=None, workspace_path=tmp_path, default_restrict_to_workspace=True,
            config_path=tmp_path / "config.json", runtime_model_name=None,
            runtime_surface="webui", runtime_capabilities_overrides=None)
        channel = RoleChannel(WebSocketChannel(config, bus, gateway=gateway), {}, tmp_path / "access.jsonl", store)
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        listener.setblocking(False)
        port = listener.getsockname()[1]
        app = web.Application()
        install_artifact_read_routes(app, channel, scope, workspace, public_port=port)
        with pytest.raises(ValueError, match="已经注册"):
            install_artifact_read_routes(app, channel, scope, workspace, public_port=port)
        conflicting = web.Application()
        async def existing(request):
            return web.Response()
        conflicting.router.add_get("/api/v2/artifacts/{artifact_id}", existing)
        with pytest.raises(ValueError, match="已经注册"):
            install_artifact_read_routes(conflicting, channel, scope, workspace, public_port=port)
        runner = web.AppRunner(app)
        await runner.setup()
        await web.SockSite(runner, listener).start()
        run_id, artifact_id = str(uuid4()), str(uuid4())
        paths = [f"/api/v2/runs/{run_id}/artifacts", f"/api/v2/runs/{run_id}/artifact-pending-requests", f"/api/v2/runs/{run_id}/artifact-requests/original-request",
                 f"/api/v2/artifacts/{artifact_id}?version=1", f"/api/v2/artifacts/{artifact_id}/versions?version=1",
                 f"/api/v2/artifacts/{artifact_id}/file?version=1"]
        try:
            async with httpx.AsyncClient(trust_env=False) as client:
                base = "http://127.0.0.1:" + str(port)
                for path in paths:
                    for headers in ({}, {"X-Boss-Role": "BOSS"}):
                        response = await client.get(base + path, headers=headers)
                        assert response.status_code == 401 and response.json()["code"] == "UNAUTHENTICATED"
                    response = await client.get(base + path, headers={"Origin": "https://example.invalid"})
                    assert response.status_code == 403
                    response = await client.get(base + path, headers={"Host": "example.invalid"})
                    assert response.status_code == 403
                    response = await client.get(base + path, headers={"Sec-Fetch-Site": "cross-site"})
                    assert response.status_code == 403
                    response = await client.post(base + path)
                    assert response.status_code == 405
        finally:
            await runner.cleanup()

    asyncio.run(exercise())


def test_artifact_routes_require_existing_workspace(tmp_path):
    store = ControlStore(tmp_path / "business.sqlite")
    store.initialize("ui-check")
    sessions = MemorySessionManager(tmp_path / "workspace", business_store=store, sessions_root=tmp_path / "sessions")
    scope = RunScopeService(store, sessions, "ui-check")
    bus, config = MessageBus(), WebSocketConfig()
    gateway = build_gateway_services(config=config, bus=bus, session_manager=sessions,
        static_dist_path=None, workspace_path=tmp_path, default_restrict_to_workspace=True,
        config_path=tmp_path / "config.json", runtime_model_name=None,
        runtime_surface="webui", runtime_capabilities_overrides=None)
    channel = RoleChannel(WebSocketChannel(config, bus, gateway=gateway), {}, tmp_path / "access.jsonl", store)
    with pytest.raises(ValueError, match="已存在"):
        install_artifact_read_routes(web.Application(), channel, scope, tmp_path / "missing", public_port=12345)


def test_pending_requests_rejects_unauthenticated_access(tmp_path):
    async def exercise():
        store = ControlStore(tmp_path / "business.sqlite")
        store.initialize("ui-check")
        sessions = MemorySessionManager(tmp_path / "workspace", business_store=store, sessions_root=tmp_path / "sessions")
        scope = RunScopeService(store, sessions, "ui-check")
        bus, config = MessageBus(), WebSocketConfig()
        gateway = build_gateway_services(config=config, bus=bus, session_manager=sessions,
            static_dist_path=None, workspace_path=tmp_path, default_restrict_to_workspace=True,
            config_path=tmp_path / "config.json", runtime_model_name=None,
            runtime_surface="webui", runtime_capabilities_overrides=None)
        channel = RoleChannel(WebSocketChannel(config, bus, gateway=gateway), {}, tmp_path / "access.jsonl", store)
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        listener.setblocking(False)
        port = listener.getsockname()[1]
        workspace = tmp_path / "artifacts"
        workspace.mkdir()
        app = web.Application()
        install_artifact_read_routes(app, channel, scope, workspace, public_port=port)
        runner = web.AppRunner(app)
        await runner.setup()
        await web.SockSite(runner, listener).start()
        try:
            async with httpx.AsyncClient(trust_env=False) as client:
                response = await client.get(f"http://127.0.0.1:{port}/api/v2/runs/{uuid4()}/artifact-pending-requests")
                assert response.status_code == 401
                assert response.json()["code"] == "UNAUTHENTICATED"
        finally:
            await runner.cleanup()
    asyncio.run(exercise())
