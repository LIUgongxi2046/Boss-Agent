import sys
from pathlib import Path
from uuid import uuid4

import pytest
from aiohttp import web

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "validation"))

from boss_command_api import BossCommandAPI
from boss_v7_evaluation import catalogs
from boss_v7_technical import TechnicalWorkspaceAPI
from controls import ControlStore


@pytest.fixture
def store(tmp_path):
    result = ControlStore(tmp_path / "evaluation.sqlite")
    result.initialize("ui-check")
    return result


def catalog(store):
    with store.connect() as db:
        snapshot = store.get(db, "ui-check", "initial", "snapshot")
        return snapshot, catalogs(store, db, snapshot)


def selection(store, task="selection-core", prompt="builtin-runtime", sop="SOP01"):
    _, categories = catalog(store)
    prompt_choice = next(row for row in categories["prompts"] if row["id"] == prompt)
    sop_choice = next(row for row in categories["sops"] if row["id"] == sop)
    return {
        "task_set_id": task, "dataset_snapshot_id": categories["snapshots"][0]["id"],
        "model_version": categories["models"][0]["id"], "prompt_version": prompt,
        "sop_version": sop,
        "expected_versions": {"task_set_id": "1", "dataset_snapshot_id": categories["snapshots"][0]["version"],
                              "model_version": categories["models"][0]["version"],
                              "prompt_version": prompt_choice["version"], "sop_version": sop_choice["version"]},
        "pairing_conditions_confirmed": True,
    }


def run(store, task="selection-core", request_id=None, action="start"):
    values = selection(store, task)
    return BossCommandAPI(store).execute("MAINTAINER", "boss.technical.evaluation." + action,
                                         {"client_request_id": request_id or str(uuid4()), **values})


def read(store, role="MAINTAINER"):
    return TechnicalWorkspaceAPI(store).read(role, "/api/boss/ui/admin/technical/evaluation", "")


def test_projection_lists_real_task_sets_snapshots_and_sop_versions(store):
    projection = read(store)
    assert projection["projection"] == "evaluation"
    assert {row["id"] for row in projection["task_sets"]} == {"selection-core", "selection-evidence"}
    assert projection["snapshots"][0]["id"] == "selection"
    assert projection["models"][0]["id"] == "model-current"
    assert projection["prompts"][0]["id"] == "builtin-runtime"
    assert any(row["id"] == "SOP01" for row in projection["sops"])
    assert projection["attempts"] == [] and projection["evidence"] == []
    assert projection["real_adoption_state"] == "EVALUATION_ONLY_NOT_RUNTIME_ADOPTION"


def test_start_records_actual_assertions_and_evidence(store):
    status, receipt = run(store)
    assert status == 200, receipt
    result = receipt["result"]
    assert result["state"] == "PASSED", result
    projection = read(store)
    assert len(projection["attempts"]) == 1
    attempt = projection["attempts"][0]
    assert attempt["task_set_id"] == "selection-core"
    assert attempt["namespace"] == "ui-check"
    assert attempt["known_cost"] is None and attempt["total_cost"] is None
    assert attempt["usage_coverage"] == "NO_MODEL_REQUESTS"
    assert {row["id"] for row in attempt["assertions"]} == {
        "EVAL-METRIC-GROSS-MARGIN", "EVAL-SOURCE-VALIDITY", "EVAL-MEMORY-CONFIRMATION", "EVAL-READ-ONLY"}
    assert all(row["state"] == "PASSED" for row in attempt["assertions"])
    assert len(projection["evidence"]) == 4
    assert all(row["attempt_id"] == attempt["id"] for row in projection["evidence"])


def test_failed_assertion_is_recorded_and_cannot_be_cancelled(store):
    run(store)
    with store.connect() as db:
        memory = store.get(db, "ui-check", "memory", "current")
        memory["confirmation_state"] = "DRAFT"
        store.put(db, "ui-check", "memory", "current", memory)
    status, receipt = run(store)
    assert status == 200, receipt
    result = receipt["result"]
    assert result["state"] == "FAILED"
    failed = [row for row in read(store)["attempts"] if row["state"] == "FAILED"][0]
    assert any("EVAL-MEMORY-CONFIRMATION" in item for item in result["failures"])
    status, body = BossCommandAPI(store).execute("MAINTAINER", "boss.technical.evaluation.cancel",
                                                 {"client_request_id": str(uuid4()), "attempt_id": failed["id"],
                                                  "expected_state": "FAILED", "expected_namespace": "ui-check"})
    assert status == 409, body


def test_stale_versions_are_rejected_and_roles_are_separated(store):
    values = selection(store)
    values["expected_versions"]["model_version"] = "stale"
    status, body = BossCommandAPI(store).execute("MAINTAINER", "boss.technical.evaluation.start",
                                                 {"client_request_id": str(uuid4()), **values})
    assert status == 409, body
    with pytest.raises(web.HTTPForbidden):
        read(store, "BOSS")
