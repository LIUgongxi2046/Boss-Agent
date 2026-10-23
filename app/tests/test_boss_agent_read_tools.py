import asyncio
import json
import sys
from pathlib import Path

import pytest
from aiohttp import web

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "validation"))

from boss_agent_read_tools import BossResearchSourcesTool
from boss_command_api import BossCommandAPI
from controls import ControlStore


@pytest.fixture
def store(tmp_path):
    current = ControlStore(tmp_path / "agent-read.sqlite")
    current.initialize("ui-check")
    return current


@pytest.mark.parametrize("role", [None, "MAINTAINER", "finance-1"])
def test_research_tool_requires_server_authenticated_owner(store, role):
    with pytest.raises(web.HTTPUnauthorized if role is None else web.HTTPForbidden):
        BossResearchSourcesTool(store, role)


def test_research_tool_requires_current_scope_and_rejects_other_projections(store):
    tool = BossResearchSourcesTool(store, "BOSS")
    with pytest.raises(web.HTTPConflict):
        asyncio.run(tool.execute(projection="research"))
    with pytest.raises(web.HTTPForbidden):
        asyncio.run(tool.execute(projection="memory"))


def test_research_tool_reads_current_source_and_withdrawal_without_business_write(store):
    with store.connect() as db:
        original = store.get(db, "ui-check", "document", "finance-note")
    status, _ = BossCommandAPI(store).execute("BOSS", "boss.research.prepare", {
        "client_request_id": "research-tool-prepare", "expected_version": "0",
        "question": original["content"].split("；", 1)[0],
        "period": "", "country": "", "business_relation": "", "cutoff_date": "2026-10-22",
    })
    assert status == 200
    observations = []
    tool = BossResearchSourcesTool(store, "BOSS", observation_sink=observations.append)
    before = json.loads(asyncio.run(tool.execute(projection="research")))
    assert before["matched_sources"][0]["source_id"] == original["source_id"]
    assert before["matched_sources"][0]["quote"] in original["content"]
    assert "contacts" not in before
    assert "memory" not in before
    assert original["content"] not in json.dumps(observations, ensure_ascii=False)
    store.control("ui-check", "withdraw", {"source_id": "finance-note", "version": "1"})
    after = json.loads(asyncio.run(tool.execute(projection="research")))
    assert after["matched_sources"] == []
    assert original["content"] not in json.dumps(after, ensure_ascii=False)
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind IN ('task','outbox','message_outbox')").fetchone()[0] == 0
