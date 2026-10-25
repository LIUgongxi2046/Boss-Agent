import asyncio
from dataclasses import replace
import json
import os
from pathlib import Path
import sys
from uuid import uuid4

import pytest
from aiohttp import web
from loguru import logger
from nanobot import Nanobot
from nanobot.agent.loop import AgentLoop
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.config.schema import Config
from nanobot.providers.base import LLMResponse, ToolCallRequest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "validation"))
if os.environ.get("FC03_DOMAIN_ROOT"):
    sys.path.insert(0, str(Path(os.environ["FC03_DOMAIN_ROOT"]) / "validation"))

from business import checksum, encode
from controls import ControlStore
from boss_today import TodayAPI
from boss_runtime_records import runtime_records
from fc03_agent import Fc03Context, register_fc03_tools
from fc03_agent.runtime import Fc03RuntimeRecorder, Fc03SimulatedProvider


def prohibit_network(event, args):
    if event == "socket.connect":
        raise PermissionError("FC03检查禁止外部连接")


sys.addaudithook(prohibit_network)


@pytest.fixture
def scope(tmp_path):
    store = ControlStore(tmp_path / "morning.sqlite")
    store.initialize("ui-check")
    view = TodayAPI(store).read("BOSS")
    current = [Fc03Context("BOSS", "boss-1", "ui-check", "selection", "1", "fc03-request", "fc03-session",
        True, encode({}), view["date"], view["timezone"], view["snapshot_sha256"], view["order_version"])]
    return store, current, view


def registry(scope):
    tools = ToolRegistry()
    register_fc03_tools(tools, scope[0], lambda: scope[1][0])
    return tools


def test_only_current_approved_read_is_registered_and_preserves_actual_result(scope):
    tools = registry(scope)
    assert tools.tool_names == ["todayRead"]
    assert json.loads(asyncio.run(tools.get("todayRead").execute())) == scope[2]
    with scope[0].connect() as db:
        assert db.execute("SELECT count(*) FROM objects WHERE kind IN ('authorization','today_order','task','outbox')").fetchone()[0] == 0


@pytest.mark.parametrize("field,value", [("role", "MAINTAINER"), ("active", False), ("owner_id", "other"),
    ("namespace", "other"), ("dataset_version", "2"), ("date", "2026-10-01"), ("snapshot_sha256", "0" * 64)])
def test_current_identity_date_or_snapshot_mismatch_rejects(scope, field, value):
    scope[1][0] = replace(scope[1][0], **{field: value})
    with pytest.raises(web.HTTPException):
        asyncio.run(registry(scope).get("todayRead").execute())


@pytest.mark.parametrize("params", [{"confirmed": True}, {"owner_id": "other"}, {"date": "2026-10-01"}])
def test_model_cannot_inject_scope_or_owner_decision(scope, params):
    with pytest.raises(web.HTTPBadRequest):
        asyncio.run(registry(scope).get("todayRead").execute(**params))


def test_owner_order_change_requires_new_current_read_binding(scope):
    view = scope[2]
    TodayAPI(scope[0]).reorder("BOSS", {"client_request_id": "fc03-owner-order", "expected_version": view["order_version"],
        "snapshot_sha256": view["snapshot_sha256"], "item_ids": [item["item_id"] for item in reversed(view["items"])]})
    with pytest.raises(web.HTTPConflict):
        asyncio.run(registry(scope).get("todayRead").execute())


def test_registry_duplicates_are_rejected_before_mutation(scope):
    tools = registry(scope)
    with pytest.raises(web.HTTPConflict):
        register_fc03_tools(tools, scope[0], lambda: scope[1][0])
    assert tools.tool_names == ["todayRead"]


def test_model_runtime_requires_matching_server_request(scope):
    from nanobot.agent.tools.context import RequestContext, request_context
    request = RequestContext(channel="cli", chat_id="other", session_key="other", sender_id="boss-1")
    with request_context(request), pytest.raises(web.HTTPForbidden):
        asyncio.run(registry(scope).get("todayRead").execute())


def run(scope, tmp_path, producer, *, formal=False, question="今天有哪些事情需要我处理"):
    store, current, _ = scope
    logger.remove()
    logger.add(sys.stderr, level="WARNING", diagnose=False, backtrace=False)
    config = Config.model_validate({"agents": {"defaults": {"provider": "deepseek", "model": "deepseek-flash",
        "workspace": str(tmp_path / "workspace"), "maxToolIterations": 12, "maxTokens": 700,
        "maxToolResultChars": 200000, "dream": {"enabled": False}, "idleCompactAfterMinutes": 0}}})
    tools = ToolRegistry()
    snapshot = {"provider": "deepseek", "model_id": "deepseek-flash", "api_type": "chat_completions",
        "max_tool_rounds": 12, "max_output_tokens": 700, "timeout": 120, "config_sha256": checksum(config.model_dump(mode="json"))}
    recorder = Fc03RuntimeRecorder(store, "ui-check", tools, lambda: snapshot, lambda: current[0])
    from fc03_agent import TOOLS
    if formal:
        from fc03_agent.formal import FORMAL_TOOLS
        approved = FORMAL_TOOLS
    else:
        approved = TOOLS
    provider = Fc03SimulatedProvider(producer, allowed_tools=approved)
    provider.generation = config.resolve_preset().to_generation_settings()
    loop = AgentLoop.from_config(config, tool_registry=tools, provider=provider, hook_factories=[recorder.hook_factory])
    for name in list(tools.tool_names):
        tools.unregister(name)
    register_fc03_tools(tools, store, lambda: current[0], formal=formal)
    with store.connect() as db:
        configuration = store.get(db, "ui-check", "configuration", "current")
        configuration["tool_scope"] = sorted(approved)
        store.put(db, "ui-check", "configuration", "current", configuration)
    async def execute():
        async with Nanobot(loop, config=config) as bot:
            bot.runtime.add_context_provider(recorder.context)
            async def authenticated_request(request):
                binding = request.attributes["boss_runtime_binding"]
                current[0] = replace(current[0], request_id=binding.request_id, session_id=binding.session_id)
            bot.runtime.add_context_provider(authenticated_request)
            return await bot.run(question, session_key=current[0].session_id, sender_id="boss-1")
    return asyncio.run(execute())


def test_actual_runtime_consumes_today_result_and_persists_safe_versions(scope, tmp_path):
    async def producer(messages, tools):
        outputs = [json.loads(item["content"]) for item in messages if item["role"] == "tool"]
        if not outputs:
            return LLMResponse(content=None, tool_calls=[ToolCallRequest(id=str(uuid4()), name="todayRead", arguments={})])
        return LLMResponse(content=encode({"source_type": "SIMULATED", "items": outputs[-1]["items"],
            "missing_sources": outputs[-1]["missing_sources"]}))
    result = run(scope, tmp_path, producer)
    assert not result.error and json.loads(result.content)["items"] == scope[2]["items"]
    row = runtime_records(ControlStore(scope[0].path), "MAINTAINER")["runs"][0]
    assert row["feature_id"] == "FC03" and row["status"] == "SUCCEEDED"
    assert row["tool_results"][0]["snapshot_sha256"] == scope[2]["snapshot_sha256"]
    assert row["usage"] is row["cost_total"] is None
    for item in scope[2]["items"]:
        assert item["title"] not in json.dumps(row, ensure_ascii=False)
    assert "今天有哪些事情需要我处理" not in json.dumps(row, ensure_ascii=False)


@pytest.mark.parametrize("failure,status", [("failed", "FAILED"), ("cancel", "CANCELED"), ("timeout", "TIMED_OUT")])
def test_terminal_keeps_actual_read_reference(scope, tmp_path, failure, status):
    async def producer(messages, tools):
        if not any(item["role"] == "tool" for item in messages):
            return LLMResponse(content=None, tool_calls=[ToolCallRequest(id=str(uuid4()), name="todayRead", arguments={})])
        if failure == "cancel":
            raise asyncio.CancelledError()
        if failure == "timeout":
            raise TimeoutError("明确模拟的模型超时")
        return LLMResponse(content="明确模拟的模型失败", finish_reason="error", error_kind="unknown")
    if failure in {"cancel", "timeout"}:
        with pytest.raises(asyncio.CancelledError if failure == "cancel" else TimeoutError):
            run(scope, tmp_path, producer)
    else:
        run(scope, tmp_path, producer)
    row = runtime_records(ControlStore(scope[0].path), "MAINTAINER")["runs"][0]
    assert row["status"] == status and row["finished_at"]
    assert row["tool_results"][0]["snapshot_sha256"] == scope[2]["snapshot_sha256"]
    assert row["usage"] is row["cost_total"] is None


def test_revocation_stops_followup_and_preserves_first_read_reference(scope, tmp_path):
    async def producer(messages, tools):
        if any(item["role"] == "tool" for item in messages):
            scope[1][0] = replace(scope[1][0], active=False)
        return LLMResponse(content=None, tool_calls=[ToolCallRequest(id=str(uuid4()), name="todayRead", arguments={})])
    with pytest.raises(RuntimeError, match="晨间读取工具执行失败"):
        run(scope, tmp_path, producer)
    row = runtime_records(ControlStore(scope[0].path), "MAINTAINER")["runs"][0]
    assert row["status"] == "FAILED" and len(row["tool_results"]) == 1
    assert row["tool_errors"][0]["error_type"] == "HTTPForbidden"
