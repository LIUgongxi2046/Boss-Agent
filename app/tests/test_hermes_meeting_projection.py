import asyncio
import json
import secrets
import socket
import sqlite3
from dataclasses import asdict
from datetime import datetime, timedelta

import httpx
import pytest
from aiohttp import web
from tools.registry import registry

from agent_run_tool_budget import RunToolBudget
from boss_meetings import MeetingAPI
from hermes_bridge import EngineEventSink, EngineRunConfig, HermesBridge
from hermes_domain_intents import read_meeting_projection_in_transaction
from hermes_tool_registration import registered_product_tools
from hermes_bi_authority import bi_tool_definitions
from hermes_transport import HermesTransport
from hermes_transport_client import HermesTransportClient
from test_agent_run_result import setup_result


def test_meeting_tools_use_current_selected_scope(tmp_path):
    async def exercise():
        store, runs, results, original = setup_result(tmp_path, full_sources=True)
        run_id = original.config.run_id
        budget = RunToolBudget(runs, allow_migration=True)
        budget.configure(run_id, original.lease_owner, original.config.lease_epoch, 6)
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
        selected = {"simulation-meeting-material"}
        try:
            async with httpx.AsyncClient(trust_env=False) as client:
                for kind in ("catalog", "arrangement"):
                    url = endpoint + "/internal/v1/tools/meeting-projection/" + kind
                    body = {"protocol_version": 1, "call_id": "read-" + kind}
                    assert (await client.post(url, json=body)).status_code == 401
                    response = await client.post(url, json=body, headers=headers)
                    assert response.status_code == 200
                    result = response.json()["result"]
                    assert (await client.post(url, json=body, headers=headers)).json() == response.json()
                    assert {ref["source_id"] for ref in result["meeting"]["source_refs"]} <= selected
                    with store.connect() as db:
                        outside_document = store.get(db, "ui-check", "document", "finance-note")
                    assert outside_document["content"] not in json.dumps(result, ensure_ascii=False)
                    if kind == "catalog":
                        assert result["library"]["scope"] == "SELECTED_MEETING_SOURCES"
                        assert all({ref["source_id"] for ref in item["source_refs"]} <= selected for item in result["library"]["records"])
                        assert {item["source_id"] for item in result["documents"]} <= selected
                        with store.connect() as db:
                            for item in result["documents"]:
                                document = store.get(db, "ui-check", "document", item["source_id"])
                                assert item["version"] == document["version"]
                                assert item["original_locator"] == document.get("original_locator")
                                assert item["author_contact_id"] == document.get("author_contact_id")
                        assert all(action["source_id"] in selected for item in result["library"]["records"] for action in item["actions"])
                        assert all(item["target_kind"] == "meeting" for item in result["library"]["insights"])
                    else:
                        assert result["scope"] == "SELECTED_MEETING_SOURCES"
                        assert {item["contact_id"] for item in result["contacts"]} == set(result["meeting"]["participant_ids"])
                        assert result["invitation_sent"] is None
                        assert {item["source_id"] for item in result["sources"]} <= selected
                        with store.connect() as db:
                            data = MeetingAPI(store)._data(db)
                            assert result["meeting"]["preparation_due_at"] == data["meeting"].get("preparation_due_at")
                            assert result["contacts"] == [contact for contact in data["contacts"] if contact["contact_id"] in data["meeting"]["participant_ids"]]
                client_tool = HermesTransportClient(endpoint, capability, run_id)
                try:
                    with registered_product_tools(client_tool, bi_definitions=bi_tool_definitions(store, "ui-check")):
                        for name in ("bossMeetingsRead", "meetingArrangementRead"):
                            result = json.loads(await asyncio.to_thread(registry.get_entry(name).handler, {}))
                            assert {item["source_id"] for item in result["meeting"]["source_refs"]} <= selected
                finally:
                    client_tool.close()
                for index in (1, 2):
                    response = await client.post(endpoint + "/internal/v1/tools/meeting-projection/catalog",
                        json={"protocol_version": 1, "call_id": "budget-" + str(index)}, headers=headers)
                    assert response.status_code == 200
                exhausted = await client.post(endpoint + "/internal/v1/tools/meeting-projection/catalog",
                    json={"protocol_version": 1, "call_id": "budget-exhausted"}, headers=headers)
                assert exhausted.status_code == 429
                with store.connect() as db:
                    data = MeetingAPI(store)._data(db)
                    meeting = data["meeting"]
                    store.put(db, "ui-check", "meeting", meeting["meeting_id"], {**meeting, "version": str(int(meeting["version"]) + 1)})
                for kind in ("catalog", "arrangement"):
                    response = await client.post(endpoint + "/internal/v1/tools/meeting-projection/" + kind,
                        json={"protocol_version": 1, "call_id": "read-" + kind}, headers=headers)
                    assert response.status_code == 409 and response.json()["code"] == "TOOL_REQUEST_CONFLICT"
                assert len([event for event in runs.events(run_id, 0) if event["type"] == "TOOL_FINISHED" and event["payload"].get("tool_id") in {"bossMeetingsRead", "meetingArrangementRead"}]) == 6
                empty_scope = results.scope.prove("result-check", [])
                with runs.connect() as db:
                    db.execute("UPDATE agent_runs SET selected_refs=?,scope_proof=? WHERE run_id=?", ("[]", json.dumps(asdict(empty_scope)), run_id))
                for kind in ("catalog", "arrangement"):
                    response = await client.post(endpoint + "/internal/v1/tools/meeting-projection/" + kind,
                        json={"protocol_version": 1, "call_id": "outside-" + kind}, headers=headers)
                    assert response.status_code == 403
                with runs.connect() as db:
                    db.execute("UPDATE agent_runs SET lease_owner='other-worker',lease_epoch=lease_epoch+1 WHERE run_id=?", (run_id,))
                for kind in ("catalog", "arrangement"):
                    response = await client.post(endpoint + "/internal/v1/tools/meeting-projection/" + kind,
                        json={"protocol_version": 1, "call_id": "old-lease-" + kind}, headers=headers)
                    assert response.status_code == 409 and response.json()["code"] == "RUN_LEASE_UNAVAILABLE"
        finally:
            await runner.cleanup()

    asyncio.run(exercise())


def test_selected_meeting_insights_use_current_domain_projection(tmp_path):
    store, runs, results, sink = setup_result(tmp_path, full_sources=True)
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        data = MeetingAPI(store)._data(db)
        meeting = data["meeting"]
        clock = store.get(db, "ui-check", "clock", "current")["at"]
        starts_at = (datetime.fromisoformat(clock) + timedelta(hours=24)).isoformat()
        store.put(db, "ui-check", "meeting", meeting["meeting_id"], {**meeting, "material_ids": ["simulation-meeting-material"], "starts_at": starts_at})
    with runs.connect() as db:
        db.execute("BEGIN")
        db.row_factory = sqlite3.Row
        run = db.execute("SELECT * FROM agent_runs WHERE run_id=?", (sink.config.run_id,)).fetchone()
        result = read_meeting_projection_in_transaction(db, store, results.scope, run, "catalog")
    meetings = [item for item in result["library"]["records"] if item["kind"] == "meeting"]
    assert len(meetings) == 1 and meetings[0]["id"] == meeting["meeting_id"]
    assert len(result["library"]["insights"]) == 1
    assert result["library"]["insights"][0]["target_kind"] == "meeting"
    assert all(ref["source_id"] == "simulation-meeting-material" for item in result["library"]["records"] for ref in item["source_refs"])
    with store.connect() as db:
        document = store.get(db, "ui-check", "document", "simulation-meeting-material")
    store.control("ui-check", "withdraw", {"source_id": document["source_id"], "version": document["version"]})
    with runs.connect() as db:
        db.execute("BEGIN")
        db.row_factory = sqlite3.Row
        run = db.execute("SELECT * FROM agent_runs WHERE run_id=?", (sink.config.run_id,)).fetchone()
        for kind in ("catalog", "arrangement"):
            with pytest.raises((ValueError, web.HTTPException)):
                read_meeting_projection_in_transaction(db, store, results.scope, run, kind)
