import asyncio
from dataclasses import replace
import json
import os
from pathlib import Path
import sys
from uuid import uuid4

import pytest
import yaml
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
if os.environ.get("FC07_DOMAIN_ROOT"):
    sys.path.insert(0, str(Path(os.environ["FC07_DOMAIN_ROOT"]) / "validation"))

from business import checksum, encode
from boss_assignment_sources import AssignmentSourcesAPI
from boss_runtime_records import runtime_records
from boss_supply_quality import SupplyQualityAPI, IMPORT_ACTION, COORDINATE_ACTION
from controls import ControlStore
from fc07_agent import Fc07Context, register_fc07_tools
from fc07_agent.runtime import Fc07RuntimeRecorder, Fc07SimulatedProvider


def no_network(event, args):
    if event == "socket.connect":
        raise PermissionError("FC07限定检查禁止外部连接")


sys.addaudithook(no_network)


@pytest.fixture
def scope(tmp_path):
    store = ControlStore(tmp_path / "assignment.sqlite")
    store.initialize("ui-check")
    api = SupplyQualityAPI(store)
    sample = yaml.safe_load((ROOT / "data/simulation/supply-quality-v1.yaml").read_text())
    api.execute("MAINTAINER", IMPORT_ACTION, sample["initial_request"])
    view = api.read("BOSS", "SI10")
    origin = view["events"][0]
    task = api.execute("BOSS", COORDINATE_ACTION, {"client_request_id": "fc07-owner-create", "interface_id": "SI10",
        "origin_entity_type": origin["entity_type"], "origin_record_id": origin["record_id"], "origin_version": origin["version"],
        "review_sha256": view["review_sha256"], "purpose": "核查当前品质协调结果", "coordinator_id": "coordinator-1",
        "due_at": "2026-10-25T17:00:00+08:00", "timezone": "Asia/Shanghai", "evidence_requirements": ["当前专业核查依据"]})
    sources = AssignmentSourcesAPI(store).read("BOSS", task["task_id"])
    current = [Fc07Context("BOSS", "boss-1", "ui-check", "selection", "1", "fc07-request", "fc07-session",
        True, task["task_id"], task["version"], sources["review_sha256"])]
    return store, current


def call(scope, name, params):
    tools = ToolRegistry()
    register_fc07_tools(tools, scope[0], lambda: scope[1][0])
    assert set(tools.tool_names) == {"read_assignment", "assignmentSourcesRead"}
    return json.loads(asyncio.run(tools.get(name).execute(**params)))


def test_current_task_and_sources_use_same_actual_object_without_mutation(scope):
    task = call(scope, "read_assignment", {"task_id": scope[1][0].task_id})
    sources = call(scope, "assignmentSourcesRead", {"task_id": task["task_id"]})
    assert sources["task"]["task_id"] == task["task_id"] and sources["task"]["version"] == task["version"]
    assert sources["business_at"] and sources["binding_state"] == "CURRENT"
    with ControlStore(scope[0].path).connect() as db:
        assert db.execute("SELECT count(*) FROM objects WHERE kind='task'").fetchone()[0] == 1
        assert db.execute("SELECT count(*) FROM objects WHERE kind='outbox'").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM objects WHERE kind='authorization'").fetchone()[0] == 1


@pytest.mark.parametrize("field,value", [("role", "MAINTAINER"), ("active", False), ("owner_id", "other"),
    ("namespace", "other"), ("dataset_version", "2"), ("task_version", "999"), ("review_sha256", "0" * 64)])
def test_invalid_current_scope_rejects(scope, field, value):
    scope[1][0] = replace(scope[1][0], **{field: value})
    with pytest.raises(web.HTTPException):
        call(scope, "read_assignment", {"task_id": scope[1][0].task_id})


def test_model_cannot_replace_task_or_confirm_owner_decision(scope):
    with pytest.raises(web.HTTPForbidden):
        call(scope, "read_assignment", {"task_id": "different-task"})
    with pytest.raises(web.HTTPBadRequest):
        call(scope, "read_assignment", {"task_id": scope[1][0].task_id, "confirmed": True})


def test_source_revocation_requires_new_binding_and_never_completes_task(scope):
    context = scope[1][0]
    source = AssignmentSourcesAPI(scope[0]).read("BOSS", context.task_id)["sources"][0]
    scope[0].control("ui-check", "withdraw", {"source_id": source["source_id"], "version": source["current_version"]})
    with pytest.raises(web.HTTPConflict):
        call(scope, "assignmentSourcesRead", {"task_id": context.task_id})
    current = AssignmentSourcesAPI(scope[0]).read("BOSS", context.task_id)
    scope[1][0] = replace(context, review_sha256=current["review_sha256"])
    view = call(scope, "assignmentSourcesRead", {"task_id": context.task_id})
    assert view["binding_state"] == "NEEDS_REVIEW" and view["task"]["status"] == "OPEN"
    assert next(item for item in view["sources"] if item["source_id"] == source["source_id"])["excerpt"] is None


def run(scope, tmp_path, producer):
    store, current = scope
    logger.remove()
    logger.add(sys.stderr, level="WARNING", diagnose=False, backtrace=False)
    config = Config.model_validate({"agents": {"defaults": {"provider": "deepseek", "model": "deepseek-flash",
        "workspace": str(tmp_path / "workspace"), "maxToolIterations": 12, "maxTokens": 700,
        "maxToolResultChars": 200000, "dream": {"enabled": False}, "idleCompactAfterMinutes": 0}}})
    tools = ToolRegistry()
    snapshot = {"provider": "deepseek", "model_id": "deepseek-flash", "api_type": "chat_completions", "max_tool_rounds": 12,
        "max_output_tokens": 700, "timeout": 120, "config_sha256": checksum(config.model_dump(mode="json"))}
    recorder = Fc07RuntimeRecorder(store, "ui-check", tools, lambda: snapshot, lambda: current[0])
    provider = Fc07SimulatedProvider(producer)
    provider.generation = config.resolve_preset().to_generation_settings()
    sessions = SessionManager(tmp_path / "workspace", sessions_root=tmp_path / "sessions")
    loop = AgentLoop.from_config(config, tool_registry=tools, provider=provider,
                                 session_manager=sessions, hook_factories=[recorder.hook_factory])
    for name in list(tools.tool_names):
        tools.unregister(name)
    names = register_fc07_tools(tools, store, lambda: current[0])
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
            return await bot.run("读取当前交办和证据，供本人核查。", session_key=current[0].session_id, sender_id="boss-1")
    return asyncio.run(execute())


def event(name, task_id):
    return LLMResponse(content=None, tool_calls=[ToolCallRequest(id=str(uuid4()), name=name, arguments={"task_id": task_id})])


def test_actual_runtime_reads_task_then_sources_and_hands_owner_decision_to_page(scope, tmp_path):
    captured = []
    async def producer(messages, tools):
        outputs = [json.loads(item["content"]) for item in messages if item["role"] == "tool"]
        if not outputs:
            return event("read_assignment", scope[1][0].task_id)
        if len(outputs) == 1:
            return event("assignmentSourcesRead", outputs[0]["task_id"])
        captured[:] = outputs
        return LLMResponse(content=encode({"source_type": "SIMULATED", "task_id": outputs[0]["task_id"],
            "status": outputs[0]["status"], "binding_state": outputs[1]["binding_state"], "owner_decision_required": True}))
    result = run(scope, tmp_path, producer)
    assert not result.error and json.loads(result.content)["owner_decision_required"] is True
    row = runtime_records(ControlStore(scope[0].path), "MAINTAINER")["runs"][0]
    assert row["feature_id"] == "FC07" and row["status"] == "SUCCEEDED"
    assert {item["task_id"] for item in row["tool_results"]} == {scope[1][0].task_id}
    assert row["tool_results"][-1]["source_refs"]
    assert captured[0]["purpose"] not in json.dumps(row, ensure_ascii=False)
    assert row["usage"] is row["cost_total"] is None


@pytest.mark.parametrize("failure,status", [("failed", "FAILED"), ("cancel", "CANCELED"), ("timeout", "TIMED_OUT")])
def test_terminal_preserves_actual_task_reference(scope, tmp_path, failure, status):
    async def producer(messages, tools):
        if not any(item["role"] == "tool" for item in messages):
            return event("read_assignment", scope[1][0].task_id)
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
    assert row["status"] == status and row["tool_results"][0]["task_id"] == scope[1][0].task_id
    assert row["usage"] is row["cost_total"] is None


def test_runtime_revocation_stops_followup_and_preserves_existing_reference(scope, tmp_path):
    async def producer(messages, tools):
        if any(item["role"] == "tool" for item in messages):
            scope[1][0] = replace(scope[1][0], active=False)
            return event("assignmentSourcesRead", scope[1][0].task_id)
        return event("read_assignment", scope[1][0].task_id)
    with pytest.raises(RuntimeError, match="交办读取工具执行失败"):
        run(scope, tmp_path, producer)
    row = runtime_records(ControlStore(scope[0].path), "MAINTAINER")["runs"][0]
    assert row["status"] == "FAILED" and len(row["tool_results"]) == 1
    assert row["tool_errors"][0]["error_type"] == "HTTPForbidden"
