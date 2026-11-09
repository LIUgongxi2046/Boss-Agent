import asyncio
import hashlib
import json
import os
import socket
from pathlib import Path

import httpx
from aiohttp import web
from nanobot.bus.queue import MessageBus
from nanobot.channels.websocket.runtime import WebSocketChannel, WebSocketConfig
from nanobot.webui.gateway_services import build_gateway_services
from websockets.asyncio.server import serve

from agent_run_api import product_application
from application_paths import application_frontend_directory
from role_channel import RoleChannel


ROOT = Path(__file__).resolve().parents[2]


def test_independent_frontend_through_product_gateway(tmp_path):
    async def exercise():
        frontend = application_frontend_directory(ROOT / "validation", os.environ["BOSS_PRODUCT_FRONTEND_DIR"])
        manifest = json.loads((frontend / "asset-manifest.json").read_text())
        entry = manifest["index.html"]
        assert entry["isEntry"] is True
        assets = {"index.html"}
        for item in manifest.values():
            assets.add(item["file"])
            assets.update(item.get("css", []))
            assets.update(item.get("assets", []))
        assets.update(path.relative_to(frontend).as_posix() for path in (frontend / "boss-brand").iterdir())
        assert len(assets) > 12
        assert all((frontend / name).is_file() for name in assets)
        config = WebSocketConfig()
        bus = MessageBus()
        gateway = build_gateway_services(
            config=config, bus=bus, session_manager=None,
            static_dist_path=frontend, workspace_path=tmp_path,
            default_restrict_to_workspace=True, config_path=tmp_path / "config.json",
            runtime_model_name=None, runtime_surface="webui", runtime_capabilities_overrides=None,
        )
        channel = RoleChannel(WebSocketChannel(config, bus, gateway=gateway), {}, tmp_path / "access.jsonl")
        async with serve(channel._connection_loop, "127.0.0.1", 0, process_request=channel._dispatch_http) as upstream:
            upstream_port = upstream.sockets[0].getsockname()[1]
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.bind(("127.0.0.1", 0))
            sock.setblocking(False)
            public_port = sock.getsockname()[1]
            origin = f"http://127.0.0.1:{public_port}"
            runner = web.AppRunner(product_application(channel, public_port=public_port, upstream_port=upstream_port))
            await runner.setup()
            await web.SockSite(runner, sock).start()
            try:
                async with httpx.AsyncClient(trust_env=False) as client:
                    for name in sorted(assets):
                        response = await client.get(origin + ("/" if name == "index.html" else "/" + name))
                        assert response.status_code == 200
                        assert hashlib.sha256(response.content).digest() == hashlib.sha256((frontend / name).read_bytes()).digest()
                    assert (await client.get(origin + "/webui/bootstrap")).status_code == 401
                    assert (await client.get(origin + "/api/boss/identity")).status_code == 401
                    assert (await client.get(origin + "/api/boss/ui/evidence", params={"source": "finance-note"})).status_code == 401
                    response = await client.post(origin + "/api/v2/runs", json={})
                    assert response.status_code == 401
                    assert response.json()["code"] == "UNAUTHENTICATED"
            finally:
                await runner.cleanup()

    asyncio.run(exercise())
