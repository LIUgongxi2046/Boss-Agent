from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from aiohttp import web
from nanobot.agent.hook import AgentHook
from nanobot.session.manager import SessionManager
from nanobot.webui.workspaces import WebUIWorkspaceController

from boss_conversation_sources import ConversationSources
from public_conversation import PublicConversation
from test_native import CHAT, execute, native, read


def catalogue(native, query="", *, chat=CHAT):
    return native[1].source_selection.listing("BOSS", {"chat_id": chat, "query": query})


def selection(native, *source_ids, view=None, chat=CHAT):
    view = view or catalogue(native, chat=chat)
    sources = {row["source_id"]: row for row in view["sources"]}
    return {"chat_id": chat, "client_request_id": str(uuid4()),
        "execution_namespace": view["execution_namespace"], "dataset_version": view["dataset_version"],
        "expected_context_version": view["context_version"], "expected_catalogue_version": view["catalogue_version"],
        "source_refs": [{"source_id": identifier, "version": sources[identifier]["version"]} for identifier in source_ids]}


def create_session(native):
    sessions = native[2].sessions
    sessions.save(sessions.get_or_create("websocket:" + CHAT))


def objects(native):
    with native[0].connect() as db:
        return db.execute("SELECT namespace,kind,id,body FROM objects ORDER BY namespace,kind,id").fetchall()


def test_catalogue_search_uses_current_index_without_creating_native_session(native):
    before = objects(native)
    view = catalogue(native)
    assert view["context_version"] == "0" and view["can_bind"] and view["selected_sources"] == []
    assert native[2].sessions.read_session_snapshot("websocket:" + CHAT) is None
    unknown = native[1].source_selection.receipt("BOSS", {"chat_id": CHAT, "client_request_id": str(uuid4())})
    assert unknown["outcome"] == "UNKNOWN" and unknown["write_performed_by_lookup"] is False
    finance = next(row for row in view["sources"] if row["source_id"] == "finance-note")
    assert finance["allowed"] and "content" not in finance
    with native[0].connect() as db:
        document = native[0].get(db, "ui-check", "document", "finance-note")
    for query in ("finance-note", document["content"][:8], "%_"):
        searched = catalogue(native, query)
        assert searched["catalogue_version"] == view["catalogue_version"] and searched["query"] == query
        if query != "%_":
            assert any(row["source_id"] == "finance-note" for row in searched["sources"])
    assert objects(native) == before


def test_binding_reopens_and_receipts_do_not_write_or_grant_business_authority(native, tmp_path):
    create_session(native)
    request = selection(native, "finance-note", "meeting-minutes")
    service = native[1].source_selection
    recorded = service.bind("BOSS", request, active=lambda: True)
    assert recorded["outcome"] == "RECORDED" and recorded["context_version"] == "1"
    assert not recorded["business_authorization_granted"] and not recorded["business_mutation_performed"]
    before = objects(native)
    reopened = ConversationSources(native[0], SessionManager(tmp_path / "workspace", sessions_root=tmp_path / "sessions"))
    assert reopened.bind("BOSS", request, active=lambda: True) == recorded
    assert reopened.listing("BOSS", {"chat_id": CHAT, "query": ""})["selected_sources"] == request["source_refs"]
    assert reopened.receipt("BOSS", {"chat_id": CHAT, "client_request_id": request["client_request_id"]}) == {**recorded, "write_performed_by_lookup": False}
    assert reopened.receipt("BOSS", {"chat_id": CHAT, "client_request_id": str(uuid4())})["outcome"] == "UNKNOWN"
    assert objects(native) == before
    assert not read(native, "task") and not read(native, "authorization")
    with pytest.raises(web.HTTPConflict):
        service.bind("BOSS", {**request, "source_refs": []}, active=lambda: True)


def test_concurrent_bindings_preserve_one_context_and_each_original_receipt(native):
    create_session(native)
    first = selection(native, "finance-note")
    second = selection(native, "meeting-minutes")
    service = native[1].source_selection
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda value: service.bind("BOSS", value, active=lambda: True), (first, second)))
    assert sorted(row["outcome"] for row in results) == ["RECORDED", "REJECTED"]
    for request, result in zip((first, second), results):
        assert service.receipt("BOSS", {"chat_id": CHAT, "client_request_id": request["client_request_id"]}) == {**result, "write_performed_by_lookup": False}
    assert catalogue(native)["context_version"] == "1"


@pytest.mark.parametrize("change", ["namespace", "dataset", "catalogue", "source", "role", "inactive"])
def test_invalid_selection_does_not_change_current_binding(native, change):
    create_session(native)
    request = selection(native, "finance-note")
    role, active = "BOSS", True
    if change == "namespace":
        request["execution_namespace"] = "not-current"
    elif change == "dataset":
        request["dataset_version"] += "-changed"
    elif change == "catalogue":
        native[0].control("ui-check", "withdraw", {"source_id": "meeting-minutes", "version": "1"})
    elif change == "source":
        request["source_refs"][0]["version"] += "-changed"
    elif change == "role":
        role = "MAINTAINER"
    else:
        active = False
    if change in ("role", "inactive"):
        with pytest.raises(web.HTTPException):
            native[1].source_selection.bind(role, request, active=lambda: active)
    else:
        assert native[1].source_selection.bind(role, request, active=lambda: active)["outcome"] == "REJECTED"
    assert not read(native, "conversation_source_binding")


def test_public_requests_require_current_owner_and_attached_native_chat(native, tmp_path):
    create_session(native)
    api = PublicConversation(native[0], native[2].sessions, tmp_path / "media")
    request = selection(native, "finance-note")
    for role, attached, active in (("MAINTAINER", True, True), ("BOSS", False, True), ("BOSS", True, False)):
        with pytest.raises(web.HTTPException):
            api.sources(role, "boss.conversation.sources.bind", request, attached=lambda chat: attached, active=lambda: active)
    result = api.sources("BOSS", "boss.conversation.sources.bind", request, attached=lambda chat: chat == CHAT, active=lambda: True)
    assert result["outcome"] == "RECORDED"
    before = objects(native)
    receipt = api.sources("BOSS", "boss.conversation.sources.receipt", {"chat_id": CHAT, "client_request_id": request["client_request_id"]}, attached=lambda chat: chat == CHAT, active=lambda: True)
    assert receipt["source_refs"] == request["source_refs"] and objects(native) == before


def test_public_binding_persists_actual_native_draft_workspace(native, tmp_path):
    sessions = native[2].sessions
    workspaces = WebUIWorkspaceController(session_manager=sessions, default_workspace=tmp_path / "workspace", default_restrict_to_workspace=True)
    workspaces.stage_scope(CHAT, workspaces.restricted_default_scope())
    api = PublicConversation(native[0], sessions, tmp_path / "media", workspaces=workspaces)
    request = selection(native, "finance-note")
    assert sessions.read_session_snapshot("websocket:" + CHAT) is None
    result = api.sources("BOSS", "boss.conversation.sources.bind", request, attached=lambda chat: chat == CHAT, active=lambda: True)
    assert result["outcome"] == "RECORDED"
    session = sessions.read_session_snapshot("websocket:" + CHAT)
    assert session is not None and session.metadata["webui"] and not session.messages
    assert native[1].source_selection.pin(CHAT)["native_session_created_at"] == session.created_at.isoformat()


def test_recreated_native_session_cannot_adopt_previous_selection(native):
    create_session(native)
    native[1].source_selection.bind("BOSS", selection(native, "finance-note"), active=lambda: True)
    sessions = native[2].sessions
    assert sessions.delete_session("websocket:" + CHAT)
    create_session(native)
    with pytest.raises(web.HTTPConflict):
        native[1].source_selection.pin(CHAT)


def test_actual_agent_reads_selected_sources_and_clearing_resets_followup(native):
    create_session(native)
    request = selection(native, "finance-note", "meeting-minutes")
    assert native[1].source_selection.bind("BOSS", request, active=lambda: True)["outcome"] == "RECORDED"
    results, _ = execute(native, ["请读取资料"])
    assert "finance-note" in results[0].content and "meeting-minutes" in results[0].content
    run = read(native, "runtime_run")[0]
    assert run["conversation_context"]["source_selection"]["source_refs"] == request["source_refs"]
    assert {row["source_id"] for row in run["tool_results"] if row["tool_id"] == "bossEvidenceRead"} == {"finance-note", "meeting-minutes"}
    cleared = native[1].source_selection.bind("BOSS", selection(native), active=lambda: True)
    assert cleared["outcome"] == "RECORDED" and cleared["source_refs"] == []
    execute(native, ["继续读取资料"])
    final = read(native, "runtime_run")[-1]
    assert final["status"] == "WAITING_INPUT" and not any(row["tool_id"] == "bossEvidenceRead" for row in final["tool_results"])


def test_running_turn_rejects_binding_and_source_withdrawal_stops_later_iteration(native):
    create_session(native)
    original = selection(native, "finance-note")
    service = native[1].source_selection
    service.bind("BOSS", original, active=lambda: True)
    class WithdrawAfterRead(AgentHook):
        def __init__(self):
            super().__init__(reraise=True)
            self.executed = False

        async def after_execute_tool(self, context, tool_call, tool, params, result):
            if tool_call.name != "bossEvidenceRead":
                return
            self.executed = True
            assert not catalogue(native)["can_bind"]
            assert service.bind("BOSS", selection(native), active=lambda: True)["outcome"] == "REJECTED"
            native[0].control("ui-check", "withdraw", {"source_id": "finance-note", "version": "1"})
    hook = WithdrawAfterRead()
    with pytest.raises(web.HTTPException):
        execute(native, ["请读取资料"], hooks=[hook])
    assert hook.executed and read(native, "runtime_run")[0]["status"] == "FAILED"
    assert service.receipt("BOSS", {"chat_id": CHAT, "client_request_id": original["client_request_id"]})["outcome"] == "RECORDED"
    with pytest.raises(web.HTTPException):
        service.pin(CHAT)


def test_final_answer_rechecks_selected_source_after_model_iteration(native):
    create_session(native)
    native[1].source_selection.bind("BOSS", selection(native, "finance-note"), active=lambda: True)
    class WithdrawAfterAnswer(AgentHook):
        def __init__(self):
            super().__init__(reraise=True)
            self.executed = False

        async def after_iteration(self, context):
            if not context.tool_calls and context.response is not None and context.response.content:
                self.executed = True
                native[0].control("ui-check", "withdraw", {"source_id": "finance-note", "version": "1"})
    hook = WithdrawAfterAnswer()
    with pytest.raises(web.HTTPException):
        execute(native, ["读取资料"], hooks=[hook])
    assert hook.executed and read(native, "runtime_run")[0]["status"] == "FAILED"
