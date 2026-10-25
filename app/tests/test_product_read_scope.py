import asyncio
import json
import sys
from pathlib import Path

import pytest
from aiohttp import web

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "validation"))

from boss_agent_read_tools import BossResearchSourcesTool
from boss_page_api import BossPageAPI
from test_product_runtime_configuration import product

NEW_READS = {"bossDashboardRead", "bossMeetingsRead", "bossEvidenceRead", "bossTasksRead", "bossCalendarConflictRead", "bossCalendarSharePreview"}


def activate(product, values, key="public-read-scope"):
    runtime, commands, _ = product
    state = runtime.read()
    code, draft = commands.execute("MAINTAINER", "boss.runtime.save", {"client_request_id": key + "-save",
        "expected_version": state["draft"]["version"] if state["draft"] else "0", "values": values})
    assert code == 200, draft
    code, checked = commands.execute("MAINTAINER", "boss.runtime.validate", {"client_request_id": key + "-validate",
        "expected_version": draft["version"], "expected_content_sha256": draft["content_sha256"]})
    assert code == 200, checked
    payload = {"client_request_id": key + "-activate", "expected_version": checked["version"],
        "expected_content_sha256": checked["content_sha256"], "expected_active_version": state["current"]["version"]}
    response = commands.execute("MAINTAINER", "boss.runtime.activate", payload)
    assert response[0] == 200, response
    assert commands.execute("MAINTAINER", "boss.runtime.activate", payload) == response
    return response[1]


def test_public_read_catalog_keeps_initial_scope_and_legacy_research_semantics(product):
    runtime, _, pages = product
    code, view = pages.serve("MAINTAINER", "/api/boss/ui/admin/runtime-configuration")
    assert code == 200 and NEW_READS <= set(view["available_tools"])
    assert not (NEW_READS & set(runtime.registry.tool_names))
    assert view["current"]["workspace_read_mode"] == "SOURCE_EXCERPTS"
    assert view["workspace_access"] == {"mode": "SOURCE_EXCERPTS", "enabled": False, "allowed_projections": []}
    activate(product, {"max_tool_rounds": 4, "max_output_tokens": 700, "tool_scope": ["query_metrics", "bossWorkspaceRead"]})
    assert isinstance(runtime.registry.get("bossWorkspaceRead"), BossResearchSourcesTool)
    assert runtime.read()["workspace_access"] == {"mode": "SOURCE_EXCERPTS", "enabled": True, "allowed_projections": ["research"]}
    _, _, error = runtime.registry.prepare_call("bossWorkspaceRead", {"projection": "knowledge"})
    assert error


def test_legacy_research_execution_rejects_other_projection_without_writes(product):
    runtime, _, _ = product
    tool = BossResearchSourcesTool(runtime.store, "BOSS")
    with runtime.store.connect() as db:
        before = tuple(db.iterdump())
    with pytest.raises(web.HTTPForbidden):
        asyncio.run(tool.execute("knowledge"))
    with runtime.store.connect() as db:
        assert tuple(db.iterdump()) == before


def test_explicit_workspace_projection_mode_registers_only_selected_scope_and_reads_actual_state(product):
    runtime, _, _ = product
    values = {"max_tool_rounds": 4, "max_output_tokens": 700, "tool_scope": ["query_metrics", "bossWorkspaceRead", "bossTasksRead", "bossEvidenceRead"],
        "workspace_read_mode": "WORKSPACE_PROJECTIONS", "workspace_projections": ["research", "knowledge"]}
    activate(product, values)
    tool = runtime.registry.get("bossWorkspaceRead")
    assert not isinstance(tool, BossResearchSourcesTool)
    assert tool.allowed_projections == frozenset({"research", "knowledge"})
    assert runtime.registry.tool_names.count("bossWorkspaceRead") == 1
    assert runtime.read()["workspace_access"] == {"mode": "WORKSPACE_PROJECTIONS", "enabled": True, "allowed_projections": ["knowledge", "research"]}
    assert tool.parameters["properties"]["projection"]["enum"] == ["knowledge", "research"]
    for projection in ("memory", "approvals", "source-index"):
        _, _, error = runtime.registry.prepare_call("bossWorkspaceRead", {"projection": projection})
        assert error
    with runtime.store.connect() as db:
        before = tuple(db.iterdump())
    result = json.loads(asyncio.run(tool.execute("knowledge")))
    code, expected = BossPageAPI(runtime.store).serve("BOSS", "/api/boss/ui/workspace/knowledge")
    assert code == 200
    assert {key: value for key, value in result.items() if key != "read_at"} == {key: value for key, value in expected.items() if key != "read_at"}
    evidence = json.loads(asyncio.run(runtime.registry.get("bossEvidenceRead").execute("finance-note")))
    assert evidence["source_id"] == "finance-note" and evidence["content"]
    tasks = json.loads(asyncio.run(runtime.registry.get("bossTasksRead").execute()))
    assert tasks["tasks"] == []
    with runtime.store.connect() as db:
        assert tuple(db.iterdump()) == before


@pytest.mark.parametrize("mode,projections", [("WORKSPACE_PROJECTIONS", []), ("WORKSPACE_PROJECTIONS", ["source-index"]),
    ("WORKSPACE_PROJECTIONS", ["memory", "memory"]), ("SOURCE_EXCERPTS", ["knowledge"]), ("ALL", ["knowledge"])])
def test_public_runtime_rejects_ambiguous_or_excess_workspace_scope(product, mode, projections):
    runtime, commands, _ = product
    with runtime.store.connect() as db:
        before = tuple(db.iterdump())
    code, _ = commands.execute("MAINTAINER", "boss.runtime.save", {"client_request_id": "public-invalid-workspace-scope", "expected_version": "0",
        "values": {"max_tool_rounds": 4, "max_output_tokens": 700, "tool_scope": ["query_metrics", "bossWorkspaceRead"],
            "workspace_read_mode": mode, "workspace_projections": projections}})
    assert code == 400
    with runtime.store.connect() as db:
        assert tuple(db.iterdump()) == before
