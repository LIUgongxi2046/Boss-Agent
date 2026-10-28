import asyncio
from dataclasses import replace
import inspect
import json
import os
import subprocess
from pathlib import Path
import sys

import pytest
from aiohttp import web
from loguru import logger
from nanobot import Nanobot
from nanobot.agent.hook import AgentHook
from nanobot.agent.loop import AgentLoop
from nanobot.agent.tools.context import RequestContext
from nanobot.config.schema import Config
from nanobot.providers.base import LLMResponse
from nanobot.session.manager import SessionManager

ROOT = Path(__file__).resolve().parents[3]
DOMAIN = Path(os.environ["FC03_NATIVE_DOMAIN_ROOT"])
sys.path.insert(0, str(DOMAIN / "validation"))
sys.path.insert(0, str(ROOT / "validation/fc03_agent"))

from native import NativeMorningAdapter
from business import checksum
from boss_conversation import ConversationAPI
from controls import ControlStore
from fc03_agent.formal import FormalMorningTool, FORMAL_TOOLS
from fc03_agent.runtime import Fc03SimulatedProvider
from product_bi import FeatureProvider, FeatureRecorder, FeatureToolRegistry, ProductBI
from product_fc01 import ProductFc01
from product_morning import ProductMorning


def prohibit_network(event, args):
    if event == "socket.connect":
        raise PermissionError("原生晨间检查禁止外部连接")


sys.addaudithook(prohibit_network)
CHAT = "morning-native-discussion"
DAY = {"date": "2026-10-24", "timezone": "Asia/Shanghai"}


@pytest.fixture
def native(tmp_path):
    assert Path(inspect.getfile(NativeMorningAdapter)).resolve() == ROOT / "validation/fc03_agent/native.py"
    logger.remove()
    logger.add(sys.stderr, level="WARNING", diagnose=False, backtrace=False)
    store = ControlStore(tmp_path / "native.sqlite")
    store.initialize("ui-check")
    service = ProductMorning(store)
    adapter = NativeMorningAdapter(service)
    config = Config.model_validate({"agents": {"defaults": {"provider": "deepseek", "model": "deepseek-flash",
        "workspace": str(tmp_path / "workspace"), "maxToolIterations": 12, "maxTokens": 700,
        "maxToolResultChars": 200000, "dream": {"enabled": False}, "idleCompactAfterMinutes": 0}}})
    snapshot = {"provider": "deepseek", "model_id": "deepseek-flash", "api_type": "chat_completions",
        "max_tool_rounds": 12, "max_output_tokens": 700, "timeout": 120, "config_sha256": checksum(config.model_dump(mode="json"))}
    registry = FeatureToolRegistry()
    provider = FeatureProvider(ProductFc01(store), ProductBI(store), service)
    provider.generation = config.resolve_preset().to_generation_settings()
    recorder = FeatureRecorder(store, registry, lambda: snapshot, ProductBI(store), service)
    sessions = SessionManager(tmp_path / "workspace", sessions_root=tmp_path / "sessions")
    loop = AgentLoop.from_config(config, provider=provider, tool_registry=registry, session_manager=sessions,
        hook_factories=[recorder.hook_factory, adapter.hook_factory])
    adapter.bind_sessions(loop.sessions)
    for name in list(registry.tool_names):
        registry.unregister(name)
    for name in sorted(FORMAL_TOOLS):
        registry.register(FormalMorningTool(store, service.context_provider, name))
    with store.connect() as db:
        state = store.get(db, "ui-check", "configuration", "current")
        state["tool_scope"] = sorted(FORMAL_TOOLS)
        store.put(db, "ui-check", "configuration", "current", state)
    return store, service, adapter, loop, config, recorder


def bind(native, **selection):
    return native[2].bind("BOSS", "native-binding-original", {"chat_id": CHAT, **DAY, **selection},
        attached=lambda chat: chat == CHAT, active=lambda: True)


def request(turn="native-turn-original", content="继续讨论当前事项"):
    return RequestContext(channel="websocket", chat_id=CHAT, session_key="websocket:" + CHAT,
        sender_id="boss-1", original_user_text=content, metadata={"webui_turn_id": turn})


def rows(native, kind):
    with native[0].connect() as db:
        return [json.loads(row[0]) for row in db.execute("SELECT body FROM objects WHERE kind=?", (kind,))]


def run_turns(native, questions, *, before_context=None, hooks=None):
    store, service, adapter, loop, config, recorder = native
    admitted = []
    async def execute():
        async with Nanobot(loop, config=config) as bot:
            async def transport(current):
                current.metadata["webui_turn_id"] = current.turn_id
                receipt = adapter.admit("BOSS", current.chat_id, current.turn_id, current.original_user_text,
                    attached=lambda chat: chat == CHAT, active=lambda: True)
                assert receipt["enqueue"]
                admitted.append(receipt)
                if before_context is not None:
                    before_context(current)
            for context in (transport, adapter.native_context, recorder.context):
                bot.runtime.add_context_provider(context)
            return [await bot.run(question, session_key="websocket:" + CHAT, channel="websocket", chat_id=CHAT,
                sender_id="boss-1", hooks=hooks) for question in questions]
    return asyncio.run(execute()), admitted


def test_actual_native_sdk_keeps_two_inputs_one_session_and_one_list(native):
    bind(native)
    questions = ["今天有哪些事情需要本人处理", "继续讨论当前清单，说明需要处理的事项"]
    results, admitted = run_turns(native, questions)
    assert all(not result.error and "当前模拟资料" in result.content for result in results)
    runs = rows(native, "runtime_run")
    assert len(runs) == 2 and {row["session_id"] for row in runs} == {"websocket:" + CHAT}
    assert len({row["run_id"] for row in runs}) == 2
    assert {row["feature_id"] for row in runs} == {"FC03"}
    assert len(rows(native, "morning_list")) == 1
    receipt = native[2].binding_receipt("BOSS", "native-binding-original", active=lambda: True)
    assert receipt["result"]["list_id"] is not None and receipt["result"]["item_id"] is None
    subprocess.run(["node", str(ROOT / "app/tests/helpers/validate_morning_binding.mjs")],
                   input=json.dumps(receipt), text=True, check=True, capture_output=True)
    assert [len(row["tool_results"]) for row in runs] == [4, 3]
    session = native[3].sessions.get_or_create("websocket:" + CHAT)
    text = json.dumps(session.messages, ensure_ascii=False)
    assert all(question in text for question in questions)
    assert all(question not in json.dumps(runs, ensure_ascii=False) for question in questions)
    assert all(row["usage"] is row["cost_total"] is None for row in runs)
    assert len(rows(native, "authorization")) == len(rows(native, "outbox")) == 0
    assert not native[2].proofs
    original = admitted[0]
    duplicate = native[2].admit("BOSS", CHAT, original["turn_id"], questions[0], attached=lambda chat: True, active=lambda: True)
    assert duplicate["enqueue"] is False and duplicate["run_id"] == runs[0]["run_id"]
    with pytest.raises(web.HTTPConflict):
        native[2].admit("BOSS", CHAT, original["turn_id"], "修改原问题", attached=lambda chat: True, active=lambda: True)
    assert len(rows(native, "runtime_run")) == 2


def select_knowledge(native):
    sessions = native[3].sessions
    sessions.save(sessions.get_or_create("websocket:" + CHAT))
    service = native[2].source_selection
    catalogue = service.listing("BOSS", {"chat_id": CHAT, "query": ""})
    source_refs = [{"source_id": source["source_id"], "version": source["version"]} for source in catalogue["sources"]
        if source["source_id"] in {"finance-note", "meeting-minutes"}]
    assert len(source_refs) == 2
    result = service.bind("BOSS", {"chat_id": CHAT, "client_request_id": "morning-knowledge-selection",
        "execution_namespace": catalogue["execution_namespace"], "dataset_version": catalogue["dataset_version"],
        "expected_context_version": catalogue["context_version"], "expected_catalogue_version": catalogue["catalogue_version"],
        "source_refs": source_refs}, active=lambda: True)
    assert result["outcome"] == "RECORDED"
    return source_refs


def test_native_morning_reads_selected_knowledge_and_records_versions(native):
    bind(native)
    refs = select_knowledge(native)
    results, _ = run_turns(native, ["结合选择的知识资料讨论今天的事项"])
    assert "相关材料" in results[0].content
    with native[0].connect() as db:
        assert all(native[0].get(db, "ui-check", "document", ref["source_id"])["content"] in results[0].content for ref in refs)
    row = rows(native, "runtime_run")[0]
    assert row["status"] == "SUCCEEDED" and row["morning_context"]["source_selection"]["source_refs"] == refs
    documents = [step["document_ref"] for step in row["tool_results"] if "document_ref" in step]
    assert all(ref in documents for ref in refs)
    projected = ConversationAPI(native[0]).read("BOSS", {"chat_id": CHAT, "session_id": "websocket:" + CHAT})["runs"][0]
    for source in refs:
        reference = next(ref for ref in projected["context_references"] if ref["id"] == source["source_id"])
        assert reference["recorded_version"] == source["version"] and reference["adoption_state"] == "CURRENT"
        assert {support["origin"] for support in reference["support"]} == {"SOURCE_SELECTION", "TOOL_RESULT"}
    assert not rows(native, "authorization") and not rows(native, "outbox")


@pytest.mark.parametrize("stage", ["TOOL", "ANSWER"])
def test_native_morning_stops_when_selected_knowledge_is_withdrawn(native, stage):
    bind(native)
    select_knowledge(native)
    class WithdrawKnowledge(AgentHook):
        def __init__(self):
            super().__init__(reraise=True)
            self.executed = False

        async def after_execute_tool(self, context, tool_call, tool, params, result):
            if self.executed or stage != "TOOL":
                return
            self.executed = True
            assert not native[2].source_selection.listing("BOSS", {"chat_id": CHAT, "query": ""})["can_bind"]
            native[0].control("ui-check", "withdraw", {"source_id": "finance-note", "version": "1"})

        async def after_iteration(self, context):
            if stage == "ANSWER" and not context.tool_calls and context.response is not None and context.response.content:
                self.executed = True
                native[0].control("ui-check", "withdraw", {"source_id": "finance-note", "version": "1"})
    hook = WithdrawKnowledge()
    with pytest.raises(web.HTTPException):
        run_turns(native, ["结合选择的知识资料讨论今天的事项"], hooks=[hook])
    assert hook.executed and rows(native, "runtime_run")[0]["status"] == "FAILED"
    assert len(rows(native, "runtime_run")[0]["tool_results"]) == (1 if stage == "TOOL" else 5)


def test_selected_native_sdk_consumes_exact_item(native):
    view = native[1].api.query("BOSS", {**DAY, "client_request_id": "selected-list-original", "session_id": "owner-selection"})
    item = view["items"][-1]
    bind(native, list_id=view["list_id"], item_id=item["item_id"])
    results, _ = run_turns(native, ["讨论所选择的当前事项"])
    assert item["title"] in results[0].content
    row = rows(native, "runtime_run")[0]
    assert row["morning_context"]["selected_item_ref"]["item_id"] == item["item_id"]
    assert {reference["list_id"] for reference in row["tool_results"]} == {view["list_id"]}
    assert len(rows(native, "morning_list")) == 1


def test_selected_todo_titles_limit_discussion_and_offer_processing_actions(native):
    view = native[1].api.query("BOSS", {**DAY, "client_request_id": "batch-selection-current", "session_id": "owner-selection"})
    chosen = view["items"][:1]
    assert len(chosen) == 1 and len(view["items"]) > 1
    bind(native)
    question = "请协助处理以下事项，说明当前问题、建议和需要我确认的操作：\n" + "\n".join(item["title"] + "：" + item["reason"] for item in chosen)
    results, _ = run_turns(native, [question])
    answer = results[0].content
    assert not results[0].error and all("### " + item["title"] in answer for item in chosen)
    assert all("### " + item["title"] not in answer for item in view["items"][1:])
    assert "确认具体处理操作" in answer and "SIMULATED" not in answer
    assert rows(native, "runtime_run")[0]["status"] == "SUCCEEDED"


@pytest.mark.parametrize("fields", [{"owner_id": "other"}, {"session_id": "sdk:forged"}, {"confirmed": True},
    {"list_id": "unknown-list"}, {"item_id": "unknown-item"}, {"date": "invalid"}, {"timezone": "invalid-zone"}])
def test_bind_rejects_client_scope_or_invalid_input(native, fields):
    with pytest.raises(web.HTTPException):
        bind(native, **fields)
    assert not rows(native, "morning_native_binding")


@pytest.mark.parametrize("role,attached,active", [("MAINTAINER", True, True), ("BOSS", False, True), ("BOSS", True, False)])
def test_binding_requires_current_identity_and_connection(native, role, attached, active):
    with pytest.raises(web.HTTPException):
        native[2].bind(role, "native-binding-original", {"chat_id": CHAT, **DAY},
            attached=lambda chat: attached, active=lambda: active)
    assert not rows(native, "morning_native_binding")


def test_binding_receipt_is_read_only_after_reopen_and_missing_proof_rejects(native):
    receipt = bind(native)
    assert bind(native) == receipt
    reopened = NativeMorningAdapter(ProductMorning(ControlStore(native[0].path)))
    assert reopened.binding_receipt("BOSS", "native-binding-original", active=lambda: True) == receipt
    unknown = reopened.binding_receipt("BOSS", "native-binding-unknown", active=lambda: True)
    assert unknown["outcome"] == "NOT_FOUND_IN_CURRENT_STORE" and unknown["write_performed_by_lookup"] is False
    with pytest.raises(web.HTTPForbidden):
        asyncio.run(reopened.native_context(request()))
    assert not rows(native, "runtime_run") and not rows(native, "morning_public_request")


@pytest.mark.parametrize("fields", [{"sender_id": "maintainer-1"}, {"channel": "cli"}, {"session_key": "websocket:other"}])
def test_context_rejects_forged_identity_or_route(native, fields):
    bind(native)
    current = request()
    native[2].admit("BOSS", CHAT, current.metadata["webui_turn_id"], current.original_user_text,
        attached=lambda chat: True, active=lambda: True)
    with pytest.raises(web.HTTPForbidden):
        asyncio.run(native[2].native_context(replace(current, **fields)))
    assert not rows(native, "runtime_run")
    native[2].finish(native[2].turn_key(CHAT, current.metadata["webui_turn_id"]))


def test_unbound_native_message_keeps_existing_admission(native):
    assert native[2].admit("BOSS", "ordinary-chat", None, "继续讨论" * 1500,
        attached=None, active=None) is None
    current = RequestContext(channel="websocket", chat_id="ordinary-chat", session_key="websocket:ordinary-chat",
        sender_id="boss-1", original_user_text="普通会话")
    assert asyncio.run(native[2].native_context(current)) is None and not current.attributes


def test_admitted_turn_rejects_changed_input_and_concurrent_message(native):
    bind(native)
    current = request()
    native[2].admit("BOSS", CHAT, current.metadata["webui_turn_id"], current.original_user_text,
        attached=lambda chat: True, active=lambda: True)
    with pytest.raises(web.HTTPConflict):
        native[2].admit("BOSS", CHAT, "concurrent-new-turn", "另外一个问题", attached=lambda chat: True, active=lambda: True)
    current = RequestContext(channel="websocket", chat_id=CHAT, session_key="websocket:" + CHAT,
        sender_id="boss-1", original_user_text="改变已提交原文", metadata=current.metadata)
    with pytest.raises(web.HTTPForbidden):
        asyncio.run(native[2].native_context(current))
    assert not native[2].proofs and not rows(native, "runtime_run")
    assert rows(native, "morning_public_request")[0]["status"] == "FAILED"


def test_admitted_input_and_current_connection_are_checked(native):
    bind(native)
    state = {"active": True}
    current = request()
    native[2].admit("BOSS", CHAT, current.metadata["webui_turn_id"], current.original_user_text,
        attached=lambda chat: True, active=lambda: state["active"])
    state["active"] = False
    with pytest.raises(web.HTTPUnauthorized):
        asyncio.run(native[2].native_context(current))
    assert not current.attributes and not native[2].proofs
    assert rows(native, "morning_public_request")[0]["status"] == "FAILED"


def test_changed_source_stops_before_model_and_keeps_original_receipt(native):
    view = native[1].api.query("BOSS", {**DAY, "client_request_id": "source-list-original", "session_id": "owner-selection"})
    item = next(item for item in view["items"] if any(ref["kind"] == "document" for ref in item["source_refs"]))
    source = next(ref for ref in item["source_refs"] if ref["kind"] == "document")
    bind(native, list_id=view["list_id"], item_id=item["item_id"])
    def withdraw(current):
        native[0].control("ui-check", "withdraw", {"source_id": source["id"], "version": source["version"]})
    with pytest.raises(web.HTTPException):
        run_turns(native, ["继续核查当前依据"], before_context=withdraw)
    assert not rows(native, "runtime_run") and not native[2].proofs
    row = rows(native, "morning_public_request")[0]
    receipt = native[1].receipt("BOSS", row["request_id"])
    assert receipt["request_state"] == "FAILED" and receipt["receipt"]["result"]["list_id"] == view["list_id"]


def test_source_withdrawal_between_actual_model_steps_stops_adoption(native):
    bind(native)
    async def events(messages, tools):
        outputs = [json.loads(message["content"]) for message in messages if message["role"] == "tool"]
        if outputs:
            source = next(source for source in outputs[0]["source_statuses"] if source["status"] == "VALID")
            native[0].control("ui-check", "withdraw", {"source_id": source["source_id"], "version": source["version"]})
        return await native[1].events(messages, tools)
    native[1].provider = Fc03SimulatedProvider(events, allowed_tools=FORMAL_TOOLS)
    with pytest.raises(web.HTTPException):
        run_turns(native, ["核查今日资料与来源"])
    row = rows(native, "runtime_run")[0]
    assert row["status"] == "FAILED" and len(row["tool_results"]) == 1
    assert len(rows(native, "morning_list")) == 1 and not native[2].proofs


@pytest.mark.parametrize("failure,status", [("error", "FAILED"), ("cancel", "CANCELED"), ("timeout", "TIMED_OUT")])
def test_native_terminal_preserves_real_list_and_clears_proof(native, failure, status):
    bind(native)
    async def events(messages, tools):
        if not any(message["role"] == "tool" for message in messages):
            return await native[1].events(messages, tools)
        if failure == "cancel":
            raise asyncio.CancelledError()
        if failure == "timeout":
            raise TimeoutError("明确模拟的晨间服务超时")
        return LLMResponse(content="明确模拟的晨间模型失败", finish_reason="error", error_kind="unknown")
    native[1].provider = Fc03SimulatedProvider(events, allowed_tools=FORMAL_TOOLS)
    if failure == "error":
        run_turns(native, ["查询今日工作"])
    else:
        with pytest.raises(asyncio.CancelledError if failure == "cancel" else TimeoutError):
            run_turns(native, ["查询今日工作"])
    assert rows(native, "runtime_run")[0]["status"] == status
    assert len(rows(native, "morning_list")) == 1 and not native[2].proofs
    original = rows(native, "morning_public_request")[0]
    assert native[1].receipt("BOSS", original["request_id"])["receipt"]["outcome"] == "RECORDED"
