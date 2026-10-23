import sys
from datetime import datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "validation"))

from boss_command_api import BossCommandAPI
from boss_page_api import BossPageAPI
from controls import ControlStore
from legacy_assignment_fixture import create_legacy_assignment
from test_boss_command_api import create_input, send_input, feedback_input


@pytest.fixture
def product(tmp_path):
    database = tmp_path / "source-public.sqlite"
    content = {key: value for key, value in create_input().items() if key != "client_request_id"}
    legacy = create_legacy_assignment(database, content)
    store = ControlStore(database)
    commands, pages = BossCommandAPI(store), BossPageAPI(store)
    with store.connect() as db:
        original = store.get(db, "ui-check", "document", "finance-note")
    source = {"source_id": "sim-doc-public-review", "title": original["source_id"],
              "author_contact_id": original["author_contact_id"], "published_at": datetime.fromisoformat(original["published_at"]).date().isoformat(), "content": original["content"]}
    code, result = commands.execute("MAINTAINER", "boss.knowledge.source.create", {"client_request_id": "source-public-create", **source})
    assert code == 200
    return store, commands, pages, source, legacy["task"]


def revise(product):
    _, commands, _, source, _ = product
    code, result = commands.execute("MAINTAINER", "boss.knowledge.source.revise", {
        "client_request_id": "source-public-revise", "expected_version": "1", **source})
    assert code == 200
    return result


def read(product):
    _, _, pages, _, task = product
    code, result = pages.serve("BOSS", "/api/boss/ui/assignment-source-review", "task_id=" + task["task_id"])
    assert code == 200
    return result


def confirm(product):
    _, commands, _, _, task = product
    view = read(product)
    values = {"client_request_id": "source-public-confirm", "task_id": task["task_id"],
              "task_version": view["task"]["version"], "review_sha256": view["review_sha256"], "reason": create_input()["purpose"]}
    code, result = commands.execute("BOSS", "boss.assignment.sources.confirm", values)
    assert code == 200
    return values, result


def test_public_owner_review_tracks_current_source_without_sending(product):
    store, commands, pages, source, task = product
    assert read(product)["binding_state"] == "MISSING"
    changed = read(product)
    assert changed["can_confirm"] is True
    assert changed["sources"][0]["pinned_version"] is None and changed["sources"][0]["current_version"] == "1"
    values, result = confirm(product)
    assert result["status"] == task["status"] == "OPEN" and result["message_sent"] is False
    assert commands.execute("BOSS", "boss.assignment.sources.confirm", values) == (200, result)
    assert read(product)["binding_state"] == "CURRENT"
    projected = next(row for row in pages.serve("BOSS", "/api/boss/ui/tasks")[1]["tasks"] if row["task_id"] == task["task_id"])
    assert projected["source_reference_state"] == "CURRENT"
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind='outbox'").fetchone()[0] == 0
    receipt = pages.serve("BOSS", "/api/boss/ui/operation-status", "action=boss.assignment.sources.confirm&client_request_id=" + values["client_request_id"])[1]
    assert receipt["outcome"] == "RECORDED"
    assert receipt["result"]["sources_reconfirmed"] is True


@pytest.mark.parametrize("query", ["", "task_id=", "task_id=a&task_id=b", "task_id=a&namespace=ui-check", "task_id=a&owner_id=boss-1"])
def test_public_source_review_query_rejection(product, query):
    _, _, pages, _, _ = product
    assert pages.serve("BOSS", "/api/boss/ui/assignment-source-review", query)[0] == 400


def test_maintainer_cannot_review_or_confirm_owner_sources(product):
    _, commands, pages, _, task = product
    assert pages.serve("MAINTAINER", "/api/boss/ui/assignment-source-review", "task_id=" + task["task_id"])[0] == 403
    assert commands.execute("MAINTAINER", "boss.assignment.sources.confirm", {"client_request_id": "source-denied-confirm"})[0] == 403


def test_public_result_resubmission_after_current_source_review(product):
    _, commands, pages, source, task = product
    _, initial_review = confirm(product)
    code, sent = commands.execute("BOSS", "boss.assignment.send", send_input({**task, "version": initial_review["version"]}))
    assert code == 200
    first_input = feedback_input({**task, "version": sent["task_version"]}, evidence=[source["source_id"]])
    code, first = commands.execute("MAINTAINER", "boss.simulation.feedback", first_input)
    assert code == 200
    revise(product)
    assert read(product)["result_evidence_requires_resubmission"] is True
    assert read(product)["binding_state"] == "CURRENT"
    second_input = feedback_input({**task, "version": first["task"]["version"]}, key="source-result-resubmit", evidence=[source["source_id"]])
    code, second = commands.execute("MAINTAINER", "boss.simulation.feedback", second_input)
    assert code == 200
    assert second["feedback_id"] != first["feedback_id"]
    complete = {"client_request_id": "source-public-complete", "task_id": task["task_id"],
                "task_version": second["task"]["version"], "feedback_id": second["feedback_id"]}
    assert commands.execute("BOSS", "boss.assignment.complete", complete)[0] == 200
    assert pages.serve("BOSS", "/api/boss/ui/tasks")[1]["tasks"][0]["status"] == "COMPLETED_CONFIRMED"
