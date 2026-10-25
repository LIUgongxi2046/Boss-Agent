import asyncio
from dataclasses import replace
import json
from uuid import uuid4

import pytest
from aiohttp import web
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.providers.base import LLMResponse, ToolCallRequest

from test_agent import scope, run
from business import encode
from boss_morning import MorningAPI, QUERY_ACTION
from boss_runtime_records import runtime_records
from controls import ControlStore
from fc03_agent import register_fc03_tools
from fc03_agent.formal import FORMAL_TOOLS, FormalMorningTool


@pytest.fixture
def formal(scope):
    day = {"date": "2026-10-23", "timezone": "Asia/Shanghai"}
    preview = MorningAPI(scope[0]).read("BOSS", day)
    scope[1][0] = replace(scope[1][0], read_parameters_json=encode(day), **day,
        snapshot_sha256=preview["snapshot_sha256"], order_version=preview["order_version"], client_request_id="morning-agent-formal")
    return scope[0], scope[1], preview


def call(formal, name, params):
    registry = ToolRegistry()
    register_fc03_tools(registry, formal[0], lambda: formal[1][0], formal=True)
    assert set(registry.tool_names) == FORMAL_TOOLS
    return json.loads(asyncio.run(registry.get(name).execute(**params)))


def event(name, params):
    return LLMResponse(content=None, tool_calls=[ToolCallRequest(id=str(uuid4()), name=name, arguments=params)])


def test_formal_query_is_idempotent_and_receipt_is_read_only(formal):
    day = json.loads(formal[1][0].read_parameters_json)
    first = call(formal, "todayRead", day)
    assert call(formal, "todayRead", day) == first
    reopened = ControlStore(formal[0].path)
    receipt = FormalMorningTool(reopened, lambda: formal[1][0], "todayRead").receipt()
    assert receipt["result"]["list_id"] == first["list_id"]
    with reopened.connect() as db:
        assert db.execute("SELECT count(*) FROM objects WHERE kind='morning_list'").fetchone()[0] == 1
        assert db.execute("SELECT count(*) FROM objects WHERE kind='authorization'").fetchone()[0] == 0


def test_actual_runtime_consumes_persistent_list_detail_and_source(formal, tmp_path):
    consumed = []
    async def producer(messages, tools):
        outputs = [json.loads(item["content"]) for item in messages if item["role"] == "tool"]
        if not outputs:
            return event("todayRead", json.loads(formal[1][0].read_parameters_json))
        view = outputs[0]
        if len(outputs) == 1:
            return event("morningListRead", {"list_id": view["list_id"]})
        if len(outputs) == 2:
            return event("morningDetailRead", {"list_id": view["list_id"], "item_id": view["items"][0]["item_id"]})
        if len(outputs) == 3:
            source = next(item for item in view["source_statuses"] if item["status"] == "VALID")
            return event("morningSourceRead", {"list_id": view["list_id"], "source_id": source["source_id"]})
        consumed[:] = outputs
        return LLMResponse(content=encode({"list_id": view["list_id"], "items": outputs[1]["result"]["items"],
            "source_version": outputs[3]["document"]["version"], "source_type": "SIMULATED"}))
    result = run(formal, tmp_path, producer, formal=True)
    assert not result.error and len(consumed) == 4
    row = runtime_records(ControlStore(formal[0].path), "MAINTAINER")["runs"][0]
    assert row["status"] == "SUCCEEDED" and len(row["tool_results"]) == 4
    assert {ref["list_id"] for ref in row["tool_results"]} == {consumed[0]["list_id"]}
    assert {ref["list_version"] for ref in row["tool_results"]} == {consumed[0]["list_version"]}
    assert row["tool_results"][-1]["document_ref"]["version"] == consumed[-1]["document"]["version"]
    for item in consumed[0]["items"]:
        assert item["title"] not in json.dumps(row, ensure_ascii=False)
    assert row["usage"] is row["cost_total"] is None


def test_wrong_date_or_request_fields_are_rejected(formal):
    day = json.loads(formal[1][0].read_parameters_json)
    with pytest.raises(web.HTTPForbidden):
        call(formal, "todayRead", {**day, "date": "2026-10-24"})
    with pytest.raises(web.HTTPBadRequest):
        call(formal, "todayRead", {**day, "client_request_id": "model-controlled"})


def test_owner_sort_requires_new_binding_for_list_read(formal):
    view = call(formal, "todayRead", json.loads(formal[1][0].read_parameters_json))
    MorningAPI(formal[0]).reorder("BOSS", {"list_id": view["list_id"], "date": view["date"], "timezone": view["timezone"],
        "client_request_id": "formal-owner-sort", "expected_version": view["order_version"],
        "snapshot_sha256": view["snapshot_sha256"], "item_ids": [item["item_id"] for item in reversed(view["items"])]})
    with pytest.raises(web.HTTPConflict):
        call(formal, "morningListRead", {"list_id": view["list_id"]})


def test_unselected_list_and_stale_source_are_rejected(formal):
    day = json.loads(formal[1][0].read_parameters_json)
    first = call(formal, "todayRead", day)
    formal[1][0] = replace(formal[1][0], client_request_id="morning-other-intent")
    with pytest.raises(web.HTTPForbidden):
        call(formal, "morningListRead", {"list_id": first["list_id"]})
    formal[1][0] = replace(formal[1][0], client_request_id="morning-agent-formal")
    source = next(item for item in first["source_statuses"] if item["status"] == "VALID")
    formal[0].control("ui-check", "withdraw", {"source_id": source["source_id"], "version": source["version"]})
    with pytest.raises(web.HTTPException):
        call(formal, "morningSourceRead", {"list_id": first["list_id"], "source_id": source["source_id"]})
    receipt = FormalMorningTool(formal[0], lambda: formal[1][0], "todayRead").receipt()
    assert receipt["result"]["list_id"] == first["list_id"]


@pytest.mark.parametrize("failure,status", [("failed", "FAILED"), ("cancel", "CANCELED"), ("timeout", "TIMED_OUT")])
def test_formal_terminal_and_original_receipt_keep_one_list(formal, tmp_path, failure, status):
    async def producer(messages, tools):
        if not any(item["role"] == "tool" for item in messages):
            return event("todayRead", json.loads(formal[1][0].read_parameters_json))
        if failure == "cancel":
            raise asyncio.CancelledError()
        if failure == "timeout":
            raise TimeoutError("明确模拟的模型超时")
        return LLMResponse(content="明确模拟的模型失败", finish_reason="error", error_kind="unknown")
    if failure in {"cancel", "timeout"}:
        with pytest.raises(asyncio.CancelledError if failure == "cancel" else TimeoutError):
            run(formal, tmp_path, producer, formal=True)
    else:
        run(formal, tmp_path, producer, formal=True)
    reopened = ControlStore(formal[0].path)
    row = runtime_records(reopened, "MAINTAINER")["runs"][0]
    receipt = FormalMorningTool(reopened, lambda: formal[1][0], "todayRead").receipt()
    assert row["status"] == status and row["tool_results"][0]["list_id"] == receipt["result"]["list_id"]
    with reopened.connect() as db:
        assert db.execute("SELECT count(*) FROM objects WHERE kind='morning_list'").fetchone()[0] == 1
