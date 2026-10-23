import asyncio
import hashlib
import json
import sys
from pathlib import Path
from uuid import uuid4

import pytest
from aiohttp import web
from nanobot.agent.tools.context import RequestContext, request_context
from nanobot.agent.tools.registry import ToolRegistry

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "validation"))

from business import OPERATIONS
from connection import RecordedProvider
from controls import ControlStore
from model_probe import BusinessTool


def test_redaction_preserves_existing_run_identity():
    path = next((ROOT / "evidence" / "T16").glob("deepseek-*/http-requests.json"))
    event = next(row for row in json.loads(path.read_text()) if row["type"] == "request")
    projected = RecordedProvider._sanitize_history({**event, "run_id": path.parent.name})
    assert projected["run_id"] == path.parent.name
    assert "input" not in projected


def test_redaction_preserves_reported_cache_usage():
    path = next((ROOT / "evidence" / "T16").glob("deepseek-*/http-requests.json"))
    event = next(row for row in json.loads(path.read_text()) if row["type"] == "stream_metadata" and row.get("usage"))
    projected = RecordedProvider._sanitize_history(event)
    assert projected["usage"]["prompt_cache_hit_tokens"] == event["usage"]["prompt_cache_hit_tokens"]
    assert projected["usage"]["prompt_cache_miss_tokens"] == event["usage"]["prompt_cache_miss_tokens"]


@pytest.fixture
def runtime(tmp_path):
    from boss_runtime_records import RuntimeRecorder

    store = ControlStore(tmp_path / "runtime.sqlite")
    store.initialize("ui-check")
    registry = ToolRegistry()
    for operation in OPERATIONS:
        registry.register(BusinessTool(operation, store, {
            "owner_id": "boss-1", "execution_namespace": "ui-check", "dataset_id": "selection",
            "dataset_version": "1", "session_id": "runtime-test", "request_id": str(uuid4()),
        }, {}, []))
    snapshot = {
        "provider": "deepseek", "model_id": "deepseek-flash", "api_type": "chat_completions",
        "max_tool_rounds": 12, "max_output_tokens": 700, "timeout": 120,
        "config_sha256": hashlib.sha256((ROOT / "specs/agent-assets.json").read_bytes()).hexdigest(),
    }
    recorder = RuntimeRecorder(store, "ui-check", registry, lambda: snapshot)
    return store, recorder, snapshot, registry


def context():
    return RequestContext(channel="cli", chat_id=str(uuid4()), session_key=str(uuid4()), sender_id="boss-1")


def test_context_admission_persists_metadata_and_reopens(runtime):
    from boss_runtime_records import runtime_records

    store, recorder, _, _ = runtime
    request = context()
    block = asyncio.run(recorder.context(request))
    rows = runtime_records(ControlStore(store.path), "MAINTAINER")["runs"]
    assert len(rows) == 1
    row = rows[0]
    assert row["status"] == "QUEUED" and row["configuration_version"] == "1"
    assert row["session_id"] == request.session_key and row["run_id"]
    assert row["cost_total"] is None and row["usage"] is None
    assert row["tool_config_sha256"] and len(row["tool_configuration"]) == 5
    assert all(item["implementation_sha256"] for item in row["tool_configuration"])
    assert row["run_id"] in block.content
    assert "credential_ref" not in json.dumps(row)
    assert "简报优先展示现金与本人承诺。" not in json.dumps(row)


@pytest.mark.parametrize("field,value", [("enabled", False), ("max_tool_rounds", 2), ("timeout", 20)])
def test_disabled_or_unapplied_configuration_is_rejected_before_admission(runtime, field, value):
    store, recorder, _, _ = runtime
    with store.connect() as db:
        current = store.get(db, "ui-check", "configuration", "current")
        store.put(db, "ui-check", "configuration", "current", {**current, field: value, "version": "2"})
    with pytest.raises(web.HTTPConflict):
        asyncio.run(recorder.context(context()))
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind='runtime_run'").fetchone()[0] == 0


def test_tool_outside_current_configuration_is_rejected(runtime):
    from boss_agent_read_tools import BossResearchSourcesTool

    store, recorder, _, registry = runtime
    registry.register(BossResearchSourcesTool(store, "BOSS"))
    with pytest.raises(web.HTTPForbidden):
        asyncio.run(recorder.context(context()))


@pytest.mark.parametrize("role", [None, "contact-1"])
def test_runtime_metadata_rejects_other_roles(runtime, role):
    from boss_runtime_records import runtime_records

    store, _, _, _ = runtime
    with pytest.raises(web.HTTPUnauthorized if role is None else web.HTTPForbidden):
        runtime_records(store, role)


def test_runtime_context_rejects_non_owner(runtime):
    _, recorder, _, _ = runtime
    request = RequestContext(channel="cli", chat_id="maintainer", session_key="maintainer", sender_id="maintainer-1")
    with pytest.raises(web.HTTPForbidden):
        asyncio.run(recorder.context(request))


def test_existing_turn_keeps_admission_while_next_turn_reads_configuration(runtime):
    from boss_runtime_records import runtime_records

    store, recorder, snapshot, _ = runtime
    request = context()
    original = asyncio.run(recorder.context(request))
    with store.connect() as db:
        config = store.get(db, "ui-check", "configuration", "current")
        store.put(db, "ui-check", "configuration", "current", {**config, "version": "2", "max_tool_rounds": 2})
    assert asyncio.run(recorder.context(request)) == original
    snapshot["max_tool_rounds"] = 2
    asyncio.run(recorder.context(context()))
    rows = runtime_records(store, "BOSS")["runs"]
    assert {row["configuration_version"] for row in rows} == {"1", "2"}


def test_actual_business_result_is_bound_without_body(runtime):
    from boss_runtime_records import runtime_records
    from nanobot.agent.hook import AgentHookContext, AgentRunHookContext, AgentTurnHookContext
    from nanobot.providers.base import ToolCallRequest

    store, recorder, _, registry = runtime
    request = context()
    asyncio.run(recorder.context(request))
    hook = recorder.hook_factory(AgentTurnHookContext(attributes=request.attributes))
    payload = json.loads(next((ROOT / "evidence" / "T16").glob("deepseek-*/events.json")).read_text())
    query = next(item["input"] for item in payload if item["type"] == "tool" and item["name"] == "query_metrics")
    query["envelope"].update(execution_namespace="ui-check", session_id=request.session_key)
    params = {key: value for key, value in query.items() if key != "envelope"}
    call = ToolCallRequest(id=str(uuid4()), name="query_metrics", arguments=params)
    async def run():
        with request_context(request):
            await hook.before_run(AgentRunHookContext(messages=[]))
            output = await registry.get("query_metrics").execute(**params)
            await hook.after_execute_tool(AgentHookContext(iteration=1, messages=[]), call,
                                          registry.get("query_metrics"), params, output)
            await hook.after_run(AgentRunHookContext(messages=[], stop_reason="completed"))
            return json.loads(output)
    result = asyncio.run(run())
    row = runtime_records(ControlStore(store.path), "MAINTAINER")["runs"][0]
    assert row["status"] == "SUCCEEDED"
    assert row["tool_results"][0]["query_id"] == result["query_id"]
    with store.connect() as db:
        query_record = store.get(db, "ui-check", "query", result["query_id"])
    assert query_record["envelope"]["request_id"] == row["request_id"]
    assert query_record["envelope"]["session_id"] == row["session_id"]
    assert "values" not in json.dumps(row) and "finance-note" not in json.dumps(row)
    assert row["usage_coverage"] == "NOT_OBSERVED"
