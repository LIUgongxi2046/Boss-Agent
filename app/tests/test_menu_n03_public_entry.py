import pytest
from aiohttp import web

from public_conversation import PublicConversation, CONVERSATION_BUSINESS_ACTIONS
from test_menu_n03_entry import CHAT, CONTEXT, selection, business_snapshot
from test_menu_n02_task_entry import bind_request


def invoke(api, action, payload, *, role="BOSS", active=True, attached=True):
    return api.business(role, "boss.conversation.business." + action, payload,
                        active=lambda: active, attached=lambda chat: attached and chat == CHAT)


def test_public_preparation_binding_current_read_and_clear_preserve_business_state(selection, tmp_path):
    store, sessions, entry, request = selection
    api = PublicConversation(store, sessions, tmp_path / "media")
    before = business_snapshot(store)
    prepared = invoke(api, "prepare", request)
    assert prepared["current_use_verified"] and prepared["binding_state"] == "PREPARED"
    bound = invoke(api, "bind", bind_request(prepared, CHAT))
    assert bound["binding_state"] == "BOUND" and bound["context"]["session_id"] == CONTEXT["session_id"]
    current = invoke(api, "read", {"chat_id": CHAT, "adopt_selection": True})
    assert current["current_use_verified"] and current["entry"] == bound
    receipt = invoke(api, "receipt", {"client_request_id": request["client_request_id"]})
    assert receipt["entry"]["current_use_verified"] is False
    assert receipt == entry.receipt("BOSS", {"client_request_id": request["client_request_id"]})
    cleared = invoke(api, "clear", {})
    assert cleared == {"source_type": "RUNTIME_RECORD", "current_selection_cleared": True,
                       "business_authorization_granted": False, "business_mutation_performed": False}
    assert entry.read("BOSS", CONTEXT)["entry"] == bound
    assert business_snapshot(store) == before
    reopened = PublicConversation(type(store)(store.path), sessions, tmp_path / "media")
    assert invoke(reopened, "read", {"chat_id": CHAT})["entry"] == bound


@pytest.mark.parametrize("role,active,attached,status", [(None, True, True, 401), ("MAINTAINER", True, True, 403),
    ("BOSS", False, True, 401), ("BOSS", True, False, 403)])
def test_public_current_identity_and_attachment_are_required(selection, tmp_path, role, active, attached, status):
    store, sessions, entry, request = selection
    prepared = entry.prepare("BOSS", request)
    api = PublicConversation(store, sessions, tmp_path / "media")
    before = business_snapshot(store)
    with pytest.raises(web.HTTPException) as failure:
        invoke(api, "bind", bind_request(prepared, CHAT), role=role, active=active, attached=attached)
    assert failure.value.status == status
    assert entry.receipt("BOSS", {"client_request_id": request["client_request_id"]})["entry"]["binding_state"] == "PREPARED"
    assert business_snapshot(store) == before


def test_public_selection_fields_and_late_source_change_are_rejected(selection, tmp_path):
    store, sessions, entry, request = selection
    api = PublicConversation(store, sessions, tmp_path / "media")
    prepared = invoke(api, "prepare", request)
    invoke(api, "bind", bind_request(prepared, CHAT))
    for payload in ({"chat_id": CHAT, "adopt_selection": "true"}, {"chat_id": CHAT, "role": "BOSS"},
                    {"chat_id": CHAT, "preparation_sha256": prepared["preparation_sha256"]}):
        with pytest.raises(web.HTTPBadRequest):
            invoke(api, "read", payload)
    with pytest.raises(web.HTTPBadRequest):
        invoke(api, "clear", {"chat_id": CHAT})
    store.control("ui-check", "withdraw", {"source_id": "finance-note", "version": "1"})
    with pytest.raises(web.HTTPConflict):
        invoke(api, "read", {"chat_id": CHAT, "adopt_selection": True})
    assert invoke(api, "receipt", {"client_request_id": request["client_request_id"]})["entry"]["preparation_sha256"] == prepared["preparation_sha256"]
    assert len(CONVERSATION_BUSINESS_ACTIONS) == 5
