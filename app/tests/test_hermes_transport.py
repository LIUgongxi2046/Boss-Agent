import asyncio
import json
import secrets
import socket
import sys
from dataclasses import asdict
from pathlib import Path

import httpx
import pytest
from aiohttp import web

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "validation"))

from agent_run_store import RunStore
from agent_run_requirements import RunRequirements
from agent_run_tool_budget import RunToolBudget
from agent_run_scope import RunScopeService
from boss_memory_sessions import MemorySessionManager
from controls import ControlStore
from hermes_bridge import EngineEventSink, EngineRunConfig, HermesBridge
from hermes_transport import HermesTransport
from hermes_transport_client import HermesTransportClient


def test_local_transport_request_events_and_failure(tmp_path):
    async def exercise():
        path = tmp_path / "runs.sqlite"
        store = RunStore(path)
        run_id = store.create_run("boss-1", "space-1", "request", "digest")
        with store.connect() as db:
            db.execute("UPDATE agent_runs SET goal=? WHERE run_id=?", ("检查运行目标与事件", run_id))
        lease = store.acquire_lease(run_id, 0, "worker", 60)
        store.transition(run_id, store.read_run(run_id)["revision"], "RUNNING", "worker", lease["epoch"])
        token = secrets.token_urlsafe(32)
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        sock.listen()
        sock.setblocking(False)
        port = sock.getsockname()[1]
        endpoint = f"http://127.0.0.1:{port}"
        config = EngineRunConfig(run_id, lease["epoch"], "903230b1e23e0c496b28e5d2e8c4f2639cd506b6", endpoint, 1)
        app = web.Application(client_max_size=65536)
        HermesTransport(EngineEventSink(store, config, "worker"), token, actor_id="boss-1", space_id="space-1").install(app)
        runner = web.AppRunner(app)
        await runner.setup()
        await web.SockSite(runner, sock).start()
        headers = {"Authorization": "Bearer " + token}
        async with httpx.AsyncClient(trust_env=False) as client:
            unauthorized = await client.get(endpoint + "/internal/v1/request")
            assert unauthorized.status_code == 401 and unauthorized.json()["code"] == "INVALID_CAPABILITY"
            model_request = {"protocol_version": 1}
            assert (await client.post(endpoint + "/internal/v1/model-execution", json=model_request)).status_code == 401
            invalid_model = await client.post(endpoint + "/internal/v1/model-execution", headers=headers, json={"protocol_version": True})
            assert invalid_model.status_code == 400
            disabled_model = await client.post(endpoint + "/internal/v1/model-execution", headers=headers, json=model_request)
            assert disabled_model.status_code == 503 and disabled_model.json()["code"] == "MODEL_EXECUTION_UNAVAILABLE"
            intent_request = {"protocol_version": 1, "request_key": "technical-request", "action": "boss.minutes.confirm", "params": {}}
            assert (await client.post(endpoint + "/internal/v1/tools/domain-intent", json=intent_request)).status_code == 401
            denied_intent = await client.post(endpoint + "/internal/v1/tools/domain-intent", headers=headers, json=intent_request)
            assert denied_intent.status_code == 503 and denied_intent.json()["code"] == "INTENT_SERVICE_UNAVAILABLE"
            assert (await client.post(endpoint + "/internal/v1/tools/domain-intent", headers=headers, json={**intent_request, "actor_id": "boss-1"})).status_code == 400
            transport_client = HermesTransportClient(endpoint, token, run_id)
            try:
                with pytest.raises(httpx.HTTPStatusError) as denied:
                    await asyncio.to_thread(transport_client.authorize_model_execution)
                assert denied.value.response.status_code == 503
            finally:
                transport_client.close()
            response = await client.get(endpoint + "/internal/v1/request", headers=headers)
            assert response.status_code == 200
            assert response.json()["goal"] == "检查运行目标与事件"
            unavailable = await client.post(endpoint + "/internal/v1/tools/read-documents", headers=headers, json={"protocol_version": 1, "call_id": "check"})
            assert unavailable.status_code == 503 and unavailable.json()["code"] == "TOOL_SERVICE_UNAVAILABLE"
            for format_name in ("MARKDOWN", "PDF", "DOCX", "XLSX", "PPTX"):
                artifact_request = {"protocol_version": 1, "arguments": {"source_ids": ["simulation-meeting-material"], "request_key": "check", "format_name": format_name}}
                assert (await client.post(endpoint + "/internal/v1/tools/meeting-brief", json=artifact_request)).status_code == 401
                response = await client.post(endpoint + "/internal/v1/tools/meeting-brief", headers=headers, json=artifact_request)
                assert response.status_code == 503 and response.json()["code"] == "ARTIFACT_SERVICE_UNAVAILABLE"
            invalid_artifact = await client.post(endpoint + "/internal/v1/tools/meeting-brief", headers=headers, json={"protocol_version": 1, "arguments": {"source_ids": ["simulation-meeting-material"], "request_key": "check", "path": "/private"}})
            assert invalid_artifact.status_code == 400
            event = {"protocol_version": 1, "origin_event_id": "actual-start", "type": "RUN_STARTED", "payload": {"engine_commit": config.engine_commit}}
            first = await client.post(endpoint + "/internal/v1/events", headers=headers, json=event)
            second = await client.post(endpoint + "/internal/v1/events", headers=headers, json=event)
            assert first.status_code == second.status_code == 200
            assert first.json() == second.json()
            async with httpx.AsyncClient(trust_env=False) as reconnected:
                assert (await reconnected.post(endpoint + "/internal/v1/events", headers=headers, json=event)).json() == first.json()
            async with httpx.AsyncClient(trust_env=False) as reopened:
                assert (await reopened.post(endpoint + "/internal/v1/events", headers=headers, json=event)).json() == first.json()
            invalid = await client.post(endpoint + "/internal/v1/events", headers=headers, json={**event, "type": "TOOL_STARTED", "payload": {}})
            assert invalid.status_code == 400 and invalid.json()["code"] == "INVALID_EVENT"
            conflict = await client.post(endpoint + "/internal/v1/events", headers=headers, json={**event, "type": "TOOL_STARTED", "payload": {"tool_id": "tool", "call_id": "call"}})
            assert conflict.status_code == 409 and conflict.json()["code"] == "EVENT_CONFLICT"
            first_input = store.add_input(run_id, 1, "first-input", "补充来源范围")
            second_input = store.add_input(run_id, 2, "second-input", "补充时间范围")
            context = (await client.get(endpoint + "/internal/v1/input-context", headers=headers)).json()
            assert context["requirements"] == {"goal_revision": 3, "state": "UNAVAILABLE", "required_outputs": None}
            RunRequirements(store, allow_migration=True)
            context = (await client.get(endpoint + "/internal/v1/input-context", headers=headers)).json()
            assert context["requirements"] == {"goal_revision": 3, "state": "PENDING_CONFIRMATION", "required_outputs": None}
            transport_client = HermesTransportClient(endpoint, token, run_id)
            try:
                with pytest.raises(ValueError, match="成果要求尚未确认"):
                    await asyncio.to_thread(transport_client.prepare_turn)
            finally:
                transport_client.close()
            with store.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                RunRequirements.save_in_transaction(db, run_id, 3, "technical-requirements", ["TEXT", "PDF"])
            pending = await client.get(endpoint + "/internal/v1/inputs", headers=headers)
            assert pending.json()["input"]["input_id"] == first_input["input_id"]
            assert (await client.get(endpoint + "/internal/v1/inputs", headers=headers)).json() == pending.json()
            out_of_order = await client.post(endpoint + "/internal/v1/inputs/ack", headers=headers, json={"protocol_version": 1, "input_seq": 2})
            assert out_of_order.status_code == 409 and out_of_order.json()["code"] == "INPUT_ORDER_INVALID"
            ack = await client.post(endpoint + "/internal/v1/inputs/ack", headers=headers, json={"protocol_version": 1, "input_seq": 1})
            replay = await client.post(endpoint + "/internal/v1/inputs/ack", headers=headers, json={"protocol_version": 1, "input_seq": 1})
            assert ack.status_code == 200 and ack.json() == replay.json()
            assert (await client.get(endpoint + "/internal/v1/inputs", headers=headers)).json()["input"]["input_id"] == second_input["input_id"]
            probe = Path(__file__).with_name("hermes_input_probe.py")
            process = await asyncio.create_subprocess_exec(sys.executable, str(probe), stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            try:
                stdout, stderr = await asyncio.wait_for(process.communicate(json.dumps({"endpoint": endpoint, "capability": token, "run_id": run_id}).encode()), 15)
            finally:
                if process.returncode is None:
                    process.kill()
                    await process.wait()
            assert process.returncode == 0, stderr.decode()
            prepared = json.loads(stdout)
            assert prepared["goal_revision"] == 3
            assert json.loads(prepared["prompt"]) == {"goal": "检查运行目标与事件", "additional_inputs": ["补充来源范围", "补充时间范围"], "required_outputs": ["TEXT", "PDF"]}
            assert (await client.post(endpoint + "/internal/v1/inputs/ack", headers=headers, json={"protocol_version": 1, "input_seq": 2})).status_code == 200
            assert (await client.get(endpoint + "/internal/v1/inputs", headers=headers)).json()["input"] is None
            store.add_input(run_id, 3, "third-input", "补充会议范围")
            context = (await client.get(endpoint + "/internal/v1/input-context", headers=headers)).json()
            assert context["requirements"] == {"goal_revision": 4, "state": "PENDING_CONFIRMATION", "required_outputs": None}
            transport_client = HermesTransportClient(endpoint, token, run_id)
            try:
                with pytest.raises(ValueError, match="成果要求尚未确认"):
                    await asyncio.to_thread(transport_client.prepare_turn)
            finally:
                transport_client.close()
            assert (await client.get(endpoint + "/internal/v1/inputs", headers=headers)).json()["input"]["input_seq"] == 3
            assert (await client.get(endpoint + "/internal/v1/input-context")).status_code == 401
            store.cancel(run_id, store.read_run(run_id)["revision"])
            assert (await client.get(endpoint + "/internal/v1/request", headers=headers)).status_code == 409
            assert (await client.get(endpoint + "/internal/v1/input-context", headers=headers)).status_code == 409
            assert (await client.post(endpoint + "/internal/v1/events", headers=headers, json={**event, "origin_event_id": "after-cancel"})).status_code == 409
        await runner.cleanup()
        events = RunStore(path, allow_migration=False).events(run_id, 0)
        assert len([event for event in events if event["type"] == "RUN_STARTED"]) == 1

    asyncio.run(exercise())


def test_transport_client_rejects_remote_endpoint():
    token = secrets.token_urlsafe(32)
    with pytest.raises(ValueError):
        HermesTransportClient("https://api.deepseek.com", token, "run-1")


def test_parent_cancel_blocks_child_event_and_replay(tmp_path):
    async def exercise():
        path = tmp_path / "parent-child.sqlite"
        store = RunStore(path)
        parent = store.create_run("boss-1", "space-1", "parent", "parent-digest")
        parent_lease = store.acquire_lease(parent, 0, "parent-worker", 60)
        store.transition(parent, store.read_run(parent)["revision"], "RUNNING", "parent-worker", parent_lease["epoch"])
        child = store.create_child_run(parent, "parent-worker", parent_lease["epoch"], "child", "child-digest")
        child_lease = store.acquire_lease(child, 0, "child-worker", 60)
        store.transition(child, store.read_run(child)["revision"], "RUNNING", "child-worker", child_lease["epoch"])
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        sock.listen()
        sock.setblocking(False)
        endpoint = f"http://127.0.0.1:{sock.getsockname()[1]}"
        config = EngineRunConfig(child, child_lease["epoch"], "903230b1e23e0c496b28e5d2e8c4f2639cd506b6", endpoint, 1)
        token = secrets.token_urlsafe(32)
        app = web.Application()
        HermesTransport(EngineEventSink(store, config, "child-worker"), token, actor_id="boss-1", space_id="space-1").install(app)
        runner = web.AppRunner(app)
        await runner.setup()
        await web.SockSite(runner, sock).start()
        headers = {"Authorization": "Bearer " + token}
        event = {"protocol_version": 1, "origin_event_id": "child-start", "type": "RUN_STARTED", "payload": {"engine_commit": config.engine_commit}}
        async with httpx.AsyncClient(trust_env=False) as client:
            first = await client.post(endpoint + "/internal/v1/events", headers=headers, json=event)
            assert first.status_code == 200
            parent_revision = store.read_run(parent)["revision"]
            concurrent_event = {**event, "origin_event_id": "concurrent"}
            concurrent, receipt = await asyncio.gather(
                client.post(endpoint + "/internal/v1/events", headers=headers, json=concurrent_event),
                asyncio.to_thread(store.cancel, parent, parent_revision),
            )
            assert concurrent.status_code in {200, 409}
            assert receipt["status"] == "CANCEL_REQUESTED"
            assert (await client.post(endpoint + "/internal/v1/events", headers=headers, json=event)).status_code == 409
            assert (await client.post(endpoint + "/internal/v1/events", headers=headers, json={**event, "origin_event_id": "late"})).status_code == 409
        await runner.cleanup()
        events = RunStore(path, allow_migration=False).events(child, 0)
        assert len([event for event in events if event["type"] == "RUN_STARTED"]) == (2 if concurrent.status_code == 200 else 1)

    asyncio.run(exercise())


def test_bound_source_requires_scope_service(tmp_path):
    async def exercise():
        path = tmp_path / "source.sqlite"
        ControlStore(path).initialize("space-1")
        store = RunStore(path)
        run_id = store.create_run("boss-1", "space-1", "request", "digest")
        with store.connect() as db:
            db.execute("UPDATE agent_runs SET goal=?,selected_refs=? WHERE run_id=?", ("检查来源", '["finance-note"]', run_id))
        lease = store.acquire_lease(run_id, 0, "worker", 60)
        store.transition(run_id, store.read_run(run_id)["revision"], "RUNNING", "worker", lease["epoch"])
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        sock.listen()
        sock.setblocking(False)
        endpoint = f"http://127.0.0.1:{sock.getsockname()[1]}"
        config = EngineRunConfig(run_id, lease["epoch"], "903230b1e23e0c496b28e5d2e8c4f2639cd506b6", endpoint, 1)
        token = secrets.token_urlsafe(32)
        app = web.Application()
        HermesTransport(EngineEventSink(store, config, "worker"), token, actor_id="boss-1", space_id="space-1").install(app)
        runner = web.AppRunner(app)
        await runner.setup()
        await web.SockSite(runner, sock).start()
        async with httpx.AsyncClient(trust_env=False) as client:
            response = await client.get(endpoint + "/internal/v1/request", headers={"Authorization": "Bearer " + token})
            assert response.status_code == 409
        await runner.cleanup()

    asyncio.run(exercise())


def test_persisted_session_scope_is_checked_after_reopen(tmp_path):
    async def exercise():
        path = tmp_path / "business.sqlite"
        business = ControlStore(path)
        business.initialize("ui-check")
        sessions = MemorySessionManager(tmp_path / "workspace", business_store=business, sessions_root=tmp_path / "sessions")
        session = sessions.get_or_create("websocket:scope-check")
        sessions.save(session, fsync=True)
        scope = RunScopeService(business, sessions, "ui-check")
        proof = scope.prove("scope-check", [])
        store = RunStore(path)
        run_id = store.create_run(proof.owner_id, proof.namespace, "scope-request", "scope-digest")
        with store.connect() as db:
            db.execute("UPDATE agent_runs SET goal=?,conversation_id=?,selected_refs=?,scope_proof=? WHERE run_id=?", ("检查会话范围", proof.chat_id, "[]", json.dumps(asdict(proof)), run_id))
        lease = store.acquire_lease(run_id, 0, "worker", 60)
        store.transition(run_id, store.read_run(run_id)["revision"], "RUNNING", "worker", lease["epoch"])
        store = RunStore(path, allow_migration=False)
        budget = RunToolBudget(store, allow_migration=True)
        budget.configure(run_id, "worker", lease["epoch"], 1)
        sessions = MemorySessionManager(tmp_path / "workspace", business_store=business, sessions_root=tmp_path / "sessions")
        scope = RunScopeService(business, sessions, "ui-check")
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        sock.listen()
        sock.setblocking(False)
        endpoint = f"http://127.0.0.1:{sock.getsockname()[1]}"
        config = EngineRunConfig(run_id, lease["epoch"], "903230b1e23e0c496b28e5d2e8c4f2639cd506b6", endpoint, 1)
        token = secrets.token_urlsafe(32)
        app = web.Application()
        transport = HermesTransport(EngineEventSink(store, config, "worker"), token, actor_id=proof.owner_id, space_id=proof.namespace, scope_service=scope, tool_budget=budget, bridge=HermesBridge(business))
        transport.install(app)
        with store.connect() as db:
            db.execute("BEGIN")
            with pytest.raises(web.HTTPConflict) as rejected:
                transport.read_bound_documents_in_transaction(db, HermesBridge(business))
            assert json.loads(rejected.value.text)["code"] == "SOURCE_PROOF_UNAVAILABLE"
        runner = web.AppRunner(app)
        await runner.setup()
        await web.SockSite(runner, sock).start()
        try:
            async with httpx.AsyncClient(trust_env=False) as client:
                headers = {"Authorization": "Bearer " + token}
                response = await client.get(endpoint + "/internal/v1/request", headers=headers)
                assert response.status_code == 200 and response.json()["selected_refs"] == []
                result_request = {"protocol_version": 1, "origin_event_id": "technical-result", "goal_revision": 1,
                                  "text": "检查会话范围", "citations": []}
                assert (await client.post(endpoint + "/internal/v1/result", json=result_request)).status_code == 401
                invalid = await client.post(endpoint + "/internal/v1/result", headers=headers, json={**result_request, "goal_revision": True})
                assert invalid.status_code == 400
                saved = await client.post(endpoint + "/internal/v1/result", headers=headers, json=result_request)
                repeated = await client.post(endpoint + "/internal/v1/result", headers=headers, json=result_request)
                assert saved.status_code == repeated.status_code == 200
                assert saved.json() == repeated.json()
                assert saved.json()["event"]["payload"]["text"] == "检查会话范围"
                transport_client = HermesTransportClient(endpoint, token, run_id)
                try:
                    recorded = await asyncio.to_thread(transport_client.record_result, "technical-result", 1, "检查会话范围", [])
                    assert recorded == saved.json()["event"]
                    assert await asyncio.to_thread(transport_client.citation_checks, recorded["event_id"]) == []
                finally:
                    transport_client.close()
                assert store.read_run(run_id)["status"] == "RUNNING"
                with store.connect() as db:
                    db.execute("BEGIN")
                    assert store.result_in_transaction(db, run_id, 1) == saved.json()["event"]
                response = await client.post(endpoint + "/internal/v1/tools/read-documents", headers=headers, json={"protocol_version": 1, "call_id": "missing-source"})
                assert response.status_code == 409 and response.json()["code"] == "SOURCE_PROOF_UNAVAILABLE"
                response = await client.get(endpoint + "/internal/v1/tools/read-documents/missing-source", headers=headers)
                assert response.status_code == 409 and response.json()["code"] == "SOURCE_PROOF_UNAVAILABLE"
                response = await client.get(endpoint + "/internal/v1/tools/read-documents/missing-source")
                assert response.status_code == 401 and response.json()["code"] == "INVALID_CAPABILITY"
                with store.connect() as db:
                    assert db.execute("SELECT count(*) FROM agent_tool_reservations").fetchone()[0] == 0
                sessions.delete_session("websocket:scope-check")
                response = await client.get(endpoint + "/internal/v1/request", headers=headers)
                assert response.status_code == 404
                rejected_result = await client.post(endpoint + "/internal/v1/result", headers=headers, json={**result_request, "origin_event_id": "after-delete"})
                assert rejected_result.status_code >= 400
                with store.connect() as db:
                    assert db.execute("SELECT count(*) FROM agent_run_events WHERE type='RESULT_RECORDED'").fetchone()[0] == 1
        finally:
            await runner.cleanup()

    asyncio.run(exercise())
