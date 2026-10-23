import hashlib
import argparse
import json
import subprocess
from pathlib import Path
from types import ModuleType

from business import initial_materials, require


ROOT = Path(__file__).resolve().parents[1]
LEGACY_COMMIT = "819e519842e41ee04e360c0ab99caf914c85baab"


def create_legacy_assignment(database, content):
    database = Path(database).resolve()
    require(database.is_relative_to(ROOT / ".work") or database.is_relative_to(ROOT / "validation/.work"),
            "迁移检查数据库必须位于本工程中间目录")
    require(not database.exists(), "迁移检查不能覆盖已有数据库")
    source = subprocess.check_output(["git", "show", LEGACY_COMMIT + ":validation/business.py"], cwd=ROOT)
    module = ModuleType("boss_legacy_business")
    module.__file__ = str(ROOT / "validation/business.py")
    exec(compile(source, module.__file__, "exec"), module.__dict__)
    require(module.initial_materials() == initial_materials(), "历史版本与当前获准资料不一致")
    store = module.Store(database)
    baseline = store.initialize("ui-check")
    authorization_id = store.authorize("ui-check", "create_assignment", content)
    task = store.invoke("create_assignment", {
        "envelope": {"request_id": "legacy-version-check", "owner_id": "boss-1", "execution_namespace": "ui-check",
                     "dataset_id": "selection", "dataset_version": "1", "session_id": "legacy-version-check"},
        "authorization_id": authorization_id, "idempotency_key": "legacy-version-check", **content,
    })
    return {"task": task, "baseline": baseline, "producer_commit": LEGACY_COMMIT,
            "producer_sha256": hashlib.sha256(source).hexdigest(), "model_requested": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", type=Path, required=True)
    args = parser.parse_args()
    directory = args.directory.resolve()
    require(directory.parent == (ROOT / "validation/.work").resolve(), "检查应用目录必须属于当前工程")
    directory.mkdir(mode=0o700)
    result = create_legacy_assignment(directory / "business.sqlite", {
        "purpose": "核查饲料外销经营明细并准备会议", "coordinator_id": "coordinator-1",
        "due_at": "2026-10-25T17:00:00+08:00", "timezone": "Asia/Shanghai",
        "evidence_requirements": ["经营原始明细"], "related_meeting_id": "meeting-1",
        "related_event_ids": ["event-1"], "source_refs": ["finance-note"], "content_version": "1",
    })
    print(json.dumps(result, ensure_ascii=False))
