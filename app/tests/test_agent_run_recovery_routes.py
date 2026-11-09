import asyncio
import socket
from uuid import uuid4

import httpx
import pytest
from aiohttp import web

from agent_run_recovery_routes import VALIDATORS, install_run_recovery_routes
from test_agent_run_dispatcher import services_for


def test_recovery_receipt_schema_rejects_extra_fields():
    valid = {"run_id": str(uuid4()), "status": "INTERRUPTED", "unknown_reservations": 1}
    assert VALIDATORS["receipt"].is_valid(valid)
    assert not VALIDATORS["receipt"].is_valid({**valid, "actor_id": "technical-owner"})
    assert not VALIDATORS["receipt"].is_valid({**valid, "status": "SUCCEEDED"})
    assert not VALIDATORS["receipt"].is_valid({**valid, "unknown_reservations": -1})


def test_recovery_route_requires_authenticated_same_origin_post(tmp_path):
    services = services_for(tmp_path)

    async def exercise():
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        listener.setblocking(False)
        port = listener.getsockname()[1]
        app = web.Application()
        install_run_recovery_routes(app, services.recovery.channel, services.recovery, public_port=port)
        with pytest.raises(ValueError, match="已经注册"):
            install_run_recovery_routes(app, services.recovery.channel, services.recovery, public_port=port)
        conflict = web.Application()

        async def existing(request):
            return web.Response()

        conflict.router.add_post("/api/v2/runs/{run_id}/recover-expired", existing)
        with pytest.raises(ValueError, match="已经注册"):
            install_run_recovery_routes(conflict, services.recovery.channel, services.recovery, public_port=port)
        runner = web.AppRunner(app)
        await runner.setup()
        await web.SockSite(runner, listener).start()
        base = "http://127.0.0.1:" + str(port)
        url = base + "/api/v2/runs/" + str(uuid4()) + "/recover-expired"
        try:
            async with httpx.AsyncClient(trust_env=False) as client:
                for headers in ({"Origin": base}, {"Origin": base, "X-Boss-Role": "BOSS"}, {"Origin": base, "Authorization": "Bearer invalid"}):
                    response = await client.post(url, json={}, headers=headers)
                    assert response.status_code == 401 and response.json()["code"] == "UNAUTHENTICATED"
                assert (await client.post(url, json={}, headers={"Origin": "https://example.invalid"})).status_code == 403
                assert (await client.post(url, json={}, headers={"Origin": base, "Sec-Fetch-Site": "cross-site"})).status_code == 403
                assert (await client.post(url, json={"actor_id": "technical-owner"}, headers={"Origin": base})).status_code == 401
                assert (await client.get(url, headers={"Origin": base})).status_code == 405
                assert (await client.post(url, content=b"{}", headers={"Origin": base, "Content-Type": "text/plain"})).status_code == 401
                recheck_url = base + "/api/v2/runs/" + str(uuid4()) + "/completion-recheck"
                recheck_body = {"finish_event_id": "technical-finish", "request_key": "technical-recheck"}
                assert (await client.post(recheck_url, json=recheck_body, headers={"Origin": base})).status_code == 401
                assert (await client.post(recheck_url, json=recheck_body, headers={"Origin": "https://example.invalid"})).status_code == 403
                assert (await client.get(recheck_url, headers={"Origin": base})).status_code == 405
        finally:
            await runner.cleanup()

    asyncio.run(exercise())
