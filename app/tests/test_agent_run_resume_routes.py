import asyncio
import socket
from uuid import uuid4

import httpx
import pytest
from aiohttp import web

from agent_run_resume_routes import VALIDATORS, install_run_resume_routes
from test_agent_run_dispatcher import services_for


def test_resume_request_schema_rejects_extra_fields_and_invalid_versions():
    valid = {"expected_revision": 0, "expected_goal_revision": 1, "request_key": "technical-request"}
    assert VALIDATORS["request"].is_valid(valid)
    assert not VALIDATORS["request"].is_valid({**valid, "actor_id": "technical-owner"})
    assert not VALIDATORS["request"].is_valid({**valid, "expected_goal_revision": 0})
    assert not VALIDATORS["request"].is_valid({**valid, "expected_revision": True})


def test_resume_routes_reject_unauthenticated_and_cross_origin(tmp_path):
    services = services_for(tmp_path)

    async def exercise():
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        listener.setblocking(False)
        port = listener.getsockname()[1]
        app = web.Application()
        install_run_resume_routes(app, services.recovery.channel, services.broker, public_port=port)
        with pytest.raises(ValueError, match="已经注册"):
            install_run_resume_routes(app, services.recovery.channel, services.broker, public_port=port)
        conflict = web.Application()

        async def existing(request):
            return web.Response()

        conflict.router.add_post("/api/v2/runs/{run_id}/resume", existing)
        with pytest.raises(ValueError, match="已经注册"):
            install_run_resume_routes(conflict, services.recovery.channel, services.broker, public_port=port)
        runner = web.AppRunner(app)
        await runner.setup()
        await web.SockSite(runner, listener).start()
        base = "http://127.0.0.1:" + str(port)
        prefix = "/api/v2/runs/" + str(uuid4())
        try:
            async with httpx.AsyncClient(trust_env=False) as client:
                for path in (prefix + "/resume-status", prefix + "/resume-requests/request-1"):
                    for headers in ({}, {"X-Boss-Role": "BOSS"}, {"Authorization": "Bearer invalid"}):
                        result = await client.get(base + path, headers=headers)
                        assert result.status_code == 401 and result.json()["code"] == "UNAUTHENTICATED"
                    assert (await client.get(base + path, headers={"Origin": "https://example.invalid"})).status_code == 403
                    assert (await client.post(base + path)).status_code == 405
                payload = {"expected_revision": 0, "expected_goal_revision": 1, "request_key": "request-1"}
                for headers in ({"Origin": base}, {"Origin": base, "X-Boss-Role": "BOSS"}, {"Origin": base, "Authorization": "Bearer invalid"}):
                    result = await client.post(base + prefix + "/resume", json=payload, headers=headers)
                    assert result.status_code == 401 and result.json()["code"] == "UNAUTHENTICATED"
                assert (await client.post(base + prefix + "/resume", json=payload)).status_code == 403
                assert (await client.post(base + prefix + "/resume", json=payload, headers={"Origin": base, "Sec-Fetch-Site": "cross-site"})).status_code == 403
                assert (await client.get(base + prefix + "/resume")).status_code == 405
        finally:
            await runner.cleanup()

    asyncio.run(exercise())
