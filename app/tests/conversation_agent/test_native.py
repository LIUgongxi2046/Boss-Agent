import asyncio
import base64
from copy import deepcopy
from dataclasses import replace
import json
import sys
from pathlib import Path
from uuid import uuid4

import pytest
from aiohttp import web
from loguru import logger
from nanobot import Nanobot
from nanobot.agent.hook import AgentHook
from nanobot.agent.loop import AgentLoop
from nanobot.agent.tools.context import RequestContext
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.providers.base import LLMResponse, ToolCallRequest
from nanobot.config.schema import Config
from nanobot.session.manager import SessionManager
from nanobot.runtime_context import public_history_messages
from nanobot.webui.media_gateway import WebUIMediaGateway

from conftest import DOMAIN
from business import checksum
from controls import ControlStore
from boss_conversation import ConversationAPI
from boss_conversation_attachments import ConversationAttachments
from boss_command_api import BossCommandAPI
from boss_memory_runtime import MemoryContextInvalidated, OwnerMemoryContext
from boss_memory_sessions import MemoryAutoCompact, MemorySessionManager
from conversation_agent.native import NativeConversationAgent
from product_bi import FeatureToolRegistry


CHAT = "n02-native-current"


@pytest.fixture
def native(tmp_path, request):
    logger.remove()
    logger.add(sys.stderr, level="WARNING", diagnose=False, backtrace=False)
    store = ControlStore(tmp_path / "native.sqlite")
    store.initialize("ui-check")
    config = Config.model_validate({"agents": {"defaults": {"workspace": str(tmp_path / "workspace"),
        "provider": "deepseek", "model": "deepseek-flash", "maxToolIterations": 12, "maxTokens": 700,
        "maxToolResultChars": 200000, "dream": {"enabled": False}, "idleCompactAfterMinutes": 0}}})
    sessions = MemorySessionManager(tmp_path / "workspace", business_store=store, sessions_root=tmp_path / "sessions")
    media_root = tmp_path / "media"
    media_root.mkdir()
    attachments = ConversationAttachments(sessions, media_root)
    registry = FeatureToolRegistry()
    snapshot = {"provider": "deepseek", "model_id": "deepseek-flash", "api_type": "chat_completions",
        "max_tool_rounds": 12, "max_output_tokens": 700, "timeout": 120, "config_sha256": checksum(config.model_dump(mode="json"))}
    agent_class = request.param if hasattr(request, "param") else NativeConversationAgent
    agent = agent_class(store, registry, lambda: snapshot, attachments)
    agent.provider.generation = config.resolve_preset().to_generation_settings()
    loop = AgentLoop.from_config(config, session_manager=sessions, provider=agent.provider, tool_registry=registry,
        hook_factories=[agent.recorder.hook_factory])
    loop.auto_compact = MemoryAutoCompact(sessions, loop.consolidator)
    sessions.invalidate_context = loop.auto_compact.invalidate_memory_context
    for name in list(registry.tool_names):
        registry.unregister(name)
    for tool in agent.tools():
        registry.register(tool)
    with store.connect() as db:
        row = store.get(db, "ui-check", "configuration", "current")
        row["tool_scope"] = sorted(registry.tool_names)
        store.put(db, "ui-check", "configuration", "current", row)
    gateway = WebUIMediaGateway(workspace_path=tmp_path, logger=logger, media_dir=lambda _: media_root)
    return store, agent, loop, config, gateway


def read(native, kind):
    with native[0].connect() as db:
        return [json.loads(row[0]) for row in db.execute("SELECT body FROM objects WHERE kind=? ORDER BY rowid", (kind,))]


def execute(native, questions, *, upload=None, before_context=None, memory_context=False, hooks=None):
    store, agent, loop, config, gateway = native
    admitted = []
    async def run():
        async with Nanobot(loop, config=config) as bot:
            async def transport(request):
                request.metadata["webui_turn_id"] = request.turn_id
                value = agent.admit("BOSS", CHAT, request.turn_id, request.original_user_text,
                    media_sha256=checksum(upload[0] if upload else []), attached=lambda chat: chat == CHAT, active=lambda: True)
                if value is None:
                    return
                assert value["enqueue"]
                admitted.append(value)
                if upload:
                    agent.record_media("BOSS", value["client_request_id"], upload[0], upload[1], active=lambda: True)
                if before_context is not None:
                    before_context(request)
            async def recorder(request):
                if agent.handles(request):
                    return await agent.recorder.context(request)
            providers = [transport, agent.native_context]
            if memory_context:
                providers.append(OwnerMemoryContext(store))
            providers.extend([agent.scope_context, recorder])
            remove = [bot.runtime.add_context_provider(provider) for provider in providers]
            try:
                return [await bot.run(question, channel="websocket", chat_id=CHAT, session_key="websocket:" + CHAT,
                    sender_id="boss-1", media=upload[1] if upload else None, hooks=hooks) for question in questions]
            finally:
                for unsubscribe in reversed(remove):
                    unsubscribe()
    return asyncio.run(run()), admitted


def test_native_current_input_plans_actual_parameters_and_follows_current_source(native):
    results, admitted = execute(native, ["请读取来源 finance-note", "读取 meeting-minutes", "再次读取 finance-note", "继续核查这份资料的版本", "查看当前联系人与消息"])
    assert "来源：finance-note" in results[0].content and "来源：finance-note" in results[3].content
    assert "来源：meeting-minutes" in results[1].content
    assert "本人消息历史" in results[4].content and "联系人：" in results[4].content
    assert all(not result.content.startswith("{") for result in results)
    runs = ConversationAPI(native[0]).read("BOSS", {"session_id": "websocket:" + CHAT, "chat_id": CHAT})["runs"]
    assert len(runs) == 5 and len({row["run_id"] for row in runs}) == 5
    assert all(row["status"] == "SUCCEEDED" for row in runs)
    row = read(native, "runtime_run")[0]
    assert row["tool_results"][0]["parameters_sha256"] == checksum({"source": "finance-note"})
    assert row["conversation_context"]["client_request_id"] == admitted[0]["client_request_id"]
    assert not native[1].proofs
    assert not read(native, "task") and not read(native, "authorization")


@pytest.mark.parametrize("change", ["delete", "replace", "revoke", "expire"])
def test_native_run_stops_when_adopted_memory_changes(native, change):
    store = native[0]
    api = BossCommandAPI(store)
    with store.connect() as db:
        current = store.get(db, "ui-check", "memory", "current")
    values = {"text": current["text"], "source_note": "采用本人当前要求", "visibility": "BOSS_ONLY",
              "valid_until": "2026-10-23T00:00:00+08:00"}
    status, confirmed = api.execute("BOSS", "boss.owner_workspace.personal-memory.confirm", {
        "client_request_id": str(uuid4()), "expected_version": current["version"],
        "expected_candidate_version": "0", "confirmation": True, "values": values,
    })
    assert status == 200, confirmed
    confirmed = confirmed["result"]

    class ChangeMemoryAfterRead(AgentHook):
        def __init__(self):
            super().__init__(reraise=True)
            self.executed = False

        async def after_execute_tool(self, context, tool_call, tool, params, result):
            assert not self.executed
            self.executed = True
            if change == "expire":
                store.control("ui-check", "clock", {"at": "2026-10-23T09:00:00+08:00"})
                return
            if change == "revoke":
                status, changed = api.execute("BOSS", "boss.authorization.revoke", {
                    "client_request_id": str(uuid4()), "authorization_id": confirmed["authorization_id"],
                    "expected_version": "1", "reason": "本人撤销记忆确认",
                })
            else:
                payload = {"client_request_id": str(uuid4()), "expected_version": confirmed["version"],
                           "expected_candidate_version": "0", "confirmation": True}
                if change == "replace":
                    payload["values"] = values
                status, changed = api.execute("BOSS", "boss.owner_workspace.personal-memory."
                                              + ("confirm" if change == "replace" else "delete"), payload)
            assert status == 200, changed

    mutation = ChangeMemoryAfterRead()
    with pytest.raises(MemoryContextInvalidated, match="OWNER_MEMORY_CONTEXT_CHANGED"):
        execute(native, ["读取 finance-note"], memory_context=True, hooks=[mutation])
    assert mutation.executed
    row = read(native, "runtime_run")[0]
    assert row["status"] == "CANCELED" and row["stop_reason"] == "OWNER_MEMORY_CONTEXT_CHANGED"
    assert row["memory_reference"]["eligible"] is True
    assert row["memory_reference"]["version"] == confirmed["version"]
    assert len(row["tool_results"]) == len(row["simulated_model_events"]) == 1
    assert row["model_completion_observed"] is False
    assert read(native, "conversation_intent")[0]["status"] == "CANCELED"
    assert not native[1].proofs


def test_memory_cleanup_preserves_visible_history_and_excludes_previous_context_after_reopen(native):
    store, _, loop, _, _ = native
    api = BossCommandAPI(store)
    with store.connect() as db:
        memory = store.get(db, "ui-check", "memory", "current")
    execute(native, ["读取 finance-note"], memory_context=True)
    session = loop.sessions.get_or_create("websocket:" + CHAT)
    original = public_history_messages(session.messages)
    assert memory["text"] in json.dumps(session.messages, ensure_ascii=False)
    session.commit_summary_checkpoint(memory["text"])
    loop.sessions.save(session, fsync=True)
    previous_session = deepcopy(session)
    status, receipt = api.execute("BOSS", "boss.owner_workspace.personal-memory.delete", {
        "client_request_id": str(uuid4()), "expected_version": memory["version"],
        "expected_candidate_version": "0", "confirmation": True,
    })
    assert status == 200, receipt
    result = loop.sessions.reconcile_memory()
    assert result == {"sessions_checked": 1, "sessions_changed": 1}
    assert public_history_messages(session.messages)[:len(original)] == original
    assert memory["text"] not in json.dumps(session.messages, ensure_ascii=False)
    assert "_last_summary" not in session.metadata and "runtime_checkpoint" not in session.metadata
    assert session.provider_state is None and session.get_history() == []
    loop.sessions.save(previous_session, fsync=True)
    session = loop.sessions.get_or_create(session.key)
    assert memory["text"] not in json.dumps(session.messages, ensure_ascii=False)
    assert "_last_summary" not in session.metadata and session.get_history() == []
    reopened = MemorySessionManager(loop.sessions.workspace, business_store=ControlStore(store.path),
                                   sessions_root=loop.sessions.sessions_dir.parent)
    saved = reopened.get_or_create(session.key)
    assert saved.get_history() == [] and saved.metadata == session.metadata
    assert public_history_messages(saved.messages)[:len(original)] == original
    assert reopened.reconcile_memory() == {"sessions_checked": 1, "sessions_changed": 0}

    class ObserveActualInput(AgentHook):
        def __init__(self):
            super().__init__(reraise=True)
            self.seen = []

        async def before_iteration(self, context):
            self.seen.append(json.dumps(context.messages, ensure_ascii=False))

    observed = ObserveActualInput()
    results, _ = execute(native, ["读取 meeting-minutes"], memory_context=True, hooks=[observed])
    assert "来源：meeting-minutes" in results[0].content
    assert observed.seen and all(memory["text"] not in value for value in observed.seen)
    assert all("读取 finance-note" not in value for value in observed.seen)
    assert read(native, "runtime_run")[-1]["memory_reference"]["eligible"] is False
    with store.connect() as db:
        propagation = store.get(db, "ui-check", "memory_deletion", memory["memory_id"])
    assert propagation["loaded_sessions"] == "NATIVE_REPLAY_AND_CONTEXT_CLEARED"
    assert propagation["sessions_checked"] == 1 and propagation["backups"] == "NOT_VERIFIED"


def test_memory_cleanup_failure_stops_context_admission_and_records_failure(native):
    store, _, loop, _, _ = native
    execute(native, ["读取 finance-note"], memory_context=True)
    session = loop.sessions.get_or_create("websocket:" + CHAT)
    clean = deepcopy(session)
    user_message = next(row for row in session.messages if row["role"] == "user")
    user_message["content"] += "\n" + public_history_messages([user_message])[0]["content"]
    original_manager = SessionManager(loop.sessions.workspace, sessions_root=loop.sessions.sessions_dir.parent)
    original_manager.save(session, fsync=True)
    with store.connect() as db:
        current = store.get(db, "ui-check", "memory", "current")
    status, result = BossCommandAPI(store).execute("BOSS", "boss.owner_workspace.personal-memory.delete", {
        "client_request_id": str(uuid4()), "expected_version": current["version"],
        "expected_candidate_version": "0", "confirmation": True,
    })
    assert status == 200, result
    with pytest.raises(web.HTTPConflict):
        loop.sessions.reconcile_memory()
    with store.connect() as db:
        propagation = store.get(db, "ui-check", "memory_deletion", current["memory_id"])
    assert propagation["loaded_sessions"] == "FAILED" and propagation["failure_reason"]
    with pytest.raises(web.HTTPConflict):
        loop.sessions.get_or_create(session.key)
    assert len(read(native, "runtime_run")) == 1
    loop.sessions.save(clean, fsync=True)
    loop.sessions.reconcile_memory()
    with store.connect() as db:
        propagation = store.get(db, "ui-check", "memory_deletion", current["memory_id"])
    assert propagation["loaded_sessions"] == "NATIVE_REPLAY_AND_CONTEXT_CLEARED"
    assert propagation["failure_reason"] is None


def test_real_upload_is_metadata_and_does_not_become_business_source(native):
    actual = (DOMAIN / "Boss-Agent-Desktop-Complete-v7/assets/boss-logo-from-reference.png").read_bytes()
    selected = [{"name": "boss-logo-from-reference.png", "data_url": "data:image/png;base64," + base64.b64encode(actual).decode()}]
    paths, failure = native[4].store_inbound_attachments(selected)
    assert failure is None
    results, _ = execute(native, ["查看附件并分析内容"], upload=(selected, paths))
    assert "待补充" in results[0].content
    item = native[1].attachments.read("BOSS", {"session_id": "websocket:" + CHAT, "chat_id": CHAT})["attachments"][0]
    assert item["original_name"] == selected[0]["name"] and item["size_bytes"] == len(actual)
    assert item["processing_state"] == "STORED" and "正式业务来源引用" in results[0].content
    row = read(native, "runtime_run")[0]
    assert row["status"] == "WAITING_INPUT" and row["stop_reason"] == "required_input"
    assert row["conversation_context"]["attachment_refs"][0]["attachment_id"] == item["attachment_id"]
    assert paths[0] not in json.dumps(row) and selected[0]["name"] not in json.dumps(row)


def test_original_intent_duplicate_and_changed_media_are_not_replayed(native):
    _, admitted = execute(native, ["查看当前任务"])
    original = admitted[0]
    again = native[1].admit("BOSS", CHAT, original["turn_id"], "查看当前任务", media_sha256=checksum([]), attached=lambda chat: True, active=lambda: True)
    assert again["enqueue"] is False and again["run_id"] == read(native, "runtime_run")[0]["run_id"]
    for text, media in (("不同文字", checksum([])), ("查看当前任务", "0" * 64)):
        with pytest.raises(web.HTTPConflict):
            native[1].admit("BOSS", CHAT, original["turn_id"], text, media_sha256=media, attached=lambda chat: True, active=lambda: True)
    assert len(read(native, "runtime_run")) == len(read(native, "conversation_intent")) == 1


def test_unknown_input_waits_and_new_input_can_continue(native):
    results, _ = execute(native, ["处理一下这个事项", "查看当前任务"])
    assert "待补充" in results[0].content
    assert "当前任务" in results[1].content
    assert [row["status"] for row in read(native, "runtime_run")] == ["WAITING_INPUT", "SUCCEEDED"]


def test_stop_has_no_new_intent_or_business_lookup(native):
    assert native[1].admit(None, CHAT, None, "/STOP", media_sha256=None, attached=None, active=None) is None
    assert not read(native, "conversation_intent") and not read(native, "runtime_run")


def test_morning_binding_keeps_priority(native):
    from product_morning import ProductMorning
    morning = ProductMorning(native[0])
    morning.native.bind_sessions(native[2].sessions)
    morning.native.bind("BOSS", "n02-morning-priority", {"chat_id": CHAT, "date": "2026-10-24", "timezone": "Asia/Shanghai"},
        attached=lambda chat: True, active=lambda: True)
    assert native[1].admit("BOSS", CHAT, str(uuid4()), "读取资料", media_sha256=checksum([]), attached=lambda chat: True, active=lambda: True) is None
    assert not read(native, "conversation_intent")


@pytest.mark.parametrize("role,attached,active", [("MAINTAINER", True, True), ("BOSS", False, True), ("BOSS", True, False)])
def test_native_admission_needs_live_owner_connection(native, role, attached, active):
    with pytest.raises(web.HTTPException):
        native[1].admit(role, CHAT, str(uuid4()), "查看消息", media_sha256=checksum([]), attached=lambda chat: attached, active=lambda: active)
    assert not read(native, "conversation_intent")


def test_new_service_can_read_original_receipt_but_cannot_adopt_old_proof(native):
    _, admitted = execute(native, ["读取 finance-note"])
    store, old, loop, config, gateway = native
    reopened = NativeConversationAgent(ControlStore(store.path), old.registry, old.recorder.runtime_snapshot, old.attachments)
    receipt = reopened.receipt("BOSS", admitted[0]["client_request_id"], active=lambda: True)
    assert receipt["request_state"] == "SUCCEEDED" and receipt["write_performed_by_lookup"] is False
    unknown = reopened.receipt("BOSS", "unknown-original-request", active=lambda: True)
    assert unknown["outcome"] == "NOT_FOUND_IN_CURRENT_STORE" and unknown["run_id"] is None
    request = RequestContext(channel="websocket", chat_id=CHAT, session_key="websocket:" + CHAT, sender_id="boss-1",
        original_user_text="读取 finance-note", metadata={"webui_turn_id": admitted[0]["turn_id"]})
    with pytest.raises(web.HTTPForbidden):
        asyncio.run(reopened.native_context(request))
    assert len(read(native, "runtime_run")) == 1


@pytest.mark.parametrize("failure,status", [("cancel", "CANCELED"), ("timeout", "TIMED_OUT")])
def test_native_terminal_keeps_original_intent_and_clears_proof(native, failure, status):
    original = native[1].provider.event_producer
    async def events(messages, tools):
        if not any(message["role"] == "tool" for message in messages):
            return await original(messages, tools)
        if failure == "cancel":
            raise asyncio.CancelledError()
        raise TimeoutError("明确模拟的原生会话超时")
    native[1].provider.event_producer = events
    with pytest.raises(asyncio.CancelledError if failure == "cancel" else TimeoutError):
        execute(native, ["读取 finance-note"])
    assert read(native, "runtime_run")[0]["status"] == status
    assert read(native, "conversation_intent")[0]["status"] == status
    assert not native[1].proofs


def query_artifact(native, workspace):
    from fc02_agent import Fc02Context, bind_query, register_fc02_tools
    from fc02_agent.runtime import Fc02RuntimeRecorder, Fc02SimulatedProvider
    store = native[0]
    with store.connect() as db:
        initial = store.get(db, "ui-check", "initial", "snapshot")
        configuration = store.get(db, "ui-check", "configuration", "current")
        configuration["tool_scope"] = sorted(set(configuration["tool_scope"]) | {"query_metrics", "read_evidence"})
        store.put(db, "ui-check", "configuration", "current", configuration)
    detail = initial["details"][0]
    params = {"region_id": detail["region_id"], "product_ids": sorted({row["product_id"] for row in initial["details"]}),
        "metric_ids": ["gross_margin"], "definition_version": "1", "period_start": initial["periods"]["CURRENT"][0],
        "period_end": initial["periods"]["CURRENT"][1], "comparison_start": initial["periods"]["BASE"][0],
        "comparison_end": initial["periods"]["BASE"][1], "question": "查询当前获准期间的毛利率及依据", "currency": "CNY",
        "trade_scope": "EXTERNAL_SALES", "query_mode": "SCOPED", "legal_entity_id": detail["legal_entity_id"],
        "quantity_unit": "tonne", "business_basis": "SELECTION_REPORTED", "settlement_state": "SETTLED"}
    current = [Fc02Context("BOSS", "boss-1", "ui-check", "selection", "1", "n02-query-original", "websocket:" + CHAT,
        True, (bind_query(params),), frozenset())]
    registry = ToolRegistry()
    async def events(messages, tools):
        outputs = [json.loads(item["content"]) for item in messages if item["role"] == "tool"]
        if not outputs:
            return LLMResponse(content=None, tool_calls=[ToolCallRequest(id=str(uuid4()), name="query_metrics", arguments=params)])
        return LLMResponse(content=json.dumps(outputs[-1], ensure_ascii=False))
    provider = Fc02SimulatedProvider(events)
    config = Config.model_validate({"agents": {"defaults": {"workspace": str(workspace), "provider": "deepseek",
        "model": "deepseek-flash", "maxToolIterations": 12, "maxTokens": 700, "dream": {"enabled": False}, "idleCompactAfterMinutes": 0}}})
    snapshot = {**native[1].recorder.runtime_snapshot(), "config_sha256": checksum(config.model_dump(mode="json"))}
    recorder = Fc02RuntimeRecorder(store, "ui-check", registry, lambda: snapshot, lambda: current[0])
    provider.generation = config.resolve_preset().to_generation_settings()
    sessions = SessionManager(workspace, sessions_root=workspace.parent / (workspace.name + "-sessions"))
    loop = AgentLoop.from_config(config, session_manager=sessions, provider=provider, tool_registry=registry, hook_factories=[recorder.hook_factory])
    for name in list(registry.tool_names):
        registry.unregister(name)
    register_fc02_tools(registry, store, lambda: current[0])
    async def run():
        async with Nanobot(loop, config=config) as bot:
            bot.runtime.add_context_provider(recorder.context)
            async def admitted(request):
                binding = request.attributes["boss_runtime_binding"]
                current[0] = replace(current[0], request_id=binding.request_id, session_id=binding.session_id)
            bot.runtime.add_context_provider(admitted)
            return await bot.run(params["question"], channel="websocket", chat_id=CHAT, session_key="websocket:" + CHAT, sender_id="boss-1")
    result = asyncio.run(run())
    assert not result.error
    return json.loads(result.content)


def test_actual_query_artifact_is_adopted_and_source_withdrawal_stops_current_read(native, tmp_path):
    query = query_artifact(native, tmp_path / "query-runtime")
    results, _ = execute(native, ["查看产物 " + query["query_id"]])
    assert query["query_id"] in results[0].content
    assert all(value["value"] is None or value["value"] in results[0].content for value in query["values"])
    row = read(native, "runtime_run")[-1]
    assert row["tool_results"][0]["query_id"] == query["query_id"]
    assert len(read(native, "query")) == 1
    native[0].control("ui-check", "withdraw", {"source_id": "finance-note", "version": "1"})
    with pytest.raises(web.HTTPException):
        execute(native, ["继续查看产物 " + query["query_id"]])
    assert len(read(native, "runtime_run")) == 2


def test_actual_owner_message_and_draft_ids_use_correct_storage_kind(native):
    commands = BossCommandAPI(native[0])
    with native[0].connect() as db:
        document = native[0].get(db, "ui-check", "document", "finance-note")
    code, draft = commands.execute("BOSS", "boss.message.draft.save", {"client_request_id": "native-owner-draft",
        "draft_id": None, "expected_version": "0", "recipient_id": "coordinator-1", "related_task_id": None,
        "body": document["content"], "attachment_refs": [{"source_id": document["source_id"], "version": document["version"]}],
        "visibility": "RECIPIENT_ONLY"})
    assert code == 200
    execute(native, ["查看草稿 " + draft["draft_id"]])
    saved = read(native, "message_draft")[0]
    code, sent = commands.execute("BOSS", "boss.message.send", {"client_request_id": "native-owner-send",
        "draft_id": draft["draft_id"], "expected_version": draft["version"], "recipient_id": saved["recipient_id"],
        "expected_content_sha256": saved["content_sha256"]})
    assert code == 200
    results, _ = execute(native, ["查看消息 " + sent["message_id"]])
    assert "SENT_SIMULATED" in results[0].content and sent["message_id"] in results[0].content
    row = read(native, "runtime_run")[-1]
    assert row["tool_results"][0]["message_id"] == sent["message_id"]
    assert len(read(native, "message_outbox")) == len(read(native, "authorization")) == 1
    assert not read(native, "outbox")


def upload_document(native):
    actual = (DOMAIN / "specs/morning-coverage.json").read_bytes()
    selected = [{"name": "morning-coverage.json", "data_url": "data:application/json;base64," + base64.b64encode(actual).decode()}]
    paths, failure = native[4].store_inbound_attachments(selected)
    assert failure is None
    return selected, paths


def test_actual_document_reference_survives_sdk_without_user_media(native):
    upload = upload_document(native)
    results, _ = execute(native, ["查看附件"], upload=upload)
    view = native[1].attachments.read("BOSS", {"session_id": "websocket:" + CHAT, "chat_id": CHAT})
    item = view["attachments"][0]
    assert item["original_name"] == "morning-coverage.json" and item["processing_state"] == "STORED"
    assert item["user_message_index"] is None
    saved = native[1].attachments.sessions.read_session_snapshot("websocket:" + CHAT)
    assert all(not message.get("media") for message in saved.messages if message["role"] == "user")
    assert "morning-coverage.json" in results[0].content and "STORED" in results[0].content
    assert read(native, "runtime_run")[0]["status"] == "SUCCEEDED"


def test_attachment_only_native_turn_then_actual_purpose(native):
    upload = upload_document(native)
    results, admitted = execute(native, [""], upload=upload)
    assert "待补充" in results[0].content and "用途" in results[0].content
    assert read(native, "runtime_run")[0]["status"] == "WAITING_INPUT"
    assert read(native, "runtime_run")[0]["conversation_context"]["attachment_refs"]
    results, _ = execute(native, ["查看已上传文件的元信息"])
    assert "morning-coverage.json" in results[0].content
    assert len(admitted) == 1 and len(read(native, "runtime_run")) == 2
    assert not read(native, "query") and not read(native, "authorization")


@pytest.mark.parametrize("change", ["changed", "missing"])
def test_actual_document_change_or_removal_stops_current_adoption(native, change):
    upload = upload_document(native)
    execute(native, ["查看附件"], upload=upload)
    path = Path(upload[1][0])
    if change == "changed":
        path.write_bytes((DOMAIN / "specs/conversation.schema.json").read_bytes())
    else:
        path.unlink()
    with pytest.raises(web.HTTPConflict):
        execute(native, ["继续查看附件"])
    assert len(read(native, "runtime_run")) == 1
    assert read(native, "conversation_intent")[-1]["status"] == "FAILED"


def test_sdk_side_channel_commands_create_no_conversation_intent(native):
    for command in ("/help", "/new", "/goal", "/model", "/stop", "/HELP"):
        assert native[1].admit("BOSS", CHAT, str(uuid4()), command, media_sha256=checksum([]), attached=lambda chat: True, active=lambda: True) is None
    results, admitted = execute(native, ["/help", "/new", "/stop"])
    assert len(results) == 3 and not admitted
    assert not read(native, "conversation_intent") and not read(native, "runtime_run")


def complete_query_text(native):
    with native[0].connect() as db:
        initial = native[0].get(db, "ui-check", "initial", "snapshot")
    current, previous = initial["periods"]["CURRENT"], initial["periods"]["BASE"]
    return ("查询 region-1 的全部当前产品的毛利率，查询期间" + "至".join(current)
        + "，对比期间" + "至".join(previous) + "，使用当前获准口径")


def test_current_complete_query_and_scoped_followup_change_actual_parameters(native):
    results, _ = execute(native, [complete_query_text(native), "继续只看 product-1，指标改为销售收入"])
    queries = read(native, "query")
    assert len(queries) == 2
    first, second = queries
    assert first["context_snapshot"]["product_ids"] == ["product-1", "product-2"]
    assert second["context_snapshot"]["product_ids"] == ["product-1"]
    assert second["context_snapshot"]["metric_ids"] == ["revenue"]
    assert second["parent_query_id"] == first["query_id"]
    assert second["context_snapshot"]["period_start"] == first["context_snapshot"]["period_start"]
    assert set(second["overridden_fields"]) == {"product_ids", "metric_ids"}
    for query, result, row in zip(queries, results, read(native, "runtime_run")):
        assert query["query_id"] in result.content and "来源" in result.content
        assert "{\"" not in result.content and "SIMULATED" in result.content
        assert row["tool_results"][0]["query_id"] == query["query_id"]
        assert row["tool_results"][0]["parameters_sha256"] == checksum({key: value for key, value in query["context_snapshot"].items() if key != "envelope"})
        artifact = ConversationAPI(native[0]).artifact("BOSS", {"session_id": "websocket:" + CHAT, "chat_id": CHAT,
            "run_id": row["run_id"], "kind": "query", "id": query["query_id"]})
        assert artifact["data"]["values"] == query["values"]
    assert not read(native, "authorization") and not read(native, "task")


def test_query_missing_conditions_can_be_completed_by_next_input(native):
    results, _ = execute(native, ["查询当前毛利率"])
    assert not read(native, "query") and "待补充" in results[0].content and "期间" in results[0].content
    results, _ = execute(native, [complete_query_text(native).replace("的毛利率", "").replace("查询 region-1", "补充 region-1")])
    assert len(read(native, "query")) == 1
    assert read(native, "query")[0]["context_snapshot"]["metric_ids"] == ["gross_margin"]


def test_existing_formal_query_conditions_can_be_changed_without_new_loop(native, tmp_path):
    original = query_artifact(native, tmp_path / "query-existing")
    execute(native, ["继续查询 " + original["query_id"] + "，只看 product-2，指标改为成本"])
    current = read(native, "query")[-1]
    assert current["parent_query_id"] == original["query_id"]
    assert current["context_snapshot"]["metric_ids"] == ["cost"]
    assert current["context_snapshot"]["product_ids"] == ["product-2"]
    native[0].control("ui-check", "withdraw", {"source_id": "finance-note", "version": "1"})
    with pytest.raises(web.HTTPException):
        execute(native, ["继续只看 product-1"])
    assert len(read(native, "query")) == 2


def test_followup_dates_change_formal_query_periods(native):
    execute(native, [complete_query_text(native)])
    first = read(native, "query")[0]
    scope = first["context_snapshot"]
    execute(native, ["继续查询期间改为" + scope["comparison_start"] + "至" + scope["comparison_end"]
        + "，比较期间改为" + scope["period_start"] + "至" + scope["period_end"]])
    second = read(native, "query")[1]
    assert second["parent_query_id"] == first["query_id"]
    assert second["context_snapshot"]["period_start"] == scope["comparison_start"]
    assert second["context_snapshot"]["comparison_start"] == scope["period_start"]
    assert next(item["value"] for item in second["values"] if item["period_scope"] == "CURRENT") == next(
        item["value"] for item in first["values"] if item["period_scope"] == "BASE")


def test_unuploaded_media_digest_cannot_adopt_attachment_only_input(native):
    receipt = native[1].admit("BOSS", CHAT, str(uuid4()), "", media_sha256="0" * 64,
        attached=lambda chat: True, active=lambda: True)
    request = RequestContext(channel="websocket", chat_id=CHAT, session_key="websocket:" + CHAT, sender_id="boss-1",
        original_user_text="", metadata={"webui_turn_id": receipt["turn_id"]})
    with pytest.raises(web.HTTPConflict):
        asyncio.run(native[1].native_context(request))
    assert not read(native, "runtime_run") and read(native, "conversation_intent")[0]["status"] == "FAILED"
    with pytest.raises(web.HTTPBadRequest):
        native[1].admit("BOSS", CHAT, str(uuid4()), "  ", media_sha256=checksum([]), attached=lambda chat: True, active=lambda: True)


def test_successful_upload_must_match_this_admitted_native_media_digest(native):
    upload = upload_document(native)
    receipt = native[1].admit("BOSS", CHAT, str(uuid4()), "", media_sha256="0" * 64,
        attached=lambda chat: True, active=lambda: True)
    with pytest.raises(web.HTTPConflict):
        native[1].record_media("BOSS", receipt["client_request_id"], upload[0], upload[1], active=lambda: True)
    assert native[1].attachments.sessions.read_session_snapshot("websocket:" + CHAT) is None
    assert not native[1].pending_media and not read(native, "runtime_run")
    native[1].finish(receipt["client_request_id"])


def test_model_cannot_change_bound_native_query_scope(native):
    original = native[1].provider.event_producer
    async def events(messages, tools):
        response = await original(messages, tools)
        call = response.tool_calls[0]
        call.arguments["product_ids"] = ["product-1"]
        return response
    native[1].provider.event_producer = events
    with pytest.raises(RuntimeError):
        execute(native, [complete_query_text(native)])
    assert not read(native, "query") and read(native, "runtime_run")[0]["status"] == "FAILED"


def test_source_withdrawal_after_native_query_prevents_final_result_release(native):
    original = native[1].provider.event_producer
    async def events(messages, tools):
        if any(item["role"] == "tool" for item in messages):
            native[0].control("ui-check", "withdraw", {"source_id": "finance-note", "version": "1"})
        return await original(messages, tools)
    native[1].provider.event_producer = events
    with pytest.raises(web.HTTPException):
        execute(native, [complete_query_text(native)])
    assert len(read(native, "query")) == 1 and read(native, "runtime_run")[0]["status"] == "FAILED"
    receipt = native[1].receipt("BOSS", read(native, "conversation_intent")[0]["client_request_id"], active=lambda: True)
    assert receipt["request_state"] == "FAILED" and receipt["write_performed_by_lookup"] is False


def test_unsupported_explicit_metric_or_product_waits_without_reusing_old_scope(native):
    execute(native, [complete_query_text(native)])
    results, _ = execute(native, ["继续指标改为净利润", "继续查询净利润", "继续只看 product-unknown"])
    assert all("待补充" in result.content for result in results)
    assert len(read(native, "query")) == 1
    assert [row["status"] for row in read(native, "runtime_run")] == ["SUCCEEDED", "WAITING_INPUT", "WAITING_INPUT", "WAITING_INPUT"]


def test_admission_can_be_explicitly_canceled_before_runtime(native):
    receipt = native[1].admit("BOSS", CHAT, str(uuid4()), "查看任务", media_sha256=checksum([]),
        attached=lambda chat: True, active=lambda: True)
    native[1].finish(receipt["client_request_id"], status="CANCELED")
    value = native[1].receipt("BOSS", receipt["client_request_id"], active=lambda: True)
    assert value["request_state"] == "CANCELED" and value["run_id"] is None
    assert not read(native, "runtime_run")
