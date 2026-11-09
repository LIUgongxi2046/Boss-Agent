import asyncio
import hashlib
import json
import socket

import httpx
from aiohttp import web
from nanobot.bus.queue import MessageBus
from nanobot.channels.websocket.runtime import WebSocketChannel, WebSocketConfig
from nanobot.config.loader import set_config_path
from nanobot.webui.gateway_services import build_gateway_services

from agent_run_api import product_application
from agent_run_broker import RunBroker
from agent_run_scope import RunScopeService
from agent_run_store import RunStore
from boss_memory_sessions import MemorySessionManager
from controls import ControlStore
from hermes_plan_routes import install_plan_execution
from role_channel import RoleChannel


def test_plan_receipts_reject_unauthenticated_requests(tmp_path):
    set_config_path(tmp_path / "config.json")
    store = ControlStore(tmp_path / "business.sqlite")
    store.initialize("ui-check")
    runs = RunStore(store.path)
    sessions = MemorySessionManager(tmp_path / "workspace", business_store=store, sessions_root=tmp_path / "sessions")
    scope = RunScopeService(store, sessions, "ui-check")
    broker = RunBroker(runs, scope_service=scope)
    with store.connect() as db:
        before = hashlib.sha256("\n".join(db.iterdump()).encode()).hexdigest()

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
        origin = f"http://127.0.0.1:{port}"
        app = product_application(channel, broker, public_port=port, upstream_port=9)
        install_plan_execution(app, channel, store, scope, public_port=port)
        runner = web.AppRunner(app)
        await runner.setup()
        await web.SockSite(runner, listener).start()
        paths = [("POST", "/api/v2/owner-plans/execution-methods"),
                 ("POST", "/api/v2/owner-plans/execution-preview"),
                 ("POST", "/api/v2/owner-plans/execution-decision"),
                 ("POST", "/api/v2/owner-plans/execution-binding"),
                 ("GET", "/api/v2/owner-plans/technical-plan/execution-receipts/decision/technical-request"),
                 ("GET", "/api/v2/owner-plans/technical-plan/execution-receipts/binding/technical-request")]
        results = []
        try:
            async with httpx.AsyncClient(trust_env=False) as client:
                for method, path in paths:
                    for request_origin, expected in ((origin, 401), ("https://example.invalid", 403)):
                        response = await client.request(method, origin + path, headers={"Origin": request_origin}, json={} if method == "POST" else None)
                        assert response.status_code == expected
                        results.append({"method": method, "path": path, "status": response.status_code, "body": response.text})
        finally:
            await runner.cleanup()
        return results

    results = asyncio.run(exercise())
    with store.connect() as db:
        after = hashlib.sha256("\n".join(db.iterdump()).encode()).hexdigest()
        assert db.execute("SELECT count(*) FROM agent_runs").fetchone() == (0,)
        assert db.execute("SELECT count(*) FROM objects WHERE kind='authorization'").fetchone() == (0,)
    assert before == after
    (tmp_path / "result.json").write_text(json.dumps({"responses": results, "database_sha256": before,
        "database_unchanged": before == after}, ensure_ascii=False), encoding="utf-8")
