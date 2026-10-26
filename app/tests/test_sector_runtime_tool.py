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
