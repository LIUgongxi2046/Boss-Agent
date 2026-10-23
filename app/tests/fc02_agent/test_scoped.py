from dataclasses import replace
import json

import pytest
from aiohttp import web
from nanobot.providers.base import LLMResponse

from test_agent import scope, call, run, tool_call
from business import SPEC
from controls import ControlStore
from boss_runtime_records import runtime_records
from fc02_agent import Fc02Tool, bind_query, bind_scoped_followup

pytestmark = pytest.mark.skipif("scoped_query_input" not in SPEC["io_schema"]["$defs"],
                                reason="需要N1正式SCOPED领域与Schema")


@pytest.fixture
def scoped(scope):
    params = {**scope[2], "query_mode": "SCOPED", "legal_entity_id": "entity-1", "quantity_unit": "tonne",
              "business_basis": "SELECTION_REPORTED", "settlement_state": "SETTLED"}
    scope[1][0] = replace(scope[1][0], query_bindings=(bind_query(params),))
    return scope[0], scope[1], params


def test_scoped_query_replay_and_original_request_receipt(scoped):
    first = call(scoped, "query_metrics", scoped[2])
    assert call(scoped, "query_metrics", scoped[2]) == first
    receipt = Fc02Tool(scoped[0], lambda: scoped[1][0], "query_metrics").receipt()
    assert receipt["outcome"] == "RECORDED" and receipt["query"]["result"]["query_id"] == first["query_id"]
    with ControlStore(scoped[0].path).connect() as db:
        assert db.execute("SELECT count(*) FROM objects WHERE kind='query'").fetchone()[0] == 1
        assert db.execute("SELECT count(*) FROM objects WHERE kind='authorization'").fetchone()[0] == 0


def test_scoped_followup_uses_formal_persistent_snapshot(scoped):
    first = call(scoped, "query_metrics", scoped[2])
    scoped[1][0] = replace(scoped[1][0], request_id="fc02-scoped-followup")
    binding = bind_scoped_followup(scoped[0], scoped[1][0], first["query_id"], "继续按产品查询", {"product_ids": ["product-1"]})
    scoped[1][0] = replace(scoped[1][0], query_bindings=(binding,))
    result = call(scoped, "query_metrics", json.loads(binding.parameters_json))
    assert result["parent_query_id"] == first["query_id"]
    assert result["overridden_fields"] == ["product_ids"]
    assert result["context_snapshot"]["legal_entity_id"] == "entity-1"
    assert len(result["detail_refs"]) < len(first["detail_refs"])


def test_scoped_context_and_request_recover_after_runtime_timeout(scoped, tmp_path):
    async def producer(messages, tools):
        if not any(item["role"] == "tool" for item in messages):
            return tool_call("query_metrics", scoped[2])
        raise TimeoutError("明确模拟的模型超时")
    with pytest.raises(TimeoutError):
        run(scoped, tmp_path, producer)
    reopened = ControlStore(scoped[0].path)
    row = runtime_records(reopened, "MAINTAINER")["runs"][0]
    receipt = Fc02Tool(reopened, lambda: scoped[1][0], "query_metrics").receipt()
    assert row["status"] == "TIMED_OUT"
    assert receipt["query"]["result"]["query_id"] == row["tool_results"][0]["query_id"]
    assert receipt["query"]["result"]["context_snapshot"]["product_ids"] == scoped[2]["product_ids"]
    with reopened.connect() as db:
        assert db.execute("SELECT count(*) FROM objects WHERE kind='query'").fetchone()[0] == 1


def test_scoped_runtime_followup_and_evidence_are_same_formal_query(scoped, tmp_path):
    first = call(scoped, "query_metrics", scoped[2])
    scoped[1][0] = replace(scoped[1][0], request_id="fc02-scoped-runtime")
    binding = bind_scoped_followup(scoped[0], scoped[1][0], first["query_id"], "继续按产品查询", {"product_ids": ["product-2"]})
    scoped[1][0] = replace(scoped[1][0], query_bindings=(binding,))
    async def producer(messages, tools):
        outputs = [json.loads(item["content"]) for item in messages if item["role"] == "tool"]
        if not outputs:
            return tool_call("query_metrics", json.loads(binding.parameters_json))
        if len(outputs) == 1:
            output = outputs[0]
            assert output["parent_query_id"] == first["query_id"]
            return tool_call("read_evidence", {"query_id": output["query_id"], "source_ids": [item["source_id"] for item in output["sources"]], "detail_refs": output["detail_refs"]})
        assert outputs[-1]["original_records"]
        return LLMResponse(content="SIMULATED：已读取当前产品查询的原始依据。")
    assert not run(scoped, tmp_path, producer).error
    row = runtime_records(ControlStore(scoped[0].path), "MAINTAINER")["runs"][0]
    assert row["tool_results"][0]["query_id"] == row["tool_results"][1]["query_id"]
    assert row["tool_results"][0]["bi_query_context"]["previous_query_id"] == first["query_id"]


def test_scoped_source_withdrawal_retains_historical_receipt(scoped):
    first = call(scoped, "query_metrics", scoped[2])
    scoped[0].control("ui-check", "withdraw", {"source_id": "finance-note", "version": "1"})
    with pytest.raises(web.HTTPGone):
        call(scoped, "read_evidence", {"query_id": first["query_id"], "source_ids": ["finance-note"], "detail_refs": first["detail_refs"]})
    receipt = Fc02Tool(scoped[0], lambda: scoped[1][0], "query_metrics").receipt()
    assert receipt["query"]["adoption_state"] == "HISTORICAL_REQUIRES_REQUERY"
