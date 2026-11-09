import asyncio
import json
import secrets
import socket
import subprocess
from pathlib import Path

import httpx
from aiohttp import web

from agent_run_broker import RunBroker, RunIdentity
from agent_run_tool_budget import RunToolBudget
from hermes_bridge import EngineEventSink, EngineRunConfig, HermesBridge
from hermes_transport import HermesTransport
from test_agent_run_result import setup_result


ROOT = Path(__file__).resolve().parents[2]


def test_recorded_question_reaches_component(tmp_path):
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
        proof = results.scope.prove("result-check", ["simulation-meeting-material"])
        identity = RunIdentity(proof.owner_id, proof.namespace, "BOSS", frozenset({proof.chat_id}), frozenset({"simulation-meeting-material"}))
        broker = RunBroker(runs, scope_service=results.scope)
        question = "请提供会议需要讨论的事项。"
        async with httpx.AsyncClient(trust_env=False) as client:
            response = await client.post(endpoint + "/internal/v1/tools/input-required", headers={"Authorization": "Bearer " + capability}, json={"protocol_version": 1, "call_id": "technical-question", "goal_revision": 1, "question": question})
            assert response.status_code == 200
        snapshot = broker.read(identity, run_id)
        events = broker.events(identity, run_id, 0)["events"]
        output = subprocess.run(["node", str(ROOT / "app/tests/u2_09_waiting_question_check.cjs")], cwd=ROOT,
                                input=json.dumps({"snapshot":snapshot,"events":events}, ensure_ascii=False), text=True, capture_output=True)
        assert output.returncode == 0, output.stderr
        assert json.loads(output.stdout)["checked"]
        await runner.cleanup()

    asyncio.run(exercise())
