import asyncio
import hashlib
import socket
import sqlite3
import sys
from dataclasses import replace
from pathlib import Path

import pytest
import httpx
from aiohttp import web
from nanobot.bus.queue import MessageBus
from nanobot.channels.websocket.runtime import WebSocketChannel, WebSocketConfig
from nanobot.webui.gateway_services import build_gateway_services

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "validation"))

from agent_run_store import RunStore
from agent_run_api import product_application
from agent_run_broker import RunBroker
from agent_run_scope import RunScopeService
from boss_comprehensive_simulation import populate
from boss_command_api import BossCommandAPI
from boss_memory_sessions import MemorySessionManager
from boss_supply_quality import SupplyQualityAPI
from controls import ControlStore
from hermes_bridge import EngineEventSink, EngineRunConfig
from hermes_business_tools import HermesBusinessTools, ReceiptBinding
from hermes_intents import HermesIntentService, install_owner_decision, owner_decision_routes, preview_response, validate_current_preview, validate_decision_state, validate_owner_decision
from role_channel import RoleChannel
from sop_write_tools.fc01 import Fc01Context, content_digest


def database_digest(path):
    with sqlite3.connect(path) as db:
        return hashlib.sha256("\n".join(db.iterdump()).encode()).hexdigest()


def test_intent_preparation_replay_and_original_receipt(tmp_path):
    business_path = tmp_path / "business.sqlite"
    business = ControlStore(business_path)
    business.initialize("ui-check")
    populate(business, "2026-10-28T10:00:00+08:00")
    view = SupplyQualityAPI(business).read("BOSS", "SI10")
    origin = view["events"][0]
    params = {"interface_id": "SI10", "origin_entity_type": origin["entity_type"], "origin_record_id": origin["record_id"], "origin_version": origin["version"], "review_sha256": view["review_sha256"], "purpose": "核查品质事件并提交当前依据", "coordinator_id": "coordinator-1", "due_at": "2026-10-30T17:00:00+08:00", "timezone": "Asia/Shanghai", "evidence_requirements": ["专业核查记录"]}
    current = [Fc01Context("BOSS", "boss-1", "ui-check", "selection", "1", "intent-request-001", "intent-session-001", frozenset({"bossSupplyQualityPrepare"}), False, frozenset({("bossSupplyQualityPrepare", content_digest(params))}), ())]
    selected = [params]
    runs = RunStore(tmp_path / "runs.sqlite")
    run_id = runs.create_run("boss-1", "ui-check", "run-request-001", "run-digest-001")
    lease = runs.acquire_lease(run_id, 0, "worker-1", 300)
    runs.transition(run_id, runs.read_run(run_id)["revision"], "RUNNING", "worker-1", lease["epoch"])
    config = EngineRunConfig(run_id, lease["epoch"], "903230b1e23e0c496b28e5d2e8c4f2639cd506b6", "http://127.0.0.1:1234", 3)
    gate = EngineEventSink(runs, config, "worker-1")
    tools = HermesBusinessTools(business, lambda: current[0], lambda: selected[0], lambda: ReceiptBinding("boss.assignment.send", "unmatched-request-001"), run_gate=gate)
    with pytest.raises(ValueError):
        HermesIntentService(runs, tools)
    service = HermesIntentService(runs, tools, allow_migration=True)
    before = database_digest(business_path)
    with pytest.raises(web.HTTPForbidden):
        asyncio.run(service.prepare("intent-key-001"))
    current[0] = replace(current[0], active=True)
    intent = asyncio.run(service.prepare("intent-key-001"))
    assert intent["status"] == "WAITING_CONFIRMATION"
    assert intent["authorization_id"] is None
    assert intent["preview"]["owner_decision_required"] is True
    assert intent["preview"]["business_authority_granted"] is False
    response = preview_response(intent, intent["preview"])
    assert response["schema_version"] == 1 and response["allowed_actions"] == ["CONFIRM", "REJECT"]
    assert response["preview"]["coordinate_input"]["origin_record_id"] == origin["record_id"]
    selected_sources = [ref["source_id"] for ref in intent["preview"]["source_refs"]]
    with business.connect() as db:
        db.execute("BEGIN")
        assert validate_current_preview(db, business, intent, selected_sources) == intent["preview"]
        with pytest.raises(web.HTTPConflict):
            validate_current_preview(db, business, {**intent, "expected_revision": "0"}, selected_sources)
        with pytest.raises(web.HTTPConflict):
            validate_current_preview(db, business, intent, [])
    command = BossCommandAPI(business)
    with business.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        with pytest.raises(web.HTTPConflict):
            command.coordinate_in_transaction(db, {**params, "origin_version": "0", "client_request_id": intent["client_request_id"]}, actor_id="boss-1", space_id="ui-check", scope_revision=intent["scope_revision"])
        with pytest.raises(web.HTTPConflict):
            command.coordinate_in_transaction(db, {**params, "client_request_id": intent["client_request_id"]}, actor_id="boss-1", space_id="ui-check", scope_revision="0" * 64)
        with pytest.raises(web.HTTPForbidden):
            command.coordinate_in_transaction(db, {**params, "client_request_id": intent["client_request_id"]}, actor_id="another-owner", space_id="ui-check", scope_revision=intent["scope_revision"])
        with pytest.raises(web.HTTPConflict):
            command.verify_coordinate_receipt_in_transaction(db, actor_id="boss-1", space_id="ui-check", payload={**params, "client_request_id": intent["client_request_id"]}, source_refs=intent["preview"]["source_refs"], authorization_id="missing")
    assert runs.read_run(run_id)["status"] == "WAITING_CONFIRMATION"
    decision = {"decision": "REJECT", "expected_revision": intent["revision"], "payload_digest": intent["payload_digest"], "request_key": "decision-request-001"}
    validate_owner_decision(decision)
    with pytest.raises(web.HTTPBadRequest):
        validate_owner_decision({**decision, "decision": []})
    with pytest.raises(web.HTTPBadRequest):
        validate_owner_decision({**decision, "actor_id": "boss-1"})
    validate_decision_state(intent, runs.read_run(run_id), decision)
    with pytest.raises(web.HTTPConflict):
        validate_decision_state(intent, runs.read_run(run_id), {**decision, "expected_revision": intent["revision"] + 1})
    with pytest.raises(web.HTTPConflict):
        validate_decision_state(intent, runs.read_run(run_id), {**decision, "payload_digest": "0" * 64})
    with pytest.raises(web.HTTPConflict):
        validate_decision_state(intent, {**runs.read_run(run_id), "goal_revision": 2}, decision)
    assert asyncio.run(service.prepare("intent-key-001")) == intent
    with pytest.raises(PermissionError):
        service.execute(intent["intent_id"])
    result = service.receipt(intent["intent_id"])
    assert result["receipt"]["client_request_id"] == intent["client_request_id"]
    assert result["receipt"]["outcome"] == "NOT_FOUND_IN_CURRENT_STORE"
    assert result["receipt_binding_verified"] is False
    assert service.receipt(intent["intent_id"]) == result
    selected[0] = {**params, "purpose": "其他协调内容"}
    with pytest.raises(ValueError):
        asyncio.run(service.prepare("intent-key-001"))
    current[0] = replace(current[0], role="MAINTAINER")
    with pytest.raises(web.HTTPForbidden):
        service.receipt(intent["intent_id"])
    assert database_digest(business_path) == before
    assert [event["type"] for event in runs.events(run_id, 0)] == ["STATUS_CHANGED", "INTENT_PREPARED", "STATUS_CHANGED"]
    reopened = HermesIntentService(RunStore(runs.path), tools)
    current[0] = replace(current[0], role="BOSS")
    assert reopened.receipt(intent["intent_id"]) == result
    runs.cancel(run_id, runs.read_run(run_id)["revision"])
    assert reopened.receipt(intent["intent_id"]) == result
    selected[0] = params
    with pytest.raises(ValueError):
        asyncio.run(reopened.prepare("intent-key-001"))
    with pytest.raises(ValueError, match="原租约仍然有效"):
        reopened.inspect_recovery(run_id, "boss-1", "ui-check")
    with runs.connect() as db:
        db.execute("UPDATE agent_runs SET status='INTERRUPTED',lease_owner=NULL,lease_expires_at=NULL,revision=revision+1 WHERE run_id=?", (run_id,))
        intent_count = db.execute("SELECT count(*) FROM agent_intents").fetchone()[0]
    events = runs.events(run_id, 0)
    recovery = reopened.inspect_recovery(run_id, "boss-1", "ui-check")
    assert recovery["status"] == "INTERRUPTED"
    assert recovery["duplicate_execution_allowed"] is False and recovery["automatic_requeue"] is False
    assert recovery["recovery_action"] == "NO_RECORDED_DECISION"
    assert len(recovery["intents"]) == 1 and recovery["intents"][0]["status"] == "WAITING_CONFIRMATION"
    assert recovery["intents"][0]["action"] == "boss.supply_quality.coordinate"
    assert recovery["intents"][0]["source_refs"] == intent["preview"]["source_refs"]
    assert recovery["receipts"] == [] and recovery["original_receipt"] is None
    assert recovery["process_evidence"] == [] and recovery["unknown_reservations"] == 0
    assert runs.events(run_id, 0) == events
    with runs.connect() as db:
        assert db.execute("SELECT count(*) FROM agent_intents").fetchone()[0] == intent_count
    with pytest.raises(ValueError):
        reopened.inspect_recovery(run_id, "other-owner", "ui-check")
    with pytest.raises(ValueError):
        asyncio.run(reopened.prepare("intent-key-001"))
    assert runs.events(run_id, 0) == events
    with runs.connect() as db:
        assert db.execute("SELECT count(*) FROM agent_intents").fetchone()[0] == intent_count


def test_owner_decision_http_rejects_unverified_requests(tmp_path):
    async def exercise():
        business = ControlStore(tmp_path / "business.sqlite")
        business.initialize("ui-check")
        sessions = MemorySessionManager(tmp_path / "workspace", business_store=business, sessions_root=tmp_path / "sessions")
        runs = RunStore(business.path)
        broker = RunBroker(runs, scope_service=RunScopeService(business, sessions, "ui-check"))
        bus, config = MessageBus(), WebSocketConfig()
        gateway = build_gateway_services(config=config, bus=bus, session_manager=sessions, static_dist_path=None, workspace_path=tmp_path, default_restrict_to_workspace=True, config_path=tmp_path / "config.json", runtime_model_name=None, runtime_surface="webui", runtime_capabilities_overrides=None)
        channel = RoleChannel(WebSocketChannel(config, bus, gateway=gateway), {}, tmp_path / "access.jsonl", business)
        app = web.Application()
        app.add_routes(owner_decision_routes(channel, broker))
        runner = web.AppRunner(app)
        await runner.setup()
        await web.TCPSite(runner, "127.0.0.1", 0).start()
        url = "http://127.0.0.1:" + str(runner.addresses[0][1])
        payload = {"decision": "REJECT", "expected_revision": 0, "payload_digest": "0" * 64, "request_key": "decision-request-001"}
        async with httpx.AsyncClient(trust_env=False) as client:
            for choice in ("REJECT", "CONFIRM"):
                for headers in ({}, {"X-Boss-Role": "BOSS"}, {"Authorization": "Bearer invalid"}):
                    response = await client.post(url + "/api/v2/intents/unknown/decision", json={**payload, "decision": choice}, headers=headers)
                    assert response.status_code == 401
        await runner.cleanup()

    asyncio.run(exercise())


def test_product_origin_and_owner_decision_boundary(tmp_path):
    async def exercise():
        business = ControlStore(tmp_path / "business.sqlite")
        business.initialize("ui-check")
        sessions = MemorySessionManager(tmp_path / "workspace", business_store=business, sessions_root=tmp_path / "sessions")
        runs = RunStore(business.path)
        broker = RunBroker(runs, scope_service=RunScopeService(business, sessions, "ui-check"))
        bus, config = MessageBus(), WebSocketConfig()
        gateway = build_gateway_services(config=config, bus=bus, session_manager=sessions, static_dist_path=None, workspace_path=tmp_path, default_restrict_to_workspace=True, config_path=tmp_path / "config.json", runtime_model_name=None, runtime_surface="webui", runtime_capabilities_overrides=None)
        channel = RoleChannel(WebSocketChannel(config, bus, gateway=gateway), {}, tmp_path / "access.jsonl", business)
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        sock.listen()
        sock.setblocking(False)
        port = sock.getsockname()[1]
        url = "http://127.0.0.1:" + str(port)
        app = product_application(channel, broker, public_port=port, upstream_port=9)
        install_owner_decision(app, channel, broker, public_port=port)
        runner = web.AppRunner(app)
        await runner.setup()
        await web.SockSite(runner, sock).start()
        endpoint = url + "/api/v2/intents/unknown/decision"
        payload = {"decision": "CONFIRM", "expected_revision": 0, "payload_digest": "0" * 64, "request_key": "decision-request-001"}
        async with httpx.AsyncClient(trust_env=False) as client:
            assert (await client.post(endpoint, json=payload, headers={"Origin": "http://attacker.invalid"})).status_code == 403
            assert (await client.post(endpoint, json=payload)).status_code == 403
            assert (await client.post(endpoint, json=payload, headers={"Origin": url, "Sec-Fetch-Site": "cross-site"})).status_code == 403
            for headers in ({"Origin": url}, {"Origin": url, "X-Boss-Role": "BOSS"}, {"Origin": url, "Authorization": "Bearer invalid"}):
                assert (await client.post(endpoint, json=payload, headers=headers)).status_code == 401
            assert (await client.get(endpoint, headers={"Origin": url})).status_code == 405
            for path in ("/api/v2/runs/unknown/intent", "/api/v2/intent-decisions/request-001"):
                assert (await client.get(url + path)).status_code == 401
                assert (await client.get(url + path, headers={"X-Boss-Role": "BOSS"})).status_code == 401
                assert (await client.get(url + path, headers={"Origin": "http://attacker.invalid"})).status_code == 403
                assert (await client.get(url + path, headers={"Sec-Fetch-Site": "cross-site"})).status_code == 403
        await runner.cleanup()

    asyncio.run(exercise())
