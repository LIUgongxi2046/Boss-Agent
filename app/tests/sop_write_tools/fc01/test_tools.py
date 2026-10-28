import asyncio
from dataclasses import replace
import json
from pathlib import Path
import sys
from uuid import uuid4

import pytest
import yaml
from aiohttp import web
from nanobot.agent.tools.registry import ToolRegistry
from nanobot import Nanobot
from nanobot.agent.loop import AgentLoop
from nanobot.config.schema import Config
from nanobot.providers.base import LLMResponse, ToolCallRequest
from nanobot.session.manager import SessionManager
from loguru import logger
from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "validation"))

from controls import ControlStore
from boss_supply_quality import SupplyQualityAPI, IMPORT_ACTION, COORDINATE_ACTION
from sop_write_tools.fc01 import Fc01Context, Fc01Tool, register_fc01_tools, content_digest
from sop_write_tools.fc01.runtime import Fc01RuntimeRecorder, Fc01SimulatedProvider
from sop_write_tools.fc01.contract import interface_contract
from boss_runtime_records import runtime_records


def prohibit_network(event, args):
    if event == "socket.connect":
        raise PermissionError("FC01限定检查禁止外部网络请求")


sys.addaudithook(prohibit_network)


@pytest.fixture
def scope(tmp_path):
    store = ControlStore(tmp_path / "fc01.sqlite")
    store.initialize("ui-check")
    sample = yaml.safe_load((ROOT / "data/simulation/supply-quality-v1.yaml").read_text())
    api = SupplyQualityAPI(store)
    api.execute("MAINTAINER", IMPORT_ACTION, sample["initial_request"])
    view = api.read("BOSS", "SI10")
    origin = view["events"][0]
    params = {"interface_id": "SI10", "origin_entity_type": origin["entity_type"],
              "origin_record_id": origin["record_id"], "origin_version": origin["version"],
              "review_sha256": view["review_sha256"], "purpose": "核查品质事件并提交当前依据",
              "coordinator_id": "coordinator-1", "due_at": "2026-10-25T17:00:00+08:00",
              "timezone": "Asia/Shanghai", "evidence_requirements": ["专业核查记录"]}
    names = frozenset({"bossSupplyQualityRead", "bossSupplyQualityQuery", "bossSupplyQualityPrepare", "bossEvidenceRead",
                       "query_metrics", "read_evidence", "create_assignment", "send_assignment", "read_assignment"})
    current = [Fc01Context("BOSS", "boss-1", "ui-check", "selection", "1", "fc01-request-001",
                           "fc01-session", names, True,
                           frozenset({("bossSupplyQualityPrepare", content_digest(params))}), ())]
    return store, current, params


def tool(scope, name):
    return Fc01Tool(scope[0], lambda: scope[1][0], name)


def execute(scope, name, params):
    registry = ToolRegistry()
    register_fc01_tools(registry, scope[0], lambda: scope[1][0], allowed_tools={name})
    return json.loads(asyncio.run(registry.get(name).execute(**params)))


def test_prepare_reads_current_sources_and_hands_owner_decision_to_ui(scope):
    store, _, params = scope
    prepared = execute(scope, "bossSupplyQualityPrepare", params)
    assert prepared["source_type"] == "SIMULATED"
    assert prepared["owner_decision_required"] is True
    assert prepared["business_authority_granted"] is False
    assert prepared["coordinate_input"] == params
    assert prepared["source_refs"]
    contract = interface_contract(store, lambda: scope[1][0])
    Draft202012Validator(contract["preparation_output"], format_checker=FormatChecker()).validate(prepared)
    with ControlStore(store.path).connect() as db:
        assert db.execute("SELECT count(*) FROM objects WHERE kind IN ('task','authorization','outbox')").fetchone()[0] == 0
        for ref in prepared["source_refs"]:
            assert store.get(db, "ui-check", "document", ref["source_id"])["version"] == ref["version"]


@pytest.mark.parametrize("field,value", [("role", "MAINTAINER"), ("active", False),
    ("owner_id", "other"), ("dataset_version", "2"), ("namespace", "other"), ("allowed_tools", frozenset())])
def test_scope_revocation_rejects_current_tool(scope, field, value):
    scope[1][0] = replace(scope[1][0], **{field: value})
    with pytest.raises(web.HTTPException):
        asyncio.run(tool(scope, "bossSupplyQualityRead").execute(interface_id="SI10"))


def test_model_content_cannot_replace_server_binding(scope):
    with pytest.raises(web.HTTPForbidden):
        asyncio.run(tool(scope, "bossSupplyQualityPrepare").execute(**{**scope[2], "purpose": "其他内容"}))
    with pytest.raises(web.HTTPBadRequest):
        asyncio.run(tool(scope, "bossSupplyQualityPrepare").execute(**{**scope[2], "confirmed": True}))


def test_source_change_rejects_old_preparation(scope):
    source = execute(scope, "bossSupplyQualityPrepare", scope[2])["source_refs"][0]
    with scope[0].connect() as db:
        document = scope[0].get(db, "ui-check", "document", source["source_id"])
        document["version"] = "2"
        scope[0].put(db, "ui-check", "document", source["source_id"], document)
    with pytest.raises(web.HTTPConflict):
        asyncio.run(tool(scope, "bossSupplyQualityPrepare").execute(**scope[2]))


def test_no_owner_operation_registration_and_no_partial_mutation(scope):
    registry = ToolRegistry()
    with pytest.raises(web.HTTPForbidden):
        register_fc01_tools(registry, scope[0], lambda: scope[1][0],
                            allowed_tools={"bossSupplyQualityRead", "boss.supply_quality.coordinate"})
    assert registry.tool_names == []


def test_send_without_existing_owner_authorization_rejected(scope):
    with pytest.raises(web.HTTPForbidden):
        asyncio.run(tool(scope, "send_assignment").execute(task_id="unknown", task_version="1",
            recipient_id="coordinator-1", body="请核查", content_version="1"))


def test_query_uses_formal_filters_and_rejects_other_interface(scope):
    output = execute(scope, "bossSupplyQualityQuery", {"interface_id": "SI10", "object_ids": [], "filters": {}})
    assert output["records"] and output["source_type"] == "SIMULATED"
    with pytest.raises(web.HTTPBadRequest):
        asyncio.run(tool(scope, "bossSupplyQualityQuery").execute(interface_id="SI01", object_ids=[], filters={}))


def test_owner_coordinate_then_runtime_reads_same_persisted_task(scope, tmp_path):
    prepared = execute(scope, "bossSupplyQualityPrepare", scope[2])
    # 本人领域入口代表检查中的明确本人操作，模型工具没有该入口。
    created = SupplyQualityAPI(scope[0]).execute("BOSS", COORDINATE_ACTION,
        {**prepared["coordinate_input"], "client_request_id": "fc01-owner-coordinate"})
    async def producer(messages, tools):
        outputs = [json.loads(message["content"]) for message in messages if message["role"] == "tool"]
        if not outputs:
            return request_tool("read_assignment", {"task_id": created["task_id"]})
        assert outputs[-1]["task_id"] == created["task_id"] and outputs[-1]["status"] == "OPEN"
        return LLMResponse(content="SIMULATED：已重新读取本人协调任务。")
    result, row = run_runtime(scope, tmp_path, producer)
    assert not result.error
    assert row["tool_results"][0]["task_id"] == created["task_id"]
    with ControlStore(scope[0].path).connect() as db:
        assert scope[0].get(db, "ui-check", "task", created["task_id"])["status"] == "OPEN"
        assert db.execute("SELECT count(*) FROM objects WHERE kind='task'").fetchone()[0] == 1
    assert SupplyQualityAPI(ControlStore(scope[0].path)).receipt("BOSS", COORDINATE_ACTION,
               "fc01-owner-coordinate")["result"]["task_id"] == created["task_id"]


def request_tool(name, params):
    return LLMResponse(content=None, tool_calls=[ToolCallRequest(id=str(uuid4()), name=name, arguments=params)])


def run_runtime(scope, tmp_path, producer, *, session="fc01-session"):
    store, current, _ = scope
    logger.remove()
    logger.add(sys.stderr, level="WARNING", diagnose=False, backtrace=False)
    config = Config.model_validate({"agents": {"defaults": {
        "provider": "deepseek", "model": "deepseek-flash", "workspace": str(tmp_path / "workspace"),
        "maxToolIterations": 12, "maxTokens": 700, "maxToolResultChars": 200000,
        "dream": {"enabled": False}, "idleCompactAfterMinutes": 0}}})
    registry = ToolRegistry()
    effective = {"provider": "deepseek", "model_id": "deepseek-flash", "api_type": "chat_completions",
                 "max_tool_rounds": 12, "max_output_tokens": 700, "timeout": 120, "config_sha256": content_digest(config.model_dump(mode="json"))}
    recorder = Fc01RuntimeRecorder(store, "ui-check", registry, lambda: effective)
    provider = Fc01SimulatedProvider(producer)
    provider.generation = config.resolve_preset().to_generation_settings()
    sessions = SessionManager(tmp_path / "workspace", sessions_root=tmp_path / "sessions")
    loop = AgentLoop.from_config(config, tool_registry=registry, provider=provider,
                                 session_manager=sessions, hook_factories=[recorder.hook_factory])
    for name in list(registry.tool_names):
        registry.unregister(name)
    register_fc01_tools(registry, store, lambda: current[0], allowed_tools=current[0].allowed_tools)
    with store.connect() as db:
        active = store.get(db, "ui-check", "configuration", "current")
        active["tool_scope"] = registry.tool_names
        store.put(db, "ui-check", "configuration", "current", active)

    async def run():
        async with Nanobot(loop, config=config) as bot:
            bot.runtime.add_context_provider(recorder.context)
            async def bind(request):
                # 独立检查绑定实际Runtime编号；生产认证绑定由N3提供。
                binding = request.attributes["boss_runtime_binding"]
                current[0] = replace(current[0], request_id=binding.request_id, session_id=binding.session_id)
            bot.runtime.add_context_provider(bind)
            return await bot.run("读取当前采购品质资料并准备本人协调内容。外部模型事件明确SIMULATED。",
                                 session_key=session, sender_id="boss-1")
    result = asyncio.run(run())
    row = runtime_records(ControlStore(store.path), "MAINTAINER")["runs"][0]
    return result, row


def test_actual_nanobot_runtime_consumes_tools_sources_and_owner_handoff(scope, tmp_path):
    async def producer(messages, tools):
        outputs = [json.loads(message["content"]) for message in messages if message["role"] == "tool"]
        assert "boss.supply_quality.coordinate" not in {item["function"]["name"] for item in tools}
        if not outputs:
            return request_tool("bossSupplyQualityRead", {"interface_id": "SI09"})
        if len(outputs) == 1:
            assert outputs[0]["supply"] and outputs[0]["supply"][0]["available_quantity"] == "20"
            return request_tool("bossSupplyQualityRead", {"interface_id": "SI10"})
        if len(outputs) == 2:
            return request_tool("bossEvidenceRead", {"source": outputs[-1]["events"][0]["source_id"]})
        if len(outputs) == 3:
            assert outputs[-1]["version"] == scope[2]["origin_version"]
            return request_tool("bossSupplyQualityPrepare", scope[2])
        assert outputs[-1]["coordinate_input"] == scope[2]
        assert outputs[-1]["owner_decision_required"] is True
        return LLMResponse(content="SIMULATED：协调内容需要本人在食品品质页面确认。")

    result, row = run_runtime(scope, tmp_path, producer)
    assert not result.error and result.stop_reason == "completed"
    assert row["status"] == "SUCCEEDED" and row["source_type"] == "SIMULATED"
    assert row["external_model_invoked"] is False and row["model_behavior_evaluation_passed"] is False
    assert row["usage"] is None and row["cost_total"] is None
    assert row["configuration_version"] == "1" and row["tool_configuration"]
    assert len(row["simulated_model_events"]) == 5
    assert all(event["source_type"] == "SIMULATED" for event in row["simulated_model_events"])
    assert [item["tool_id"] for item in row["tool_results"]] == ["bossSupplyQualityRead", "bossSupplyQualityRead", "bossEvidenceRead", "bossSupplyQualityPrepare"]
    assert row["tool_results"][-1]["origin"]["origin_version"] == scope[2]["origin_version"]
    assert row["tool_results"][-1]["source_refs"]
    assert scope[2]["purpose"] not in json.dumps(row, ensure_ascii=False)
    assert "credential" not in json.dumps(row)


@pytest.mark.parametrize("failure,status", [("failed", "FAILED"), ("cancel", "CANCELED"), ("timeout", "TIMED_OUT")])
def test_actual_runtime_failure_keeps_tools_and_unknown_cost(scope, tmp_path, failure, status):
    async def producer(messages, tools):
        if not any(message["role"] == "tool" for message in messages):
            return request_tool("bossSupplyQualityRead", {"interface_id": "SI10"})
        if failure == "cancel":
            raise asyncio.CancelledError()
        if failure == "timeout":
            raise TimeoutError("明确模拟的外部模型超时")
        return LLMResponse(content="明确模拟的外部模型失败", finish_reason="error", error_kind="unknown")
    if failure in {"cancel", "timeout"}:
        with pytest.raises(asyncio.CancelledError if failure == "cancel" else TimeoutError):
            run_runtime(scope, tmp_path, producer)
        row = runtime_records(ControlStore(scope[0].path), "MAINTAINER")["runs"][0]
    else:
        _, row = run_runtime(scope, tmp_path, producer)
    assert row["status"] == status
    assert row["tool_results"][0]["tool_id"] == "bossSupplyQualityRead"
    assert row["finished_at"] and row["cost_total"] is None and row["usage"] is None


def test_runtime_rejects_unbound_content_and_stops_followup(scope, tmp_path):
    async def producer(messages, tools):
        assert not any(message["role"] == "tool" for message in messages)
        return request_tool("bossSupplyQualityPrepare", {**scope[2], "purpose": "其他内容"})
    with pytest.raises(RuntimeError, match="FC01工具执行失败"):
        run_runtime(scope, tmp_path, producer)
    row = runtime_records(ControlStore(scope[0].path), "MAINTAINER")["runs"][0]
    assert row["status"] == "FAILED" and row["tool_results"] == []
    assert row["tool_errors"][0]["error_type"] == "HTTPForbidden"
    assert scope[2]["purpose"] not in json.dumps(row, ensure_ascii=False)


def test_runtime_binding_must_match_current_request(scope):
    from nanobot.agent.tools.context import RequestContext, request_context
    request = RequestContext(channel="cli", chat_id="other", session_key="other", sender_id="boss-1")
    with request_context(request), pytest.raises(web.HTTPForbidden):
        asyncio.run(tool(scope, "bossSupplyQualityRead").execute(interface_id="SI09"))
