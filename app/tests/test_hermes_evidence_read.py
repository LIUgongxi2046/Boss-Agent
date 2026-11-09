import asyncio
import json
import secrets
import socket

import httpx
import pytest
from aiohttp import web
from tools.registry import registry

from agent_run_tool_budget import RunToolBudget
from business import checksum
from hermes_bridge import EngineEventSink, EngineRunConfig, HermesBridge
from hermes_bi_authority import bi_tool_definitions
from hermes_tool_registration import registered_product_tools
from hermes_transport import HermesTransport
from hermes_transport_client import HermesTransportClient
from test_agent_source_history import prepare_history
from test_agent_run_result import setup_result


def test_evidence_tool_enforces_run_scope_and_goal_revision(tmp_path):
    async def exercise():
        store, runs, results, original_sink = setup_result(tmp_path, full_sources=True)
        run_id = original_sink.config.run_id
        budget = RunToolBudget(runs, allow_migration=True)
        budget.configure(run_id, original_sink.lease_owner, original_sink.config.lease_epoch, 3)
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        listener.setblocking(False)
        endpoint = "http://127.0.0.1:" + str(listener.getsockname()[1])
        config = EngineRunConfig(run_id, original_sink.config.lease_epoch, original_sink.config.engine_commit, endpoint, 1)
        sink = EngineEventSink(runs, config, original_sink.lease_owner)
        capability = secrets.token_urlsafe(32)
        transport = HermesTransport(sink, capability, actor_id="boss-1", space_id="ui-check", scope_service=results.scope, tool_budget=budget, bridge=HermesBridge(store))
        app = web.Application()
        transport.install(app)
        runner = web.AppRunner(app)
        await runner.setup()
        await web.SockSite(runner, listener).start()
        source = "simulation-meeting-material"
        body = {"protocol_version": 1, "call_id": "evidence-1", "source": source}
        brief = {"source_ids": [source], "request_key": "runtime-brief", "format_name": "MARKDOWN", "expected_goal_revision": 1, "meeting_id": "meeting-1", "meeting_version": "1", "sections": [{"kind": "FACT", "text": "核查会议资料", "source_ids": [source]}]}
        headers = {"Authorization": "Bearer " + capability}
        url = endpoint + "/internal/v1/tools/read-evidence"
        try:
            async with httpx.AsyncClient(trust_env=False) as client:
                assert (await client.post(url, json=body)).status_code == 401
                assert (await client.post(url, json={**body, "source": "finance-note"}, headers=headers)).status_code == 403
                first = await client.post(url, json=body, headers=headers)
                assert first.status_code == 200
                assert (await client.post(url, json=body, headers=headers)).json() == first.json()
                with store.connect() as db:
                    document = store.get(db, "ui-check", "document", source)
                assert first.json()["result"]["content"] == document["content"]
                assert first.json()["result"]["version"] == document["version"]
                assert first.json()["result"]["source_sha256"] == checksum(document)
                brief_url = endpoint + "/internal/v1/tools/runtime-meeting-brief"
                assert (await client.post(brief_url, json={"protocol_version": 1, "arguments": brief})).status_code == 401
                invalid = {**brief, "sections": [{"kind": "FACT", "text": "核查会议资料", "source_ids": [source], "owner_id": "boss-1"}]}
                assert (await client.post(brief_url, json={"protocol_version": 1, "arguments": invalid}, headers=headers)).status_code == 400
                assert (await client.post(brief_url, json={"protocol_version": 1, "arguments": brief}, headers=headers)).status_code == 503
                transport_client = HermesTransportClient(endpoint, capability, run_id)
                try:
                    with registered_product_tools(transport_client, bi_definitions=bi_tool_definitions(store, "ui-check")):
                        assert registry.get_entry("workspace_read_file") is not None
                        assert registry.get_entry("workspace_write_file") is not None
                        definitions = registry.get_definitions({"workspace_read_file", "workspace_write_file"}, quiet=True)
                        assert {item["function"]["name"] for item in definitions} == {"workspace_read_file", "workspace_write_file"}
                        assert registry.get_definitions({"boss_runtime_meeting_brief"}, quiet=True) == []
                        with pytest.raises(httpx.HTTPStatusError) as unavailable:
                            await asyncio.to_thread(registry.get_entry("boss_runtime_meeting_brief").handler, brief)
                        assert unavailable.value.response.status_code == 503
                        result = json.loads(await asyncio.to_thread(registry.get_entry("bossEvidenceRead").handler, {"source": source}))
                        assert result["content"] == document["content"]
                        assert result["source_sha256"] == checksum(document)
                        with pytest.raises(httpx.HTTPStatusError) as forbidden:
                            await asyncio.to_thread(registry.get_entry("bossEvidenceRead").handler, {"source": "finance-note"})
                        assert forbidden.value.response.status_code == 403
                finally:
                    transport_client.close()
                document_url = endpoint + "/internal/v1/tools/read-documents"
                document_body = {"protocol_version": 1, "call_id": "document-read"}
                document_result = await client.post(document_url, json=document_body, headers=headers)
                assert document_result.status_code == 200
                assert (await client.get(document_url + "/document-read", headers=headers)).json() == document_result.json()
                assert any(record["data"]["content"] == document["content"] for record in document_result.json()["result"]["records"])
                runs.add_input(run_id, 1, "more-input", "补充会议关注事项")
                rejected = await client.post(url, json={**body, "call_id": "evidence-2"}, headers=headers)
                assert rejected.status_code == 409 and rejected.json()["code"] == "GOAL_CHANGED"
                runs.apply_input(run_id, 1, sink.lease_owner, sink.config.lease_epoch)
                store.control("ui-check", "withdraw", {"source_id": source, "version": document["version"]})
                withdrawn = await client.post(url, json={**body, "call_id": "evidence-withdrawn"}, headers=headers)
                assert withdrawn.status_code >= 400 and document["content"] not in withdrawn.text
                for response in (await client.post(document_url, json=document_body, headers=headers), await client.get(document_url + "/document-read", headers=headers)):
                    assert response.status_code >= 400 and document["content"] not in response.text
                with runs.connect() as db:
                    assert db.execute("SELECT count(*) FROM agent_tool_reservations WHERE run_id=? AND tool_name='bossEvidenceRead'", (run_id,)).fetchone() == (2,)
                    stored = db.execute("SELECT body FROM objects WHERE namespace=? AND kind='hermes_document_result'", ("ui-check",)).fetchone()
                    assert stored is not None and json.loads(stored[0])["state"] == "REVOKED" and "result" not in json.loads(stored[0])
                events = [event for event in runs.events(run_id, 0) if event["type"] == "TOOL_FINISHED" and event["payload"].get("tool_id") == "bossEvidenceRead"]
                assert len(events) == 2 and all(event["payload"]["goal_revision"] == 1 for event in events)
                assert all(event["payload"]["source_ref"] == {"source_id": source, "version": document["version"], "source_sha256": checksum(document)} for event in events)
        finally:
            await runner.cleanup()

    asyncio.run(exercise())


def test_source_revision_blocks_original_tool_results(tmp_path):
    async def exercise():
        store, runs, results, original, commands, source, recorded, _ = prepare_history(tmp_path)
        run_id = original.config.run_id
        budget = RunToolBudget(runs, allow_migration=True)
        budget.configure(run_id, original.lease_owner, original.config.lease_epoch, 4)
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
        evidence_url = endpoint + "/internal/v1/tools/read-evidence"
        document_url = endpoint + "/internal/v1/tools/read-documents"
        evidence_request = {"protocol_version": 1, "call_id": "revision-evidence", "source": source["source_id"]}
        document_request = {"protocol_version": 1, "call_id": "revision-document"}
        try:
            async with httpx.AsyncClient(trust_env=False) as client:
                evidence = await client.post(evidence_url, json=evidence_request, headers=headers)
                documents = await client.post(document_url, json=document_request, headers=headers)
                assert evidence.status_code == documents.status_code == 200
                assert evidence.json()["result"]["version"] == "1"
                assert (await client.get(document_url + "/revision-document", headers=headers)).json() == documents.json()
                saved_event = next(event for event in runs.events(run_id, 0) if event["type"] == "TOOL_FINISHED" and event["payload"].get("call_id") == "revision-evidence")
                assert saved_event["payload"]["source_ref"]["version"] == "1"
                assert recorded["payload"]["source_pins"][0]["version"] == "1"
                revision = {**source, "client_request_id": "source-revision-check", "expected_version": "1"}
                assert commands.execute("MAINTAINER", "boss.knowledge.source.revise", revision)[0] == 200
                for response in (await client.post(evidence_url, json=evidence_request, headers=headers), await client.post(document_url, json=document_request, headers=headers), await client.get(document_url + "/revision-document", headers=headers)):
                    assert response.status_code >= 400 and source["content"] not in response.text
                assert next(event for event in runs.events(run_id, 0) if event["event_id"] == saved_event["event_id"]) == saved_event
                with runs.connect() as db:
                    db.execute("BEGIN")
                    assert runs.result_in_transaction(db, run_id, 1)["payload"]["source_pins"][0]["version"] == "1"
        finally:
            await runner.cleanup()

    asyncio.run(exercise())


def test_tool_budget_replay_and_cancellation(tmp_path):
    async def exercise():
        store, runs, results, original = setup_result(tmp_path, full_sources=True)
        run_id = original.config.run_id
        budget = RunToolBudget(runs, allow_migration=True)
        budget.configure(run_id, original.lease_owner, original.config.lease_epoch, 1)
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
        url = endpoint + "/internal/v1/tools/read-evidence"
        headers = {"Authorization": "Bearer " + capability}
        body = {"protocol_version": 1, "call_id": "budget-read", "source": "simulation-meeting-material"}
        try:
            async with httpx.AsyncClient(trust_env=False) as client:
                first = await client.post(url, json=body, headers=headers)
                assert first.status_code == 200
                assert (await client.post(url, json=body, headers=headers)).json() == first.json()
                exhausted = await client.post(url, json={**body, "call_id": "budget-next"}, headers=headers)
                assert exhausted.status_code == 429 and exhausted.json()["code"] == "TOOL_BUDGET_EXHAUSTED"
                runs.cancel(run_id, runs.read_run(run_id)["revision"])
                for call_id in ("budget-read", "budget-next"):
                    response = await client.post(url, json={**body, "call_id": call_id}, headers=headers)
                    assert response.status_code == 409 and response.json()["code"] == "RUN_NOT_ACTIVE"
                with runs.connect() as db:
                    assert db.execute("SELECT count(*) FROM agent_tool_reservations WHERE run_id=?", (run_id,)).fetchone() == (1,)
                assert len([event for event in runs.events(run_id, 0) if event["type"] == "TOOL_FINISHED" and event["payload"].get("tool_id") == "bossEvidenceRead"]) == 1
        finally:
            await runner.cleanup()

    asyncio.run(exercise())
