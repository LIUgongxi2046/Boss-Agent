import json
import sqlite3
from dataclasses import asdict, replace
from pathlib import Path

import pytest
from aiohttp import web
from nanobot.agent.skills import SkillsLoader
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.config.loader import save_config
from nanobot.config.schema import Config

from agent_artifact_formats import create_runtime_format, parse_format, verify_runtime_format
from agent_artifact_meeting_brief import RuntimeMeetingBriefPreparation
from agent_artifacts import ArtifactPreparation
from agent_run_method_selection import AgentRunMethodSelection
from agent_run_meeting_scope import meeting_context_in_transaction
from agent_run_object_scope import AgentRunObjectScope
from agent_run_requirements import RunRequirements
from agent_run_tool_budget import RunToolBudget
from boss_meetings import MeetingAPI
from boss_native_skills import BossSkillCatalog
from boss_skill_drafts import BossSkillDrafts
from boss_simulation_api import _context
from business import checksum
from hermes_bridge import EngineEventSink
from hermes_domain_intents import prepare_meeting_brief_in_transaction
from hermes_skill_adapter import HermesSkillAdapter
from test_agent_run_result import setup_result


ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("format_name", ["MARKDOWN", "PDF", "DOCX", "XLSX", "PPTX"])
def test_runtime_format_reads_simulated_meeting_material(tmp_path, format_name):
    store, _, _, _ = setup_result(tmp_path, full_sources=True)
    with store.connect() as db:
        source = store.get(db, "ui-check", "document", "simulation-meeting-material")
        meeting = MeetingAPI(store)._data(db)["meeting"]
    paragraphs = ["会议简报", meeting["meeting_id"], meeting["version"], source["source_id"], source["version"], source["content"]]
    content = create_runtime_format(format_name, paragraphs)
    assert parse_format(format_name, content)["format"] == format_name
    verify_runtime_format(format_name, content, paragraphs)
    with pytest.raises(ValueError, match="不一致"):
        verify_runtime_format(format_name, content, paragraphs + ["未登记内容"])


def test_runtime_brief_rejects_missing_method_adoption(tmp_path):
    store, runs, results, sink = setup_result(tmp_path, full_sources=True)
    workspace = tmp_path / "artifacts"
    workspace.mkdir()
    runs.configure_file_budget(sink.config.run_id, sink.lease_owner, sink.config.lease_epoch, 1, 200000)
    preparation = ArtifactPreparation(store, workspace, run_gate=sink, scope_service=results.scope, max_files=1, max_bytes=200000)
    config = Config()
    config.agents.defaults.workspace = str(ROOT / "agent")
    config_path = tmp_path / "config.json"
    save_config(config, config_path)
    catalog = BossSkillCatalog(SkillsLoader(ROOT / "agent"), ToolRegistry())
    drafts = BossSkillDrafts(store, catalog, config_path)
    skill = HermesSkillAdapter(store, results.scope, catalog, drafts, run_gate=sink, sop_id="SOP04")
    AgentRunObjectScope(runs, results.scope, allow_migration=True)
    AgentRunMethodSelection(runs, results.scope, catalog, drafts, allow_migration=True)
    service = RuntimeMeetingBriefPreparation(preparation, skill, allow_migration=True)
    with store.connect() as db:
        meeting = MeetingAPI(store)._data(db)["meeting"]
        source = store.get(db, "ui-check", "document", "simulation-meeting-material")
    sections = [{"kind": "FACT", "text": source["content"], "source_ids": [source["source_id"]]}]
    arguments = {"request_key": "meeting-brief", "format_name": "MARKDOWN", "expected_goal_revision": 1, "meeting_id": meeting["meeting_id"], "meeting_version": meeting["version"], "sections": sections}
    with pytest.raises(ValueError, match="会议编号或版本"):
        service.create(sink.config.run_id, [source["source_id"]], **{**arguments, "meeting_version": "outdated"})
    with pytest.raises(ValueError, match="目标版本"):
        service.create(sink.config.run_id, [source["source_id"]], **{**arguments, "expected_goal_revision": 2})
    with pytest.raises(ValueError):
        service.create(sink.config.run_id, ["finance-note"], **arguments)
    with pytest.raises(ValueError, match="明确对象选择"):
        service.create(sink.config.run_id, [source["source_id"]], **arguments)
    with runs.connect() as db:
        assert db.execute("SELECT count(*) FROM agent_artifact_briefs").fetchone() == (0,)
        assert db.execute("SELECT count(*) FROM agent_file_reservations").fetchone() == (0,)
    assert list(workspace.iterdir()) == []


def test_runtime_brief_requires_selected_scope_format_and_method(tmp_path):
    store, runs, results, sink = setup_result(tmp_path)
    object_scope = AgentRunObjectScope(runs, results.scope, allow_migration=True)
    RunRequirements(runs, allow_migration=True)
    with store.connect() as db:
        session = results.scope.sources._session(db, _context(db), "result-check")
        binding = store.get(db, "ui-check", "conversation_source_binding", session["session_id"])
        document = store.get(db, "ui-check", "document", "meeting-minutes")
        binding["source_refs"].append({"source_id": "meeting-minutes", "version": document["version"]})
        binding["source_pins"].append({"source_id": "meeting-minutes", "version": document["version"], "content_sha256": checksum(document)})
        store.put(db, "ui-check", "conversation_source_binding", session["session_id"], binding)
    sources = ["finance-note", "meeting-minutes"]
    proof = results.scope.prove("result-check", sources)
    run_id = runs.create_run(proof.owner_id, proof.namespace, "brief-scope-create", "brief-scope-digest")
    with runs.connect() as db:
        db.execute("UPDATE agent_runs SET conversation_id=?,goal=?,selected_refs=?,scope_proof=? WHERE run_id=?", ("result-check", "会议资料技术核查", json.dumps(sources), json.dumps(asdict(proof)), run_id))
        db.commit()
        db.execute("BEGIN IMMEDIATE")
        context = meeting_context_in_transaction(object_scope, db, proof, "meeting-1")
        ref = {"entity_type": "meeting_context", "object_id": "meeting-1", "version": context["meeting"]["version"], "sha256": checksum(context)}
        db.row_factory = sqlite3.Row
        run = db.execute("SELECT * FROM agent_runs WHERE run_id=?", (run_id,)).fetchone()
        db.row_factory = None
        object_scope._bind_in_transaction(db, run, proof, {"expected_goal_revision": 1, "request_key": "technical-scope", "objects": [ref]})
        RunRequirements.save_in_transaction(db, run_id, 1, "technical-outputs", ["MARKDOWN"])
    lease = runs.acquire_queued_for_execution(run_id, 0, "brief-worker", 60)
    gate = EngineEventSink(runs, replace(sink.config, run_id=run_id, lease_epoch=lease["epoch"]), "brief-worker")
    runs.configure_file_budget(run_id, gate.lease_owner, gate.config.lease_epoch, 1, 200000)
    workspace = tmp_path / "brief-workspace"
    workspace.mkdir()
    preparation = ArtifactPreparation(store, workspace, run_gate=gate, scope_service=results.scope, max_files=1, max_bytes=200000)
    config = Config()
    config.agents.defaults.workspace = str(ROOT / "agent")
    config_path = tmp_path / "brief-config.json"
    save_config(config, config_path)
    catalog = BossSkillCatalog(SkillsLoader(ROOT / "agent"), ToolRegistry())
    drafts = BossSkillDrafts(store, catalog, config_path)
    skill = HermesSkillAdapter(store, results.scope, catalog, drafts, run_gate=gate, sop_id="SOP04")
    AgentRunMethodSelection(runs, results.scope, catalog, drafts, allow_migration=True)
    service = RuntimeMeetingBriefPreparation(preparation, skill, allow_migration=True)
    RunToolBudget(runs, allow_migration=True)
    arguments = {"request_key": "brief", "format_name": "DOCX", "expected_goal_revision": 1, "meeting_id": "meeting-1", "meeting_version": "1", "sections": [{"kind": "FACT", "text": "技术核查", "source_ids": ["finance-note"]}]}
    with pytest.raises(ValueError, match="格式缺少本人选择"):
        service.create(run_id, sources, **arguments)
    with pytest.raises(ValueError, match="方法选择"):
        service.create(run_id, sources, **{**arguments, "format_name": "MARKDOWN"})
    with runs.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        result = prepare_meeting_brief_in_transaction(db, store, object_scope, gate, {"meeting_id": "meeting-1", "meeting_version": "1", "expected_version": "0"}, "technical-domain-brief")
        assert result["version"] == "1"
        db.row_factory = sqlite3.Row
        run = db.execute("SELECT * FROM agent_runs WHERE run_id=?", (run_id,)).fetchone()
        db.row_factory = None
        with pytest.raises(ValueError, match="工具回执"):
            service._domain_brief(db, run, context, [], None)
        db.rollback()
    with runs.connect() as db:
        assert db.execute("SELECT count(*) FROM objects WHERE kind='meeting_brief'").fetchone() == (0,)
    with store.connect() as db:
        initial = store.get(db, "ui-check", "initial", "snapshot")
        initial["meeting"]["participant_ids"] = ["finance-1"]
        store.put(db, "ui-check", "initial", "snapshot", initial)
    with pytest.raises(web.HTTPConflict) as error:
        service.create(run_id, sources, **{**arguments, "format_name": "MARKDOWN"})
    assert "成员已经变化" in error.value.text
    with runs.connect() as db:
        assert db.execute("SELECT count(*) FROM agent_file_reservations WHERE run_id=?", (run_id,)).fetchone() == (0,)
    assert list(workspace.iterdir()) == []
