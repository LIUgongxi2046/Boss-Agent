import asyncio
import json
import sys
from pathlib import Path

import pytest
from aiohttp import web

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "validation"))

from boss_sector_pack import ensure_sector_pack
from controls import ControlStore
from runtime_sector_read import BossSectorReadTool
from test_product_runtime_configuration import product  # noqa: F401  (pytest fixture)


@pytest.fixture
def store(tmp_path):
    result = ControlStore(tmp_path / "sector-tool.sqlite")
    result.initialize("ui-check")
    with result.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        snapshot = result.get(db, "ui-check", "initial", "snapshot")
        ensure_sector_pack(result, db, snapshot)
    return result


def test_tool_reads_the_same_filtered_sector_projection(store):
    tool = BossSectorReadTool(store, "BOSS")
    assert tool.name == "bossSectorRead" and tool.read_only is True
    body = json.loads(asyncio.run(tool.execute("F15", {"区域": "华东"})))
    assert body["projection"] == "sector-workspace" and body["page_id"] == "F15"
    assert body["applied_filters"] == {"区域": "华东"}
    assert len(body["records"]) == 3
    assert body["metrics"][0]["value"] is not None


def test_tool_rejects_unknown_page_and_other_roles(store):
    tool = BossSectorReadTool(store, "BOSS")
    with pytest.raises(web.HTTPBadRequest):
        asyncio.run(tool.execute("F99"))
    with pytest.raises(web.HTTPForbidden):
        BossSectorReadTool(store, "MAINTAINER")


def test_sector_tool_can_be_activated_in_the_runtime_scope(product):
    runtime, commands, _ = product
    with runtime.store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        snapshot = runtime.store.get(db, "ui-check", "initial", "snapshot")
        ensure_sector_pack(runtime.store, db, snapshot)
    state = runtime.read()
    values = {"max_tool_rounds": 4, "max_output_tokens": 700,
              "tool_scope": ["query_metrics", "bossSectorRead"]}
    code, draft = commands.execute("MAINTAINER", "boss.runtime.save", {
        "client_request_id": "sector-tool-save",
        "expected_version": state["draft"]["version"] if state["draft"] else "0",
        "values": values})
    assert code == 200, draft
    code, checked = commands.execute("MAINTAINER", "boss.runtime.validate", {
        "client_request_id": "sector-tool-validate", "expected_version": draft["version"],
        "expected_content_sha256": draft["content_sha256"]})
    assert code == 200, checked
    code, activated = commands.execute("MAINTAINER", "boss.runtime.activate", {
        "client_request_id": "sector-tool-activate", "expected_version": checked["version"],
        "expected_content_sha256": checked["content_sha256"],
        "expected_active_version": state["current"]["version"]})
    assert code == 200, activated
    tool = runtime.registry.get("bossSectorRead")
    assert tool is not None
    body = json.loads(asyncio.run(tool.execute("F16", {"区域": "华东"})))
    assert body["page_id"] == "F16"
    assert body["relations"]
