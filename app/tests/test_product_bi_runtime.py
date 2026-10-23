import asyncio
import json
from pathlib import Path

import pytest
import yaml
from aiohttp import web
from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012
from nanobot import Nanobot
from nanobot.agent.loop import AgentLoop
from nanobot.config.loader import save_config
from nanobot.config.schema import Config

from test_fc02_bi_queries import request
from boss_command_api import BossCommandAPI
from controls import ControlStore
from connection import settings
from product_bi import ProductBI, FeatureProvider, FeatureRecorder, FeatureToolRegistry, FeatureBusinessTool, BI_TOOLS
from product_fc01 import ProductFc01
from product_runtime import ProductRuntime
from sop_write_tools.fc01 import Fc01Tool, TOOLS
from boss_supply_quality import SupplyQualityAPI, IMPORT_ACTION
from test_boss_supply_quality import definition
from test_boss_material_cost_reports import reports_input
from test_product_read_scope import activate
from product_fc01 import REQUIRED


@pytest.fixture
def product_bi(tmp_path):
    settings()
    store = ControlStore(tmp_path / "business.sqlite")
    store.initialize("ui-check")
    config = Config.model_validate({"agents":{"defaults":{"workspace":str(tmp_path / "workspace"),
        "provider":"deepseek","model":"deepseek-flash","maxToolIterations":12,"maxTokens":700,
        "maxToolResultChars":200000,"dream":{"enabled":False},"idleCompactAfterMinutes":0}},
        "providers":{"deepseek":{"apiKey":"${DEEPSEEK_API_KEY}","apiBase":"https://api.deepseek.com"}}})
    filename = tmp_path / "config.json"
    save_config(config, filename)
    fc01, bi = ProductFc01(store), ProductBI(store)
    provider = FeatureProvider(fc01, bi)
    registry = FeatureToolRegistry()
    recorder = FeatureRecorder(store, registry, lambda: runtime.snapshot(), bi)
    loop = AgentLoop.from_config(config, provider=provider, tool_registry=registry, hook_factories=[recorder.hook_factory])
    tools = [FeatureBusinessTool(store,fc01,bi,name) if name in BI_TOOLS else Fc01Tool(store,fc01.context_provider,name) for name in sorted(TOOLS)]
    runtime = ProductRuntime(store,filename,loop,registry,tools,provider)
    fc01.runtime = bi.runtime = runtime
    return store, bi, runtime, recorder, config


def payload(key="public-bi-current", **scope):
    params = request(**scope)
    return {"client_request_id":key,"question":params.pop("question"),
            "scope":{name:value for name,value in params.items() if name not in {"envelope","query_mode"}}}


def validate_public_output(kind, body):
    directory = Path(__file__).resolve().parents[2] / "specs"
    path = directory / "product-bi.openapi.yaml"
    schema = yaml.safe_load(path.read_text())
    core = directory / "openapi.yaml"
    registry = Registry().with_resources([(path.as_uri(),Resource.from_contents(schema,default_specification=DRAFT202012)),
        (core.as_uri(),Resource.from_contents(yaml.safe_load(core.read_text()),default_specification=DRAFT202012)),
        ((directory / "bi-scenario-input.schema.json").as_uri(),Resource.from_contents(json.loads((directory / "bi-scenario-input.schema.json").read_text())))])
    Draft202012Validator({**schema,"$id":path.as_uri(),"$ref":"#/components/schemas/"+kind},registry=registry,format_checker=FormatChecker()).validate(body)


def test_public_bi_actual_runtime_followup_and_persistent_receipt(product_bi):
    store, bi, runtime, recorder, config = product_bi
    original = payload()
    async def execute():
        async with Nanobot(runtime.loop,config=config) as bot:
            bi.bot = bot
            for provider in (runtime.context,bi.scope_context,recorder.context):
                bot.runtime.add_context_provider(provider)
            first = await bi.execute("BOSS",original,False,lambda:True)
            assert await bi.execute("BOSS",original,False,lambda:True) == first
            parent = first["receipt"]["query"]["result"]
            follow = {"client_request_id":"public-bi-follow","question":"继续查询product-1", "parent_query_id":parent["query_id"],"overrides":{"product_ids":["product-1"]}}
            child = await bi.execute("BOSS",follow,True,lambda:True)
            incomparable = await bi.execute("BOSS",{**follow,"client_request_id":"public-bi-compare", "overrides":{"comparison_scope":{"currency":"USD"}}},True,lambda:True)
            assert incomparable["receipt"]["query"]["result"]["comparison"]["state"] == "INCOMPARABLE"
            return first, child
    first, child = asyncio.run(execute())
    parent, query = first["receipt"]["query"]["result"], child["receipt"]["query"]["result"]
    assert child["request_state"] == "SUCCEEDED" and query["parent_query_id"] == parent["query_id"]
    assert query["envelope"]["session_id"] == parent["envelope"]["session_id"]
    assert query["overridden_fields"] == ["product_ids"] and len(query["detail_refs"]) == 4
    reopened = ProductBI(ControlStore(store.path))
    assert reopened.receipt("BOSS","public-bi-follow") == child
    validate_public_output("PublicReceipt",child)
    validate_public_output("QueryRead",child["receipt"]["query"])
    validate_public_output("Dimensions",reopened.serve("BOSS","/api/boss/ui/bi/dimensions",""))
    validate_public_output("History",reopened.serve("BOSS","/api/boss/ui/bi/history",""))
    assert reopened.serve("BOSS","/api/boss/ui/bi/query","query_id="+query["query_id"])["result"] == query
    with store.connect() as db:
        row = store.get(db,"ui-check","runtime_run",child["run_id"])
        assert db.execute("SELECT count(*) FROM objects WHERE kind='query'").fetchone()[0] == 3
        assert db.execute("SELECT count(*) FROM objects WHERE kind IN ('authorization','task','outbox')").fetchone()[0] == 0
    assert row["feature_id"] == "FC02" and row["usage"] is None and row["cost_total"] is None
    assert {item["tool_id"] for item in row["tool_configuration"]} == BI_TOOLS
    assert [item["query_id"] for item in row["tool_results"]] == [query["query_id"],query["query_id"]]
    assert row["tool_results"][0]["bi_query_context"]["overridden_fields"] == ["product_ids"]
    assert original["question"] not in json.dumps(row,ensure_ascii=False)
    schema = json.loads((Path(__file__).resolve().parents[2] / "specs/runtime-records.schema.json").read_text())
    Draft202012Validator({**schema,"$ref":"#/$defs/CurrentRuntimeRun"},format_checker=FormatChecker()).validate(row)
    assert set(runtime.registry.tool_names) == set(runtime.read()["current"]["tool_scope"])


def test_public_bi_refuses_untrusted_scope_and_role_without_query(product_bi):
    store, bi, runtime, recorder, config = product_bi
    async def execute():
        with pytest.raises(web.HTTPForbidden):
            await bi.execute("MAINTAINER",payload(),False,lambda:True)
        with pytest.raises(web.HTTPBadRequest):
            invalid = payload()
            invalid["scope"]["envelope"] = {"owner_id":"other"}
            bi._request("BOSS",invalid,False,lambda:True)
    asyncio.run(execute())
    for role in (None,"MAINTAINER"):
        with pytest.raises(web.HTTPException):
            bi.serve(role,"/api/boss/ui/bi/dimensions","")
    for key in ("short","a" * 129,"经营请求编号"):
        with pytest.raises(web.HTTPBadRequest):
            bi.receipt("BOSS",key)
        with pytest.raises(web.HTTPBadRequest):
            bi.cancel("BOSS",key,lambda:True)
    with pytest.raises(web.HTTPNotFound):
        bi.serve("BOSS","/api/boss/ui/bi/unknown/dimensions","")
    with store.connect() as db:
        assert db.execute("SELECT count(*) FROM objects WHERE kind IN ('query','bi_public_request','runtime_run')").fetchone()[0] == 0


def test_public_bi_cancel_preserves_query_and_original_request(product_bi):
    store, bi, runtime, recorder, config = product_bi
    original = payload("public-bi-cancel")
    async def execute():
        async with Nanobot(runtime.loop,config=config) as bot:
            bi.bot = bot
            for provider in (runtime.context,bi.scope_context,recorder.context):
                bot.runtime.add_context_provider(provider)
            task = asyncio.create_task(bi.execute("BOSS",original,False,lambda:True))
            while True:
                with store.connect() as db:
                    count = db.execute("SELECT count(*) FROM objects WHERE kind='query'").fetchone()[0]
                if count:
                    break
                assert not task.done()
                await asyncio.sleep(0)
            canceled = bi.cancel("BOSS",original["client_request_id"],lambda:True)
            assert canceled["cancel_requested"] is True
            with pytest.raises(asyncio.CancelledError):
                await task
            return bi.receipt("BOSS",original["client_request_id"])
    receipt = asyncio.run(execute())
    assert receipt["request_state"] == "CANCELED" and receipt["receipt"]["outcome"] == "RECORDED"
    query = receipt["receipt"]["query"]["result"]
    reopened = ProductBI(ControlStore(store.path))
    assert reopened.receipt("BOSS",original["client_request_id"]) == receipt
    store.control("ui-check","withdraw",{"source_id":"finance-note","version":"1"})
    assert reopened.receipt("BOSS",original["client_request_id"])["receipt"]["query"]["adoption_state"] == "HISTORICAL_REQUIRES_REQUERY"
    with pytest.raises(web.HTTPGone):
        reopened.api.read("BOSS",query["query_id"])
    with store.connect() as db:
        assert db.execute("SELECT count(*) FROM objects WHERE kind='query'").fetchone()[0] == 1


def test_shared_runtime_routes_fc01_preparation_to_its_actual_recorder(product_bi):
    store, bi, runtime, recorder, config = product_bi
    SupplyQualityAPI(store).execute("MAINTAINER",IMPORT_ACTION,definition()["initial_request"])
    SupplyQualityAPI(store).execute("MAINTAINER",IMPORT_ACTION,reports_input())
    activate((runtime,BossCommandAPI(store,runtime),None),{"max_tool_rounds":6,"max_output_tokens":700,"tool_scope":sorted(REQUIRED)})
    view = SupplyQualityAPI(store).read("BOSS","SI09")
    origin = next(row for row in view["records"] if row["record_id"] == "sim-cost-inbound_receipt-1")
    params = {"interface_id":"SI09","origin_entity_type":origin["entity_type"],"origin_record_id":origin["record_id"],
        "origin_version":origin["version"],"review_sha256":view["review_sha256"],"purpose":"核查当前采购依据",
        "coordinator_id":"coordinator-1","due_at":"2026-10-25T17:00:00+08:00","timezone":"Asia/Shanghai","evidence_requirements":["当前资料"]}
    fc01 = runtime.provider.fc01
    async def execute():
        async with Nanobot(runtime.loop,config=config) as bot:
            fc01.bot = bot
            for provider in (runtime.context,bi.scope_context,recorder.context):
                bot.runtime.add_context_provider(provider)
            return await fc01.prepare("BOSS",{"client_request_id":"shared-fc01-prepare","coordinate_input":params},lambda:True)
    result = asyncio.run(execute())
    with store.connect() as db:
        run = store.get(db,"ui-check","runtime_run",result["run_id"])
    assert run["feature_id"] == "FC01" and run["status"] == "SUCCEEDED"
    assert run["usage"] is None and run["cost_total"] is None
    assert {item["tool_id"] for item in run["tool_configuration"]} == REQUIRED
    assert result["owner_decision_required"] is True and "bi_query_context" not in run
