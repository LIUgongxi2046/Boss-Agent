import json
import sqlite3
import sys
from pathlib import Path

import pytest
from aiohttp import web

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "validation"))

import runtime_records_query
from controls import ControlStore


@pytest.fixture
def observed_task(tmp_path):
    report = json.loads((ROOT / "evidence/T16/runtime-record-faults/w2-written-client-closed/runtime-records.json").read_text())
    run = report["runs"][0]
    source = ROOT / "validation/.work" / run["namespace"] / "business.sqlite"
    target = tmp_path / "observed-task.sqlite"
    with sqlite3.connect(source.as_uri() + "?mode=ro", uri=True) as original:
        with sqlite3.connect(target) as copied:
            original.backup(copied)
    store = ControlStore(target)
    task_id = next(item["task_id"] for item in run["tool_results"] if "task_id" in item)
    return store, run, task_id


def contents(store):
    with store.connect() as db:
        return tuple(db.iterdump())


def test_failed_real_run_task_metadata_is_current_and_read_only(observed_task):
    store, run, task_id = observed_task
    before = contents(store)
    with store.connect() as db:
        task = store.get(db, run["namespace"], "task", task_id)
    result = runtime_records_query.read_runtime_task_reference(store, "MAINTAINER", run["namespace"], run["run_id"], task_id)
    assert result == {
        "projection": "runtime-task-reference", "source_type": "RUNTIME_RECORD",
        "task_source_type": "SIMULATED", "namespace": run["namespace"], "run_id": run["run_id"],
        "dataset_id": "selection", "dataset_version": "1",
        "task_id": task_id, "task_version": task["version"], "task_status": "OPEN",
        "read_at": result["read_at"], "private_body_available_here": False,
        "business_mutation_performed": False,
    }
    assert run["status"] == "FAILED"
    assert task["purpose"] not in json.dumps(result, ensure_ascii=False)
    assert contents(store) == before


@pytest.mark.parametrize("role,status", [(None, 401), ("CONTACT", 403)])
def test_task_reference_rejects_unauthorized_identity(observed_task, role, status):
    store, run, task_id = observed_task
    before = contents(store)
    with pytest.raises(web.HTTPException) as failure:
        runtime_records_query.read_runtime_task_reference(store, role, run["namespace"], run["run_id"], task_id)
    assert failure.value.status == status
    assert contents(store) == before


def test_task_reference_requires_observed_link_and_active_server_namespace(observed_task):
    store, run, task_id = observed_task
    before = contents(store)
    for namespace, run_id, linked_id, status in [
        (run["namespace"], run["run_id"], run["run_id"], 403),
        (run["namespace"], task_id, task_id, 404),
        (task_id, run["run_id"], task_id, 409),
        (run["namespace"], "", task_id, 400),
    ]:
        with pytest.raises(web.HTTPException) as failure:
            runtime_records_query.read_runtime_task_reference(store, "MAINTAINER", namespace, run_id, linked_id)
        assert failure.value.status == status
    assert contents(store) == before
