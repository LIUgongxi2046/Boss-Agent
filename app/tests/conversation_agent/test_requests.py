import asyncio
from uuid import uuid4

import pytest
from aiohttp import web
from nanobot.agent.tools.context import RequestContext

from business import checksum
from controls import ControlStore
from conversation_agent.native import NativeConversationAgent
from test_native import CHAT, execute, native


FIELDS = {"source_type", "client_request_id", "outcome", "request_state", "run_id", "chat_id", "session_id", "turn_id",
    "write_performed_by_lookup", "business_authority_granted"}


def counts(store):
    with store.connect() as db:
        return (db.execute("SELECT namespace,kind,count(*) FROM objects GROUP BY namespace,kind ORDER BY namespace,kind").fetchall(),
            db.execute("SELECT count(*) FROM audit").fetchone(), db.execute("SELECT count(*) FROM idempotency").fetchone(),
            db.execute("SELECT count(*) FROM spaces").fetchone())


def admit(agent, chat_id=CHAT):
    return agent.admit("BOSS", chat_id, str(uuid4()), "查看当前任务", media_sha256=checksum([]),
        attached=lambda chat: chat == chat_id, active=lambda: True)


def test_requests_read_actual_sdk_and_pre_runtime_states_after_store_reopen(native):
    store, agent = native[:2]
    _, completed = execute(native, ["查看当前任务"])
    failed = agent.admit("BOSS", CHAT, str(uuid4()), "查看附件", media_sha256="0" * 64,
        attached=lambda chat: chat == CHAT, active=lambda: True)
    request = RequestContext(channel="websocket", chat_id=CHAT, session_key="websocket:" + CHAT, sender_id="boss-1",
        original_user_text="查看附件", metadata={"webui_turn_id": failed["turn_id"]})
    with pytest.raises(web.HTTPConflict):
        asyncio.run(agent.native_context(request))
    canceled = admit(agent)
    agent.finish(canceled["client_request_id"], status="CANCELED")
    pending = admit(agent)
    other = admit(agent, "n02-requests-other")
    before, proofs = counts(store), dict(agent.proofs)
    current = agent.requests("BOSS", CHAT, attached=lambda chat: chat == CHAT, active=lambda: True)
    assert [item["request_state"] for item in current] == ["SUCCEEDED", "FAILED", "CANCELED", "ADMITTED"]
    expected = [*completed, failed, canceled, pending]
    assert [item["client_request_id"] for item in current] == [item["client_request_id"] for item in expected]
    assert [item["turn_id"] for item in current] == [item["turn_id"] for item in expected]
    assert all(set(item) == FIELDS and item["outcome"] == "RECORDED" and item["write_performed_by_lookup"] is False for item in current)
    assert all(item["run_id"] is None for item in current[1:])
    assert other["client_request_id"] not in {item["client_request_id"] for item in current}
    assert current == [agent.receipt("BOSS", item["client_request_id"], active=lambda: True) for item in expected]
    assert agent.proofs == proofs and counts(store) == before
    reopened = NativeConversationAgent(ControlStore(store.path), agent.registry, agent.recorder.runtime_snapshot, agent.attachments)
    assert not reopened.proofs and not reopened.pending_media
    assert reopened.requests("BOSS", CHAT, attached=lambda chat: chat == CHAT, active=lambda: True) == current
    assert not reopened.proofs and not reopened.pending_media and counts(store) == before


def test_requests_empty_attached_chat_is_empty_and_never_creates_state(native):
    store, agent = native[:2]
    before = counts(store)
    assert agent.requests("BOSS", "n02-requests-empty", attached=lambda chat: chat == "n02-requests-empty", active=lambda: True) == []
    assert counts(store) == before and not agent.proofs
    assert agent.attachments.sessions.read_session_snapshot("websocket:n02-requests-empty") is None


@pytest.mark.parametrize("role,attached,active", [(None, True, True), ("MAINTAINER", True, True), ("BOSS", False, True), ("BOSS", True, False)])
def test_requests_require_live_attached_owner_without_mutation(native, role, attached, active):
    store, agent = native[:2]
    admit(agent)
    before, proofs = counts(store), dict(agent.proofs)
    with pytest.raises(web.HTTPException):
        agent.requests(role, CHAT, attached=lambda chat: attached, active=lambda: active)
    assert counts(store) == before and agent.proofs == proofs


@pytest.mark.parametrize("guard", ["active", "attached"])
def test_requests_recheck_connection_before_releasing_results(native, guard):
    store, agent = native[:2]
    admit(agent)
    calls = []
    def current():
        calls.append(True)
        return len(calls) == 1
    before = counts(store)
    with pytest.raises(web.HTTPException):
        agent.requests("BOSS", CHAT, attached=(lambda chat: current()) if guard == "attached" else lambda chat: True,
            active=current if guard == "active" else lambda: True)
    assert counts(store) == before


@pytest.mark.parametrize("field,value", [("owner_id", "unapproved-owner"), ("dataset_id", "unapproved-dataset"),
    ("dataset_version", "unapproved-version"), ("session_id", "websocket:n02-other-session")])
def test_requests_reject_tampered_actual_intent_scope(native, field, value):
    store, agent = native[:2]
    result = admit(agent)
    with store.connect() as db:
        row = store.get(db, "ui-check", "conversation_intent", result["client_request_id"])
        row[field] = value
        store.put(db, "ui-check", "conversation_intent", result["client_request_id"], row)
    before = counts(store)
    with pytest.raises(web.HTTPForbidden):
        agent.requests("BOSS", CHAT, attached=lambda chat: True, active=lambda: True)
    assert counts(store) == before


def test_requests_reject_inactive_namespace_and_invalid_chat(native):
    store, agent = native[:2]
    admit(agent)
    before = counts(store)
    with pytest.raises(web.HTTPBadRequest):
        agent.requests("BOSS", "../n02-invalid", attached=lambda chat: True, active=lambda: True)
    assert counts(store) == before
    store.initialize("n02-other-namespace")
    before = counts(store)
    with pytest.raises(web.HTTPException):
        agent.requests("BOSS", CHAT, attached=lambda chat: True, active=lambda: True)
    assert counts(store) == before
