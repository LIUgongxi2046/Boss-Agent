import asyncio
import hashlib
import json
import socket

import httpx
import pytest
from aiohttp import web
from nanobot.bus.queue import MessageBus
from nanobot.channels.websocket.runtime import WebSocketChannel, WebSocketConfig
from nanobot.config.loader import set_config_path
from nanobot.webui.gateway_services import build_gateway_services

from agent_artifact_routes import install_artifact_read_routes, require_artifact_read_boundary
from agent_run_api import product_application, require_product_engine_ready
from agent_run_broker import RunBroker
from agent_run_scope import RunScopeService
from agent_run_store import RunStore
from boss_memory_sessions import MemorySessionManager
from controls import ControlStore
from hermes_intents import install_owner_decision
from role_channel import RoleChannel


def test_same_origin_interface_boundaries_and_database_state(tmp_path):
    set_config_path(tmp_path / "config.json")
    store = ControlStore(tmp_path / "business.sqlite")
    store.initialize("ui-check")
    runs = RunStore(store.path)
    sessions = MemorySessionManager(tmp_path / "workspace", business_store=store, sessions_root=tmp_path / "sessions")
    scope = RunScopeService(store, sessions, "ui-check")
    broker = RunBroker(runs, scope_service=scope)
    workspace = tmp_path / "artifacts"
    workspace.mkdir()
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
        install_owner_decision(app, channel, broker, public_port=port)
        install_artifact_read_routes(app, channel, scope, workspace, public_port=port)
        runner = web.AppRunner(app)
        await runner.setup()
        await web.SockSite(runner, listener).start()
        requests = [
            ("POST", "/api/v2/runs", {"conversation_id": "technical", "goal": "会议资料", "selected_refs": [], "request_key": "repeat-request"}),
            ("POST", "/api/v2/runs", {}),
            ("POST", "/api/v2/runs/unknown/inputs", {}),
            ("POST", "/api/v2/runs/unknown/cancel", {}),
            ("GET", "/api/v2/runs/unknown/events?after_seq=invalid", None),
            ("GET", "/api/v2/requests/repeat-request", None),
            ("GET", "/api/v2/runs/unknown/artifacts", None),
            ("GET", "/api/v2/artifacts/unknown?version=0", None),
            ("GET", "/api/v2/runs/unknown/intent", None),
            ("POST", "/api/v2/intents/unknown/decision", {"request_key": "repeat-request"}),
            ("GET", "/api/v2/intent-decisions/repeat-request", None),
        ]
        responses = []
        try:
            async with httpx.AsyncClient(trust_env=False) as client:
                for method, path, payload in requests:
                    for label, extra, expected in (("no_auth", {}, 401), ("role_header", {"X-Boss-Role": "BOSS"}, 401),
                                                    ("wrong_role_header", {"X-Boss-Role": "MAINTAINER"}, 401),
                                                    ("invalid_token", {"Authorization": "Bearer invalid"}, 401),
                                                    ("cross_origin", {"Origin": "https://example.invalid"}, 403)):
                        headers = {"Origin": origin, **extra}
                        for attempt in range(2):
                            result = await client.request(method, origin + path, json=payload, headers=headers)
                            assert result.status_code == expected
                            responses.append({"method": method, "path": path, "case": label, "attempt": attempt + 1,
                                              "status": result.status_code, "body": result.text})
        finally:
            await runner.cleanup()
        return responses

    responses = asyncio.run(exercise())
    with store.connect() as db:
        after = hashlib.sha256("\n".join(db.iterdump()).encode()).hexdigest()
        assert db.execute("SELECT count(*) FROM agent_runs").fetchone() == (0,)
        assert db.execute("SELECT count(*) FROM objects WHERE kind='authorization'").fetchone() == (0,)
    assert before == after
    assert list(workspace.iterdir()) == []
    for boundary in (require_product_engine_ready, require_artifact_read_boundary):
        with pytest.raises(web.HTTPServiceUnavailable) as rejected:
            boundary()
        assert rejected.value.status == 503
        assert json.loads(rejected.value.text)["code"] == "SERVICE_NOT_READY"
    (tmp_path / "result.json").write_text(json.dumps({"responses": responses, "database_sha256": before,
        "database_unchanged": before == after, "runs": 0, "authorizations": 0,
        "artifact_files": 0, "direct_service_guards": [503, 503]}, ensure_ascii=False, indent=2), encoding="utf-8")
