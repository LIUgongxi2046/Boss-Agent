import asyncio
import json
import secrets
import socket
import sqlite3
from dataclasses import asdict
from pathlib import Path

import httpx
import pytest
from aiohttp import web
from tools.registry import registry

from agent_run_scope import RunScopeService
from agent_run_store import RunStore
from agent_run_tool_budget import RunToolBudget
from boss_comprehensive_simulation import populate
from boss_meetings import MeetingAPI
from boss_memory_sessions import MemorySessionManager
from business import checksum
from controls import ControlStore
from hermes_bridge import EngineEventSink, EngineRunConfig, HermesBridge
from hermes_domain_intents import draft_result_event_in_transaction, preview_domain_intent, read_minutes_context_in_transaction, save_meeting_draft_in_transaction, save_minutes_draft_in_transaction
from hermes_tool_registration import registered_product_tools
from hermes_bi_authority import bi_tool_definitions
from hermes_transport import HermesTransport
from hermes_transport_client import HermesTransportClient


def test_meeting_context_propagates_current_draft_and_rejects_changes(tmp_path):
    async def exercise():
        store = ControlStore(tmp_path / "business.sqlite")
        store.initialize("ui-check")
        populate(store, "2026-10-28T10:00:00+08:00")
        sessions = MemorySessionManager(tmp_path / "workspace", business_store=store, sessions_root=tmp_path / "sessions")
        session = sessions.get_or_create("websocket:meeting-context")
        sessions.save(session, fsync=True)
        with store.connect() as db:
            initial = store.get(db, "ui-check", "initial", "snapshot")
            document = store.get(db, "ui-check", "document", "simulation-meeting-material")
            ref = {"source_id": document["source_id"], "version": document["version"]}
            original_minutes_document = store.get(db, "ui-check", "document", "meeting-minutes")
            minute_ref = {"source_id": original_minutes_document["source_id"], "version": original_minutes_document["version"]}
            binding = {"namespace": "ui-check", "owner_id": initial["owner_id"], "dataset_id": initial["dataset_id"], "dataset_version": initial["dataset_version"], "chat_id": "meeting-context", "session_id": session.key, "native_session_created_at": session.created_at.isoformat(), "binding_id": "meeting-context-binding", "context_version": "1", "source_refs": [ref, minute_ref], "source_pins": [{**ref, "content_sha256": checksum(document)}, {**minute_ref, "content_sha256": checksum(original_minutes_document)}]}
            store.put(db, "ui-check", "conversation_source_binding", session.key, binding)
        scope = RunScopeService(store, sessions, "ui-check")
        proof = scope.prove("meeting-context", [document["source_id"], original_minutes_document["source_id"]])
        runs = RunStore(store.path)
        run_id = runs.create_run(proof.owner_id, proof.namespace, "meeting-context-run", "meeting-context-digest")
        with runs.connect() as db:
            db.execute("UPDATE agent_runs SET conversation_id=?,selected_refs=?,scope_proof=? WHERE run_id=?", (proof.chat_id, json.dumps([document["source_id"], original_minutes_document["source_id"]]), json.dumps(asdict(proof)), run_id))
        lease = runs.acquire_lease(run_id, 0, "worker", 120)
        runs.transition(run_id, lease["revision"], "RUNNING", "worker", lease["epoch"])
        narrow_proof = scope.prove("meeting-context", [document["source_id"]])
        with runs.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("UPDATE agent_runs SET selected_refs=?,scope_proof=? WHERE run_id=?", (json.dumps([document["source_id"]]), json.dumps(asdict(narrow_proof)), run_id))
            db.row_factory = sqlite3.Row
            narrowed_run = db.execute("SELECT * FROM agent_runs WHERE run_id=?", (run_id,)).fetchone()
            with pytest.raises(web.HTTPForbidden) as forbidden:
                read_minutes_context_in_transaction(db, store, scope, narrowed_run)
            assert forbidden.value.text == "纪要来源未获当前运行选择"
            db.rollback()
        budget = RunToolBudget(runs, allow_migration=True)
        budget.configure(run_id, "worker", lease["epoch"], 8)
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        listener.setblocking(False)
        endpoint = "http://127.0.0.1:" + str(listener.getsockname()[1])
        config = EngineRunConfig(run_id, lease["epoch"], "903230b1e23e0c496b28e5d2e8c4f2639cd506b6", endpoint, 1)
        sink = EngineEventSink(runs, config, "worker")
        capability = secrets.token_urlsafe(32)
        transport = HermesTransport(sink, capability, actor_id=proof.owner_id, space_id=proof.namespace, scope_service=scope, tool_budget=budget, bridge=HermesBridge(store))
        app = web.Application()
        transport.install(app)
        runner = web.AppRunner(app)
        await runner.setup()
        await web.SockSite(runner, listener).start()
        headers = {"Authorization": "Bearer " + capability}
        url = endpoint + "/internal/v1/tools/meeting-context"
        try:
            async with httpx.AsyncClient(trust_env=False) as client:
                receipt_url = endpoint + "/internal/v1/tools/decision-receipt"
                receipt_request = {"protocol_version": 1, "intent_id": "missing-intent", "call_id": "receipt-check"}
                assert (await client.post(receipt_url, json=receipt_request)).status_code == 401
                assert (await client.post(receipt_url, json=receipt_request, headers=headers)).status_code == 503
                transport_client = HermesTransportClient(endpoint, capability, run_id)
                with pytest.raises(httpx.HTTPStatusError) as missing_receipt:
                    await asyncio.to_thread(transport_client.read_decision_receipt, "missing-intent", "receipt-client")
                assert missing_receipt.value.response.status_code == 503
                transport_client.close()
                request = {"protocol_version": 1, "call_id": "empty-meeting"}
                assert (await client.post(url, json=request)).status_code == 401
                empty = await client.post(url, json=request, headers=headers)
                assert empty.status_code == 200 and empty.json()["result"]["draft"] is None
                assert (await client.post(url, json=request, headers=headers)).json() == empty.json()
                api = MeetingAPI(store)
                with store.connect() as db:
                    db.execute("BEGIN IMMEDIATE")
                    data = api._data(db)
                    meeting = data["meeting"]
                    actual = empty.json()["result"]["meeting"]
                    assert actual["starts_at"] == meeting["starts_at"] and actual["ends_at"] == meeting.get("ends_at")
                    assert actual["timezone"] == meeting["timezone"] and actual["participant_ids"] == meeting["participant_ids"]
                    assert {item["source_id"] for item in actual["source_refs"]} == set(meeting["material_ids"]).intersection({document["source_id"], original_minutes_document["source_id"]})
                    assert all(item["source_sha256"] == checksum(store.get(db, "ui-check", "document", item["source_id"])) for item in actual["source_refs"])
                    payload = {"meeting_id": meeting["meeting_id"], "meeting_version": meeting["version"], "expected_version": "0", "purpose": "核查会议材料", "starts_at": meeting["starts_at"], "ends_at": meeting["ends_at"], "timezone": "Asia/Shanghai", "preparation_due_at": meeting["preparation_due_at"], "participant_ids": ["coordinator-1"], "source_refs": [ref]}
                draft_body = {"protocol_version": 1, "request_key": "technical-draft", "params": payload}
                draft_url = endpoint + "/internal/v1/tools/meeting-draft"
                assert (await client.post(draft_url, json=draft_body)).status_code == 401
                denied = await client.post(draft_url, json=draft_body, headers=headers)
                assert denied.status_code == 503 and denied.json()["code"] == "DRAFT_SERVICE_UNAVAILABLE"
                with runs.connect() as db:
                    db.execute("BEGIN IMMEDIATE")
                    db.row_factory = sqlite3.Row
                    run = db.execute("SELECT * FROM agent_runs WHERE run_id=?", (run_id,)).fetchone()
                    before = db.execute("SELECT count(*) FROM objects WHERE kind='authorization'").fetchone()[0]
                    saved = save_meeting_draft_in_transaction(db, store, scope, run, payload, "technical-draft")
                    assert save_meeting_draft_in_transaction(db, store, scope, run, payload, "technical-draft") == saved
                    meeting_event = draft_result_event_in_transaction(db, store, run_id, run["goal_revision"], "technical-draft", "meeting", saved)
                    formal_event = draft_result_event_in_transaction(db, store, run_id, run["goal_revision"], "technical-draft", "meeting", saved, tool_name="meetingDraftSave")
                    assert formal_event["tool_id"] == "meetingDraftSave" and formal_event["draft_ref"] == meeting_event["draft_ref"]
                    formal_receipt = db.execute("SELECT result FROM idempotency WHERE namespace=? AND operation=? AND key=?", ("ui-check", "boss.meeting.draft.save", formal_event["draft_ref"]["domain_request_key"])).fetchone()
                    assert formal_receipt is not None
                    receipt = json.loads(formal_receipt[0])
                    assert receipt["version"] == saved["confirmation_parameters"]["draft_version"]
                    assert receipt["state"] == "DRAFT" and receipt["invitation_sent"] is False and receipt["meeting_changed"] is False
                    assert meeting_event["goal_revision"] == run["goal_revision"]
                    assert meeting_event["draft_ref"]["sha256"] == checksum(store.get(db, "ui-check", "meeting_draft", meeting["meeting_id"]))
                    assert meeting_event["draft_ref"]["version"] == saved["confirmation_parameters"]["draft_version"]
                    with pytest.raises(web.HTTPConflict):
                        save_meeting_draft_in_transaction(db, store, scope, run, {**payload, "purpose": "核查会议版本"}, "technical-draft")
                    with pytest.raises(web.HTTPForbidden):
                        save_meeting_draft_in_transaction(db, store, scope, run, {**payload, "source_refs": [{"source_id": "finance-note", "version": "1"}]}, "outside-source")
                    assert db.execute("SELECT count(*) FROM objects WHERE kind='authorization'").fetchone()[0] == before
                    assert store.get(db, "ui-check", "meeting", meeting["meeting_id"])["version"] == meeting["version"]
                assert (await client.post(url, json=request, headers=headers)).status_code == 409
                draft_request = {"protocol_version": 1, "call_id": "draft-meeting"}
                response = await client.post(url, json=draft_request, headers=headers)
                assert response.status_code == 200
                result = response.json()["result"]
                params = result["draft"]["confirmation_parameters"]
                assert params == saved["confirmation_parameters"]
                with runs.connect() as db:
                    db.execute("BEGIN")
                    db.row_factory = sqlite3.Row
                    run = db.execute("SELECT * FROM agent_runs WHERE run_id=?", (run_id,)).fetchone()
                    preview = preview_domain_intent(db, store, scope, run, "boss.meeting.confirm", params)
                    assert preview["details"] == result["draft"]["details"]
                    assert preview["source_refs"] == result["draft"]["source_refs"]
                intent = await client.post(endpoint + "/internal/v1/tools/domain-intent", headers=headers, json={"protocol_version": 1, "request_key": "meeting-intent", "action": "boss.meeting.confirm", "params": params})
                assert intent.status_code == 503 and intent.json()["code"] == "INTENT_SERVICE_UNAVAILABLE"
                formal_url = endpoint + "/internal/v1/tools/domain-intent/meetingConfirm"
                wrong_action = await client.post(formal_url, headers=headers, json={"protocol_version": 1, "request_key": "formal-confirm", "action": "boss.meeting.cancel", "params": params})
                assert wrong_action.status_code == 400
                assert (await client.post(formal_url, json={"protocol_version": 1, "request_key": "formal-confirm", "action": "boss.meeting.confirm", "params": params})).status_code == 401
                transport_client = HermesTransportClient(endpoint, capability, run_id)
                try:
                    with registered_product_tools(transport_client, bi_definitions=bi_tool_definitions(store, "ui-check")):
                        receipt_tool = registry.get_entry("read_decision_receipt")
                        with pytest.raises(httpx.HTTPStatusError) as denied_receipt:
                            await asyncio.to_thread(receipt_tool.handler, {"intent_id": "missing-intent"})
                        assert denied_receipt.value.response.status_code == 503
                        entry = registry.get_entry("read_meeting_context")
                        registered = json.loads(await asyncio.to_thread(entry.handler, {}))
                        assert registered == result
                        draft_tool = registry.get_entry("save_meeting_draft")
                        with pytest.raises(httpx.HTTPStatusError) as tool_denied:
                            await asyncio.to_thread(draft_tool.handler, {"request_key": "registered-draft", "params": payload})
                        assert tool_denied.value.response.status_code == 503
                        formal_tool = registry.get_entry("meetingDraftSave")
                        with pytest.raises(httpx.HTTPStatusError) as formal_denied:
                            await asyncio.to_thread(formal_tool.handler, {"client_request_id": "formal-draft", **payload})
                        assert formal_denied.value.response.status_code == 503
                        confirm_tool = registry.get_entry("meetingConfirm")
                        with pytest.raises(httpx.HTTPStatusError) as confirm_denied:
                            await asyncio.to_thread(confirm_tool.handler, {"request_key": "formal-confirm", **params})
                        assert confirm_denied.value.response.status_code == 503
                        with pytest.raises(ValueError):
                            await asyncio.to_thread(confirm_tool.handler, {"request_key": "formal-confirm", **params, "acknowledge_conflict": True})
                        for tool_name in ("meetingCancel", "meetingHeld"):
                            finish_tool = registry.get_entry(tool_name)
                            with pytest.raises(httpx.HTTPStatusError) as finish_denied:
                                await asyncio.to_thread(finish_tool.handler, {"request_key": "formal-finish", "meeting_id": meeting["meeting_id"], "expected_version": meeting["version"], "reason": "核查会议安排"})
                            assert finish_denied.value.response.status_code == 503
                        scoped_brief = registry.get_entry("boss.meeting.brief.prepare")
                        with pytest.raises(httpx.HTTPStatusError) as scoped_denied:
                            await asyncio.to_thread(scoped_brief.handler, {"request_key": "scoped-brief", "meeting_id": meeting["meeting_id"], "meeting_version": meeting["version"], "expected_version": "0"})
                        assert scoped_denied.value.response.status_code == 503
                        assert registry.get_definitions({"boss_meeting_brief", "boss_meeting_brief_docx"}, quiet=True) == []
                        brief_tool = registry.get_entry("boss_meeting_brief")
                        with pytest.raises(httpx.HTTPStatusError) as brief_denied:
                            await asyncio.to_thread(brief_tool.handler, {"request_key": "registered-brief", "source_ids": [document["source_id"]], "format_name": "DOCX"})
                        assert brief_denied.value.response.status_code == 503
                finally:
                    transport_client.close()
                assert (await client.post(url, json={**draft_request, "actor_id": proof.owner_id}, headers=headers)).status_code == 400
                with runs.connect() as db:
                    db.execute("BEGIN IMMEDIATE")
                    db.row_factory = sqlite3.Row
                    run = db.execute("SELECT * FROM agent_runs WHERE run_id=?", (run_id,)).fetchone()
                    updated = save_meeting_draft_in_transaction(db, store, scope, run, {**payload, "expected_version": saved["confirmation_parameters"]["draft_version"], "purpose": "核查当前会议材料"}, "updated-draft")
                    with pytest.raises(web.HTTPConflict):
                        save_meeting_draft_in_transaction(db, store, scope, run, payload, "technical-draft")
                assert (await client.post(url, json=draft_request, headers=headers)).status_code == 409
                latest = await client.post(url, json={"protocol_version": 1, "call_id": "latest-meeting"}, headers=headers)
                assert latest.status_code == 200 and latest.json()["result"]["draft"]["confirmation_parameters"]["draft_version"] == updated["confirmation_parameters"]["draft_version"]
                minutes_url = endpoint + "/internal/v1/tools/minutes-context"
                minutes_draft_url = endpoint + "/internal/v1/tools/minutes-draft"
                read_request = {"protocol_version": 1, "request_key": "minutes-read-1"}
                assert (await client.post(minutes_url, json=read_request)).status_code == 401
                current_minutes = await client.post(minutes_url, json=read_request, headers=headers)
                assert current_minutes.status_code == 200
                minute = current_minutes.json()["result"]["minutes"]
                old_version = minute["details"]["version"] if minute else "0"
                payload_minutes = {"meeting_id": meeting["meeting_id"], "meeting_version": meeting["version"], "source_id": document["source_id"], "source_version": document["version"], "expected_version": old_version, "entries": [{"kind": "ASSIGNMENT_DRAFT", "text": "核查会议资料", "source_anchor": document["content"][:10]}]}
                write_request = {"protocol_version": 1, "request_key": "minutes-save-1", "params": payload_minutes}
                assert (await client.post(minutes_draft_url, json=write_request)).status_code == 401
                assert (await client.post(minutes_draft_url, json=write_request, headers=headers)).status_code == 503
                with runs.connect() as db:
                    db.execute("BEGIN IMMEDIATE")
                    db.row_factory = sqlite3.Row
                    run = db.execute("SELECT * FROM agent_runs WHERE run_id=?", (run_id,)).fetchone()
                    before = db.execute("SELECT count(*) FROM objects WHERE kind IN ('authorization','task')").fetchone()[0]
                    minutes = save_minutes_draft_in_transaction(db, store, scope, run, payload_minutes, "minutes-save-1")
                    assert save_minutes_draft_in_transaction(db, store, scope, run, payload_minutes, "minutes-save-1") == minutes
                    minute_event = draft_result_event_in_transaction(db, store, run_id, run["goal_revision"], "minutes-save-1", "minutes", minutes)
                    assert minute_event["goal_revision"] == run["goal_revision"]
                    assert minute_event["draft_ref"]["sha256"] == checksum(store.get(db, "ui-check", "minutes", meeting["meeting_id"]))
                    assert minute_event["draft_ref"]["version"] == minutes["confirmation_parameters"]["expected_version"]
                    assert minutes["details"]["entries"][0]["kind"] == "ASSIGNMENT_DRAFT"
                    assert preview_domain_intent(db, store, scope, run, "boss.minutes.confirm", minutes["confirmation_parameters"])["owner_decision_required"]
                    with pytest.raises(web.HTTPConflict):
                        save_minutes_draft_in_transaction(db, store, scope, run, {**payload_minutes, "entries": [{**payload_minutes["entries"][0], "text": "核查不同资料"}]}, "minutes-save-1")
                    with pytest.raises(web.HTTPForbidden):
                        save_minutes_draft_in_transaction(db, store, scope, run, {**payload_minutes, "source_id": "finance-note"}, "minutes-save-2")
                    with pytest.raises(web.HTTPBadRequest):
                        save_minutes_draft_in_transaction(db, store, scope, run, {**payload_minutes, "entries": [{**payload_minutes["entries"][0], "source_anchor": "不存在的原文"}]}, "minutes-save-3")
                    assert db.execute("SELECT count(*) FROM objects WHERE kind IN ('authorization','task')").fetchone()[0] == before
                assert (await client.post(minutes_url, json=read_request, headers=headers)).status_code == 409
                newest = await client.post(minutes_url, json={"protocol_version": 1, "request_key": "minutes-read-2"}, headers=headers)
                assert newest.status_code == 200 and newest.json()["result"]["minutes"] == minutes
                transport_client = HermesTransportClient(endpoint, capability, run_id)
                try:
                    with registered_product_tools(transport_client, bi_definitions=bi_tool_definitions(store, "ui-check")):
                        registered_minutes = json.loads(await asyncio.to_thread(registry.get_entry("read_minutes_context").handler, {}))
                        assert registered_minutes["minutes"] == minutes
                        with pytest.raises(httpx.HTTPStatusError) as denied_minutes:
                            await asyncio.to_thread(registry.get_entry("save_minutes_draft").handler, {"request_key": "minutes-save-4", "params": payload_minutes})
                        assert denied_minutes.value.response.status_code == 503
                finally:
                    transport_client.close()
                assert (await client.post(minutes_url, json={"protocol_version": 1, "request_key": "minutes-read-3"}, headers=headers)).status_code == 200
                assert (await client.post(minutes_url, json={"protocol_version": 1, "request_key": "minutes-read-4"}, headers=headers)).status_code == 429
                store.control("ui-check", "withdraw", ref)
                assert (await client.post(url, json=draft_request, headers=headers)).status_code in {409, 410}
                with runs.connect() as db:
                    db.execute("BEGIN IMMEDIATE")
                    db.row_factory = sqlite3.Row
                    run = db.execute("SELECT * FROM agent_runs WHERE run_id=?", (run_id,)).fetchone()
                    with pytest.raises(ValueError, match="来源已经撤销"):
                        save_meeting_draft_in_transaction(db, store, scope, run, payload, "technical-draft")
                    with pytest.raises(ValueError, match="来源已经撤销"):
                        save_minutes_draft_in_transaction(db, store, scope, run, payload_minutes, "minutes-save-1")
            with runs.connect() as db:
                assert db.execute("SELECT count(*) FROM agent_tool_reservations WHERE run_id=? AND tool_name='read_meeting_context'", (run_id,)).fetchone() == (4,)
                assert db.execute("SELECT count(*) FROM objects WHERE kind='hermes_meeting_context_result'").fetchone() == (0,)
        finally:
            await runner.cleanup()

    asyncio.run(exercise())
