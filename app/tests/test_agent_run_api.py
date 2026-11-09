import asyncio
import json
import sqlite3
from pathlib import Path

import httpx
import yaml
from aiohttp import web
from jsonschema import Draft202012Validator, FormatChecker

from agent_run_api import IDENTITY_KEY, routes
from agent_run_broker import RunBroker, RunIdentity
from agent_run_store import RunStore


ROOT = Path(__file__).resolve().parents[2]
RUN_SCHEMA = json.loads((ROOT / "specs/agent-runs.schema.json").read_text())
EVENT_SCHEMA = json.loads((ROOT / "specs/agent-events.schema.json").read_text())


def validate_response(schema, name, value):
    Draft202012Validator({"$ref": "#/$defs/" + name, "$defs": schema["$defs"]}, format_checker=FormatChecker()).validate(value)


async def start_server(broker, identity):
    @web.middleware
    async def identity_context(request, handler):
        if identity is not None:
            request[IDENTITY_KEY] = identity
        return await handler(request)

    app = web.Application(middlewares=[identity_context], client_max_size=131072)
    app.add_routes(routes(broker))
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "127.0.0.1", 0).start()
    return runner, "http://127.0.0.1:" + str(runner.addresses[0][1])


def test_http_identity_scope_retries_and_persistence(tmp_path):
    async def exercise():
        path = tmp_path / "runs.sqlite"
        store = RunStore(path)
        broker = RunBroker(store)
        owner = RunIdentity("boss-1", "space-1", "BOSS", frozenset({"conversation-1"}), frozenset({"source-1"}))
        other = RunIdentity("boss-1", "space-2", "BOSS", frozenset({"conversation-1"}), frozenset({"source-1"}))
        maintainer = RunIdentity("maintainer-1", "space-1", "MAINTAINER", frozenset({"conversation-1"}), frozenset({"source-1"}))
        revoked = RunIdentity("boss-1", "space-1", "BOSS", frozenset({"conversation-1"}), frozenset())
        servers = [await start_server(broker, value) for value in (owner, other, maintainer, None, revoked)]
        try:
            async with httpx.AsyncClient(trust_env=False) as client:
                base, other_base, maint_base, anonymous_base, revoked_base = [value[1] for value in servers]
                payload = {"conversation_id": "conversation-1", "goal": "准备会议资料", "selected_refs": ["source-1"], "request_key": "create-1"}
                response = await client.post(base + "/api/v2/runs", json=payload)
                assert response.status_code == 200
                receipt = response.json()
                validate_response(RUN_SCHEMA, "receipt", receipt)
                run_id = receipt["run_id"]
                original = await client.get(base + "/api/v2/requests/create-1")
                assert original.status_code == 200
                validate_response(RUN_SCHEMA, "request_receipt", original.json())
                assert original.json() == {"request_key": "create-1", "operation": "create", "run_id": run_id, "outcome": "RECORDED", "receipt": receipt}
                assert (await client.get(other_base + "/api/v2/requests/create-1")).status_code == 404
                assert (await client.get(revoked_base + "/api/v2/requests/create-1")).status_code == 403
                assert (await client.get(maint_base + "/api/v2/requests/create-1")).status_code == 403
                assert (await client.get(anonymous_base + "/api/v2/requests/create-1")).status_code == 401
                assert (await client.get(base + "/api/v2/requests/create-1?actor_id=boss-1")).status_code == 400
                assert (await client.post(base + "/api/v2/runs", json=payload)).json() == receipt
                assert (await client.post(base + "/api/v2/runs", json={**payload, "goal": "其他目标"})).status_code == 409
                assert (await client.post(base + "/api/v2/runs", json={**payload, "actor_id": "other"})).status_code == 400
                oversized = await client.post(base + "/api/v2/runs", content=b" " * 131073, headers={"Content-Type": "application/json"})
                assert oversized.status_code == 413
                validate_response(RUN_SCHEMA, "error", oversized.json())
                error = await client.post(base + "/api/v2/runs", json={**payload, "actor_id": "other"})
                validate_response(RUN_SCHEMA, "error", error.json())
                assert error.json()["code"] == "INVALID_INPUT"
                assert (await client.post(base + "/api/v2/runs", json={**payload, "conversation_id": "unknown"})).status_code == 403
                assert (await client.post(base + "/api/v2/runs", json={**payload, "selected_refs": ["other"]})).status_code == 403
                assert (await client.get(other_base + "/api/v2/runs/" + run_id)).status_code == 404
                assert (await client.get(maint_base + "/api/v2/runs/" + run_id)).status_code == 403
                assert (await client.get(anonymous_base + "/api/v2/runs/" + run_id)).status_code == 401
                assert (await client.get(revoked_base + "/api/v2/runs/" + run_id)).status_code == 403
                assert (await client.get(base + "/api/v2/runs/" + run_id + "?actor_id=boss-1")).status_code == 400
                addition = {"input": "关注事项", "expected_goal_revision": 1, "request_key": "input-1"}
                added = await client.post(base + "/api/v2/runs/" + run_id + "/inputs", json=addition)
                assert added.status_code == 200 and added.json()["goal_revision"] == 2
                assert (await client.get(base + "/api/v2/requests/input-1")).json()["receipt"] == added.json()
                validate_response(RUN_SCHEMA, "request_receipt", (await client.get(base + "/api/v2/requests/input-1")).json())
                validate_response(RUN_SCHEMA, "input_receipt", added.json())
                assert (await client.post(base + "/api/v2/runs/" + run_id + "/inputs", json=addition)).json() == added.json()
                assert (await client.post(revoked_base + "/api/v2/runs/" + run_id + "/inputs", json=addition)).status_code == 403
                assert (await client.post(base + "/api/v2/runs/" + run_id + "/inputs", json={**addition, "request_key": "create-1"})).status_code == 409
                assert (await client.post(base + "/api/v2/runs/" + run_id + "/inputs", json={**addition, "request_key": "input-2"})).status_code == 409
                snapshot = (await client.get(base + "/api/v2/runs/" + run_id)).json()
                validate_response(RUN_SCHEMA, "snapshot", snapshot)
                assert snapshot["allowed_actions"] == ["READ_EVENTS", "ADD_INPUT", "CANCEL"]
                assert snapshot["goal"] == payload["goal"] and snapshot["goal_revision"] == 2
                cancellation = {"expected_revision": snapshot["revision"], "request_key": "cancel-1"}
                canceled = await client.post(base + "/api/v2/runs/" + run_id + "/cancel", json=cancellation)
                assert canceled.json()["status"] == "CANCELED"
                assert (await client.get(base + "/api/v2/requests/cancel-1")).json()["receipt"] == canceled.json()
                assert (await client.get(base + "/api/v2/runs/" + run_id)).json()["allowed_actions"] == ["READ_EVENTS"]
                assert (await client.get(base + "/api/v2/requests/unknown")).status_code == 404
                assert (await client.post(base + "/api/v2/runs/" + run_id + "/cancel", json=cancellation)).json() == canceled.json()
                assert (await client.post(base + "/api/v2/runs/" + run_id + "/inputs", json={**addition, "expected_goal_revision": 2, "request_key": "input-3"})).status_code == 409
                events = (await client.get(base + "/api/v2/runs/" + run_id + "/events?after_seq=0")).json()
                validate_response(EVENT_SCHEMA, "page", events)
                assert [event["seq"] for event in events["events"]] == [1, 2]
                assert all(event["trace_id"] and event["payload_version"] == 1 for event in events["events"])
                assert (await client.get(other_base + "/api/v2/runs/" + run_id + "/events?after_seq=0")).status_code == 404
                assert (await client.get(base + "/api/v2/runs/" + run_id + "/events?after_seq=-1")).status_code == 400
                assert RunStore(path).read_run(run_id)["status"] == "CANCELED"
                with sqlite3.connect(path) as db:
                    assert db.execute("SELECT count(*) FROM agent_runs").fetchone()[0] == 1
                    assert db.execute("SELECT count(*) FROM agent_run_inputs").fetchone()[0] == 1
        finally:
            for runner, _ in servers:
                await runner.cleanup()

    asyncio.run(exercise())


def test_schema_files_are_valid_and_describe_live_routes():
    Draft202012Validator.check_schema(RUN_SCHEMA)
    Draft202012Validator.check_schema(EVENT_SCHEMA)
    contract = yaml.safe_load((ROOT / "specs/agent-runtime.openapi.yaml").read_text())
    assert contract["openapi"] == "3.1.0"
    assert set(contract["paths"]).issuperset({"/api/v2/runs", "/api/v2/runs/{run_id}", "/api/v2/runs/{run_id}/inputs", "/api/v2/runs/{run_id}/cancel", "/api/v2/runs/{run_id}/events", "/api/v2/runs/{run_id}/result", "/api/v2/requests/{request_key}"})
    unavailable = contract["paths"]["/api/v2/runs"]["post"]["responses"]["503"]
    assert "CREATE_NOT_ADMITTED" in unavailable["description"]
    assert unavailable["content"]["application/json"]["schema"]["$ref"] == "./agent-runs.schema.json#/$defs/error"
