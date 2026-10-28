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
from nanobot.session.manager import SessionManager

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "validation"))
if os.environ.get("FC04_DOMAIN_ROOT"):
    sys.path.insert(0, str(Path(os.environ["FC04_DOMAIN_ROOT"]) / "validation"))

from business import checksum, encode
from controls import ControlStore
from boss_workspace_api import BossWorkspaceAPI
from boss_runtime_records import runtime_records
from fc04_agent import Fc04Context, notifications_digest, register_fc04_tools
from fc04_agent.runtime import Fc04RuntimeRecorder, Fc04SimulatedProvider


def no_network(event, args):
    if event == "socket.connect":
        raise PermissionError("FC04检查禁止外部连接")


sys.addaudithook(no_network)


@pytest.fixture
def scope(tmp_path):
    store = ControlStore(tmp_path / "notifications.sqlite")
    store.initialize("ui-check")
    store.control("ui-check", "rules", {"version": "1", "cooldown_seconds": 1800, "quiet_start": 22,
        "quiet_end": 7, "timezone": "Asia/Shanghai", "important_escalation": True})
    status, view = BossWorkspaceAPI(store).serve("BOSS", "/api/boss/ui/workspace/notifications")
    assert status == 200
    current = [Fc04Context("BOSS", "boss-1", "ui-check", "selection", "1", "fc04-request", "fc04-session",
                          True, notifications_digest(view))]
    return store, current, view


def call(scope, params):
    tools = ToolRegistry()
    register_fc04_tools(tools, scope[0], lambda: scope[1][0])
    assert tools.tool_names == ["bossWorkspaceRead"]
    assert tools.get("bossWorkspaceRead").allowed_projections == frozenset({"notifications"})
    return json.loads(asyncio.run(tools.get("bossWorkspaceRead").execute(**params)))


def test_actual_notifications_projection_and_rules_are_preserved_without_dispatch(scope):
    result = call(scope, {"projection": "notifications"})
    assert notifications_digest(result) == notifications_digest(scope[2])
    assert result["rules"][0]["version"] == "1"
    with scope[0].connect() as db:
        assert db.execute("SELECT count(*) FROM objects WHERE kind IN ('authorization','dispatch','delivery','notification')").fetchone()[0] == 0


@pytest.mark.parametrize("field,value", [("role", "MAINTAINER"), ("active", False), ("owner_id", "other"),
    ("namespace", "other"), ("dataset_version", "2"), ("projection_sha256", "0" * 64)])
def test_wrong_current_scope_is_rejected(scope, field, value):
    scope[1][0] = replace(scope[1][0], **{field: value})
    with pytest.raises(web.HTTPException):
        call(scope, {"projection": "notifications"})


@pytest.mark.parametrize("params", [{"projection": "memory"}, {"projection": "notifications", "confirmed": True}])
def test_model_cannot_expand_private_projection_or_confirm_owner_action(scope, params):
    with pytest.raises(web.HTTPBadRequest):
        call(scope, params)


def test_rule_change_rejects_old_bound_projection(scope):
    scope[0].control("ui-check", "rules", {"version": "2", "cooldown_seconds": 1800, "quiet_start": 22,
        "quiet_end": 7, "timezone": "Asia/Shanghai", "important_escalation": False})
    with pytest.raises(web.HTTPConflict):
        call(scope, {"projection": "notifications"})


def run(scope, tmp_path, producer):
    store, current, _ = scope
    logger.remove()
    logger.add(sys.stderr, level="WARNING", diagnose=False, backtrace=False)
    config = Config.model_validate({"agents": {"defaults": {"provider": "deepseek", "model": "deepseek-flash",
        "workspace": str(tmp_path / "workspace"), "maxToolIterations": 12, "maxTokens": 700,
        "maxToolResultChars": 200000, "dream": {"enabled": False}, "idleCompactAfterMinutes": 0}}})
    tools = ToolRegistry()
    snapshot = {"provider": "deepseek", "model_id": "deepseek-flash", "api_type": "chat_completions", "max_tool_rounds": 12,
        "max_output_tokens": 700, "timeout": 120, "config_sha256": checksum(config.model_dump(mode="json"))}
    recorder = Fc04RuntimeRecorder(store, "ui-check", tools, lambda: snapshot, lambda: current[0])
    provider = Fc04SimulatedProvider(producer)
    provider.generation = config.resolve_preset().to_generation_settings()
    sessions = SessionManager(tmp_path / "workspace", sessions_root=tmp_path / "sessions")
    loop = AgentLoop.from_config(config, tool_registry=tools, provider=provider,
                                 session_manager=sessions, hook_factories=[recorder.hook_factory])
    for name in list(tools.tool_names):
        tools.unregister(name)
    names = register_fc04_tools(tools, store, lambda: current[0])
    with store.connect() as db:
        configuration = store.get(db, "ui-check", "configuration", "current")
        configuration["tool_scope"] = names
        store.put(db, "ui-check", "configuration", "current", configuration)
    async def execute():
        async with Nanobot(loop, config=config) as bot:
            bot.runtime.add_context_provider(recorder.context)
            async def bind(request):
                binding = request.attributes["boss_runtime_binding"]
                current[0] = replace(current[0], request_id=binding.request_id, session_id=binding.session_id)
            bot.runtime.add_context_provider(bind)
            return await bot.run("读取当前经营提醒和实际规则，供本人处理。", session_key=current[0].session_id, sender_id="boss-1")
    return asyncio.run(execute())


def event():
    return LLMResponse(content=None, tool_calls=[ToolCallRequest(id=str(uuid4()), name="bossWorkspaceRead", arguments={"projection": "notifications"})])


def test_actual_sdk_consumes_formal_projection_and_records_rule_versions(scope, tmp_path):
    async def producer(messages, tools):
        outputs = [json.loads(item["content"]) for item in messages if item["role"] == "tool"]
        if not outputs:
            return event()
        return LLMResponse(content=encode({"source_type": "SIMULATED", "rules": outputs[-1]["rules"],
            "events": outputs[-1]["events"], "dispatches": outputs[-1]["dispatches"], "owner_decision_required": True}))
    result = run(scope, tmp_path, producer)
    assert not result.error and json.loads(result.content)["rules"] == scope[2]["rules"]
    row = runtime_records(ControlStore(scope[0].path), "MAINTAINER")["runs"][0]
    assert row["feature_id"] == "FC04" and row["status"] == "SUCCEEDED"
    assert row["tool_results"][0]["rule_versions"] == ["1"]
    assert row["usage"] is row["cost_total"] is None
    assert "读取当前经营提醒" not in json.dumps(row, ensure_ascii=False)


@pytest.mark.parametrize("failure,status", [("failed", "FAILED"), ("cancel", "CANCELED"), ("timeout", "TIMED_OUT")])
def test_actual_terminal_preserves_completed_read_reference(scope, tmp_path, failure, status):
    async def producer(messages, tools):
        if not any(item["role"] == "tool" for item in messages):
            return event()
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
    assert row["status"] == status and row["tool_results"][0]["rule_versions"] == ["1"]
    assert row["usage"] is row["cost_total"] is None


def test_runtime_revocation_stops_next_read_and_preserves_reference(scope, tmp_path):
    async def producer(messages, tools):
        if any(item["role"] == "tool" for item in messages):
            scope[1][0] = replace(scope[1][0], active=False)
        return event()
    with pytest.raises(RuntimeError, match="经营提醒读取失败"):
        run(scope, tmp_path, producer)
    row = runtime_records(ControlStore(scope[0].path), "MAINTAINER")["runs"][0]
    assert row["status"] == "FAILED" and len(row["tool_results"]) == 1
    assert row["tool_errors"][0]["error_type"] == "HTTPForbidden"
