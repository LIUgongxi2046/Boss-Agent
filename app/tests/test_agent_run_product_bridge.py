import asyncio
import json
import socket

import httpx
import pytest
from aiohttp import web
from jsonschema import Draft202012Validator
from nanobot.bus.queue import MessageBus
from nanobot.channels.websocket.runtime import WebSocketChannel, WebSocketConfig
from nanobot.webui.gateway_services import build_gateway_services
from websockets.asyncio.server import serve

from agent_run_api import product_application, require_product_engine_ready
from agent_run_broker import RunBroker
from agent_run_scope import RunScopeService
from agent_run_store import RunStore
from boss_memory_sessions import MemorySessionManager
from controls import ControlStore
from hermes_bridge import HermesBridge, RequestBudgetBoundaryUnavailable
from role_channel import RoleChannel


def test_product_engine_guard_preserves_unavailable_error(tmp_path):
    store = ControlStore(tmp_path / "business.sqlite")
    store.initialize("ui-check")
    run_store = RunStore(store.path)
    with pytest.raises(web.HTTPServiceUnavailable) as rejected:
        require_product_engine_ready()
    assert rejected.value.status == 503
    assert '"code": "SERVICE_NOT_READY"' in rejected.value.text
    with pytest.raises(web.HTTPServiceUnavailable) as create_rejected:
        require_product_engine_ready(for_create=True)
    create_error = json.loads(create_rejected.value.text)
    assert create_error["code"] == "CREATE_NOT_ADMITTED"
    assert create_error["message"] == "运行安全条件尚未通过，本次没有创建运行"
    from agent_run_api import SCHEMA
    Draft202012Validator({"$ref": "#/$defs/error", "$defs": SCHEMA["$defs"]}).validate(create_error)
    with pytest.raises(RequestBudgetBoundaryUnavailable):
        HermesBridge(store).start(run_id="unavailable", lease_epoch=1, budget={"model_requests": 1})
    with run_store.connect() as db:
        assert db.execute("SELECT count(*) FROM agent_runs").fetchone()[0] == 0


def test_product_bridge_rejects_unauthenticated_requests(tmp_path):
    async def exercise():
        bus = MessageBus()
        config = WebSocketConfig()
        gateway = build_gateway_services(config=config, bus=bus, session_manager=None,
            static_dist_path=None, workspace_path=tmp_path, default_restrict_to_workspace=True,
            config_path=tmp_path / "config.json", runtime_model_name=None,
            runtime_surface="webui", runtime_capabilities_overrides=None)
        original = WebSocketChannel(config, bus, gateway=gateway)
        channel = RoleChannel(original, {}, tmp_path / "access.jsonl")
        app = product_application(channel)
        async def subscription(request):
            channel.require_run_subscription(request, request.match_info["chat_id"])
            return web.Response(status=204)
        app.add_routes([web.get("/subscription/{chat_id}", subscription)])
        runner = web.AppRunner(app)
        await runner.setup()
        await web.TCPSite(runner, "127.0.0.1", 0).start()
        product_url = "http://127.0.0.1:" + str(runner.addresses[0][1])
        try:
            async with httpx.AsyncClient() as client:
                for headers in ({}, {"X-Boss-Role": "BOSS"}, {"Authorization": "Bearer invalid"}):
                    response = await client.post(product_url + "/api/v2/runs", json={"goal": "会议资料"}, headers=headers)
                    assert response.status_code == 401
                    assert response.json()["code"] == "UNAUTHENTICATED"
                    response = await client.get(product_url + "/subscription/scope-check", headers=headers)
                    assert response.status_code == 401 and response.json()["code"] == "UNAUTHENTICATED"
                    method_url = product_url + "/api/v2/runs/00000000-0000-0000-0000-000000000000/method-selection"
                    response = await client.post(method_url, json={}, headers=headers)
                    assert response.status_code == 401 and response.json()["code"] == "UNAUTHENTICATED"
                    response = await client.get(method_url + "/requests/example", headers=headers)
                    assert response.status_code == 401 and response.json()["code"] == "UNAUTHENTICATED"
                    response = await client.get(product_url + "/api/v2/runs/00000000-0000-0000-0000-000000000000/available-methods", headers=headers)
                    assert response.status_code == 401 and response.json()["code"] == "UNAUTHENTICATED"
                    response = await client.post(product_url + "/api/v2/runs/00000000-0000-0000-0000-000000000000/object-scope", json={}, headers=headers)
                    assert response.status_code == 401 and response.json()["code"] == "UNAUTHENTICATED"
                    response = await client.get(product_url + "/api/v2/runs/00000000-0000-0000-0000-000000000000/object-scope/candidates", headers=headers)
                    assert response.status_code == 401 and response.json()["code"] == "UNAUTHENTICATED"
                    response = await client.get(product_url + "/api/v2/runs/00000000-0000-0000-0000-000000000000/object-scope/meeting-candidates/meeting-1", headers=headers)
                    assert response.status_code == 401 and response.json()["code"] == "UNAUTHENTICATED"
                    response = await client.get(product_url + "/api/v2/runs/00000000-0000-0000-0000-000000000000/object-scope/requests/example", headers=headers)
                    assert response.status_code == 401 and response.json()["code"] == "UNAUTHENTICATED"
                async with serve(channel._connection_loop, "127.0.0.1", 0, process_request=channel._dispatch_http) as server:
                    websocket_url = "http://127.0.0.1:" + str(server.sockets[0].getsockname()[1])
                    response = await client.post(websocket_url + "/api/v2/runs", json={"goal": "会议资料"})
                    assert response.status_code == 502
        finally:
            await runner.cleanup()

    asyncio.run(exercise())


def test_product_broker_rejects_missing_identity_with_real_scope(tmp_path):
    async def exercise():
        store = ControlStore(tmp_path / "business.sqlite")
        store.initialize("ui-check")
        sessions = MemorySessionManager(tmp_path / "workspace", business_store=store, sessions_root=tmp_path / "sessions")
        sessions.save(sessions.get_or_create("websocket:scope-check"), fsync=True)
        run_store = RunStore(store.path)
        scope = RunScopeService(store, sessions, "ui-check")
        broker = RunBroker(run_store, scope_service=scope)
        bus, config = MessageBus(), WebSocketConfig()
        gateway = build_gateway_services(config=config, bus=bus, session_manager=sessions,
            static_dist_path=None, workspace_path=tmp_path, default_restrict_to_workspace=True,
            config_path=tmp_path / "config.json", runtime_model_name=None,
            runtime_surface="webui", runtime_capabilities_overrides=None)
        channel = RoleChannel(WebSocketChannel(config, bus, gateway=gateway), {}, tmp_path / "access.jsonl", store)
        runner = web.AppRunner(product_application(channel, broker))
        await runner.setup()
        await web.TCPSite(runner, "127.0.0.1", 0).start()
        url = "http://127.0.0.1:" + str(runner.addresses[0][1])
        try:
            async with httpx.AsyncClient() as client:
                request = {"conversation_id": "scope-check", "goal": "准备会议资料", "selected_refs": [], "request_key": "request-1"}
                response = await client.post(url + "/api/v2/runs", json=request, headers={"X-Boss-Role": "BOSS"})
                assert response.status_code == 401
                with run_store.connect() as db:
                    assert db.execute("SELECT count(*) FROM agent_runs").fetchone()[0] == 0
        finally:
            await runner.cleanup()

    asyncio.run(exercise())


def test_same_origin_gateway_rejects_untrusted_requests(tmp_path):
    async def exercise():
        store = ControlStore(tmp_path / "business.sqlite")
        store.initialize("ui-check")
        sessions = MemorySessionManager(tmp_path / "workspace", business_store=store, sessions_root=tmp_path / "sessions")
        run_store = RunStore(store.path)
        broker = RunBroker(run_store, scope_service=RunScopeService(store, sessions, "ui-check"))
        bus, config = MessageBus(), WebSocketConfig()
        gateway = build_gateway_services(config=config, bus=bus, session_manager=sessions,
            static_dist_path=None, workspace_path=tmp_path, default_restrict_to_workspace=True,
            config_path=tmp_path / "config.json", runtime_model_name=None,
            runtime_surface="webui", runtime_capabilities_overrides=None)
        channel = RoleChannel(WebSocketChannel(config, bus, gateway=gateway), {}, tmp_path / "access.jsonl", store)
        async with serve(channel._connection_loop, "127.0.0.1", 0, process_request=channel._dispatch_http) as upstream:
            upstream_port = upstream.sockets[0].getsockname()[1]
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.bind(("127.0.0.1", 0))
            sock.setblocking(False)
            public_port = sock.getsockname()[1]
            origin = "http://127.0.0.1:" + str(public_port)
            runner = web.AppRunner(product_application(channel, broker, public_port=public_port, upstream_port=upstream_port))
            await runner.setup()
            await web.SockSite(runner, sock).start()
            try:
                async with httpx.AsyncClient(trust_env=False) as client:
                    response = await client.get(origin + "/webui/bootstrap")
                    assert response.status_code == 401
                    response = await client.post(origin + "/api/v2/runs", json={"goal": "会议资料"}, headers={"Origin": origin})
                    assert response.status_code == 401 and response.json()["code"] == "UNAUTHENTICATED"
                    response = await client.post(origin + "/api/v2/runs", json={}, headers={"Origin": "http://example.com"})
                    assert response.status_code == 403
                    response = await client.get(origin + "/api/v2/runs/unknown", headers={"Host": "example.com"})
                    assert response.status_code == 403
                    response = await client.get(origin + "/api/v2/runs/unknown", headers={"Sec-Fetch-Site": "cross-site"})
                    assert response.status_code == 403
                    response = await client.get(origin + "/?token=unknown", headers={"Upgrade": "websocket", "Connection": "Upgrade", "Origin": origin})
                    assert response.status_code == 401
                    with run_store.connect() as db:
                        assert db.execute("SELECT count(*) FROM agent_runs").fetchone()[0] == 0
            finally:
                await runner.cleanup()

    asyncio.run(exercise())
