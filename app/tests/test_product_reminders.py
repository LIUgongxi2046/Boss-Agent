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

from boss_agent_read_tools import BossResearchSourcesTool
from boss_command_api import BossCommandAPI
from boss_page_api import BossPageAPI
from boss_runtime_records import runtime_records
from boss_supply_quality import SupplyQualityAPI
from product_bi import ProductBI, FeatureProvider, FeatureRecorder, FeatureToolRegistry
from product_fc01 import REQUIRED
from product_reminders import ProductReminders
from product_runtime import ProductRuntime
from sop_write_tools.fc01 import Fc01Tool
from test_product_mvp import mvp


def validate_public(kind, value):
    directory = Path(__file__).resolve().parents[2] / "specs"
    path = directory / "product-reminders.openapi.yaml"
    resources = []
    for name in ("product-reminders.openapi.yaml", "product-fc01.openapi.yaml", "simulated-supply-quality.schema.json", "business-alert.schema.json"):
        source = directory / name
        resources.append((source.as_uri(), Resource.from_contents(yaml.safe_load(source.read_text()), default_specification=DRAFT202012)))
    schema = yaml.safe_load(path.read_text())
    Draft202012Validator({**schema, "$id": path.as_uri(), "$ref": "#/components/schemas/" + kind}, registry=Registry().with_resources(resources), format_checker=FormatChecker()).validate(value)


def test_public_reminder_request_adopts_actual_scoped_sdk_and_preserves_shared_mvp(mvp):
    store, fc01, _, _, config, payload = mvp
    service, bi = ProductReminders(store), ProductBI(store)
    registry = FeatureToolRegistry()
    provider = FeatureProvider(fc01, bi, reminders=service)
    recorder = FeatureRecorder(store, registry, lambda: runtime.snapshot(), bi, reminders=service)
    loop = AgentLoop.from_config(config, provider=provider, tool_registry=registry, hook_factories=[recorder.hook_factory])
    tools = [Fc01Tool(store, fc01.context_provider, name) for name in sorted(REQUIRED)] + [BossResearchSourcesTool(store, "BOSS")]
    runtime = ProductRuntime(store, store.path.parent / "config.json", loop, registry, tools, provider,
        workspace_api=BossPageAPI(store), workspace_tool_factory=service.workspace_tool)
    service.runtime = fc01.runtime = bi.runtime = runtime
    commands = BossCommandAPI(store, runtime)
    code, seeded = commands.execute("MAINTAINER", "boss.simulation.event.seed", {"client_request_id": "fc04-sdk-current-event", "event_id": "event-1"})
    assert code == 200, seeded
    code, observation = commands.execute("MAINTAINER", "boss.simulation.alert.load", {"client_request_id": "fc04-sdk-current-observation", "expected_version": "0", "mode": "SIMULATED", "definition_version": "FC04-ALERT-1", "seed": 20261024, "frame": "RESOURCE_SHORTAGE"})
    assert code == 200, observation
    current = runtime.read()
    code, saved = commands.execute("MAINTAINER", "boss.runtime.save", {"client_request_id": "fc04-sdk-save", "expected_version": current["draft"]["version"],
        "values": {"max_tool_rounds": 6, "max_output_tokens": 700, "tool_scope": sorted(tool.name for tool in tools), "workspace_read_mode": "WORKSPACE_PROJECTIONS", "workspace_projections": ["memory", "notifications"]}})
    assert code == 200, saved
    code, checked = commands.execute("MAINTAINER", "boss.runtime.validate", {"client_request_id": "fc04-sdk-check", "expected_version": saved["version"], "expected_content_sha256": saved["content_sha256"]})
    assert code == 200, checked
    code, enabled = commands.execute("MAINTAINER", "boss.runtime.activate", {"client_request_id": "fc04-sdk-enable", "expected_version": checked["version"], "expected_content_sha256": checked["content_sha256"], "expected_active_version": current["current"]["version"]})
    assert code == 200, enabled
    request = {"client_request_id": "fc04-sdk-current-preparation"}
    async def execute():
        async with Nanobot(loop, config=config) as bot:
            service.bot = fc01.bot = bot
            for context in (runtime.context, fc01.scope_context, service.scope_context, recorder.context):
                bot.runtime.add_context_provider(context)
            value = await service.prepare("BOSS", request, lambda: True)
            assert await service.prepare("BOSS", request, lambda: True) == value
            supply = SupplyQualityAPI(store).read("BOSS", "SI09")
            shared = await fc01.query("BOSS", {"client_request_id": "fc04-shared-mvp-current", "coordinate_input": {**payload["coordinate_input"], "review_sha256": supply["review_sha256"]}}, lambda: True)
            shared_run = runtime_records(store, "MAINTAINER", "ui-check", run_id=shared["run_id"])["runs"][0]
            assert {tool["tool_id"] for tool in shared_run["tool_configuration"]} == REQUIRED
            return value
    result = asyncio.run(execute())
    validate_public("Receipt", result)
    assert result["request_state"] == "SUCCEEDED" and result["adoption_state"] == "CURRENT"
    projection = result["preparation"]["projection"]
    assert projection["events"][0]["event_id"] == "event-1" and projection["rules"][0]["version"] == "1"
    assert projection["notifications"] == [] and projection["dispatches"] == []
    assert result["preparation"]["business_authority_granted"] is False and result["write_performed_by_lookup"] is False
    run = runtime_records(store, "MAINTAINER", "ui-check", run_id=result["run_id"])["runs"][0]
    schema = json.loads((Path(__file__).resolve().parents[2] / "specs/runtime-records.schema.json").read_text())
    Draft202012Validator({**schema, "$ref": "#/$defs/CurrentRuntimeRun"}, format_checker=FormatChecker()).validate(run)
    assert run["feature_id"] == "FC04" and run["reminder_context"]["projection_sha256"] == result["projection_sha256"]
    assert [tool["tool_id"] for tool in run["tool_configuration"]] == ["bossWorkspaceRead"]
    assert run["tool_results"][0]["rule_versions"] == ["1"] and run["tool_results"][0]["event_refs"][0]["event_id"] == "event-1"
    actual_alert = projection["business_alerts"]["items"][0]
    reference = run["tool_results"][0]["business_alert_refs"][0]
    assert reference["event_id"] == observation["event_id"] and reference["event_version"] == observation["event_version"]
    assert reference["business_rule_version"] == (actual_alert["business_rule"]["version"] if actual_alert["business_rule"] is not None else None)
    assert reference["review_sha256"] == actual_alert["review_sha256"]
    assert reference["sources"] == [{field: source[field] for field in ("source_id", "version", "status", "sha256") if field in source} for source in actual_alert["sources"]]
    assert not {"facts", "documents", "participation_reason"} & set(reference)
    assert run["usage"] is None and run["cost_total"] is None
    assert "SIMULATED：读取当前获准的经营提醒" not in json.dumps(run, ensure_ascii=False)
    for role in (None, "MAINTAINER"):
        with pytest.raises(web.HTTPForbidden):
            service.receipt(role, request["client_request_id"], lambda: True)
    assert commands.execute("BOSS", "boss.reminder.ack", {"client_request_id": "fc04-sdk-owner-ack", "event_id": "event-1", "event_version": "1", "reminder_version": "0"})[0] == 200
    historical = service.receipt("BOSS", request["client_request_id"], lambda: True)
    validate_public("Receipt", historical)
    assert historical["adoption_state"] == "HISTORICAL_REQUIRES_REQUERY" and historical["preparation"] is None
    with store.connect() as db:
        assert db.execute("SELECT count(*) FROM objects WHERE kind IN ('task','outbox','notification','dispatch')").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM objects WHERE kind='authorization'").fetchone()[0] == 1
