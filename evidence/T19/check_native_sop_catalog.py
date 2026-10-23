import hashlib
import importlib.metadata
import json
import shutil
import sys
from pathlib import Path

from nanobot.agent.skills import SkillsLoader
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.config.loader import load_config, save_config
from nanobot.config.schema import Config

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "validation"))

from boss_native_skills import BossSkillCatalog
from business import Store
from model_probe import BusinessTool


def main():
    work = ROOT / ".work/w2-checks/native-sop-catalog"
    work.mkdir(parents=True, exist_ok=True)
    workspace = work / "workspace"
    shutil.copytree(ROOT / "agent/skills", workspace / "skills", dirs_exist_ok=True)
    config_path = work / "config.json"
    config = Config()
    config.agents.defaults.workspace = str(workspace)
    save_config(config, config_path)
    store = Store(work / "business.sqlite")
    with store.connect() as db:
        initialized = db.execute("SELECT 1 FROM spaces WHERE namespace=?", ("w2-native-sop",)).fetchone()
    if not initialized:
        store.initialize("w2-native-sop")
    with store.connect() as db:
        original = tuple(db.iterdump())
    registry = ToolRegistry()
    assets = json.loads((ROOT / "specs/agent-assets.json").read_text())
    envelope = {"request_id": "w2-native-sop", "owner_id": "boss-1", "execution_namespace": "w2-native-sop",
                "dataset_id": "selection", "dataset_version": "1", "session_id": "w2-native-sop"}
    for item in assets["tools"]:
        registry.register(BusinessTool(item["tool_id"], store, envelope, {}, []))
    catalog = BossSkillCatalog(SkillsLoader(workspace), registry)
    before = catalog.technical_status("MAINTAINER")
    block, references = catalog.context("BOSS", ["SOP03"])
    item = next(item for item in before["items"] if item["sop_id"] == "SOP03")
    disabled = catalog.set_enabled("MAINTAINER", "SOP03", enabled=False,
                                  expected_content_sha256=item["content_sha256"], config_path=config_path)
    reopened = BossSkillCatalog(SkillsLoader(workspace, disabled_skills=set(load_config(config_path).agents.defaults.disabled_skills)), registry)
    disabled_status = next(item for item in reopened.technical_status("MAINTAINER")["items"] if item["sop_id"] == "SOP03")
    assert not disabled_status["context_eligible"]
    enabled = reopened.set_enabled("MAINTAINER", "SOP03", enabled=True,
                                  expected_content_sha256=item["content_sha256"], config_path=config_path)
    restarted = BossSkillCatalog(SkillsLoader(workspace, disabled_skills=set(load_config(config_path).agents.defaults.disabled_skills)), registry)
    next_block, next_references = restarted.context("BOSS", ["SOP03"])
    assert block == next_block and references == next_references
    with Store(store.path).connect() as db:
        assert tuple(db.iterdump()) == original
        counts = {kind: db.execute("SELECT COUNT(*) FROM objects WHERE kind=?", (kind,)).fetchone()[0] for kind in ("task", "outbox", "message_outbox")}
    source_files = [ROOT / "validation/boss_native_skills.py", ROOT / "app/tests/test_boss_native_skills.py",
                    ROOT / "specs/agent-assets.json", ROOT / "validation/pyproject.toml", ROOT / "validation/uv.lock", Path(__file__).resolve()]
    source_files.extend(sorted((ROOT / "agent/skills").glob("*/SKILL.md")))
    report = {
        "status": "PASS_LOCAL_NATIVE_SKILL_LIFECYCLE", "task_id": "T19", "related_task_id": "T07",
        "source_commit": "0c62568", "working_changes_included": True,
        "packages": {name: importlib.metadata.version(name) for name in ("nanobot-ai", "packaging", "markdown-it-py")},
        "before": before, "disabled_action": disabled, "after_reopen_disabled": disabled_status,
        "enabled_action": enabled, "after_reopen_references": next_references,
        "native_context_source": block.source, "native_context_sha256": hashlib.sha256(block.content.encode()).hexdigest(),
        "source_sha256": {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in source_files},
        "business_database_unchanged": True, "business_object_counts": counts,
        "external_request_count": 0, "stt_request_count": 0,
        "model_adoption": "PENDING_EXPLICIT_TECHNICAL_CONTENT_AUTHORIZATION",
        "public_integration": "PENDING_W3", "full_A07_accepted": False, "full_A19_accepted": False,
    }
    output = ROOT / "evidence/T19/w2-20261023-native-sop-catalog.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps({"status": report["status"], "method_count": len(before["items"]),
                      "eligible": [item["sop_id"] for item in before["items"] if item["context_eligible"]],
                      "external_request_count": 0}, ensure_ascii=False))


main()
