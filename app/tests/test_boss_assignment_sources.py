import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from aiohttp import web

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "validation"))

from controls import ControlStore
from boss_command_api import BossCommandAPI
from test_boss_command_api import create_input, send_input, feedback_input
from test_boss_tool_sources import authorized_tool


@pytest.fixture
def scenario(tmp_path):
    from boss_assignment_sources import AssignmentSourcesAPI
    store = ControlStore(tmp_path / "source-review.sqlite")
    store.initialize("ui-check")
    commands = BossCommandAPI(store)
    status, created = commands.execute("BOSS", "boss.assignment.create", create_input())
    assert status == 200
    return store, commands, AssignmentSourcesAPI(store), created


def confirmation(review, task_id, key="owner-source-confirm"):
    view = review.read("BOSS", task_id)
    return {"client_request_id": key, "task_id": task_id, "task_version": view["task"]["version"],
            "review_sha256": view["review_sha256"], "reason": create_input()["purpose"]}


def revise_finance(store):
    with store.connect() as db:
        document = store.get(db, "ui-check", "document", "finance-note")
        document["version"] = str(int(document["version"]) + 1)
        store.put(db, "ui-check", "document", "finance-note", document)
    return document


def test_legacy_source_review_saves_current_binding_without_inventing_history(scenario):
    store, _, review, created = scenario
    with store.connect() as db:
        original = store.get(db, "ui-check", "task", created["task_id"])
        db.execute("DELETE FROM objects WHERE kind='assignment_source_binding' AND id=?", (created["task_id"],))
    view = review.read("BOSS", created["task_id"])
    assert view["binding_state"] == "MISSING" and view["can_confirm"] is True
    assert view["sources"][0]["pinned_version"] is None
    payload = confirmation(review, created["task_id"])
    confirmed = review.execute("BOSS", payload)
    assert confirmed["status"] == original["status"] == "OPEN"
    assert confirmed["version"] == "2" and confirmed["message_sent"] is False
    with store.connect() as db:
        task = store.get(db, "ui-check", "task", created["task_id"])
        assert task["purpose"] == original["purpose"] and task["due_at"] == original["due_at"]
        binding = store.get(db, "ui-check", "assignment_source_binding", task["task_id"])
        assert binding["previous_binding_sha256"] is None
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind='assignment_source_binding_revision'").fetchone()[0] == 0
    content = {key: value for key, value in send_input({**created, "version": confirmed["version"]}).items() if key != "client_request_id"}
    sent = store.invoke("send_assignment", authorized_tool(store, "send_assignment", content, "reviewed-legacy-send"))
    assert sent["task_version"] == "3"


def test_changed_source_requires_explicit_review_and_preserves_known_binding(scenario):
    store, _, review, created = scenario
    with store.connect() as db:
        original = store.get(db, "ui-check", "assignment_source_binding", created["task_id"])
    document = revise_finance(store)
    view = review.read("BOSS", created["task_id"])
    assert view["binding_state"] == "NEEDS_REVIEW" and view["can_confirm"] is True
    assert view["sources"][0]["pinned_version"] == original["source_versions"]["finance-note"]
    payload = confirmation(review, created["task_id"])
    result = review.execute("BOSS", payload)
    assert review.execute("BOSS", payload) == result
    with store.connect() as db:
        revision = store.get(db, "ui-check", "assignment_source_binding_revision", created["task_id"] + ":v1")
        assert revision["binding"] == original
        assert store.get(db, "ui-check", "assignment_source_binding", created["task_id"])["source_versions"] == {"finance-note": document["version"]}
        audit = "".join(row[0] + row[1] for row in db.execute("SELECT input,output FROM audit WHERE operation='boss.assignment.sources.confirm'"))
        assert payload["reason"] not in audit and document["content"] not in audit
    assert review.read("BOSS", created["task_id"])["binding_state"] == "CURRENT"


@pytest.mark.parametrize("change", ["source", "clock", "task"])
def test_source_review_rechecks_complete_snapshot_and_rolls_back_rejected_write(scenario, change):
    store, _, review, created = scenario
    revise_finance(store)
    payload = confirmation(review, created["task_id"])
    with store.connect() as db:
        before = store.get(db, "ui-check", "task", created["task_id"])
        authorization_count = db.execute("SELECT COUNT(*) FROM objects WHERE kind='authorization'").fetchone()[0]
        if change == "source":
            document = store.get(db, "ui-check", "document", "finance-note")
            document["published_at"] = store.get(db, "ui-check", "document", "meeting-minutes")["published_at"]
            store.put(db, "ui-check", "document", "finance-note", document)
        elif change == "clock":
            clock = store.get(db, "ui-check", "clock", "current")
            clock["version"] = str(int(clock["version"]) + 1)
            store.put(db, "ui-check", "clock", "current", clock)
        else:
            before["version"] = str(int(before["version"]) + 1)
            store.put(db, "ui-check", "task", before["task_id"], before)
    with pytest.raises(web.HTTPConflict):
        review.execute("BOSS", payload)
    with store.connect() as db:
        assert store.get(db, "ui-check", "task", created["task_id"]) == before
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind='authorization'").fetchone()[0] == authorization_count


@pytest.mark.parametrize("role,error", [(None, web.HTTPUnauthorized), ("MAINTAINER", web.HTTPForbidden), ("coordinator-1", web.HTTPForbidden)])
def test_source_review_is_owner_only(scenario, role, error):
    _, _, review, created = scenario
    payload = confirmation(review, created["task_id"])
    with pytest.raises(error):
        review.read(role, created["task_id"])
    with pytest.raises(error):
        review.execute(role, payload)


@pytest.mark.parametrize("state,error", [("CONFLICTED", web.HTTPConflict), ("SUPERSEDED", web.HTTPConflict),
    ("INCOMPLETE", web.HTTPConflict), ("RECEIVED", web.HTTPConflict), ("WITHDRAWN", web.HTTPGone), ("EXPIRED", web.HTTPGone)])
def test_source_review_never_authorizes_noncurrent_documents(scenario, state, error):
    store, _, review, created = scenario
    payload = confirmation(review, created["task_id"])
    with store.connect() as db:
        document = store.get(db, "ui-check", "document", "finance-note")
        document["validity_state"] = state
        store.put(db, "ui-check", "document", "finance-note", document)
    view = review.read("BOSS", created["task_id"])
    assert view["can_confirm"] is False and view["sources"][0]["excerpt"] is None
    with pytest.raises(error):
        review.execute("BOSS", payload)


def test_source_review_rejects_current_binding_and_canceled_task(scenario):
    store, commands, review, created = scenario
    assert review.read("BOSS", created["task_id"])["can_confirm"] is False
    with pytest.raises(web.HTTPConflict):
        review.execute("BOSS", confirmation(review, created["task_id"]))
    assert commands.execute("BOSS", "boss.assignment.cancel", {"client_request_id": "review-cancel-task",
        "task_id": created["task_id"], "task_version": "1", "reason": create_input()["purpose"]})[0] == 200
    revise_finance(store)
    assert review.read("BOSS", created["task_id"])["can_confirm"] is False
    with pytest.raises(web.HTTPConflict):
        review.execute("BOSS", confirmation(review, created["task_id"]))


def test_concurrent_source_review_has_one_confirmation_and_reopens_consistently(scenario):
    store, _, review, created = scenario
    revise_finance(store)
    payload = confirmation(review, created["task_id"])
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(review.execute, "BOSS", {**payload, "client_request_id": key})
                   for key in ("concurrent-review-first", "concurrent-review-second")]
    assert sum(future.exception() is None for future in futures) == 1
    assert all(future.exception() is None or isinstance(future.exception(), web.HTTPConflict) for future in futures)
    from boss_assignment_sources import AssignmentSourcesAPI
    reopened = AssignmentSourcesAPI(ControlStore(store.path))
    assert reopened.read("BOSS", created["task_id"])["binding_state"] == "CURRENT"
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM idempotency WHERE operation='boss.assignment.sources.confirm'").fetchone()[0] == 1


def test_review_does_not_replace_result_evidence_or_confirm_completion(scenario):
    store, commands, review, created = scenario
    status, sent = commands.execute("BOSS", "boss.assignment.send", send_input(created))
    assert status == 200
    status, feedback = commands.execute("MAINTAINER", "boss.simulation.feedback", feedback_input(
        {"task_id": created["task_id"], "version": sent["task_version"]}))
    assert status == 200
    with store.connect() as db:
        original = store.get(db, "ui-check", "feedback", feedback["feedback_id"])
        outbox_count = db.execute("SELECT COUNT(*) FROM objects WHERE kind='outbox'").fetchone()[0]
    revise_finance(store)
    view = review.read("BOSS", created["task_id"])
    assert view["result_evidence_requires_resubmission"] is True
    confirmed = review.execute("BOSS", confirmation(review, created["task_id"]))
    assert confirmed["status"] == "RESULT_SUBMITTED" and confirmed["business_status_unchanged"] is True
    with store.connect() as db:
        assert store.get(db, "ui-check", "feedback", feedback["feedback_id"]) == original
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind='outbox'").fetchone()[0] == outbox_count
    assert commands.execute("BOSS", "boss.assignment.complete", {"client_request_id": "review-old-result-complete",
        "task_id": created["task_id"], "task_version": confirmed["version"], "feedback_id": feedback["feedback_id"]})[0] == 409


def test_reconfirmed_minutes_origin_preserves_original_task_provenance(scenario):
    from test_boss_minutes_assignment_chain import save_minutes, confirm_minutes, create_linked_task
    store, commands, review, _ = scenario
    assert save_minutes(commands)[0] == 200
    assert confirm_minutes(commands)[0] == 200
    status, linked = create_linked_task(commands)
    assert status == 200
    with store.connect() as db:
        original = store.get(db, "ui-check", "task", linked["task_id"])
        document = store.get(db, "ui-check", "document", "meeting-minutes")
        document["version"] = str(int(document["version"]) + 1)
        store.put(db, "ui-check", "document", "meeting-minutes", document)
    confirmed = review.execute("BOSS", confirmation(review, linked["task_id"], "origin-source-review"))
    content = {key: value for key, value in send_input({**linked, "version": confirmed["version"]}).items() if key != "client_request_id"}
    assert store.invoke("send_assignment", authorized_tool(store, "send_assignment", content, "origin-reviewed-send"))["task_version"] == "3"
    with store.connect() as db:
        task = store.get(db, "ui-check", "task", linked["task_id"])
        assert task["origin_source_version"] == original["origin_source_version"]
        assert store.get(db, "ui-check", "assignment_source_binding", linked["task_id"])["origin_source"]["version"] == document["version"]


def test_completed_task_source_review_is_read_only(scenario):
    store, commands, review, created = scenario
    status, sent = commands.execute("BOSS", "boss.assignment.send", send_input(created))
    assert status == 200
    status, feedback = commands.execute("MAINTAINER", "boss.simulation.feedback", feedback_input({"task_id": created["task_id"], "version": sent["task_version"]}))
    assert status == 200
    assert commands.execute("BOSS", "boss.assignment.complete", {"client_request_id": "source-review-completed",
        "task_id": created["task_id"], "task_version": feedback["task"]["version"], "feedback_id": feedback["feedback_id"]})[0] == 200
    revise_finance(store)
    assert review.read("BOSS", created["task_id"])["can_confirm"] is False
    with pytest.raises(web.HTTPConflict):
        review.execute("BOSS", confirmation(review, created["task_id"]))


@pytest.mark.parametrize("field", ["access_scope", "source_type"])
def test_source_review_withholds_current_source_outside_approved_scope(scenario, field):
    store, _, review, created = scenario
    payload = confirmation(review, created["task_id"])
    with store.connect() as db:
        data = store.get(db, "ui-check", "initial", "snapshot")
        document = store.get(db, "ui-check", "document", "finance-note")
        document[field] = data["contacts"][0]["contact_id"] if field == "access_scope" else "PUBLIC_SOURCE"
        store.put(db, "ui-check", "document", "finance-note", document)
    view = review.read("BOSS", created["task_id"])
    assert view["can_confirm"] is False
    assert view["sources"][0]["excerpt"] is None and view["sources"][0]["current_version"] is None
    with pytest.raises(web.HTTPForbidden):
        review.execute("BOSS", payload)


def test_committed_source_confirmation_remains_readable_after_withdrawal(scenario):
    store, _, review, created = scenario
    document = revise_finance(store)
    payload = confirmation(review, created["task_id"])
    result = review.execute("BOSS", payload)
    store.control("ui-check", "withdraw", {"source_id": "finance-note", "version": document["version"]})
    assert review.execute("BOSS", payload) == result
    with pytest.raises(web.HTTPConflict):
        review.execute("BOSS", {**payload, "reason": payload["reason"] + "。"})


def test_source_review_projection_and_input_use_declared_schema(scenario):
    from jsonschema import Draft202012Validator, FormatChecker
    from boss_assignment_sources import SCHEMA
    store, _, review, created = scenario
    for definition, value in (("Projection", review.read("BOSS", created["task_id"])),
                              ("ConfirmationInput", confirmation(review, created["task_id"]))):
        Draft202012Validator({**SCHEMA, "$ref": "#/$defs/" + definition}, format_checker=FormatChecker()).validate(value)
    revise_finance(store)
    review.execute("BOSS", confirmation(review, created["task_id"]))
    Draft202012Validator(SCHEMA, format_checker=FormatChecker()).validate(review.read("BOSS", created["task_id"]))


def test_current_source_projection_uses_callers_existing_transaction(scenario):
    store, _, review, created = scenario
    with store.connect() as db:
        db.execute("BEGIN")
        projection = review.project_in_transaction("BOSS", db, created["task_id"])
        assert projection["binding_state"] == "CURRENT"
        with pytest.raises(web.HTTPForbidden):
            review.project_in_transaction("MAINTAINER", db, created["task_id"])
