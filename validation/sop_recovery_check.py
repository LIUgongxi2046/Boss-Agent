import argparse
import hashlib
import json
import os
import uuid
from pathlib import Path

from filelock import FileLock
from nanobot.agent.skills import SkillsLoader
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.config.loader import load_config
from nanobot.webui.settings_services import WebUISettingsConfig

from boss_agent_read_tools import BossResearchSourcesTool
from boss_native_skills import BossSkillCatalog
from boss_skill_drafts import BossSkillDrafts
from business import OPERATIONS, checksum, initial_materials
from controls import ControlStore
from runtime_assignment_source_tool import BossAssignmentSourcesReadTool
from runtime_owner_read_tools import BossTodayReadTool, BossOwnerPlansReadTool


ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--application-directory", type=Path, required=True)
    parser.add_argument("--action", choices=("inspect", "prepare"), required=True)
    parser.add_argument("--sop-id", default="SOP03")
    args = parser.parse_args()
    directory = args.application_directory.resolve(strict=True)
    assert directory.parent == (ROOT / "validation/.work").resolve()
    with FileLock(str(directory / "application.lock"), timeout=0):
        config_path = directory / "config.json"
        config = load_config(config_path)
        store = ControlStore(directory / "business.sqlite")
        with store.connect() as db:
            store.active(db, "ui-check")
            initial = store.get(db, "ui-check", "initial", "snapshot")
            assert initial == initial_materials()
            current = store.get(db, "ui-check", "configuration", "current")
            before = tuple(db.iterdump())
        os.environ["BOSS_APPLICATION_WORK_DIR"] = str(directory)
        os.environ["BOSS_APPLICATION_PORTS"] = json.dumps(json.loads((directory / "instance.json").read_text())["ports"])
        from application import ApplicationTool

        envelope = {"request_id": "sop-recovery-" + str(uuid.uuid4()), "owner_id": initial["owner_id"],
            "execution_namespace": "ui-check", "dataset_id": initial["dataset_id"], "dataset_version": initial["dataset_version"],
            "session_id": "sop-local-recovery"}
        available = {name: ApplicationTool(name, store, envelope, {}, []) for name in OPERATIONS}
        for tool in (BossResearchSourcesTool(store, "BOSS"), BossTodayReadTool(store, "BOSS"),
                     BossOwnerPlansReadTool(store, "BOSS"), BossAssignmentSourcesReadTool(store, "BOSS")):
            available[tool.name] = tool
        registry = ToolRegistry()
        for name in current["tool_scope"]:
            registry.register(available[name])
        loader = SkillsLoader(config.workspace_path, disabled_skills=set(config.agents.defaults.disabled_skills))
        methods = BossSkillDrafts(store, BossSkillCatalog(loader, registry), config_path)
        view = methods.read("MAINTAINER", args.sop_id)
        if args.action == "prepare":
            draft = view["draft"]
            assert draft is not None and draft["state"] == "DRAFT" and draft["validation_status"] == "VALIDATED_STATIC_ONLY"
            assert draft["tool_config_sha256"] == checksum(registry.get_definitions())
            original_sha = hashlib.sha256(config_path.read_bytes()).hexdigest()
            payload = {"client_request_id": "sop-prepared-" + str(uuid.uuid4()), "sop_id": args.sop_id,
                "expected_draft_version": draft["draft_version"], "expected_content_sha256": draft["content_sha256"],
                "expected_active_sha256": view["active"]["content_sha256"]}
            result = WebUISettingsConfig(config_path).run_serialized(lambda path: methods.execute("MAINTAINER", "prepare", payload))
            assert hashlib.sha256(config_path.read_bytes()).hexdigest() == original_sha
        else:
            methods.require_ready()
            block, result = methods.catalog.context("BOSS", [args.sop_id])
            assert block == loader.build_explicit_skill_runtime_context("$boss-" + args.sop_id.lower())
            with store.connect() as db:
                assert tuple(db.iterdump()) == before
        with store.connect() as db:
            counts = {kind: db.execute("SELECT COUNT(*) FROM objects WHERE namespace='ui-check' AND kind=?", (kind,)).fetchone()[0]
                      for kind in ("task", "outbox", "message_outbox", "runtime_run")}
            assert counts == {kind: 0 for kind in counts}
        print(json.dumps({"status": "ACTUAL_VALIDATED_METHOD_PREPARED" if args.action == "prepare" else "ACTUAL_NATIVE_CONTEXT_READ_ONLY",
            "result": result, "application_directory": str(directory.relative_to(ROOT)), "source_type": "SIMULATED",
            "initial_snapshot_sha256": checksum(initial), "tool_config_sha256": checksum(registry.get_definitions()),
            "business_object_counts": counts, "model_requested": False, "external_retrieval_requested": False,
            "method_body_recorded": False}, ensure_ascii=False))


if __name__ == "__main__":
    main()
