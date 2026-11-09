import asyncio
import json
import secrets
import shutil
import socket
import sys
import threading
from dataclasses import asdict
from pathlib import Path

import httpx
import pytest
from aiohttp import web
from nanobot.agent.skills import SkillsLoader
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.config.loader import load_config, save_config
from nanobot.config.schema import Config

from agent_run_scope import RunScopeService
from agent_run_result import AgentRunResult
from agent_run_store import RunStore
from agent_run_tool_budget import RunToolBudget
from agent_artifacts import ArtifactPreparation
from agent_artifact_formats import verify_format
from boss_comprehensive_simulation import populate
from boss_memory_sessions import MemorySessionManager
from boss_native_skills import BossSkillCatalog
from boss_skill_drafts import BossSkillDrafts
from business import checksum
from controls import ControlStore
from hermes_bridge import EngineEventSink, EngineRunConfig, HermesBridge
from hermes_context_tools import HermesContextTools
from hermes_memory_adapter import HermesMemoryAdapter
from hermes_runtime_transport import HermesRuntimeTransport
from hermes_skill_adapter import HermesSkillAdapter
from hermes_source_invalidation import begin_source_cleanup
from model_probe import BusinessTool


ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("cancel_after_result", [False, True])
def test_local_registered_tools_read_and_reject_changed_context(tmp_path, cancel_after_result):
    async def exercise():
        workspace = tmp_path / "workspace"
        shutil.copytree(ROOT / "agent/skills", workspace / "skills")
        config = Config()
        config.agents.defaults.workspace = str(workspace)
        config_path = tmp_path / "config.json"
        save_config(config, config_path)
        store = ControlStore(tmp_path / "business.sqlite")
        store.initialize("ui-check")
        populate(store, "2026-10-28T10:00:00+08:00")
        sessions = MemorySessionManager(workspace, business_store=store, sessions_root=tmp_path / "sessions")
        session = sessions.get_or_create("websocket:context-check")
        sessions.save(session, fsync=True)
        with store.connect() as db:
            initial = store.get(db, "ui-check", "initial", "snapshot")
            document = store.get(db, "ui-check", "document", "finance-note")
            meeting_document = store.get(db, "ui-check", "document", "simulation-meeting-material")
            source = {"source_id": document["source_id"], "version": document["version"]}
            meeting_source = {"source_id": meeting_document["source_id"], "version": meeting_document["version"]}
            binding = {"namespace": "ui-check", "owner_id": initial["owner_id"], "dataset_id": initial["dataset_id"], "dataset_version": initial["dataset_version"], "chat_id": "context-check", "session_id": session.key, "native_session_created_at": session.created_at.isoformat(), "binding_id": "context-selection", "context_version": "1", "source_refs": [source, meeting_source], "source_pins": [{**source, "content_sha256": checksum(document)}, {**meeting_source, "content_sha256": checksum(meeting_document)}]}
            store.put(db, "ui-check", "conversation_source_binding", session.key, binding)
        session.add_message("user", document["content"])
        session.commit_summary_checkpoint(document["content"])
        sessions.save(session, fsync=True)
        store.hermes_source_sessions = sessions
        scope = RunScopeService(store, sessions, "ui-check")
        proof = scope.prove("context-check", ["finance-note", "simulation-meeting-material"])
        runs = RunStore(store.path)
        run_id = runs.create_run(proof.owner_id, proof.namespace, "context-run", "context-digest")
        with runs.connect() as db:
            db.execute("UPDATE agent_runs SET goal=?,conversation_id=?,selected_refs=?,scope_proof=? WHERE run_id=?", ("核查经营指标", proof.chat_id, json.dumps(["finance-note", "simulation-meeting-material"]), json.dumps(asdict(proof)), run_id))
        lease = runs.acquire_lease(run_id, 0, "worker", 600)
        runs.transition(run_id, lease["revision"], "RUNNING", "worker", lease["epoch"])
        budget = RunToolBudget(runs, allow_migration=True)
        budget.configure(run_id, "worker", lease["epoch"], 4)
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        endpoint = "http://127.0.0.1:" + str(listener.getsockname()[1])
        run = EngineRunConfig(run_id, lease["epoch"], "903230b1e23e0c496b28e5d2e8c4f2639cd506b6", endpoint, 1)
        sink = EngineEventSink(runs, run, "worker")
        registry = ToolRegistry()
        envelope = {"request_id": "context-check", "owner_id": proof.owner_id, "execution_namespace": proof.namespace, "dataset_id": proof.dataset_id, "dataset_version": proof.dataset_version, "session_id": proof.chat_id}
        for operation in ("query_metrics", "read_evidence"):
            registry.register(BusinessTool(operation, store, envelope, {}, []))
        loader = SkillsLoader(workspace)
        catalog = BossSkillCatalog(loader, registry)
        drafts = BossSkillDrafts(store, catalog, config_path)
        memory = HermesMemoryAdapter(store, scope, run_gate=sink)
        skill = HermesSkillAdapter(store, scope, catalog, drafts, run_gate=sink, sop_id="SOP03")
        tools = HermesContextTools(memory, memory.read()["reference"], skill, skill.read()["reference"])
        with runs.connect() as db:
            db.execute("BEGIN")
            with pytest.raises(web.HTTPConflict):
                tools.require_method_read_in_transaction(db, 1)
        capability = secrets.token_urlsafe(32)
        server = HermesRuntimeTransport(sink, scope, HermesBridge(store), actor_id=proof.owner_id, space_id=proof.namespace, capability=capability, max_tools=4, context_tools=tools)
        async with server.serve(listener):
            probe = Path(__file__).with_name("hermes_context_tools_probe.py")
            engine = ROOT / ".work/upgrade2/u2-03/clean-hermes"
            process = await asyncio.create_subprocess_exec(sys.executable, str(probe), str(engine), stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            try:
                _, stderr = await asyncio.wait_for(process.communicate(json.dumps({"endpoint": endpoint, "capability": capability, "run_id": run_id}).encode()), 120)
            finally:
                if process.returncode is None:
                    process.kill()
                    await process.wait()
            assert process.returncode == 0, stderr.decode()
            method_events = [event for event in runs.events(run_id, 0) if event["type"] == "TOOL_FINISHED" and event["payload"].get("tool_id") == "read_enabled_method"]
            assert len(method_events) == 1
            assert method_events[0]["payload"]["goal_revision"] == 1
            assert method_events[0]["payload"]["method_ref"] == tools.skill_reference["method"]
            with runs.connect() as db:
                db.execute("BEGIN")
                assert tools.require_method_read_in_transaction(db, 1) == method_events[0]["event_id"]
                with pytest.raises(web.HTTPConflict):
                    tools.require_method_read_in_transaction(db, 2)
            headers = {"Authorization": "Bearer " + capability}
            async with httpx.AsyncClient(trust_env=False) as client:
                result_request = {"protocol_version": 1, "origin_event_id": "technical-result", "goal_revision": 1, "text": document["content"], "citations": []}
                with pytest.raises(RuntimeError, match="结果事务检查"):
                    with tools.guarded_result(gate_check=server.transport._require_gate) as db:
                        AgentRunResult(runs, scope).record_in_transaction(db, sink, "rollback-result", 1, document["content"], [])
                        raise RuntimeError("结果事务检查")
                assert not any(event["type"] == "RESULT_RECORDED" for event in runs.events(run_id, 0))
                invalid_result = await client.post(endpoint + "/internal/v1/result", headers=headers,
                    json={**result_request, "citations": [{"source_id": "outside-scope", "locator": "1"}]})
                assert invalid_result.status_code >= 400
                assert not any(event["type"] == "RESULT_RECORDED" for event in runs.events(run_id, 0))
                result_request["citations"] = [{"source_id": "finance-note", "locator": "第一节"}]
                result = await client.post(endpoint + "/internal/v1/result", headers=headers, json=result_request)
                repeated = await client.post(endpoint + "/internal/v1/result", headers=headers, json=result_request)
                assert result.status_code == repeated.status_code == 200 and result.json() == repeated.json()
                assert result.json()["event"]["payload"]["source_pins"][0]["source_id"] == "finance-note"
                assert result.json()["event"]["payload"]["citations"] == result_request["citations"]
                assert result.json()["citation_checks"] == [{**result_request["citations"][0], "locator_verification": "NOT_VERIFIED"}]
                checks_url = endpoint + "/internal/v1/results/" + result.json()["event"]["event_id"] + "/citation-checks"
                checks = await client.get(checks_url, headers=headers)
                assert checks.status_code == 200 and checks.json()["citation_checks"] == result.json()["citation_checks"]
                assert (await client.get(checks_url)).status_code == 401
                with runs.connect() as db:
                    assert db.execute("SELECT count(*) FROM objects WHERE kind='hermes_result_citation_checks'").fetchone()[0] == 1
                assert runs.read_run(run_id)["status"] == "RUNNING"
                if cancel_after_result:
                    entered, finished = threading.Event(), threading.Event()
                    def cancel_run():
                        entered.set()
                        runs.cancel(run_id, runs.read_run(run_id)["revision"])
                        finished.set()
                    with tools.guarded_result(gate_check=server.transport._require_gate):
                        thread = threading.Thread(target=cancel_run)
                        thread.start()
                        assert entered.wait(5) and not finished.wait(0.2)
                    thread.join(5)
                    assert not thread.is_alive() and finished.is_set()
                    rejected_result = await client.post(endpoint + "/internal/v1/result", headers=headers, json=result_request)
                    assert rejected_result.status_code == 409
                    with runs.connect() as db:
                        db.execute("BEGIN IMMEDIATE")
                        with pytest.raises(web.HTTPConflict):
                            server.transport.reserve_artifact_call_in_transaction(db, {"source_ids": ["finance-note"], "request_key": "after-cancel", "format_name": "DOCX"})
                    assert len([event for event in runs.events(run_id, 0) if event["type"] == "RESULT_RECORDED"]) == 1
                    return
                artifact_payload = {"source_ids": ["simulation-meeting-material"], "request_key": "technical-artifact", "format_name": "DOCX"}
                with runs.connect() as db:
                    db.execute("BEGIN IMMEDIATE")
                    with pytest.raises(web.HTTPForbidden):
                        server.transport.reserve_artifact_call_in_transaction(db, {**artifact_payload, "source_ids": ["outside-scope"]})
                    key = server.transport.reserve_artifact_call_in_transaction(db, artifact_payload)
                    assert key == "artifact:technical-artifact"
                    with pytest.raises(web.HTTPConflict):
                        server.transport.reserve_artifact_call_in_transaction(db, artifact_payload)
                artifact_workspace = tmp_path / "artifacts"
                artifact_workspace.mkdir()
                runs.configure_file_budget(run_id, "worker", lease["epoch"], 1, 200000)
                preparation = ArtifactPreparation(store, artifact_workspace, run_gate=sink, scope_service=scope, max_files=1, max_bytes=200000)
                artifact = preparation.create_meeting_brief(run_id, ["simulation-meeting-material"], request_key="technical-file", format_name="MARKDOWN")
                repeated_artifact = preparation.create_meeting_brief(run_id, ["simulation-meeting-material"], request_key="technical-file", format_name="MARKDOWN")
                assert artifact == repeated_artifact
                verify_format("MARKDOWN", preparation.read_meeting_brief(artifact["artifact_id"]), [meeting_document])
                assert any(event["type"] == "ARTIFACT_CANDIDATE" and event["payload"]["artifact_id"] == artifact["artifact_id"] for event in runs.events(run_id, 0))
                assert (await client.post(endpoint + "/internal/v1/tools/context/memory", json={"protocol_version": 1, "call_id": "no-authorization"})).status_code == 401
                with runs.connect() as db:
                    first_call = db.execute("SELECT request_key FROM agent_tool_reservations WHERE run_id=? AND tool_name='read_product_memory'", (run_id,)).fetchone()[0]
                assert (await client.post(endpoint + "/internal/v1/tools/context/memory", headers=headers, json={"protocol_version": 1, "call_id": first_call})).status_code == 409
                conflict = await client.post(endpoint + "/internal/v1/tools/context/method", headers=headers, json={"protocol_version": 1, "call_id": first_call})
                assert conflict.status_code == 409 and conflict.json()["code"] == "TOOL_REQUEST_CONFLICT"
                assert (await client.post(endpoint + "/internal/v1/tools/context/memory", headers=headers, json={"protocol_version": 1, "call_id": "third-call"})).status_code == 200
                assert (await client.post(endpoint + "/internal/v1/tools/context/memory", headers=headers, json={"protocol_version": 1, "call_id": "budget-exhausted"})).status_code == 429
                current = load_config(config_path)
                current.agents.defaults.disabled_skills = ["boss-sop03"]
                save_config(current, config_path)
                loader.disabled_skills.add("boss-sop03")
                rejected = await client.post(endpoint + "/internal/v1/tools/context/method", headers=headers, json={"protocol_version": 1, "call_id": "disabled-method"})
                assert rejected.status_code == 409
                question = {"protocol_version": 1, "call_id": "disabled-question", "goal_revision": 1, "question": "请补充当前会议资料。"}
                rejected_question = await client.post(endpoint + "/internal/v1/tools/input-required", headers=headers, json=question)
                assert rejected_question.status_code == 409
                assert not any(event["type"] == "INPUT_REQUIRED" for event in runs.events(run_id, 0))
                with runs.connect() as db:
                    assert db.execute("SELECT count(*) FROM agent_tool_reservations WHERE run_id=? AND request_key=?", (run_id, "disabled-question")).fetchone()[0] == 0
                current.agents.defaults.disabled_skills = []
                save_config(current, config_path)
                loader.disabled_skills.clear()
                with store.connect() as db:
                    original_memory = store.get(db, "ui-check", "memory", "current")
                entered, finished = threading.Event(), threading.Event()
                def change_memory():
                    entered.set()
                    with store.connect() as db:
                        db.execute("BEGIN IMMEDIATE")
                        store.put(db, "ui-check", "memory", "current", {**original_memory, "text": original_memory["text"] + "。"})
                    finished.set()
                with tools.guarded_result(gate_check=server.transport._require_gate):
                    thread = threading.Thread(target=change_memory)
                    thread.start()
                    assert entered.wait(5) and not finished.wait(0.2)
                thread.join(5)
                assert not thread.is_alive() and finished.is_set()
                rejected = await client.post(endpoint + "/internal/v1/tools/context/memory", headers=headers, json={"protocol_version": 1, "call_id": "changed-memory"})
                assert rejected.status_code == 409
                rejected_result = await client.post(endpoint + "/internal/v1/result", headers=headers, json=result_request)
                assert rejected_result.status_code == 409
                assert (await client.get(checks_url, headers=headers)).status_code == 409
                with store.connect() as db:
                    store.put(db, "ui-check", "memory", "current", original_memory)
                method_path = workspace / "skills/boss-sop03/SKILL.md"
                method_original = method_path.read_text(encoding="utf-8")
                entered, finished = threading.Event(), threading.Event()
                def change_method():
                    entered.set()
                    with drafts._locked():
                        method_path.write_text(method_original + "\n", encoding="utf-8")
                    finished.set()
                with tools.guarded_result(gate_check=server.transport._require_gate):
                    thread = threading.Thread(target=change_method)
                    thread.start()
                    assert entered.wait(5) and not finished.wait(0.2)
                thread.join(5)
                assert not thread.is_alive() and finished.is_set()
                rejected = await client.post(endpoint + "/internal/v1/tools/context/method", headers=headers, json={"protocol_version": 1, "call_id": "changed-method"})
                assert rejected.status_code == 409
                rejected_result = await client.post(endpoint + "/internal/v1/result", headers=headers, json=result_request)
                assert rejected_result.status_code == 409
                with drafts._locked():
                    method_path.write_text(method_original, encoding="utf-8")
                with pytest.raises(RuntimeError, match="事务检查"):
                    with tools.guarded_result(gate_check=server.transport._require_gate) as db:
                        db.execute("UPDATE agent_runs SET goal=? WHERE run_id=?", ("事务检查", run_id))
                        raise RuntimeError("事务检查")
                assert runs.read_run(run_id)["goal"] == "核查经营指标"
                with store.connect() as db:
                    db.execute("DELETE FROM objects WHERE namespace=? AND kind='memory' AND id='current'", ("ui-check",))
                rejected = await client.post(endpoint + "/internal/v1/tools/context/memory", headers=headers, json={"protocol_version": 1, "call_id": "deleted-memory"})
                assert rejected.status_code == 409
                with store.connect() as db:
                    store.put(db, "ui-check", "memory", "current", original_memory)
                runs.add_input(run_id, 1, "pending-goal-input", "补充会议关注事项")
                goal_pending = await client.post(endpoint + "/internal/v1/tools/context/method", headers=headers, json={"protocol_version": 1, "call_id": "pending-goal-method"})
                assert goal_pending.status_code == 409 and goal_pending.json()["code"] == "GOAL_CHANGED"
                assert begin_source_cleanup(store, "ui-check", "finance-note", "1")
                pending = await client.get(endpoint + "/internal/v1/request", headers=headers)
                assert pending.status_code == 409 and pending.json()["code"] == "SOURCE_CLEANUP_UNAVAILABLE"
                rejected_result = await client.post(endpoint + "/internal/v1/result", headers=headers, json=result_request)
                assert rejected_result.status_code == 409
                store.control("ui-check", "withdraw", source)
                with store.connect() as db:
                    assert store.get(db, "ui-check", "hermes_source_cleanup", "finance-note")["session_state"] == "COMPLETED"
                restored = sessions.get_or_create(session.key)
                assert restored.get_history() == [] and "_last_summary" not in restored.metadata
                invalidated = await client.get(endpoint + "/internal/v1/request", headers=headers)
                assert invalidated.status_code == 410 and invalidated.json()["code"] == "SOURCE_REVOKED"
                invalidated_result = await client.post(endpoint + "/internal/v1/result", headers=headers, json=result_request)
                assert invalidated_result.status_code == 410 and invalidated_result.json()["code"] == "SOURCE_REVOKED"
        with runs.connect() as db:
            assert db.execute("SELECT count(*) FROM agent_tool_reservations WHERE run_id=?", (run_id,)).fetchone() == (4,)
        events = runs.events(run_id, 0)
        assert len([item for item in events if item["type"] == "TOOL_FINISHED"]) == 3
        assert len([item for item in events if item["type"] == "RESULT_RECORDED"]) == 1
        assert len([item for item in events if item["type"] == "TOOL_STARTED" and item["payload"]["tool_id"] == "boss_meeting_brief"]) == 1

    asyncio.run(exercise())
