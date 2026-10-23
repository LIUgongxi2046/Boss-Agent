import asyncio
import importlib
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from aiohttp import web
from jsonschema import Draft202012Validator, FormatChecker
from nanobot.agent.tools.registry import ToolRegistry

ROOT = Path(__file__).resolve().parents[2]
W1 = Path("/Users/liuhaoxian/.codex/worktrees/boss-business/Boss-Agent")
COMMIT = "f854b07a66a153fc4a92c95c86cce788d009cffe"
sys.path.insert(0, str(ROOT / "validation"))

from controls import ControlStore


@pytest.fixture
def existing_owner_store(tmp_path):
    for name in ("boss_today", "boss_owner_plans", "boss_meetings"):
        path = "validation/" + name + ".py"
        assert (W1 / path).read_bytes() == subprocess.check_output(["git", "show", COMMIT + ":" + path], cwd=W1)
    source = ROOT / ".work/w2-checks/memory-ui/memory.sqlite"
    with sqlite3.connect(source.as_uri() + "?mode=ro", uri=True) as original:
        with sqlite3.connect(tmp_path / "owner-read.sqlite") as copied:
            original.backup(copied)
    yield ControlStore(tmp_path / "owner-read.sqlite")
    for name in ("boss_today", "boss_owner_plans", "boss_meetings"):
        path = "validation/" + name + ".py"
        assert (W1 / path).read_bytes() == subprocess.check_output(["git", "show", COMMIT + ":" + path], cwd=W1)


@pytest.mark.parametrize("class_name,operation,path", [
    ("BossTodayReadTool", "todayRead", "/api/boss/ui/today"),
    ("BossOwnerPlansReadTool", "ownerPlansRead", "/api/boss/ui/owner-plans"),
])
def test_owner_read_adapter_uses_current_domain_result_without_writes(existing_owner_store, class_name, operation, path):
    module = importlib.import_module("runtime_owner_read_tools")
    tool = getattr(module, class_name)(existing_owner_store, "BOSS")
    registry = ToolRegistry()
    registry.register(tool)
    assert registry.tool_names == [operation]
    assert tool.parameters == {"type": "object", "properties": {}, "additionalProperties": False}
    for parameters in ({"namespace": "ui-check"}, {"role": "BOSS"}, {"owner_id": "boss-1"}):
        _, _, error = registry.prepare_call(operation, parameters)
        assert error
    with existing_owner_store.connect() as db:
        before = tuple(db.iterdump())
    result = json.loads(asyncio.run(tool.execute()))
    backend = yaml.safe_load(subprocess.check_output(["git", "show", COMMIT + ":specs/openapi.yaml"], cwd=W1))
    response = backend["paths"][path]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
    Draft202012Validator({**backend, **response}, format_checker=FormatChecker()).validate(result)
    assert result["source_type"] == "SIMULATED"
    if operation == "todayRead":
        assert result["items"] and result["coverage_state"] == "PARTIAL"
        assert {item["object_id"] for item in result["items"]} >= {"meeting-1", "historical-1"}
        assert result["missing_sources"] and result["conflict_state"] == "INSUFFICIENT_EVIDENCE"
    else:
        assert result["plans"] == []
        assert result["execution_owner"] == "CronService" and result["external_delivery_verified"] is False
    reopened = ControlStore(existing_owner_store.path)
    other = json.loads(asyncio.run(getattr(module, class_name)(reopened, "BOSS").execute()))
    assert other == result
    with existing_owner_store.connect() as db:
        assert tuple(db.iterdump()) == before


@pytest.mark.parametrize("class_name", ["BossTodayReadTool", "BossOwnerPlansReadTool"])
@pytest.mark.parametrize("role,status", [(None, 401), ("MAINTAINER", 403), ("CONTACT", 403)])
def test_owner_read_adapter_rejects_other_identities(existing_owner_store, class_name, role, status):
    module = importlib.import_module("runtime_owner_read_tools")
    with pytest.raises(web.HTTPException) as failure:
        getattr(module, class_name)(existing_owner_store, role)
    assert failure.value.status == status
