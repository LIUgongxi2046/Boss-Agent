import asyncio
import json
import sys
from pathlib import Path

import pytest
from aiohttp import web
from jsonschema import Draft202012Validator, FormatChecker
from nanobot import Nanobot
from nanobot.agent.loop import AgentLoop
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.config.schema import Config
from nanobot.config.loader import load_config, save_config

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "validation"))
from connection import settings
from boss_command_api import BossCommandAPI
from boss_supply_quality import SupplyQualityAPI, IMPORT_ACTION
from product_fc01 import ProductFc01, REQUIRED
from product_runtime import ProductRuntime
from runtime_records_query import read_runtime_task_reference
from sop_write_tools.fc01 import Fc01Tool, TOOLS
from sop_write_tools.fc01.runtime import Fc01RuntimeRecorder
from test_boss_supply_quality import store, definition
from test_boss_material_cost_reports import reports_input
from test_product_read_scope import activate


@pytest.mark.parametrize("interface", ["SI09", "SI10"])
def test_public_runtime_preparation_and_owner_adoption_preserve_same_task(store, tmp_path, interface):
    settings()
    SupplyQualityAPI(store).execute("MAINTAINER", IMPORT_ACTION, definition()["initial_request"])
    SupplyQualityAPI(store).execute("MAINTAINER", IMPORT_ACTION, reports_input())
    service = ProductFc01(store)
    config = Config.model_validate({"agents":{"defaults":{"workspace":str(tmp_path / "workspace"),"provider":"deepseek","model":"deepseek-flash","maxToolIterations":12,"maxTokens":4096,"maxToolResultChars":200000,"dream":{"enabled":False}}},"providers":{"deepseek":{"apiKey":"${DEEPSEEK_API_KEY}","apiBase":"https://api.deepseek.com"}}})
    filename = tmp_path / "config.json"
    save_config(config, filename)
    config = load_config(filename)
    registry = ToolRegistry()
    recorder = Fc01RuntimeRecorder(store, "ui-check", registry, lambda: runtime.snapshot())
    loop = AgentLoop.from_config(config, provider=service.provider, tool_registry=registry, hook_factories=[recorder.hook_factory])
    tools = [Fc01Tool(store, service.context_provider, name) for name in sorted(TOOLS)]
    runtime = ProductRuntime(store, filename, loop, registry, tools, service.provider)
    service.runtime = runtime
    activate((runtime,BossCommandAPI(store,runtime),None), {"max_tool_rounds":6,"max_output_tokens":700,"tool_scope":sorted(REQUIRED)})
    view = SupplyQualityAPI(store).read("BOSS",interface)
    origin = next(record for record in view["records"] if record["record_id"] == ("sim-cost-inbound_receipt-1" if interface == "SI09" else "sim-production-event-1"))
    if interface == "SI09":
        assert {report["current"]["unit_cost"] for report in view["supply"][0]["cost_reports"]} == {"2100","2150"}
    params = {"interface_id":interface,"origin_entity_type":origin["entity_type"],"origin_record_id":origin["record_id"],"origin_version":origin["version"],"review_sha256":view["review_sha256"],"purpose":"核查当前品质依据","coordinator_id":"coordinator-1","due_at":"2026-10-25T17:00:00+08:00","timezone":"Asia/Shanghai","evidence_requirements":["当前核查材料"]}
    payload = {"client_request_id":"public-fc01-prepare","coordinate_input":params}
    async def run():
        async with Nanobot(loop,config=config) as bot:
            service.bot = bot
            bot.runtime.add_context_provider(runtime.context)
            bot.runtime.add_context_provider(recorder.context)
            with pytest.raises(web.HTTPForbidden):
                await service.prepare("MAINTAINER",payload,lambda:True)
            output = await service.prepare("BOSS",payload,lambda:True)
            assert await service.prepare("BOSS",payload,lambda:True) == output
            return output
    output = asyncio.run(run())
    assert output["coordinate_input"] == params and output["owner_decision_required"] is True
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind IN ('task','authorization','outbox')").fetchone()[0] == 0
    adopted = {"client_request_id":"public-fc01-coordinate","preparation_request_id":payload["client_request_id"],"coordinate_input":params}
    created = service.coordinate("BOSS",adopted,lambda:True)
    assert service.coordinate("BOSS",adopted,lambda:True) == created
    assert read_runtime_task_reference(store,"MAINTAINER","ui-check",output["run_id"],created["task_id"])["task_status"] == "OPEN"
    with store.connect() as db:
        row = store.get(db,"ui-check","runtime_run",output["run_id"])
        assert row["owner_task_links"][0]["task_id"] == created["task_id"]
        assert row["source_type"] == "SIMULATED" and row["usage"] is None and row["cost_total"] is None
        assert len(row["simulated_model_events"]) == 5
        assert [item["tool_id"] for item in row["tool_results"]] == ["bossSupplyQualityRead","bossSupplyQualityQuery","bossEvidenceRead","bossSupplyQualityPrepare"]
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind='task'").fetchone()[0] == 1
    schema = json.loads((ROOT / "specs/runtime-records.schema.json").read_text())
    Draft202012Validator({**schema,"$ref":"#/$defs/CurrentRuntimeRun"},format_checker=FormatChecker()).validate(row)
    with pytest.raises(web.HTTPConflict):
        service.coordinate("BOSS",{**adopted,"coordinate_input":{**params,"purpose":"其他内容"}},lambda:True)
    with pytest.raises(web.HTTPForbidden):
        service.coordinate("BOSS",adopted,lambda:False)
