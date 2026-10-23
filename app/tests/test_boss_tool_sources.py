import sys
from pathlib import Path

import pytest
from aiohttp import web

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "validation"))

from boss_page_api import BossPageAPI
from controls import ControlStore
from boss_command_api import BossCommandAPI
from test_boss_meeting_brief import prepare, briefing


def service(tmp_path):
    store = ControlStore(tmp_path / "tool-sources.sqlite")
    store.initialize("ui-check")
    pages = BossPageAPI(store)
    status, response = pages.serve("BOSS", "/api/boss/ui/metrics")
    assert status == 200
    return store, pages, response["result"]


def evidence(store, query):
    return store.invoke("read_evidence", {"envelope": query["envelope"], "query_id": query["query_id"],
        "source_ids": ["finance-note"], "detail_refs": query["detail_refs"]})


def test_source_revision_requires_new_query_and_reports_actual_source_version(tmp_path):
    store, pages, query = service(tmp_path)
    with store.connect() as db:
        document = store.get(db, "ui-check", "document", "finance-note")
        original = document["content"]
        document["version"] = str(int(document["version"]) + 1)
        store.put(db, "ui-check", "document", "finance-note", document)
    with pytest.raises(web.HTTPConflict):
        evidence(store, query)
    status, response = pages.serve("BOSS", "/api/boss/ui/metrics")
    assert status == 200
    current = response["result"]
    assert current["sources"][0]["version"] == document["version"]
    result = evidence(store, current)
    record = next(row for row in result["original_records"] if row["record_id"] == "finance-note")
    assert result["sources"][0]["version"] == record["version"] == record["content"]["version"] == document["version"]
    assert record["content"]["content"] == original


def test_same_version_metadata_change_invalidates_original_query_binding(tmp_path):
    store, _, query = service(tmp_path)
    with store.connect() as db:
        document = store.get(db, "ui-check", "document", "finance-note")
        document["published_at"] = store.get(db, "ui-check", "document", "meeting-minutes")["published_at"]
        store.put(db, "ui-check", "document", "finance-note", document)
    with pytest.raises(web.HTTPConflict):
        evidence(store, query)


def test_legacy_query_without_binding_requires_requery_without_inventing_history(tmp_path):
    store, _, query = service(tmp_path)
    with store.connect() as db:
        db.execute("DELETE FROM objects WHERE namespace='ui-check' AND kind='query_source_binding' AND id=?", (query["query_id"],))
    with pytest.raises(web.HTTPConflict):
        evidence(store, query)
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind='query_source_binding'").fetchone()[0] == 0
        assert store.get(db, "ui-check", "query", query["query_id"]) == query


@pytest.mark.parametrize("state,error", [("CONFLICTED", web.HTTPConflict), ("SUPERSEDED", web.HTTPConflict),
    ("INCOMPLETE", web.HTTPConflict), ("RECEIVED", web.HTTPConflict), ("WITHDRAWN", web.HTTPGone), ("EXPIRED", web.HTTPGone)])
def test_noncurrent_source_state_stops_metrics_and_evidence(tmp_path, state, error):
    store, pages, query = service(tmp_path)
    with store.connect() as db:
        document = store.get(db, "ui-check", "document", "finance-note")
        document["validity_state"] = state
        store.put(db, "ui-check", "document", "finance-note", document)
    status, _ = pages.serve("BOSS", "/api/boss/ui/metrics")
    assert status == error.status_code
    with pytest.raises(error):
        evidence(store, query)
    query_text = '"' + document["content"] + '"'
    assert store.control("ui-check", "search", {"query": query_text})["results"] == []


def test_source_validity_end_at_business_clock_stops_new_adoption(tmp_path):
    store, pages, query = service(tmp_path)
    with store.connect() as db:
        document = store.get(db, "ui-check", "document", "finance-note")
        document["valid_until"] = store.get(db, "ui-check", "clock", "current")["at"]
        store.put(db, "ui-check", "document", "finance-note", document)
    assert pages.serve("BOSS", "/api/boss/ui/metrics")[0] == 410
    with pytest.raises(web.HTTPGone):
        evidence(store, query)


def test_source_scope_is_checked_at_both_query_and_evidence_read(tmp_path):
    store, pages, query = service(tmp_path)
    with store.connect() as db:
        document = store.get(db, "ui-check", "document", "finance-note")
        data = store.get(db, "ui-check", "initial", "snapshot")
        document["access_scope"] = data["contacts"][0]["contact_id"]
        store.put(db, "ui-check", "document", "finance-note", document)
    assert pages.serve("BOSS", "/api/boss/ui/metrics")[0] == 403
    with pytest.raises(web.HTTPForbidden):
        evidence(store, query)


def test_expired_source_is_not_reused_by_saved_meeting_materials(tmp_path):
    store, pages, _ = service(tmp_path)
    assert prepare(BossCommandAPI(store))[0] == 200
    with store.connect() as db:
        document = store.get(db, "ui-check", "document", "finance-note")
        document["valid_until"] = store.get(db, "ui-check", "clock", "current")["at"]
        store.put(db, "ui-check", "document", "finance-note", document)
    status, view = briefing(pages)
    assert status == 200
    assert view["current_status"] == "NEEDS_REVIEW"
    assert view["current"]["metrics"]["available"] is False
    current = next(row for row in view["current"]["sources"] if row["source_id"] == "finance-note")
    previous = next(row for row in view["saved_brief"]["compiled"]["sources"] if row["source_id"] == "finance-note")
    assert current["status"] == "EXPIRED" and current["excerpt"] is None
    assert previous["excerpt"] is None


def test_same_version_source_change_requires_meeting_material_review(tmp_path):
    store, pages, _ = service(tmp_path)
    assert prepare(BossCommandAPI(store))[0] == 200
    with store.connect() as db:
        document = store.get(db, "ui-check", "document", "finance-note")
        document["published_at"] = store.get(db, "ui-check", "document", "meeting-minutes")["published_at"]
        store.put(db, "ui-check", "document", "finance-note", document)
    _, view = briefing(pages)
    assert view["source_changed"] is True
    previous = next(row for row in view["saved_brief"]["compiled"]["sources"] if row["source_id"] == "finance-note")
    assert previous["excerpt"] is None


@pytest.mark.parametrize("domain", ["minutes", "message", "people", "travel", "meeting", "commitment"])
def test_expired_source_is_rejected_before_dependent_business_write(tmp_path, domain):
    from test_boss_meeting_approval import minutes_input
    from test_boss_message_calendar import msg_input
    from test_boss_people import draft
    from test_boss_travel import review_input
    from test_boss_meeting_changes import draft_input
    from test_boss_command_api import create_input
    from boss_meetings import MeetingAPI
    from business import initial_materials
    store, _, _ = service(tmp_path)
    source_id = "meeting-minutes" if domain in ("minutes", "people") else "finance-note"
    refs = [{"source_id": source_id, "version": "1"}]
    with store.connect() as db:
        document = store.get(db, "ui-check", "document", source_id)
        document["valid_until"] = store.get(db, "ui-check", "clock", "current")["at"]
        store.put(db, "ui-check", "document", source_id, document)
    commands = BossCommandAPI(store)
    if domain == "minutes":
        status, _ = commands.execute("BOSS", "boss.minutes.save", minutes_input())
    elif domain == "message":
        status, _ = commands.execute("BOSS", "boss.message.draft.save", {"client_request_id": "source-message-draft", **msg_input()})
    elif domain == "people":
        status, _ = commands.execute("BOSS", "boss.people.prepare", {"client_request_id": "source-people-prepare", **draft()})
    elif domain == "travel":
        status, _ = commands.execute("BOSS", "boss.travel.review", {"client_request_id": "source-travel-review", **review_input(transport_refs=refs)})
    elif domain == "meeting":
        with pytest.raises(web.HTTPGone):
            MeetingAPI(store).execute("BOSS", "draft.save", draft_input())
        status = 410
    else:
        assert domain == "commitment"
        data = initial_materials()
        status, _ = commands.execute("BOSS", "boss.commitment.create", {"client_request_id": "source-commitment-create", "purpose": create_input()["purpose"],
            "due_at": data["historical_task"]["due_at"], "timezone": data["private_calendar"]["timezone"], "importance": "NORMAL",
            "evidence_requirements": data["historical_task"]["evidence_requirements"], "source_refs": refs})
    assert status == 410
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind='authorization'").fetchone()[0] == 0


def test_expired_completion_evidence_blocks_decision_and_reference_status_is_current(tmp_path):
    from test_boss_command_api import create_input, send_input, feedback_input
    store, _, _ = service(tmp_path)
    api = BossCommandAPI(store)
    status, task = api.execute("BOSS", "boss.assignment.create", create_input())
    assert status == 200
    status, sent = api.execute("BOSS", "boss.assignment.send", send_input(task))
    assert status == 200
    status, feedback = api.execute("MAINTAINER", "boss.simulation.feedback", feedback_input({"task_id": task["task_id"], "version": sent["task_version"]}))
    assert status == 200
    with store.connect() as db:
        document = store.get(db, "ui-check", "document", "finance-note")
        document["valid_until"] = store.get(db, "ui-check", "clock", "current")["at"]
        store.put(db, "ui-check", "document", "finance-note", document)
        authorization_count = db.execute("SELECT COUNT(*) FROM objects WHERE kind='authorization'").fetchone()[0]
    assert store.control("ui-check", "reference_status", {"task_id": task["task_id"]})["sources"][0]["state"] == "EXPIRED"
    status, _ = api.execute("BOSS", "boss.assignment.complete", {"client_request_id": "source-completion-expired", "task_id": task["task_id"],
        "task_version": feedback["task"]["version"], "feedback_id": feedback["feedback_id"]})
    assert status == 410
    with store.connect() as db:
        assert store.get(db, "ui-check", "task", task["task_id"])["status"] == "RESULT_SUBMITTED"
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind='authorization'").fetchone()[0] == authorization_count
