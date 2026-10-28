import json
import sys
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "validation"))

from boss_comprehensive_simulation import populate
from boss_page_api import BossPageAPI
from controls import ControlStore


@pytest.fixture
def services(tmp_path):
    store = ControlStore(tmp_path / "admin-current.sqlite")
    store.initialize("ui-check")
    populate(store, "2026-10-28T09:00:00+08:00")
    return store, BossPageAPI(store)


def read(pages, path, query=""):
    status, result = pages.serve("MAINTAINER", path, query)
    assert status == 200, result
    return result


def test_admin_current_dataset_matches_boss_records_and_sanitizes_private_content(services):
    store, pages = services
    view = read(pages, "/api/boss/ui/admin/technical/datasets")
    current = view["current_snapshot"]
    with store.connect() as db:
        initial = store.get(db, "ui-check", "initial", "snapshot")
        private_text = store.get(db, "ui-check", "memory", "current")["text"]
    assert current["dataset_id"] == initial["dataset_id"] == view["current"]["dataset_id"]
    assert current["dataset_version"] == initial["dataset_version"]
    assert current["counts"]["initial_contact"] == len(initial["contacts"]) == 14
    assert current["counts"]["financial_detail"] == len(initial["details"])
    assert current["counts"]["task_summary"] == 12
    assert current["counts"]["meeting_summary"] == 4
    assert current["counts"]["application_summary"] == 4
    assert view["datasets"] == []
    records = read(pages, "/api/boss/ui/admin/technical/datasets/current-records",
                   "kind=initial_contact&offset=0&snapshot_sha256=" + current["snapshot_sha256"])
    assert records["records"] == initial["contacts"]
    documents = read(pages, "/api/boss/ui/admin/technical/datasets/current-records",
                     "kind=document_metadata&offset=0&snapshot_sha256=" + current["snapshot_sha256"])
    assert all("content" not in row for row in documents["records"])
    assert private_text not in json.dumps([current, records, documents], ensure_ascii=False)
    assert pages.serve("BOSS", "/api/boss/ui/admin/technical/datasets")[0] == 403
    assert pages.serve("MAINTAINER", "/api/boss/ui/admin/technical/datasets/current-records",
                       "kind=initial_contact&offset=0&snapshot_sha256=" + "0" * 64)[0] == 409


def test_admin_configuration_and_records_are_current_without_creating_history(services):
    store, pages = services
    with store.connect() as db:
        before = list(db.execute("SELECT namespace,kind,id,body FROM objects ORDER BY namespace,kind,id"))
        configuration = store.get(db, "ui-check", "configuration", "current")
        tasks = {json.loads(body)["task_id"]: json.loads(body) for body, in db.execute("SELECT body FROM objects WHERE kind='task'")}
    prompts = read(pages, "/api/boss/ui/workspace/prompt-versions")
    assert prompts["effective_runtime"]["model_id"] == configuration["model_id"]
    assert prompts["effective_runtime"]["configuration_version"] == configuration["version"]
    assert prompts["active"] == [] and prompts["drafts"] == []
    events = read(pages, "/api/boss/ui/admin/technical/simulation-events")
    assert events["records"] == []
    feedback = [row for row in events["business_records"] if row["kind"] == "feedback"]
    assert len(feedback) == sum(bool(task["feedback_ids"]) for task in tasks.values()) == 7
    assert all(row["related_object_id"] in tasks for row in feedback)
    assert all(row["title"] == tasks[row["related_object_id"]]["purpose"] for row in feedback)
    for row in events["business_records"]:
        if row["kind"] == "task":
            assert {source["source_id"]: source["version"] for source in row["source_refs"]} == tasks[row["id"]]["source_versions"]
    scheduler = read(pages, "/api/boss/ui/workspace/scheduler")
    assert scheduler["current_events"]
    evaluation = read(pages, "/api/boss/ui/admin/technical/evaluation")
    assert evaluation["attempts"] == [] and evaluation["observed_runs"] == []
    with store.connect() as db:
        assert before == list(db.execute("SELECT namespace,kind,id,body FROM objects ORDER BY namespace,kind,id"))


def test_admin_read_responses_match_published_schema(services):
    _, pages = services
    spec = yaml.safe_load((ROOT / "specs/admin-current-read.openapi.yaml").read_text())
    snapshot = read(pages, "/api/boss/ui/admin/technical/datasets")["current_snapshot"]
    runtime = read(pages, "/api/boss/ui/workspace/prompt-versions")["effective_runtime"]
    records = read(pages, "/api/boss/ui/admin/technical/simulation-events")["business_records"]
    values = [("CurrentSnapshot", snapshot), ("EffectiveRuntime", runtime)] + [("BusinessRecord", row) for row in records]
    for name, value in values:
        Draft202012Validator({**spec, "$ref": "#/components/schemas/" + name}).validate(value)
