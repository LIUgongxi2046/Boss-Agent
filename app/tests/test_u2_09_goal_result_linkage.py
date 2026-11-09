import asyncio
import hashlib
import json
import secrets
import shutil
import socket
import sqlite3
import subprocess
from pathlib import Path

import httpx
import pytest
from aiohttp import web

from agent_run_broker import RunBroker
from agent_run_requirements import RunRequirements
from agent_run_scope import RunScopeService
from agent_run_store import RunStore
from boss_memory_sessions import MemorySessionManager
from controls import ControlStore
from hermes_bridge import EngineEventSink, EngineRunConfig
from hermes_source_invalidation import begin_source_cleanup, require_source_cleanup_complete
from hermes_transport import HermesTransport
from hermes_transport_client import HermesTransportClient


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / ".work/upgrade2-u2-04/pytest-run-result-verified/test_result_persists_idempoten0/business.sqlite"
CITATIONS = ROOT / ".work/upgrade2-u2-04/pytest-result-citation-checks/test_result_citation_checks_us0/business.sqlite"


def test_saved_run_goal_versions_and_source_cleanup(tmp_path):
    digest = hashlib.sha256(SOURCE.read_bytes()).hexdigest()
    database = tmp_path / "business.sqlite"
    with sqlite3.connect(f"file:{SOURCE}?mode=ro&immutable=1", uri=True) as source, sqlite3.connect(database) as target:
        source.backup(target)
    runs = RunStore(database, allow_migration=False)
    with runs.connect() as db:
        db.execute("BEGIN")
        run_id = db.execute("SELECT run_id FROM agent_runs").fetchone()[0]
        run = runs.read_run(run_id)
        current = runs.result_in_transaction(db, run_id, run["goal_revision"])
        previous_input = db.execute("SELECT content FROM agent_run_inputs WHERE run_id=? ORDER BY input_seq LIMIT 1", (run_id,)).fetchone()[0]
        pins = current["payload"]["source_pins"]
        assert pins and current["payload"]["citations"]
        assert RunBroker.result_citation_checks_in_transaction(db, run["space_id"], run_id, current) is None
        assert RunRequirements.read_in_transaction(db, run_id, run["goal_revision"])["state"] == "UNAVAILABLE"
    RunRequirements(runs, allow_migration=True)
    with runs.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        assert RunRequirements.read_in_transaction(db, run_id, run["goal_revision"])["state"] == "PENDING_CONFIRMATION"
        RunRequirements.save_in_transaction(db, run_id, run["goal_revision"], "u2-09-technical-selection", ["TEXT", "PDF"])
        confirmed = RunRequirements.read_in_transaction(db, run_id, run["goal_revision"])
        assert confirmed["required_outputs"] == ["TEXT", "PDF"]
    receipt = runs.add_input(run_id, run["goal_revision"], "u2-09-technical-input", previous_input)
    with runs.connect() as db:
        db.execute("BEGIN")
        assert receipt["goal_revision"] == run["goal_revision"] + 1
        pending = RunRequirements.read_in_transaction(db, run_id, receipt["goal_revision"])
        assert pending["state"] == "PENDING_CONFIRMATION"
        assert RunRequirements.read_in_transaction(db, run_id, run["goal_revision"])["required_outputs"] == ["TEXT", "PDF"]
        assert runs.result_in_transaction(db, run_id, receipt["goal_revision"]) is None
        assert runs.result_in_transaction(db, run_id, run["goal_revision"]) == current
        require_source_cleanup_complete(db, run_id)
    updated = runs.read_run(run_id)
    events = runs.events(run_id, 0)
    payload = {"previous": run, "current": updated, "confirmed": confirmed, "pending": pending, "events": events,
               "actions": RunBroker.allowed_actions(updated), "input": previous_input}
    output = subprocess.run(["node", str(ROOT / "app/tests/u2_09_goal_versions_ui_check.cjs")], cwd=ROOT,
                            input=json.dumps(payload, ensure_ascii=False), text=True, capture_output=True)
    assert output.returncode == 0, output.stderr
    assert json.loads(output.stdout)["checked"] is True
    pin = pins[0]
    assert begin_source_cleanup(ControlStore(database), run["space_id"], pin["source_id"], pin["version"])
    with runs.connect() as db:
        db.execute("BEGIN")
        with pytest.raises(ValueError, match="来源清理尚未完成"):
            require_source_cleanup_complete(db, run_id)
    (tmp_path / "evidence.json").write_text(json.dumps({"source_sha256": digest, "previous_goal_revision": run["goal_revision"],
        "current_goal_revision": receipt["goal_revision"], "old_selection_preserved": True,
        "new_selection_state": "PENDING_CONFIRMATION", "current_result": None,
        "historic_citation_checks": None, "source_cleanup_blocked": True}, ensure_ascii=False), encoding="utf-8")


@pytest.mark.parametrize("operation", ["source", "waiting"])
def test_existing_run_through_local_engine_transport(tmp_path, operation):
    database = tmp_path / "business.sqlite"
    with sqlite3.connect(f"file:{SOURCE}?mode=ro&immutable=1", uri=True) as source, sqlite3.connect(database) as target:
        source.backup(target)
    shutil.copytree(SOURCE.parent / "workspace", tmp_path / "workspace")
    runs = RunStore(database, allow_migration=False)
    business = ControlStore(database)
    with runs.connect() as db:
        run_id = db.execute("SELECT run_id FROM agent_runs").fetchone()[0]
        previous_input = db.execute("SELECT content FROM agent_run_inputs WHERE run_id=? ORDER BY input_seq LIMIT 1", (run_id,)).fetchone()[0]
    original = runs.read_run(run_id)
    runs.interrupt_expired(run_id)
    lease = runs.acquire_lease(run_id, runs.read_run(run_id)["revision"], "u2-09-engine-check", 120)
    runs.transition(run_id, lease["revision"], "RECONCILING", "u2-09-engine-check", lease["epoch"])
    runs.transition(run_id, runs.read_run(run_id)["revision"], "RUNNING", "u2-09-engine-check", lease["epoch"])
    RunRequirements(runs, allow_migration=True)
    with runs.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        RunRequirements.save_in_transaction(db, run_id, original["goal_revision"], "u2-09-engine-selection", ["TEXT", "PDF"])
    sessions = MemorySessionManager(tmp_path / "workspace", business_store=business, sessions_root=tmp_path / "sessions")
    for session_file in (SOURCE.parent / "sessions").glob("*/*.jsonl"):
        shutil.copy2(session_file, sessions.sessions_dir / session_file.name)
    scope = RunScopeService(business, sessions, original["space_id"])

    async def exercise():
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        sock.listen()
        sock.setblocking(False)
        endpoint = "http://127.0.0.1:" + str(sock.getsockname()[1])
        capability = secrets.token_urlsafe(32)
        config = EngineRunConfig(run_id, lease["epoch"], "903230b1e23e0c496b28e5d2e8c4f2639cd506b6", endpoint, 1)
        transport = HermesTransport(EngineEventSink(runs, config, "u2-09-engine-check"), capability,
                                    actor_id=original["actor_id"], space_id=original["space_id"], scope_service=scope)
        app = web.Application()
        transport.install(app)
        runner = web.AppRunner(app)
        await runner.setup()
        await web.SockSite(runner, sock).start()
        client = HermesTransportClient(endpoint, capability, run_id)
        try:
            async with httpx.AsyncClient(trust_env=False) as probe:
                response = await probe.get(endpoint + "/internal/v1/input-context", headers={"Authorization": "Bearer " + capability})
                assert response.status_code == 200, response.text
            context = await asyncio.to_thread(client.input_context)
            assert context["requirements"]["required_outputs"] == ["TEXT", "PDF"]
            prepared = await asyncio.to_thread(client.prepare_turn)
            prompt = json.loads(prepared["prompt"])
            assert prepared["goal_revision"] == original["goal_revision"]
            assert prompt["required_outputs"] == ["TEXT", "PDF"]
            assert prompt["additional_inputs"] == [item["content"] for item in context["inputs"]]
            receipt = runs.add_input(run_id, original["goal_revision"], "u2-09-engine-input", previous_input)
            changed = await asyncio.to_thread(client.input_context)
            assert changed["goal_revision"] == receipt["goal_revision"]
            assert changed["requirements"]["state"] == "PENDING_CONFIRMATION"
            with pytest.raises(ValueError, match="成果要求尚未确认"):
                await asyncio.to_thread(client.prepare_turn)
            if operation == "waiting":
                waiting = await asyncio.to_thread(client.wait_for_requirements, receipt["goal_revision"])
                assert waiting["status"] == "WAITING_INPUT"
                assert client.waiting_state == "WAITING_INPUT"
                assert waiting["requirements"]["state"] == "PENDING_CONFIRMATION"
                assert runs.read_run(run_id)["status"] == "WAITING_INPUT"
                assert runs.events(run_id, 0)[-1]["payload"]["reason"] == "OUTPUT_REQUIREMENTS_UNCONFIRMED"
            else:
                source_id = json.loads(original["selected_refs"])[0]
                pin = json.loads(original["scope_proof"])["source_pins"][0]
                assert begin_source_cleanup(business, original["space_id"], source_id, pin[1])
                with pytest.raises(httpx.HTTPStatusError) as rejected:
                    await asyncio.to_thread(client.input_context)
                assert rejected.value.response.status_code == 409
                assert rejected.value.response.json()["code"] == "SOURCE_CLEANUP_UNAVAILABLE"
        finally:
            client.close()
            await runner.cleanup()

    asyncio.run(exercise())


def test_saved_citation_check_reaches_result_panel(tmp_path):
    database = tmp_path / "citations.sqlite"
    with sqlite3.connect(f"file:{CITATIONS}?mode=ro&immutable=1", uri=True) as source, sqlite3.connect(database) as target:
        source.backup(target)
    runs = RunStore(database, allow_migration=False)
    with runs.connect() as db:
        db.execute("BEGIN")
        run_id = db.execute("SELECT run_id FROM agent_runs").fetchone()[0]
        run = runs.read_run(run_id)
        result = runs.result_in_transaction(db, run_id, run["goal_revision"])
        checks = RunBroker.result_citation_checks_in_transaction(db, run["space_id"], run_id, result)
        events = runs.event_page_in_transaction(db, run_id, 0)["events"]
    assert checks and all(item["locator_verification"] == "NOT_VERIFIED" for item in checks)
    payload = {"run": run, "actions": RunBroker.allowed_actions(run), "result": result, "checks": checks, "events": events}
    output = subprocess.run(["node", str(ROOT / "app/tests/u2_09_citation_panel_check.cjs")], cwd=ROOT,
                            input=json.dumps(payload, ensure_ascii=False), text=True, capture_output=True, check=True)
    (tmp_path / "citation-panel.json").write_text(output.stdout, encoding="utf-8")
    assert json.loads(output.stdout)["locator_verification"] == "NOT_VERIFIED"
