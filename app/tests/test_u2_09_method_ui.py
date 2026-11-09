import json
import sqlite3
import subprocess
from pathlib import Path

from nanobot.agent.skills import SkillsLoader
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.config.loader import save_config
from nanobot.config.schema import Config

from agent_run_method_selection import AgentRunMethodSelection
from agent_run_broker import RunIdentity
from agent_run_store import RunStore
from boss_native_skills import BossSkillCatalog
from boss_skill_drafts import BossSkillDrafts
from test_agent_run_result import setup_result


ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / ".work/upgrade2/u2-03/sop04-context-tests-002"


def test_method_events_reach_run_panel(tmp_path):
    cases = []
    for directory in ("test_local_registered_tools_re0", "test_local_registered_tools_re1"):
        source = BASE / directory / "business.sqlite"
        with sqlite3.connect(f"file:{source}?mode=ro&immutable=1", uri=True) as db:
            run_id = db.execute("SELECT run_id FROM agent_runs").fetchone()[0]
        store = RunStore(source, allow_migration=False)
        run = store.read_run(run_id)
        events = store.events(run_id, 0)
        method = next(event for event in events if event["type"] == "TOOL_FINISHED" and event["payload"].get("tool_id") == "read_enabled_method")
        cases.append({"run": run, "events": events, "method": method})
    store, runs, results, sink = setup_result(tmp_path, full_sources=True)
    config = Config()
    config.agents.defaults.workspace = str(ROOT / "agent")
    config_path = tmp_path / "config.json"
    save_config(config, config_path)
    catalog = BossSkillCatalog(SkillsLoader(ROOT / "agent"), ToolRegistry())
    drafts = BossSkillDrafts(store, catalog, config_path)
    service = AgentRunMethodSelection(runs, results.scope, catalog, drafts, allow_migration=True)
    with runs.connect() as db:
        db.execute("BEGIN")
        methods = service.catalog_in_transaction(db)
        db.row_factory = sqlite3.Row
        run = db.execute("SELECT * FROM agent_runs WHERE run_id=?", (sink.config.run_id,)).fetchone()
        proof = results.scope.prove("result-check", ["simulation-meeting-material"])
        identity = RunIdentity(proof.owner_id, proof.namespace, "BOSS", frozenset({proof.chat_id}), frozenset({"simulation-meeting-material"}))
        allowed = service.can_reselect_in_transaction(db, run, identity)
    projection = {"run_id":run["run_id"],"goal_revision":run["goal_revision"],"selection_allowed":allowed,"methods":methods}
    result = subprocess.run(["node", str(ROOT / "app/tests/u2_09_method_ui_check.cjs")], cwd=ROOT,
                            input=json.dumps({"cases":cases,"catalog":projection}, ensure_ascii=False), text=True, capture_output=True, check=True)
    assert json.loads(result.stdout)["checked"] == 2


def test_sop04_missing_dependencies_from_actual_catalog():
    catalog = BossSkillCatalog(SkillsLoader(ROOT / "agent"), ToolRegistry())
    methods, _ = catalog._snapshot()
    method = next(item for item in methods if item["sop_id"] == "SOP04")
    assert method["version"] == "0.1.0"
    assert method["context_eligible"] is False
    assert "boss.meeting.brief.prepare" in method["missing_tools"]
    assert method["model_adoption_verified"] is False
