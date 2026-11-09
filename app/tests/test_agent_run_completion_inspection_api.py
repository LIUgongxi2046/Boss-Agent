import asyncio
import json
import sys
from pathlib import Path

import httpx
from jsonschema import Draft202012Validator, FormatChecker

from agent_run_broker import RunBroker, RunIdentity
from agent_run_concurrency import RunConcurrencyBudget
from hermes_process_evidence import HermesProcessEvidence
from test_agent_run_api import start_server
from test_agent_run_result import setup_result
from test_hermes_process_evidence import PROBE


ROOT = Path(__file__).resolve().parents[2]
SCHEMA = json.loads((ROOT / "specs/agent-runs.schema.json").read_text(encoding="utf-8"))


def test_process_exit_after_inspection_is_conservatively_stale_without_reinspection(tmp_path):
    store, runs, results, sink = setup_result(tmp_path)
    run = runs.read_run(sink.config.run_id)
    concurrency = RunConcurrencyBudget(runs, allow_migration=True)
    concurrency.configure(run["run_id"], sink.lease_owner, sink.config.lease_epoch, 1)
    with runs.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        concurrency.reserve_in_transaction(db, run["run_id"], sink.lease_owner, sink.config.lease_epoch, "slot", "digest")
    evidence = HermesProcessEvidence(runs, allow_migration=True)
    pid = evidence.start(run["run_id"], "slot", "digest", sink.lease_owner, sink.config.lease_epoch, run["actor_id"], run["space_id"], [sys.executable, str(PROBE), "child", "5"], cwd=PROBE.parent)
    process = evidence.processes[(run["run_id"], "slot")]
    assert pid == process.pid
    try:
        result = results.record(sink, "process-exit-result", 1, "技术结果", [])
        finish = sink.emit("process-exit-finish", "RUN_FINISHED", {"outcome": "TECHNICAL"})
        revision = runs.read_run(sink.config.run_id)["revision"]
        checked = results.inspect_completion(sink, revision, result["event_id"], finish["event_id"], "engine-finish:" + finish["event_id"])
        assert "PROCESS_GROUP_EXIT_UNVERIFIED" in checked["blockers"]
        assert process.poll() is None
        process.wait(timeout=10)
        assert evidence.observe_exit(run["run_id"], "slot")["state"] == "EXITED"
        broker = RunBroker(runs, scope_service=results.scope)
        identity = RunIdentity(run["actor_id"], run["space_id"], "BOSS", frozenset({"result-check"}), frozenset({"finance-note"}))
        inspected = broker.completion_inspection(identity, run["run_id"], finish["event_id"])
        assert inspected["stale"] is True
        assert inspected["completion_state"] == "BLOCKED"
    finally:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=10)


def test_completion_inspection_reads_saved_blockers_without_side_effects(tmp_path):
    async def exercise():
        _, runs, results, sink = setup_result(tmp_path)
        run = runs.read_run(sink.config.run_id)
        result = results.record(sink, "completion-answer", 1, "技术结果", [])
        finish = sink.emit("completion-finish", "RUN_FINISHED", {"outcome": "TECHNICAL"})
        revision = runs.read_run(sink.config.run_id)["revision"]
        checked = results.inspect_completion(sink, revision, result["event_id"], finish["event_id"], "engine-finish:" + finish["event_id"])
        assert checked["completion_state"] == "BLOCKED"
        assert "PROCESS_GROUP_EXIT_UNVERIFIED" in checked["blockers"]

        owner = RunIdentity(run["actor_id"], run["space_id"], "BOSS", frozenset({"result-check"}), frozenset({"finance-note"}))
        revoked = RunIdentity(run["actor_id"], run["space_id"], "BOSS", frozenset({"result-check"}), frozenset())
        broker = RunBroker(runs, scope_service=results.scope)
        servers = [await start_server(broker, value) for value in (owner, revoked, None)]
        try:
            async with httpx.AsyncClient() as client:
                base, revoked_base, anonymous_base = [value[1] for value in servers]
                url = base + "/api/v2/runs/" + run["run_id"] + "/completion-inspection?finish_event_id=" + finish["event_id"]
                with runs.connect() as db:
                    before_state = (db.execute("SELECT count(*) FROM agent_run_operations WHERE run_id=?", (run["run_id"],)).fetchone()[0], db.execute("SELECT revision FROM agent_runs WHERE run_id=?", (run["run_id"],)).fetchone()[0])
                response = await client.get(url)
                with runs.connect() as db:
                    assert (db.execute("SELECT count(*) FROM agent_run_operations WHERE run_id=?", (run["run_id"],)).fetchone()[0], db.execute("SELECT revision FROM agent_runs WHERE run_id=?", (run["run_id"],)).fetchone()[0]) == before_state
                assert response.status_code == 200
                payload = response.json()
                Draft202012Validator({"$ref": "#/$defs/completion_inspection", "$defs": SCHEMA["$defs"]}, format_checker=FormatChecker()).validate(payload)
                assert payload["completion_state"] == "BLOCKED"
                assert "PROCESS_GROUP_EXIT_UNVERIFIED" in payload["blockers"]
                assert payload["stale"] is False
                assert payload["inspection_revision"] == revision
                assert payload["run_revision"] == revision
                assert set(payload) == {"run_id", "goal_revision", "current_goal_revision", "inspection_revision", "run_revision", "stale", "result_event_id", "finish_event_id", "completion_state", "blockers", "output_checks", "requirements", "brief_section_audits"}
                assert payload["brief_section_audits"] == []
                assert "result" not in payload and "artifacts" not in payload
                assert (await client.get(revoked_base + url.split(base, 1)[1])).status_code == 403
                assert (await client.get(anonymous_base + url.split(base, 1)[1])).status_code == 401
                assert (await client.get(base + "/api/v2/runs/" + run["run_id"] + "/completion-inspection?finish_event_id=missing")).status_code == 404
                runs.append_event(run["run_id"], sink.lease_owner, sink.config.lease_epoch, "completion-normal-event", "STATUS_CHANGED", {"from": "RUNNING", "to": "SUCCEEDED"})
                continued = await client.get(url)
                assert continued.status_code == 200
                assert continued.json()["stale"] is False
                runs.append_event(run["run_id"], sink.lease_owner, sink.config.lease_epoch, "completion-tool-event", "TOOL_FINISHED", {"tool_id": "technical", "call_id": "technical", "outcome": "RETURNED"})
                changed = await client.get(url)
                assert changed.status_code == 200
                assert changed.json()["stale"] is True
                runs.add_input(run["run_id"], 1, "completion-new-goal", "补充目标")
                stale = await client.get(url)
                assert stale.status_code == 200
                assert stale.json()["stale"] is True
                assert stale.json()["current_goal_revision"] == 2
                assert stale.json()["completion_state"] == "BLOCKED"
        finally:
            for runner, _ in servers:
                await runner.cleanup()

    asyncio.run(exercise())
