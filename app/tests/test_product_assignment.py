import asyncio
import json
import sys
from pathlib import Path

import pytest
import yaml
from aiohttp import web
from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012
from nanobot import Nanobot
from nanobot.agent.loop import AgentLoop

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "validation"))

from boss_command_api import BossCommandAPI
from boss_runtime_records import runtime_records
from boss_supply_quality import SupplyQualityAPI
from product_assignment import ProductAssignment, AssignmentReadTool
from product_bi import ProductBI, FeatureProvider, FeatureRecorder, FeatureToolRegistry
from product_fc01 import REQUIRED
from product_runtime import ProductRuntime
from runtime_assignment_source_tool import BossAssignmentSourcesReadTool
from sop_write_tools.fc01 import Fc01Tool
from test_product_mvp import mvp, run_query


def validate_public(kind, value):
    directory = Path(__file__).resolve().parents[2] / "specs"
    path = directory / "product-assignment.openapi.yaml"
    resources = []
    for name in ("product-assignment.openapi.yaml", "product-fc01.openapi.yaml", "simulated-supply-quality.schema.json", "assignment-extension.schema.json", "assignment-source-review.schema.json", "business-tools.schema.json"):
        source = directory / name
        resources.append((source.as_uri(), Resource.from_contents(yaml.safe_load(source.read_text()), default_specification=DRAFT202012)))
    schema = yaml.safe_load(path.read_text())
    Draft202012Validator({**schema, "$id": path.as_uri(), "$ref": "#/components/schemas/" + kind}, registry=Registry().with_resources(resources), format_checker=FormatChecker()).validate(value)


def test_current_procurement_task_uses_public_actual_sdk_and_scoped_reads(mvp):
    store, fc01, _, _, config, payload = mvp
    prepared = run_query(mvp)
    task = fc01.coordinate("BOSS", {"client_request_id": "fc07-public-sdk-coordinate", "preparation_request_id": payload["client_request_id"], "coordinate_input": payload["coordinate_input"]}, lambda: True)
    service, bi = ProductAssignment(store), ProductBI(store)
    registry = FeatureToolRegistry()
    provider = FeatureProvider(fc01, bi, assignment=service)
    recorder = FeatureRecorder(store, registry, lambda: runtime.snapshot(), bi, assignment=service)
    loop = AgentLoop.from_config(config, provider=provider, tool_registry=registry, hook_factories=[recorder.hook_factory])
    tools = [Fc01Tool(store, fc01.context_provider, name) for name in sorted(REQUIRED)]
    tools += [AssignmentReadTool(Fc01Tool(store, fc01.context_provider, "read_assignment"), service), AssignmentReadTool(BossAssignmentSourcesReadTool(store, "BOSS"), service)]
    runtime = ProductRuntime(store, store.path.parent / "config.json", loop, registry, tools, provider)
    service.runtime = fc01.runtime = bi.runtime = runtime
    commands = BossCommandAPI(store, runtime)
    state = runtime.read()
    code, draft = commands.execute("MAINTAINER", "boss.runtime.save", {"client_request_id": "fc07-sdk-config-save", "expected_version": state["draft"]["version"],
        "values": {"max_tool_rounds": 6, "max_output_tokens": 700, "tool_scope": sorted([tool.name for tool in tools])}})
    assert code == 200, draft
    code, checked = commands.execute("MAINTAINER", "boss.runtime.validate", {"client_request_id": "fc07-sdk-config-check", "expected_version": draft["version"], "expected_content_sha256": draft["content_sha256"]})
    assert code == 200, checked
    code, active = commands.execute("MAINTAINER", "boss.runtime.activate", {"client_request_id": "fc07-sdk-config-enable", "expected_version": checked["version"], "expected_content_sha256": checked["content_sha256"], "expected_active_version": state["current"]["version"]})
    assert code == 200, active
    request = {"client_request_id": "fc07-actual-current-task", "task_id": task["task_id"], "task_version": task["version"]}
    async def execute():
        async with Nanobot(loop, config=config) as bot:
            service.bot = fc01.bot = bot
            for context in (runtime.context, fc01.scope_context, service.scope_context, recorder.context):
                bot.runtime.add_context_provider(context)
            result = await service.prepare("BOSS", request, lambda: True)
            assert await service.prepare("BOSS", request, lambda: True) == result
            view = SupplyQualityAPI(store).read("BOSS", "SI09")
            shared = await fc01.query("BOSS", {"client_request_id": "fc07-shared-current-mvp-query", "coordinate_input": {**payload["coordinate_input"], "review_sha256": view["review_sha256"]}}, lambda: True)
            shared_run = runtime_records(store, "MAINTAINER", "ui-check", run_id=shared["run_id"])["runs"][0]
            assert {tool["tool_id"] for tool in shared_run["tool_configuration"]} == REQUIRED
            return result
    result = asyncio.run(execute())
    validate_public("Prepare", request)
    validate_public("PreparationReceipt", result)
    assert result["request_state"] == "SUCCEEDED" and result["adoption_state"] == "CURRENT"
    assert result["preparation"]["task"]["task_id"] == task["task_id"]
    assert result["preparation"]["source_review"]["task"]["version"] == task["version"]
    assert result["preparation"]["business_authority_granted"] is False and result["write_performed_by_lookup"] is False
    run = runtime_records(store, "MAINTAINER", "ui-check", run_id=result["run_id"])["runs"][0]
    schema = json.loads((Path(__file__).resolve().parents[2] / "specs/runtime-records.schema.json").read_text())
    Draft202012Validator({**schema, "$ref": "#/$defs/CurrentRuntimeRun"}, format_checker=FormatChecker()).validate(run)
    assert run["feature_id"] == "FC07" and {tool["tool_id"] for tool in run["tool_configuration"]} == {"read_assignment", "assignmentSourcesRead"}
    assert run["assignment_context"]["task_id"] == task["task_id"] and run["usage"] is None and run["cost_total"] is None
    assert [tool["tool_id"] for tool in run["tool_results"]] == ["read_assignment", "assignmentSourcesRead"]
    assert payload["coordinate_input"]["purpose"] not in json.dumps(run, ensure_ascii=False)
    for role in (None, "MAINTAINER"):
        with pytest.raises(web.HTTPForbidden):
            service.receipt(role, request["client_request_id"], lambda: True)
    source = prepared["query"]["cost_report"]["current"]["source_id"]
    store.control("ui-check", "withdraw", {"source_id": source, "version": prepared["query"]["cost_report"]["current"]["source_version"]})
    old = service.receipt("BOSS", request["client_request_id"], lambda: True)
    validate_public("PreparationReceipt", old)
    assert old["adoption_state"] == "HISTORICAL_REQUIRES_REQUERY" and old["preparation"] is None
    with store.connect() as db:
        assert db.execute("SELECT count(*) FROM objects WHERE kind='task'").fetchone()[0] == 1
        assert db.execute("SELECT count(*) FROM objects WHERE kind='authorization'").fetchone()[0] == 1
        assert db.execute("SELECT count(*) FROM objects WHERE kind='outbox'").fetchone()[0] == 0
