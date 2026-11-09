import asyncio
import socket
from uuid import uuid4

import httpx
import pytest
from aiohttp import web

from agent_source_history_routes import install_source_history_routes
from test_agent_run_dispatcher import services_for


def test_history_route_rejects_unauthenticated_and_cross_origin(tmp_path):
    services = services_for(tmp_path)

    async def exercise():
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        listener.setblocking(False)
        port = listener.getsockname()[1]
        app = web.Application()
        install_source_history_routes(app, services.recovery.channel, services.store, services.scope, public_port=port)
        with pytest.raises(ValueError, match="已经注册"):
            install_source_history_routes(app, services.recovery.channel, services.store, services.scope, public_port=port)
        conflict = web.Application()

        async def existing(request):
            return web.Response()

        conflict.router.add_get("/api/v2/runs/{run_id}/source-history/{event_id}", existing)
        with pytest.raises(ValueError, match="已经注册"):
            install_source_history_routes(conflict, services.recovery.channel, services.store, services.scope, public_port=port)
        runner = web.AppRunner(app)
        await runner.setup()
        await web.SockSite(runner, listener).start()
        base = "http://127.0.0.1:" + str(port)
        path = "/api/v2/runs/" + str(uuid4()) + "/source-history/" + str(uuid4()) + "?source_id=finance-note&version=1"
        try:
            async with httpx.AsyncClient(trust_env=False) as client:
                for headers in ({}, {"X-Boss-Role": "BOSS"}, {"Authorization": "Bearer invalid"}):
                    response = await client.get(base + path, headers=headers)
                    assert response.status_code == 401 and response.json()["code"] == "UNAUTHENTICATED"
                assert (await client.get(base + path, headers={"Origin": "https://example.invalid"})).status_code == 403
                assert (await client.get(base + path, headers={"Host": "example.invalid"})).status_code == 403
                assert (await client.get(base + path, headers={"Sec-Fetch-Site": "cross-site"})).status_code == 403
                assert (await client.post(base + path)).status_code == 405
        finally:
            await runner.cleanup()

    asyncio.run(exercise())
