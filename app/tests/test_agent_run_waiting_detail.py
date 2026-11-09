import asyncio
import secrets
import socket

import httpx
import pytest
from aiohttp import web

from agent_run_api import VALIDATORS
from agent_run_broker import RunBroker, RunIdentity
from agent_run_store import RunStore
from agent_run_tool_budget import RunToolBudget
from hermes_bridge import EngineEventSink, EngineRunConfig, HermesBridge
from hermes_transport import HermesTransport
from test_agent_run_result import setup_result


def test_waiting_question_propagates_real_recorded_tool_input(tmp_path):
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
        try:
            async with httpx.AsyncClient(trust_env=False) as client:
                response = await client.post(endpoint + "/internal/v1/tools/input-required", headers={"Authorization": "Bearer " + capability}, json={"protocol_version": 1, "call_id": "technical-question", "goal_revision": 1, "question": question})
                assert response.status_code == 200
                snapshot = broker.read(identity, run_id)
                assert snapshot["waiting_input"] == {"event_id": response.json()["event_id"], "goal_revision": 1, "question": question}
                assert VALIDATORS["snapshot"].is_valid(snapshot)
                denied = RunIdentity(proof.owner_id, proof.namespace, "MAINTAINER", identity.conversation_ids, identity.source_refs)
                with pytest.raises(web.HTTPForbidden):
                    broker.read(denied, run_id)
                payload = {"expected_goal_revision": 1, "request_key": "supplement", "input": "讨论会议日程"}
                added = broker.mutate(identity, run_id, "inputs", payload)
                assert broker.mutate(identity, run_id, "inputs", payload) == added
                assert broker.request_receipt(identity, "supplement")["receipt"] == added
                reopened = RunBroker(RunStore(runs.path, allow_migration=False), scope_service=results.scope)
                assert reopened.request_receipt(identity, "supplement")["receipt"] == added
                with pytest.raises(web.HTTPConflict):
                    broker.mutate(identity, run_id, "inputs", {**payload, "input": "讨论其他事项"})
                with runs.connect() as db:
                    db.execute("BEGIN IMMEDIATE")
                    db.execute("UPDATE agent_run_events SET payload=? WHERE run_id=? AND type='INPUT_RECEIVED'", ('{"input_id":"invalid"}', run_id))
                    with pytest.raises(ValueError, match="接收事件"):
                        broker.verify_input_receipt_in_transaction(db, run_id, "supplement", added)
                    db.rollback()
                assert "waiting_input" not in broker.read(identity, run_id)
                store.control("ui-check", "withdraw", {"source_id": "simulation-meeting-material", "version": "1"})
                with pytest.raises((ValueError, web.HTTPException)):
                    broker.read(identity, run_id)
                with pytest.raises((ValueError, web.HTTPException)):
                    reopened.request_receipt(identity, "supplement")
        finally:
            await runner.cleanup()

    asyncio.run(exercise())
