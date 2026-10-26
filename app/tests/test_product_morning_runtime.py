import asyncio
import json
import sys
from pathlib import Path

import pytest
import yaml
from aiohttp import web
from jsonschema import Draft202012Validator, FormatChecker
from nanobot import Nanobot
from nanobot.agent.loop import AgentLoop
from nanobot.config.loader import load_config, save_config
from nanobot.config.schema import Config
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "validation"))

from boss_command_api import BossCommandAPI
from connection import settings
from controls import ControlStore
from fc03_agent.formal import FormalMorningTool, FORMAL_TOOLS
from product_bi import ProductBI, FeatureProvider, FeatureRecorder, FeatureToolRegistry, FeatureBusinessTool, BI_TOOLS
from product_fc01 import ProductFc01
from product_morning import ProductMorning
from product_runtime import ProductRuntime
from sop_write_tools.fc01 import Fc01Tool, TOOLS
from test_product_read_scope import activate
from test_product_bi_runtime import test_shared_runtime_routes_fc01_preparation_to_its_actual_recorder as verify_fc01_shared_dispatch


@pytest.fixture
def product_morning(tmp_path):
    settings()
    store = ControlStore(tmp_path / "business.sqlite")
    store.initialize("ui-check")
    config = Config.model_validate({"agents": {"defaults": {"workspace": str(tmp_path / "workspace"),
        "provider": "deepseek", "model": "deepseek-flash", "maxToolIterations": 12, "maxTokens": 700,
        "maxToolResultChars": 200000, "dream": {"enabled": False}, "idleCompactAfterMinutes": 0}},
        "providers": {"deepseek": {"apiKey": "${DEEPSEEK_API_KEY}", "apiBase": "https://api.deepseek.com"}}})
    filename = tmp_path / "config.json"
    save_config(config, filename)
    config = load_config(filename)
    fc01, bi, morning = ProductFc01(store), ProductBI(store), ProductMorning(store)
    provider, registry = FeatureProvider(fc01, bi, morning), FeatureToolRegistry()
    recorder = FeatureRecorder(store, registry, lambda: runtime.snapshot(), bi, morning)
    loop = AgentLoop.from_config(config, provider=provider, tool_registry=registry, hook_factories=[recorder.hook_factory])
    tools = [FeatureBusinessTool(store, fc01, bi, name) if name in BI_TOOLS else Fc01Tool(store, fc01.context_provider, name) for name in sorted(TOOLS)]
    tools += [FormalMorningTool(store, morning.context_provider, name) for name in sorted(FORMAL_TOOLS)]
    runtime = ProductRuntime(store, filename, loop, registry, tools, provider)
    fc01.runtime = bi.runtime = morning.runtime = runtime
    return store, morning, runtime, recorder, config


def payload(key="public-morning-current", **fields):
    return {"client_request_id": key, "date": "2026-10-24", "timezone": "Asia/Shanghai", "question": "今天有哪些事情需要本人处理", **fields}


def enable(morning, runtime):
    activate((runtime, BossCommandAPI(morning.store, runtime), None), {
        "max_tool_rounds": 6, "max_output_tokens": 700, "tool_scope": sorted(FORMAL_TOOLS)})


def validate_output(kind, value):
    directory = Path(__file__).resolve().parents[2] / "specs"
    path = directory / "product-morning.openapi.yaml"
    schema = yaml.safe_load(path.read_text())
    domain_path = directory / "morning.schema.json"
    domain = json.loads(domain_path.read_text())
    registry = Registry().with_resources([(path.as_uri(), Resource.from_contents(schema, default_specification=DRAFT202012)),
        (domain_path.as_uri(), Resource.from_contents(domain)), (domain["$id"], Resource.from_contents(domain))])
    Draft202012Validator({**schema, "$id": path.as_uri(), "$ref": "#/components/schemas/" + kind}, registry=registry, format_checker=FormatChecker()).validate(value)


def test_public_morning_actual_sdk_receipt_discussion_and_restart(product_morning):
    store, morning, runtime, recorder, config = product_morning
    enable(morning, runtime)
    async def execute():
        async with Nanobot(runtime.loop, config=config) as bot:
            morning.bot = bot
            for provider in (runtime.context, morning.scope_context, recorder.context):
                bot.runtime.add_context_provider(provider)
            original = payload()
            result = await morning.execute("BOSS", original, lambda: True)
            assert await morning.execute("BOSS", original, lambda: True) == result
            selected = result["receipt"]["result"]["list_id"]
            discussion = await morning.execute("BOSS", payload("public-morning-discuss", list_id=selected), lambda: True)
            return result, discussion
    result, discussion = asyncio.run(execute())
    assert result["request_state"] == discussion["request_state"] == "SUCCEEDED"
    assert result["receipt"] == discussion["receipt"]
    reopened = ProductMorning(ControlStore(store.path))
    assert reopened.receipt("BOSS", payload()["client_request_id"]) == result
    assert len(reopened.history("BOSS")["requests"]) == 2
    validate_output("PublicReceipt", result)
    validate_output("PublicReceipt", discussion)
    validate_output("History", reopened.history("BOSS"))
    with store.connect() as db:
        rows = [json.loads(row[0]) for row in db.execute("SELECT body FROM objects WHERE kind='runtime_run'")]
        assert db.execute("SELECT count(*) FROM objects WHERE kind='morning_list'").fetchone()[0] == 1
        assert db.execute("SELECT count(*) FROM objects WHERE kind IN ('authorization','task','outbox')").fetchone()[0] == 0
    schema = json.loads((Path(__file__).resolve().parents[2] / "specs/runtime-records.schema.json").read_text())
    for row in rows:
        assert row["feature_id"] == "FC03" and row["usage"] is None and row["cost_total"] is None
        assert {tool["tool_id"] for tool in row["tool_configuration"]} == FORMAL_TOOLS
        assert payload()["question"] not in json.dumps(row, ensure_ascii=False)
        assert row["tool_results"][0]["list_id"] == result["receipt"]["result"]["list_id"]
        Draft202012Validator({**schema, "$ref": "#/$defs/CurrentRuntimeRun"}, format_checker=FormatChecker()).validate(row)


def test_public_morning_requires_explicit_tools_and_rejects_untrusted_fields(product_morning):
    store, morning, runtime, _, _ = product_morning
    with pytest.raises(web.HTTPServiceUnavailable):
        asyncio.run(morning.execute("BOSS", payload(), lambda: True))
    for role, fields in (("MAINTAINER", {}), ("BOSS", {"owner_id": "boss-1"}), ("BOSS", {"date": "2026-02-30"}), ("BOSS", {"timezone": "Unknown/Zone"})):
        with pytest.raises(web.HTTPException):
            morning._request(role, payload(**fields), lambda: True)
    with store.connect() as db:
        assert db.execute("SELECT count(*) FROM objects WHERE kind IN ('morning_list','morning_public_request','runtime_run')").fetchone()[0] == 0


def test_public_morning_explicit_scope_and_actual_request_cancellation(product_morning):
    store, morning, runtime, recorder, config = product_morning
    async def execute():
        async with Nanobot(runtime.loop, config=config) as bot:
            morning.bot = bot
            for provider in (runtime.context, morning.scope_context, recorder.context):
                bot.runtime.add_context_provider(provider)
            with pytest.raises(web.HTTPConflict):
                await morning.execute("BOSS", payload("morning-tools-disabled"), lambda: True)
            enable(morning, runtime)
            original = payload("morning-cancel-current")
            task = asyncio.create_task(morning.execute("BOSS", original, lambda: True))
            await asyncio.sleep(0)
            canceled = morning.cancel("BOSS", original["client_request_id"], lambda: True)
            assert canceled["cancel_requested"] is True
            with pytest.raises(asyncio.CancelledError):
                await task
            saved = morning.receipt("BOSS", original["client_request_id"])
            assert saved["request_state"] == "CANCELED" and saved["receipt"]["outcome"] == "NOT_FOUND_IN_CURRENT_STORE"
            assert await morning.execute("BOSS", original, lambda: True) == saved
            with pytest.raises(web.HTTPConflict):
                await morning.execute("BOSS", {**original, "question": "明确改变的问题"}, lambda: True)
            validate_output("PublicReceipt", saved)
    asyncio.run(execute())
    with store.connect() as db:
        assert db.execute("SELECT count(*) FROM objects WHERE kind IN ('morning_list','authorization','task','outbox')").fetchone()[0] == 0


def test_morning_registration_preserves_actual_fc01_shared_dispatch(product_morning):
    store, _, runtime, recorder, config = product_morning
    verify_fc01_shared_dispatch((store, runtime.provider.bi, runtime, recorder, config))


def test_selected_morning_item_reaches_public_runtime(product_morning):
    store, morning, runtime, recorder, config = product_morning
    enable(morning, runtime)
    async def execute():
        async with Nanobot(runtime.loop, config=config) as bot:
            morning.bot = bot
            for provider in (runtime.context, morning.scope_context, recorder.context):
                bot.runtime.add_context_provider(provider)
            first = await morning.execute("BOSS", payload("menu-f01-initial", date="2026-10-23"), lambda: True)
            list_id = first["receipt"]["result"]["list_id"]
            view = morning.api.read_list("BOSS", list_id)["result"]
            item = next(item for item in view["items"] if any(ref["kind"] == "document" for ref in item["source_refs"]))
            selected = payload("menu-f01-selected", date="2026-10-23", list_id=list_id, item_id=item["item_id"])
            result = await morning.execute("BOSS", selected, lambda: True)
            assert await morning.execute("BOSS", selected, lambda: True) == result
            with pytest.raises(web.HTTPConflict):
                morning._request("BOSS", {**selected, "item_id": "unrelated-item"}, lambda: True)
            return result, item, list_id
    result, item, list_id = asyncio.run(execute())
    assert result["request_state"] == "SUCCEEDED"
    with store.connect() as db:
        run = store.get(db, "ui-check", "runtime_run", result["run_id"])
        assert db.execute("SELECT count(*) FROM objects WHERE kind='morning_list'").fetchone()[0] == 1
        assert db.execute("SELECT count(*) FROM objects WHERE kind IN ('authorization','task','outbox')").fetchone()[0] == 0
    reference = run["morning_context"]["selected_item_ref"]
    assert reference["list_id"] == list_id and reference["item_id"] == item["item_id"]
    assert reference["source_refs"] == item["source_refs"]
    details = [result for result in run["tool_results"] if result["tool_id"] == "morningDetailRead"]
    assert len(details) == 1 and details[0]["item_refs"][0]["item_id"] == item["item_id"]
    schema = json.loads((Path(__file__).resolve().parents[2] / "specs/runtime-records.schema.json").read_text())
    Draft202012Validator({**schema, "$ref": "#/$defs/CurrentRuntimeRun"}, format_checker=FormatChecker()).validate(run)
