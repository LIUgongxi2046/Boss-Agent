import asyncio
import json
import secrets
import socket
import subprocess
import sys
from pathlib import Path

import httpx
import pytest
from aiohttp import web
from tools.registry import registry

from agent_run_tool_budget import RunToolBudget
from hermes_bridge import EngineEventSink, EngineProcessSupervisor, EngineRunConfig, HermesBridge
from hermes_tool_registration import registered_product_tools
from hermes_bi_authority import bi_tool_definitions
from hermes_transport import HermesTransport
from hermes_transport_client import HermesTransportClient
from test_agent_run_result import setup_result


def test_input_required_records_received_question_and_current_goal(tmp_path):
    async def exercise():
        store, runs, results, original = setup_result(tmp_path, full_sources=True)
        run_id = original.config.run_id
        budget = RunToolBudget(runs, allow_migration=True)
        budget.configure(run_id, original.lease_owner, original.config.lease_epoch, 2)
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        listener.setblocking(False)
        endpoint = "http://127.0.0.1:" + str(listener.getsockname()[1])
        config = EngineRunConfig(run_id, original.config.lease_epoch, original.config.engine_commit, endpoint, 1)
        sink = EngineEventSink(runs, config, original.lease_owner)
        capability = secrets.token_urlsafe(32)
        transport = HermesTransport(sink, capability, actor_id="boss-1", space_id="ui-check", scope_service=results.scope, tool_budget=budget, bridge=HermesBridge(store))
        app = web.Application()
        transport.install(app)
        runner = web.AppRunner(app)
        await runner.setup()
        await web.SockSite(runner, listener).start()
        headers = {"Authorization": "Bearer " + capability}
        url = endpoint + "/internal/v1/tools/input-required"
        question = "请提供本次会议需要讨论的事项。"
        body = {"protocol_version": 1, "call_id": "input-check", "goal_revision": 2, "question": question}
        try:
            async with httpx.AsyncClient(trust_env=False) as client:
                assert (await client.post(url, json=body)).status_code == 401
                changed = await client.post(url, json=body, headers=headers)
                assert changed.status_code == 409 and changed.json()["code"] == "GOAL_CHANGED"
                assert (await client.post(url, json={**body, "goal_revision": 1, "question": "   "}, headers=headers)).status_code == 400
                client_tool = HermesTransportClient(endpoint, capability, run_id)
                try:
                    assert client_tool.waiting_state is None
                    with pytest.raises(httpx.HTTPStatusError):
                        await asyncio.to_thread(client_tool.request_additional_input, question, 2, "invalid-goal")
                    assert client_tool.waiting_state is None
                    with registered_product_tools(client_tool, bi_definitions=bi_tool_definitions(store, "ui-check")):
                        create = registry.get_entry("create_managed_child").handler
                        with pytest.raises(httpx.HTTPStatusError) as failure:
                            await asyncio.to_thread(create, {"request_key": "delegate-check", "description": "读取当前运行授权范围"})
                        assert failure.value.response.status_code == 503
                        for name in ("dispatch_managed_child", "read_managed_child_result"):
                            handler = registry.get_entry(name).handler
                            with pytest.raises(ValueError, match="参数无效"):
                                handler({"child_id": run_id})
                        response = json.loads(await asyncio.to_thread(registry.get_entry("request_additional_input").handler, {"question": question}))
                        assert response["status"] == "WAITING_INPUT" and response["goal_revision"] == 1
                        assert client_tool.waiting_state == "WAITING_INPUT"
                finally:
                    client_tool.close()
                events = runs.events(run_id, 0)
                required = [event for event in events if event["type"] == "INPUT_REQUIRED"]
                assert len(required) == 1 and required[0]["event_id"] == response["event_id"]
                assert required[0]["payload"] == {"question": question, "goal_revision": 1}
                assert any(event["type"] == "STATUS_CHANGED" and event["payload"].get("input_required_event_id") == response["event_id"] for event in events)
                assert runs.read_run(run_id)["status"] == "WAITING_INPUT"
                assert (await client.post(url, json={**body, "goal_revision": 1}, headers=headers)).status_code == 409
                assert len([event for event in runs.events(run_id, 0) if event["type"] == "INPUT_REQUIRED"]) == 1
                probe = Path(__file__).with_name("hermes_lifecycle_probe.py")
                process = subprocess.Popen([sys.executable, str(probe), "child", "30"], start_new_session=True,
                                           stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                try:
                    supervisor = EngineProcessSupervisor(sink, process, process_group=True)
                    assert supervisor.step() == "REQUIREMENTS_STOP_SENT"
                    assert supervisor.step() in {"REQUIREMENTS_STOP_WAITING", "WAITING_INPUT"}
                    process.wait(timeout=10)
                    assert supervisor.observe_exit() == "WAITING_INPUT"
                finally:
                    if process.poll() is None:
                        process.kill()
                        process.wait(timeout=10)
        finally:
            await runner.cleanup()

    asyncio.run(exercise())
