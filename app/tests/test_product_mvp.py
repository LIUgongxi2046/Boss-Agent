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
from nanobot.config.loader import load_config, save_config
from nanobot.config.schema import Config
from nanobot.session.manager import SessionManager

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "validation"))

from boss_command_api import BossCommandAPI
from boss_supply_quality import SupplyQualityAPI, IMPORT_ACTION
from connection import settings
from controls import ControlStore
from product_bi import ProductBI, FeatureProvider, FeatureRecorder, FeatureToolRegistry, FeatureBusinessTool, BI_TOOLS
from product_fc01 import REQUIRED
from product_mvp import ProductMVP
from product_runtime import ProductRuntime
from sop_write_tools.fc01 import Fc01Tool, TOOLS
from test_boss_supply_quality import definition
from test_boss_material_cost_reports import reports_input
from test_product_read_scope import activate


def validate_output(kind, value):
    directory = Path(__file__).resolve().parents[2] / "specs"
    path = directory / "product-mvp.openapi.yaml"
    schema = yaml.safe_load(path.read_text())
    resources = []
    for name in ("product-mvp.openapi.yaml", "product-fc01.openapi.yaml", "supply-quality-results.schema.json", "simulated-supply-quality.schema.json"):
        resource_path = directory / name
        body = yaml.safe_load(resource_path.read_text())
        resources.append((resource_path.as_uri(), Resource.from_contents(body, default_specification=DRAFT202012)))
    registry = Registry().with_resources(resources)
    Draft202012Validator({**schema, "$id": path.as_uri(), "$ref": "#/components/schemas/" + kind}, registry=registry, format_checker=FormatChecker()).validate(value)


@pytest.fixture
def mvp(tmp_path):
    settings()
    store = ControlStore(tmp_path / "mvp.sqlite")
    store.initialize("ui-check")
    api = SupplyQualityAPI(store)
    api.execute("MAINTAINER", IMPORT_ACTION, definition()["initial_request"])
    api.execute("MAINTAINER", IMPORT_ACTION, reports_input())
    config = Config.model_validate({"agents": {"defaults": {"workspace": str(tmp_path / "workspace"), "provider": "deepseek", "model": "deepseek-flash",
        "maxToolIterations": 6, "maxTokens": 700, "maxToolResultChars": 200000, "dream": {"enabled": False}, "idleCompactAfterMinutes": 0}},
        "providers": {"deepseek": {"apiKey": "${DEEPSEEK_API_KEY}", "apiBase": "https://api.deepseek.com"}}})
    path = tmp_path / "config.json"
    save_config(config, path)
    config = load_config(path)
    service, bi = ProductMVP(store), ProductBI(store)
    registry, provider = FeatureToolRegistry(), FeatureProvider(service, bi)
    recorder = FeatureRecorder(store, registry, lambda: runtime.snapshot(), bi)
    sessions = SessionManager(tmp_path / "workspace", sessions_root=tmp_path / "sessions")
    loop = AgentLoop.from_config(config, provider=provider, tool_registry=registry,
                                 session_manager=sessions, hook_factories=[recorder.hook_factory])
    tools = [FeatureBusinessTool(store, service, bi, name) if name in BI_TOOLS else Fc01Tool(store, service.context_provider, name) for name in sorted(TOOLS)]
    runtime = ProductRuntime(store, path, loop, registry, tools, provider)
    service.runtime = bi.runtime = runtime
    activate((runtime, BossCommandAPI(store, runtime), None), {"max_tool_rounds": 6, "max_output_tokens": 700, "tool_scope": sorted(REQUIRED)})
    view = api.read("BOSS", "SI09")
    report = view["supply"][0]["cost_reports"][0]
    origin = next(record for record in view["records"] if record["record_id"] == report["current"]["report_id"])
    payload = {"client_request_id": "mvp-current-query", "coordinate_input": {"interface_id": "SI09", "origin_entity_type": "material_cost_report",
        "origin_record_id": origin["record_id"], "origin_version": origin["version"], "review_sha256": view["review_sha256"], "purpose": "核查当前采购报告成本并协调反馈",
        "coordinator_id": "coordinator-1", "due_at": "2026-10-25T17:00:00+08:00", "timezone": "Asia/Shanghai", "evidence_requirements": ["当前成本报告及协调反馈"]}}
    return store, service, runtime, recorder, config, payload


def run_query(mvp):
    _, service, runtime, recorder, config, payload = mvp
    async def execute():
        async with Nanobot(runtime.loop, config=config) as bot:
            service.bot = bot
            for context in (runtime.context, recorder.context):
                bot.runtime.add_context_provider(context)
            result = await service.query("BOSS", payload, lambda: True)
            assert await service.query("BOSS", payload, lambda: True) == result
            return result
    return asyncio.run(execute())


def test_mvp_actual_query_source_confirmation_and_saved_record(mvp):
    store, service, _, _, _, payload = mvp
    result = run_query(mvp)
    validate_output("Receipt", result)
    validate_output("History", service.serve("BOSS", "/api/boss/ui/mvp/history", ""))
    assert result["request_state"] == "SUCCEEDED" and result["adoption_state"] == "CURRENT"
    report = result["query"]["cost_report"]
    assert report["current"]["unit_cost"] == "2150" and report["baseline"]["unit_cost"] == "2000"
    assert report["unit_cost_change"] == "150" and report["currency"] == "CNY"
    source = report["current"]["source_id"]
    document = service.serve("BOSS", "/api/boss/ui/mvp/source", "client_request_id=" + payload["client_request_id"] + "&source_id=" + source)
    assert document["source_id"] == source and document["version"] == report["current"]["source_version"]
    with store.connect() as db:
        assert db.execute("SELECT count(*) FROM objects WHERE kind IN ('task','authorization','outbox')").fetchone()[0] == 0
        run = store.get(db, "ui-check", "runtime_run", result["run_id"])
        assert {row["tool_id"] for row in run["tool_configuration"]} == REQUIRED and run["usage"] is None and run["cost_total"] is None
    adopt = {"client_request_id": "mvp-current-coordinate", "preparation_request_id": payload["client_request_id"], "coordinate_input": payload["coordinate_input"]}
    created = service.coordinate("BOSS", adopt, lambda: True)
    assert service.coordinate("BOSS", adopt, lambda: True) == created
    reopened = ProductMVP(ControlStore(store.path))
    assert reopened.receipt("BOSS", payload["client_request_id"], lambda: True) == result
    with store.connect() as db:
        assert db.execute("SELECT count(*) FROM objects WHERE kind='task'").fetchone()[0] == 1
        assert store.get(db, "ui-check", "supply_quality_coordination", "supply-quality-" + created["task_id"])["origin_record_id"] == payload["coordinate_input"]["origin_record_id"]


def test_mvp_source_scope_and_invalidated_query_never_authorize(mvp):
    store, service, _, _, _, payload = mvp
    result = run_query(mvp)
    for role in (None, "MAINTAINER"):
        with pytest.raises(web.HTTPException):
            service.serve(role, "/api/boss/ui/mvp/query", "client_request_id=" + payload["client_request_id"])
    with pytest.raises(web.HTTPForbidden):
        service.serve("BOSS", "/api/boss/ui/mvp/source", "client_request_id=" + payload["client_request_id"] + "&source_id=finance-note")
    source = result["query"]["cost_report"]["current"]["source_id"]
    store.control("ui-check", "withdraw", {"source_id": source, "version": result["query"]["cost_report"]["current"]["source_version"]})
    invalid = service.receipt("BOSS", payload["client_request_id"], lambda: True)
    validate_output("Receipt", invalid)
    assert invalid["adoption_state"] == "HISTORICAL_REQUIRES_REQUERY" and invalid["query"] is None and invalid["preparation"] is None
    with pytest.raises(web.HTTPException):
        service.coordinate("BOSS", {"client_request_id": "mvp-invalid-coordinate", "preparation_request_id": payload["client_request_id"], "coordinate_input": payload["coordinate_input"]}, lambda: True)
    with store.connect() as db:
        assert db.execute("SELECT count(*) FROM objects WHERE kind IN ('task','authorization','outbox')").fetchone()[0] == 0
