import asyncio
from dataclasses import replace
import json
import os
from pathlib import Path
import sys
from urllib.parse import urlencode
from uuid import uuid4

import pytest
from aiohttp import web
from loguru import logger
from nanobot import Nanobot
from nanobot.agent.loop import AgentLoop
from nanobot.agent.tools.context import current_request_context
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.config.schema import Config
from nanobot.providers.base import LLMResponse, ToolCallRequest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "validation"))
sys.path.insert(0, str(Path(os.environ["CONVERSATION_DOMAIN_ROOT"]) / "validation"))

from business import checksum, encode
from controls import ControlStore
from boss_page_api import BossPageAPI
from boss_runtime_records import runtime_records
from runtime_page_read_tools import BossEvidenceReadTool
from conversation_agent import ConversationContext, ConversationScope, register_conversation_reads
from conversation_agent.runtime import ConversationRuntimeRecorder, ConversationSimulatedProvider


def prohibit_network(event, args):
    if event == "socket.connect":
        raise PermissionError("一般会话检查禁止外部连接")


sys.addaudithook(prohibit_network)


@pytest.fixture
def conversation(tmp_path):
    logger.remove()
    logger.add(sys.stderr, level="WARNING", diagnose=False, backtrace=False)
    store = ControlStore(tmp_path / "conversation.sqlite")
    store.initialize("ui-check")
    api = BossPageAPI(store)
    with store.connect() as db:
        documents = [json.loads(row[0]) for row in db.execute("SELECT body FROM objects WHERE namespace='ui-check' AND kind='document'")]
    sources = []
    for document in documents:
        code, result = api.serve("BOSS", "/api/boss/ui/evidence", urlencode({"source": document["source_id"]}))
        if code == 200:
            sources.append(result)
    assert len(sources) >= 2
    sources = sources[:2]
    state = {"active": True, "contexts": {}, "params": {}, "requests": []}
    def context_provider(request):
        return replace(state["contexts"][request.turn_id], active=state["active"])
    def validate(context):
        for kind, identifier, version in context.references:
            code, value = api.serve("BOSS", "/api/boss/ui/evidence", urlencode({"source": identifier}))
            require_current = code == 200 and value["version"] == version
            if not require_current:
                return False
        return True
    scope = ConversationScope(store, context_provider, validate)
    return store, api, scope, state, sources


def execute(conversation, tmp_path, questions, *, event_producer=None, before_context=None, repeat_context=False):
    store, api, scope, state, sources = conversation
    config = Config.model_validate({"agents": {"defaults": {"workspace": str(tmp_path / "workspace"),
        "provider": "deepseek", "model": "deepseek-flash", "maxToolIterations": 12, "maxTokens": 700,
        "maxToolResultChars": 200000, "dream": {"enabled": False}, "idleCompactAfterMinutes": 0}}})
    async def actual_source_events(messages, tools):
        request = current_request_context()
        last_user = max(index for index, item in enumerate(messages) if item["role"] == "user")
        outputs = [json.loads(item["content"]) for item in messages[last_user + 1:] if item["role"] == "tool"]
        if not outputs:
            return LLMResponse(content=None, tool_calls=[ToolCallRequest(id=str(uuid4()), name="bossEvidenceRead",
                arguments=state["params"][request.turn_id])])
        return LLMResponse(content=encode(outputs[-1]))
    registry = ToolRegistry()
    snapshot = {"provider": "deepseek", "model_id": "deepseek-flash", "api_type": "chat_completions",
        "max_tool_rounds": 12, "max_output_tokens": 700, "timeout": 120, "config_sha256": checksum(config.model_dump(mode="json"))}
    recorder = ConversationRuntimeRecorder(scope, registry, lambda: snapshot)
    provider = ConversationSimulatedProvider(event_producer or actual_source_events, scope)
    provider.generation = config.resolve_preset().to_generation_settings()
    loop = AgentLoop.from_config(config, provider=provider, tool_registry=registry, hook_factories=[recorder.hook_factory])
    for name in list(registry.tool_names):
        registry.unregister(name)
    register_conversation_reads(registry, [BossEvidenceReadTool(api, "BOSS")], scope)
    with store.connect() as db:
        configuration = store.get(db, "ui-check", "configuration", "current")
        configuration["tool_scope"] = registry.tool_names
        store.put(db, "ui-check", "configuration", "current", configuration)
    async def run():
        async with Nanobot(loop, config=config) as bot:
            async def authenticated_input(request):
                source = next(source for source in sources if source["source_id"] in request.original_user_text)
                params = {"source": source["source_id"]}
                state["params"][request.turn_id] = params
                state["contexts"][request.turn_id] = ConversationContext("BOSS", "boss-1", "ui-check", "selection", "1",
                    request.turn_id, request.session_key, request.chat_id, request.turn_id, True, checksum(request.original_user_text),
                    frozenset({"bossEvidenceRead"}), frozenset({("bossEvidenceRead", checksum(params))}),
                    tuple(("document", item["source_id"], item["version"]) for item in sources))
                state["requests"].append(request)
                if before_context is not None:
                    before_context(request)
            for context in (authenticated_input, recorder.context):
                bot.runtime.add_context_provider(context)
            if repeat_context:
                bot.runtime.add_context_provider(recorder.context)
            return [await bot.run(question, sender_id="boss-1", channel="websocket", chat_id="n02-current",
                session_key="websocket:n02-current") for question in questions]
    return asyncio.run(run()), loop


def test_actual_questions_change_actual_tool_parameters_and_preserve_versions(conversation, tmp_path):
    sources = conversation[4]
    questions = ["请读取资料 " + sources[0]["source_id"], "继续查看资料 " + sources[1]["source_id"] + " 的当前版本"]
    results, loop = execute(conversation, tmp_path, questions)
    assert [json.loads(result.content)["source_id"] for result in results] == [source["source_id"] for source in sources]
    runs = runtime_records(conversation[0], "MAINTAINER")["runs"]
    assert len(runs) == 2 and {row["session_id"] for row in runs} == {"websocket:n02-current"}
    assert all(row["status"] == "SUCCEEDED" and row["feature_id"] == "N02" for row in runs)
    for source in sources:
        row = next(row for row in runs if row["tool_results"][0]["source_id"] == source["source_id"])
        reference = row["tool_results"][0]
        assert reference["version"] == source["version"]
        assert reference["parameters_sha256"] == checksum({"source": source["source_id"]})
        actual = next(json.loads(result.content) for result in results if json.loads(result.content)["source_id"] == source["source_id"])
        assert reference["result_sha256"] == checksum(actual)
        assert source["content"] not in json.dumps(row, ensure_ascii=False)
        assert row["usage"] is row["cost_total"] is None
    assert all(question not in json.dumps(runs, ensure_ascii=False) for question in questions)
    history = json.dumps(loop.sessions.get_or_create("websocket:n02-current").messages, ensure_ascii=False)
    assert all(question in history for question in questions)
    with conversation[0].connect() as db:
        assert db.execute("SELECT count(*) FROM objects WHERE kind IN ('authorization','message_outbox','task')").fetchone()[0] == 0


@pytest.mark.parametrize("field,value", [("role", "MAINTAINER"), ("owner_id", "other"), ("dataset_version", "2"),
    ("session_id", "websocket:other"), ("input_sha256", "0" * 64)])
def test_forged_scope_is_rejected_before_model(conversation, tmp_path, field, value):
    def change(request):
        conversation[3]["contexts"][request.turn_id] = replace(conversation[3]["contexts"][request.turn_id], **{field: value})
    with pytest.raises(web.HTTPForbidden):
        execute(conversation, tmp_path, ["读取 " + conversation[4][0]["source_id"]], before_context=change)
    assert not runtime_records(conversation[0], "MAINTAINER")["runs"]


def test_model_cannot_change_current_source_parameters(conversation, tmp_path):
    async def events(messages, tools):
        return LLMResponse(content=None, tool_calls=[ToolCallRequest(id=str(uuid4()), name="bossEvidenceRead",
            arguments={"source": conversation[4][1]["source_id"]})])
    with pytest.raises(RuntimeError):
        execute(conversation, tmp_path, ["读取 " + conversation[4][0]["source_id"]], event_producer=events)
    row = runtime_records(conversation[0], "MAINTAINER")["runs"][0]
    assert row["status"] == "FAILED" and not row["tool_results"]


def test_source_withdrawal_stops_next_model_step(conversation, tmp_path):
    source = conversation[4][0]
    async def events(messages, tools):
        conversation[0].control("ui-check", "withdraw", {"source_id": source["source_id"], "version": source["version"]})
        return LLMResponse(content="SIMULATED")
    with pytest.raises(web.HTTPConflict):
        execute(conversation, tmp_path, ["读取 " + source["source_id"]], event_producer=events)
    row = runtime_records(conversation[0], "MAINTAINER")["runs"][0]
    assert row["status"] == "FAILED" and not row["tool_results"]


def test_identity_revocation_during_model_step_stops_result_release(conversation, tmp_path):
    async def events(messages, tools):
        conversation[3]["active"] = False
        return LLMResponse(content="SIMULATED")
    with pytest.raises(web.HTTPForbidden):
        execute(conversation, tmp_path, ["读取 " + conversation[4][0]["source_id"]], event_producer=events)
    row = runtime_records(conversation[0], "MAINTAINER")["runs"][0]
    assert row["status"] == "FAILED" and not row["tool_results"]


def test_repeated_actual_context_keeps_one_original_runtime(conversation, tmp_path):
    execute(conversation, tmp_path, ["读取 " + conversation[4][0]["source_id"]], repeat_context=True)
    rows = runtime_records(ControlStore(conversation[0].path), "MAINTAINER")["runs"]
    assert len(rows) == 1 and rows[0]["request_id"] == conversation[3]["requests"][0].turn_id


@pytest.mark.parametrize("failure,status", [("cancel", "CANCELED"), ("timeout", "TIMED_OUT")])
def test_actual_terminal_and_original_runtime_survive_reopen(conversation, tmp_path, failure, status):
    async def events(messages, tools):
        if failure == "cancel":
            raise asyncio.CancelledError()
        raise TimeoutError("明确模拟的会话模型超时")
    with pytest.raises(asyncio.CancelledError if failure == "cancel" else TimeoutError):
        execute(conversation, tmp_path, ["读取 " + conversation[4][0]["source_id"]], event_producer=events)
    row = runtime_records(ControlStore(conversation[0].path), "MAINTAINER")["runs"][0]
    assert row["status"] == status and row["usage"] is row["cost_total"] is None
