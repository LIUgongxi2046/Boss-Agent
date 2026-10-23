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
if os.environ.get("FC02_DOMAIN_ROOT"):
    sys.path.insert(0, str(Path(os.environ["FC02_DOMAIN_ROOT"]) / "validation"))

from business import checksum
from controls import ControlStore
from boss_runtime_records import runtime_records
from fc02_agent import Fc02Context, Fc02Tool, bind_query, register_fc02_tools
from fc02_agent.runtime import Fc02RuntimeRecorder, Fc02SimulatedProvider


def prohibit_network(event, args):
    if event == "socket.connect":
        raise PermissionError("BI限定检查禁止外部连接")


sys.addaudithook(prohibit_network)


@pytest.fixture
def scope(tmp_path):
    store = ControlStore(tmp_path / "bi.sqlite")
    store.initialize("ui-check")
    with store.connect() as db:
        data = store.get(db, "ui-check", "initial", "snapshot")
    params = {"question": "查询当前获准经营变化", "metric_ids": ["sales_quantity", "revenue", "gross_profit", "gross_margin", "gross_profit_per_tonne"],
              "region_id": "region-1", "product_ids": ["product-1", "product-2"],
              "period_start": data["periods"]["CURRENT"][0], "period_end": data["periods"]["CURRENT"][1],
              "comparison_start": data["periods"]["BASE"][0], "comparison_end": data["periods"]["BASE"][1],
              "currency": "CNY", "trade_scope": "EXTERNAL_SALES", "definition_version": "1"}
    current = [Fc02Context("BOSS", "boss-1", "ui-check", "selection", "1", "fc02-initial-request",
                           "fc02-session", True, (bind_query(params),), frozenset())]
    return store, current, params


def call(scope, name, params):
    registry = ToolRegistry()
    register_fc02_tools(registry, scope[0], lambda: scope[1][0])
    return json.loads(asyncio.run(registry.get(name).execute(**params)))


def test_query_and_evidence_use_actual_persisted_objects(scope):
    query = call(scope, "query_metrics", scope[2])
    evidence = call(scope, "read_evidence", {"query_id": query["query_id"], "source_ids": [item["source_id"] for item in query["sources"]], "detail_refs": query["detail_refs"]})
    assert evidence["original_records"] and query["unexplained_causes"]
    with ControlStore(scope[0].path).connect() as db:
        assert scope[0].get(db, "ui-check", "query", query["query_id"])["detail_refs"] == query["detail_refs"]
        assert db.execute("SELECT count(*) FROM objects WHERE kind IN ('task','authorization','outbox')").fetchone()[0] == 0


def test_followup_inherits_only_unmodified_fields(scope):
    first = call(scope, "query_metrics", scope[2])
    changed = {**scope[2], "question": "继续按产品查询", "product_ids": ["product-1"]}
    binding = bind_query(changed, previous_query_id=first["query_id"], previous_parameters=scope[2], overridden_fields={"question", "product_ids"})
    scope[1][0] = replace(scope[1][0], request_id="fc02-followup-request", query_bindings=(binding,))
    result = call(scope, "query_metrics", changed)
    assert result["query_id"] != first["query_id"] and len(result["detail_refs"]) < len(first["detail_refs"])
    assert binding.visible()["overridden_fields"] == ["product_ids"]
    assert "currency" in binding.visible()["inherited_fields"]
    with pytest.raises(web.HTTPConflict):
        bind_query(changed, previous_query_id=first["query_id"], previous_parameters=scope[2], overridden_fields={"question"})


@pytest.mark.parametrize("field,value", [("role", "MAINTAINER"), ("active", False), ("owner_id", "other"), ("namespace", "other"), ("dataset_version", "2")])
def test_invalid_current_identity_rejects(scope, field, value):
    scope[1][0] = replace(scope[1][0], **{field: value})
    with pytest.raises(web.HTTPException):
        call(scope, "query_metrics", scope[2])


def test_model_cannot_change_trusted_query_or_grant_permission(scope):
    with pytest.raises(web.HTTPForbidden):
        call(scope, "query_metrics", {**scope[2], "product_ids": ["product-1"]})
    with pytest.raises(web.HTTPBadRequest):
        call(scope, "query_metrics", {**scope[2], "confirmed": True})
    registry = ToolRegistry()
    register_fc02_tools(registry, scope[0], lambda: scope[1][0])
    assert set(registry.tool_names) == {"query_metrics", "read_evidence"}


def test_old_source_rejects_current_evidence_and_preserves_query(scope):
    query = call(scope, "query_metrics", scope[2])
    scope[0].control("ui-check", "withdraw", {"source_id": query["sources"][0]["source_id"], "version": "1"})
    with pytest.raises(web.HTTPGone):
        call(scope, "read_evidence", {"query_id": query["query_id"], "source_ids": [item["source_id"] for item in query["sources"]], "detail_refs": query["detail_refs"]})
    with ControlStore(scope[0].path).connect() as db:
        assert scope[0].get(db, "ui-check", "query", query["query_id"])["query_id"] == query["query_id"]


def test_current_request_cannot_read_unselected_old_query(scope):
    query = call(scope, "query_metrics", scope[2])
    scope[1][0] = replace(scope[1][0], request_id="fc02-other-request")
    payload = {"query_id": query["query_id"], "source_ids": [item["source_id"] for item in query["sources"]], "detail_refs": query["detail_refs"]}
    with pytest.raises(web.HTTPForbidden):
        call(scope, "read_evidence", payload)
    scope[1][0] = replace(scope[1][0], readable_query_ids=frozenset({query["query_id"]}))
    assert call(scope, "read_evidence", payload)["original_records"]


def test_registry_duplicate_rejected_before_mutation(scope):
    registry = ToolRegistry()
    register_fc02_tools(registry, scope[0], lambda: scope[1][0])
    with pytest.raises(web.HTTPConflict):
        register_fc02_tools(registry, scope[0], lambda: scope[1][0])
    assert set(registry.tool_names) == {"query_metrics", "read_evidence"}


def test_runtime_request_binding_cannot_be_forged(scope):
    from nanobot.agent.tools.context import RequestContext, request_context
    request = RequestContext(channel="cli", chat_id="other", session_key="other", sender_id="boss-1")
    with request_context(request), pytest.raises(web.HTTPForbidden):
        call(scope, "query_metrics", scope[2])


def tool_call(name, params):
    return LLMResponse(content=None, tool_calls=[ToolCallRequest(id=str(uuid4()), name=name, arguments=params)])


def run(scope, tmp_path, producer):
    store, current, _ = scope
    logger.remove()
    logger.add(sys.stderr, level="WARNING", diagnose=False, backtrace=False)
    config = Config.model_validate({"agents": {"defaults": {"provider": "deepseek", "model": "deepseek-flash",
        "workspace": str(tmp_path / "workspace"), "maxToolIterations": 12, "maxTokens": 700,
        "maxToolResultChars": 200000, "dream": {"enabled": False}, "idleCompactAfterMinutes": 0}}})
    registry = ToolRegistry()
    snapshot = {"provider": "deepseek", "model_id": "deepseek-flash", "api_type": "chat_completions", "max_tool_rounds": 12,
                "max_output_tokens": 700, "timeout": 120, "config_sha256": checksum(config.model_dump(mode="json"))}
    recorder = Fc02RuntimeRecorder(store, "ui-check", registry, lambda: snapshot, lambda: current[0])
    provider = Fc02SimulatedProvider(producer)
    provider.generation = config.resolve_preset().to_generation_settings()
    loop = AgentLoop.from_config(config, tool_registry=registry, provider=provider, hook_factories=[recorder.hook_factory])
    for name in list(registry.tool_names):
        registry.unregister(name)
    register_fc02_tools(registry, store, lambda: current[0])

    async def execute():
        async with Nanobot(loop, config=config) as bot:
            bot.runtime.add_context_provider(recorder.context)
            async def authenticated_request(request):
                binding = request.attributes["boss_runtime_binding"]
                current[0] = replace(current[0], request_id=binding.request_id, session_id=binding.session_id)
            bot.runtime.add_context_provider(authenticated_request)
            return await bot.run("查询获准经营指标并读取原始依据。模型事件明确SIMULATED。", session_key=current[0].session_id, sender_id="boss-1")
    return asyncio.run(execute())


def test_actual_bi_runtime_consumes_query_and_evidence(scope, tmp_path):
    async def producer(messages, tools):
        outputs = [json.loads(item["content"]) for item in messages if item["role"] == "tool"]
        if not outputs:
            return tool_call("query_metrics", scope[2])
        if len(outputs) == 1:
            result = outputs[0]
            return tool_call("read_evidence", {"query_id": result["query_id"], "source_ids": [item["source_id"] for item in result["sources"]], "detail_refs": result["detail_refs"]})
        assert outputs[-1]["original_records"] and outputs[-1]["missing_fields"]
        return LLMResponse(content="SIMULATED：当前查询与依据已经读取，原因资料缺少。")
    result = run(scope, tmp_path, producer)
    assert not result.error
    row = runtime_records(ControlStore(scope[0].path), "MAINTAINER")["runs"][0]
    assert row["feature_id"] == "FC02" and row["status"] == "SUCCEEDED" and row["source_type"] == "SIMULATED"
    assert row["tool_results"][0]["query_id"] == row["tool_results"][1]["query_id"]
    assert row["tool_results"][0]["bi_query_context"]["parameters"]["product_ids"] == scope[2]["product_ids"]
    assert row["usage"] is None and row["cost_total"] is None
    assert scope[2]["question"] not in json.dumps(row, ensure_ascii=False)


def test_runtime_followup_keeps_visible_inheritance_and_query_chain(scope, tmp_path):
    async def producer(messages, tools):
        outputs = [json.loads(item["content"]) for item in messages if item["role"] == "tool"]
        if not outputs:
            return tool_call("query_metrics", json.loads(scope[1][0].query_bindings[0].parameters_json))
        assert outputs[-1]["detail_refs"]
        return LLMResponse(content="SIMULATED：已读取当前明确范围。")
    assert not run(scope, tmp_path / "initial", producer).error
    first = runtime_records(ControlStore(scope[0].path), "MAINTAINER")["runs"][0]["tool_results"][0]["query_id"]
    changed = {**scope[2], "question": "继续查询当前产品", "product_ids": ["product-1"]}
    scope[1][0] = replace(scope[1][0], session_id="fc02-followup", query_bindings=(bind_query(changed,
        previous_query_id=first, previous_parameters=scope[2], overridden_fields={"question", "product_ids"}),))
    assert not run(scope, tmp_path / "followup", producer).error
    rows = runtime_records(ControlStore(scope[0].path), "MAINTAINER")["runs"]
    followed = next(row for row in rows if row["session_id"] == "fc02-followup")
    reference = followed["tool_results"][0]
    assert reference["query_id"] != first and reference["bi_query_context"]["previous_query_id"] == first
    assert reference["bi_query_context"]["overridden_fields"] == ["product_ids"]
    assert "currency" in reference["bi_query_context"]["inherited_fields"]


@pytest.mark.parametrize("failure,status", [("failed", "FAILED"), ("cancel", "CANCELED"), ("timeout", "TIMED_OUT")])
def test_runtime_terminal_keeps_persisted_query(scope, tmp_path, failure, status):
    async def producer(messages, tools):
        if not any(item["role"] == "tool" for item in messages):
            return tool_call("query_metrics", scope[2])
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
    query_id = row["tool_results"][0]["query_id"]
    with ControlStore(scope[0].path).connect() as db:
        assert scope[0].get(db, "ui-check", "query", query_id)["query_id"] == query_id
    assert row["cost_total"] is None and row["usage"] is None
