import shutil
from pathlib import Path

import pytest
from nanobot.agent.skills import SkillsLoader
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.config.loader import save_config, set_config_path
from nanobot.config.schema import Config

from agent_run_scope import RunScopeService
from agent_run_store import RunStore
from boss_memory_sessions import MemorySessionManager
from boss_native_skills import BossSkillCatalog
from boss_skill_drafts import BossSkillDrafts
from controls import ControlStore
from hermes_bridge import EngineEventSink, EngineRunConfig
from hermes_skill_adapter import HermesSkillAdapter
from model_probe import BusinessTool


def test_method_catalog_and_unbound_run_rejection(tmp_path):
    set_config_path(tmp_path / "config.json")
    workspace = tmp_path / "workspace"
    shutil.copytree(Path(__file__).resolve().parents[2] / "agent/skills", workspace / "skills")
    config = Config()
    config.agents.defaults.workspace = str(workspace)
    save_config(config, tmp_path / "config.json")
    store = ControlStore(tmp_path / "business.sqlite")
    store.initialize("ui-check")
    sessions = MemorySessionManager(workspace, business_store=store, sessions_root=tmp_path / "sessions")
    scope = RunScopeService(store, sessions, "ui-check")
    runs = RunStore(store.path)
    run_id = runs.create_run("technical-check", "ui-check", "method-check", "method-digest")
    lease = runs.acquire_lease(run_id, 0, "method-worker", 60)
    runs.transition(run_id, lease["revision"], "RUNNING", "method-worker", lease["epoch"])
    registry = ToolRegistry()
    envelope = {"request_id": "method-check", "owner_id": "technical-check", "execution_namespace": "ui-check", "dataset_id": "selection", "dataset_version": "1", "session_id": "method-check"}
    for operation in ("query_metrics", "read_evidence"):
        registry.register(BusinessTool(operation, store, envelope, {}, []))
    catalog = BossSkillCatalog(SkillsLoader(workspace), registry)
    block, references = catalog.context("BOSS", ["SOP03"])
    assert block.content
    assert references[0]["sop_id"] == "SOP03"
    drafts = BossSkillDrafts(store, catalog, tmp_path / "config.json")
    run = EngineRunConfig(run_id, lease["epoch"], "903230b1e23e0c496b28e5d2e8c4f2639cd506b6", "http://127.0.0.1:1234", 1)
    adapter = HermesSkillAdapter(store, scope, catalog, drafts, run_gate=EngineEventSink(runs, run, "method-worker"), sop_id="SOP03")
    with pytest.raises(ValueError, match="会话范围"):
        adapter.read()
    with store.connect() as db:
        assert db.execute("SELECT count(*) FROM objects WHERE kind='hermes_skill_adoption'").fetchone()[0] == 0
