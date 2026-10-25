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


def authorized_tool(store, operation, content, key):
    from boss_command_api import _data_envelope
    from business import initial_materials
    authorization_id = store.authorize("ui-check", operation, content)
    return {**content, "authorization_id": authorization_id, "idempotency_key": key,
            "envelope": _data_envelope(initial_materials(), key)}


def direct_creation(store):
    from test_boss_command_api import create_input
    content = {key: value for key, value in create_input().items() if key != "client_request_id"}
    return authorized_tool(store, "create_assignment", content, "direct-source-create")


@pytest.mark.parametrize("operation", ["create_assignment", "send_assignment"])
@pytest.mark.parametrize("state,error", [("CONFLICTED", web.HTTPConflict), ("SUPERSEDED", web.HTTPConflict),
    ("INCOMPLETE", web.HTTPConflict), ("RECEIVED", web.HTTPConflict), ("WITHDRAWN", web.HTTPGone), ("EXPIRED", web.HTTPGone)])
def test_direct_writing_tools_check_current_source_before_write(tmp_path, operation, state, error):
    from test_boss_command_api import send_input
    store, _, _ = service(tmp_path)
    payload = direct_creation(store)
    expected_tasks = 0
    if operation == "send_assignment":
        created = store.invoke("create_assignment", payload)
        content = {key: value for key, value in send_input(created).items() if key != "client_request_id"}
        payload = authorized_tool(store, operation, content, "direct-source-send")
        expected_tasks = 1
    with store.connect() as db:
        document = store.get(db, "ui-check", "document", "finance-note")
        document["validity_state"] = state
        store.put(db, "ui-check", "document", "finance-note", document)
    with pytest.raises(error):
        store.invoke(operation, payload)
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind='task'").fetchone()[0] == expected_tasks
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind='outbox'").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM idempotency WHERE operation=?", (operation,)).fetchone()[0] == 0


@pytest.mark.parametrize("change", ["version", "metadata"])
def test_direct_send_requires_creation_time_source_binding(tmp_path, change):
    from test_boss_command_api import send_input
    store, _, _ = service(tmp_path)
    created = store.invoke("create_assignment", direct_creation(store))
    content = {key: value for key, value in send_input(created).items() if key != "client_request_id"}
    payload = authorized_tool(store, "send_assignment", content, "direct-source-change-send")
    with store.connect() as db:
        document = store.get(db, "ui-check", "document", "finance-note")
        if change == "version":
            document["version"] = str(int(document["version"]) + 1)
        else:
            document["published_at"] = store.get(db, "ui-check", "document", "meeting-minutes")["published_at"]
        store.put(db, "ui-check", "document", "finance-note", document)
    with pytest.raises(web.HTTPConflict):
        store.invoke("send_assignment", payload)
    with store.connect() as db:
        task = store.get(db, "ui-check", "task", created["task_id"])
        assert task["status"] == "OPEN" and task["version"] == "1"
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind='outbox'").fetchone()[0] == 0


@pytest.mark.parametrize("field", ["owner_id", "scope", "issuer_identity", "target_id", "content_version", "valid_from"])
def test_direct_tool_validates_current_authorization_identity_scope_and_window(tmp_path, field):
    store, _, _ = service(tmp_path)
    payload = direct_creation(store)
    with store.connect() as db:
        authorization = store.get(db, "ui-check", "authorization", payload["authorization_id"])
        data = store.get(db, "ui-check", "initial", "snapshot")
        authorization[field] = {"owner_id": data["contacts"][0]["contact_id"], "scope": data["dataset_id"],
            "issuer_identity": "MAINTAINER", "target_id": data["historical_task"]["task_id"],
            "content_version": str(int(payload["content_version"]) + 1), "valid_from": authorization["valid_until"]}[field]
        store.put(db, "ui-check", "authorization", authorization["authorization_id"], authorization)
    with pytest.raises(web.HTTPForbidden):
        store.invoke("create_assignment", payload)
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind='task'").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM idempotency WHERE operation='create_assignment'").fetchone()[0] == 0


def test_new_request_key_cannot_reuse_committed_create_authorization(tmp_path):
    store, _, _ = service(tmp_path)
    payload = direct_creation(store)
    original = store.invoke("create_assignment", payload)
    assert store.invoke("create_assignment", payload) == original
    with pytest.raises(web.HTTPConflict):
        store.invoke("create_assignment", {**payload, "idempotency_key": "direct-source-create-another"})
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind='task'").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM idempotency WHERE operation='create_assignment'").fetchone()[0] == 1


@pytest.mark.parametrize("operation", ["create_assignment", "send_assignment"])
def test_direct_writing_tool_rejects_source_outside_owner_scope(tmp_path, operation):
    from test_boss_command_api import send_input
    store, _, _ = service(tmp_path)
    payload = direct_creation(store)
    if operation == "send_assignment":
        created = store.invoke("create_assignment", payload)
        content = {key: value for key, value in send_input(created).items() if key != "client_request_id"}
        payload = authorized_tool(store, operation, content, "direct-scope-send")
    with store.connect() as db:
        data = store.get(db, "ui-check", "initial", "snapshot")
        document = store.get(db, "ui-check", "document", "finance-note")
        document["access_scope"] = data["contacts"][0]["contact_id"]
        store.put(db, "ui-check", "document", "finance-note", document)
    with pytest.raises(web.HTTPForbidden):
        store.invoke(operation, payload)


@pytest.mark.parametrize("operation", ["create_assignment", "send_assignment"])
def test_direct_writing_tool_checks_contact_at_business_clock(tmp_path, operation):
    from datetime import date, datetime, time, timedelta
    from test_boss_command_api import send_input
    store, _, _ = service(tmp_path)
    payload = direct_creation(store)
    if operation == "send_assignment":
        created = store.invoke("create_assignment", payload)
        content = {key: value for key, value in send_input(created).items() if key != "client_request_id"}
        payload = authorized_tool(store, operation, content, "direct-contact-send")
    with store.connect() as db:
        data = store.get(db, "ui-check", "initial", "snapshot")
        clock = store.get(db, "ui-check", "clock", "current")
        clock["at"] = datetime.combine(date.fromisoformat(data["contacts"][0]["valid_until"]) + timedelta(days=1),
                                       time.min, tzinfo=datetime.fromisoformat(clock["at"]).tzinfo).isoformat()
        store.put(db, "ui-check", "clock", "current", clock)
    with pytest.raises(web.HTTPForbidden):
        store.invoke(operation, payload)


def test_direct_send_without_creation_binding_requires_explicit_review(tmp_path):
    from test_boss_command_api import send_input
    store, _, _ = service(tmp_path)
    created = store.invoke("create_assignment", direct_creation(store))
    content = {key: value for key, value in send_input(created).items() if key != "client_request_id"}
    payload = authorized_tool(store, "send_assignment", content, "direct-legacy-send")
    with store.connect() as db:
        db.execute("DELETE FROM objects WHERE kind='assignment_source_binding' AND id=?", (created["task_id"],))
    with pytest.raises(web.HTTPConflict):
        store.invoke("send_assignment", payload)


@pytest.mark.parametrize("field", ["owner_id", "scope", "issuer_identity", "target_id", "content_version", "valid_from"])
def test_completion_control_validates_owner_authorization_before_decision(tmp_path, field):
    from test_boss_command_api import create_input, send_input, feedback_input
    store, _, _ = service(tmp_path)
    api = BossCommandAPI(store)
    status, created = api.execute("BOSS", "boss.assignment.create", create_input())
    assert status == 200
    status, sent = api.execute("BOSS", "boss.assignment.send", send_input(created))
    assert status == 200
    status, feedback = api.execute("MAINTAINER", "boss.simulation.feedback", feedback_input({"task_id": created["task_id"], "version": sent["task_version"]}))
    assert status == 200
    content = {"task_id": created["task_id"], "task_version": feedback["task"]["version"], "feedback_id": feedback["feedback_id"]}
    authorization_id = store.authorize("ui-check", "complete_assignment", content)
    with store.connect() as db:
        data = store.get(db, "ui-check", "initial", "snapshot")
        authorization = store.get(db, "ui-check", "authorization", authorization_id)
        authorization[field] = {"owner_id": data["contacts"][0]["contact_id"], "scope": data["dataset_id"],
            "issuer_identity": "MAINTAINER", "target_id": data["historical_task"]["task_id"],
            "content_version": str(int(content["task_version"]) + 1), "valid_from": authorization["valid_until"]}[field]
        store.put(db, "ui-check", "authorization", authorization_id, authorization)
    with pytest.raises(web.HTTPForbidden):
        store.control("ui-check", "decide", {"authorization_id": authorization_id, **content})
    with store.connect() as db:
        assert store.get(db, "ui-check", "task", created["task_id"])["status"] == "RESULT_SUBMITTED"


def test_direct_tool_lifecycle_reopens_and_reads_committed_receipts_after_revocation(tmp_path):
    from test_boss_command_api import send_input
    store, _, _ = service(tmp_path)
    creation = direct_creation(store)
    created = store.invoke("create_assignment", creation)
    content = {key: value for key, value in send_input(created).items() if key != "client_request_id"}
    sending = authorized_tool(store, "send_assignment", content, "direct-lifecycle-send")
    sent = store.invoke("send_assignment", sending)
    for authorization_id in (creation["authorization_id"], sending["authorization_id"]):
        store.control("ui-check", "revoke", {"authorization_id": authorization_id})
    restored = ControlStore(store.path)
    assert restored.invoke("create_assignment", creation) == created
    assert restored.invoke("send_assignment", sending) == sent
    task = restored.invoke("read_assignment", {"envelope": creation["envelope"], "task_id": created["task_id"]})
    assert task["status"] == "WAITING_FEEDBACK" and task["message_ids"] == [sent["message_id"]]
    with restored.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind='outbox'").fetchone()[0] == 1
        assert restored.get(db, "ui-check", "assignment_source_binding", created["task_id"])["source_versions"] == {"finance-note": "1"}


def test_concurrent_new_keys_use_one_owner_creation_authorization_once(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    store, _, _ = service(tmp_path)
    payload = direct_creation(store)

    def execute(key):
        return store.invoke("create_assignment", {**payload, "idempotency_key": key})

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(execute, key) for key in ("direct-concurrent-first", "direct-concurrent-second")]
    outcomes = []
    for future in futures:
        if future.exception() is None:
            outcomes.append(future.result()["status"])
        else:
            assert isinstance(future.exception(), web.HTTPConflict)
            outcomes.append("CONFLICT")
    assert sorted(outcomes) == ["CONFLICT", "OPEN"]
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind='task'").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM idempotency WHERE operation='create_assignment'").fetchone()[0] == 1


def test_public_created_assignment_is_readable_through_declared_tool_schema(tmp_path):
    from boss_command_api import _data_envelope
    from business import initial_materials
    from test_boss_command_api import create_input
    store, _, _ = service(tmp_path)
    status, created = BossCommandAPI(store).execute("BOSS", "boss.assignment.create", create_input())
    assert status == 200
    result = store.invoke("read_assignment", {"envelope": _data_envelope(initial_materials(), "public-tool-read"), "task_id": created["task_id"]})
    assert result["task_id"] == created["task_id"] and result["status"] == "OPEN"
    with store.connect() as db:
        assert store.get(db, "ui-check", "task", created["task_id"])["source_versions"] == {"finance-note": "1"}


@pytest.mark.parametrize("change,error", [("expired", web.HTTPGone), ("version", web.HTTPConflict), ("metadata", web.HTTPConflict)])
def test_direct_send_rechecks_original_minutes_source_binding(tmp_path, change, error):
    from test_boss_command_api import create_input, send_input
    from test_boss_meeting_approval import minutes_input
    store, _, _ = service(tmp_path)
    api = BossCommandAPI(store)
    assert api.execute("BOSS", "boss.minutes.save", minutes_input())[0] == 200
    assert api.execute("BOSS", "boss.minutes.confirm", {"client_request_id": "direct-origin-confirm", "meeting_id": "meeting-1",
        "expected_version": "1", "source_id": "meeting-minutes", "source_version": "1"})[0] == 200
    with store.connect() as db:
        minute = store.get(db, "ui-check", "minutes", "meeting-1")
    values = create_input()
    status, created = api.execute("BOSS", "boss.minutes.assignment.create", {"client_request_id": "direct-origin-create",
        "meeting_id": "meeting-1", "minute_version": minute["version"],
        "entry_id": next(entry["entry_id"] for entry in minute["entries"] if entry["kind"] == "ASSIGNMENT_DRAFT"),
        **{key: values[key] for key in ("purpose", "coordinator_id", "due_at", "timezone", "evidence_requirements")}})
    assert status == 200
    content = {key: value for key, value in send_input(created).items() if key != "client_request_id"}
    payload = authorized_tool(store, "send_assignment", content, "direct-origin-send")
    with store.connect() as db:
        document = store.get(db, "ui-check", "document", "meeting-minutes")
        if change == "expired":
            document["valid_until"] = store.get(db, "ui-check", "clock", "current")["at"]
        elif change == "version":
            document["version"] = str(int(document["version"]) + 1)
        else:
            document["published_at"] = store.get(db, "ui-check", "document", "finance-note")["published_at"]
        store.put(db, "ui-check", "document", "meeting-minutes", document)
    with pytest.raises(error):
        store.invoke("send_assignment", payload)
    with store.connect() as db:
        assert store.get(db, "ui-check", "task", created["task_id"])["status"] == "OPEN"
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind='outbox'").fetchone()[0] == 0


@pytest.mark.parametrize("change", ["version", "metadata", "missing_binding"])
def test_completion_requires_result_submission_time_evidence_binding(tmp_path, change):
    from test_boss_command_api import create_input, send_input, feedback_input
    store, _, _ = service(tmp_path)
    api = BossCommandAPI(store)
    status, created = api.execute("BOSS", "boss.assignment.create", create_input())
    assert status == 200
    status, sent = api.execute("BOSS", "boss.assignment.send", send_input(created))
    assert status == 200
    status, result = api.execute("MAINTAINER", "boss.simulation.feedback", feedback_input(
        {"task_id": created["task_id"], "version": sent["task_version"]}, evidence=["meeting-minutes"]))
    assert status == 200
    with store.connect() as db:
        if change == "missing_binding":
            feedback = store.get(db, "ui-check", "feedback", result["feedback_id"])
            feedback.pop("evidence_versions", None)
            feedback.pop("evidence_fingerprints", None)
            store.put(db, "ui-check", "feedback", feedback["feedback_id"], feedback)
        else:
            document = store.get(db, "ui-check", "document", "meeting-minutes")
            if change == "version":
                document["version"] = str(int(document["version"]) + 1)
            else:
                document["published_at"] = store.get(db, "ui-check", "document", "finance-note")["published_at"]
            store.put(db, "ui-check", "document", "meeting-minutes", document)
        authorization_count = db.execute("SELECT COUNT(*) FROM objects WHERE kind='authorization'").fetchone()[0]
    status, _ = api.execute("BOSS", "boss.assignment.complete", {"client_request_id": "result-binding-complete",
        "task_id": created["task_id"], "task_version": result["task"]["version"], "feedback_id": result["feedback_id"]})
    assert status == 409
    with store.connect() as db:
        assert store.get(db, "ui-check", "task", created["task_id"])["status"] == "RESULT_SUBMITTED"
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind='authorization'").fetchone()[0] == authorization_count


@pytest.mark.parametrize("scope_valid", [True, False])
def test_canceled_feedback_keeps_expired_evidence_history_with_owner_scope_checks(tmp_path, scope_valid):
    from test_boss_command_api import create_input, send_input, feedback_input
    store, _, _ = service(tmp_path)
    api = BossCommandAPI(store)
    status, created = api.execute("BOSS", "boss.assignment.create", create_input())
    assert status == 200
    status, sent = api.execute("BOSS", "boss.assignment.send", send_input(created))
    assert status == 200
    status, canceled = api.execute("BOSS", "boss.assignment.cancel", {"client_request_id": "history-scope-cancel",
        "task_id": created["task_id"], "task_version": sent["task_version"], "reason": create_input()["purpose"]})
    assert status == 200
    with store.connect() as db:
        data = store.get(db, "ui-check", "initial", "snapshot")
        document = store.get(db, "ui-check", "document", "finance-note")
        document["valid_until"] = store.get(db, "ui-check", "clock", "current")["at"]
        if not scope_valid:
            document["access_scope"] = data["contacts"][0]["contact_id"]
        store.put(db, "ui-check", "document", "finance-note", document)
    payload = {key: value for key, value in feedback_input({"task_id": created["task_id"], "version": canceled["version"]}).items()
               if key != "client_request_id"}
    if scope_valid:
        result = store.control("ui-check", "feedback", payload)
        assert result["feedback"]["historical_only"] is True and result["task"]["status"] == "CANCELED"
    else:
        with pytest.raises(web.HTTPForbidden):
            store.control("ui-check", "feedback", payload)


@pytest.mark.parametrize("state,error", [("CONFLICTED", web.HTTPConflict), ("SUPERSEDED", web.HTTPConflict),
    ("INCOMPLETE", web.HTTPConflict), ("RECEIVED", web.HTTPConflict), ("WITHDRAWN", web.HTTPGone), ("EXPIRED", web.HTTPGone)])
def test_active_feedback_cannot_adopt_noncurrent_source_before_save(tmp_path, state, error):
    from test_boss_command_api import create_input, send_input, feedback_input
    store, _, _ = service(tmp_path)
    api = BossCommandAPI(store)
    status, created = api.execute("BOSS", "boss.assignment.create", create_input())
    assert status == 200
    status, sent = api.execute("BOSS", "boss.assignment.send", send_input(created))
    assert status == 200
    with store.connect() as db:
        document = store.get(db, "ui-check", "document", "finance-note")
        document["validity_state"] = state
        store.put(db, "ui-check", "document", "finance-note", document)
    payload = {key: value for key, value in feedback_input({"task_id": created["task_id"], "version": sent["task_version"]}).items()
               if key != "client_request_id"}
    with pytest.raises(error):
        store.control("ui-check", "feedback", payload)
    with store.connect() as db:
        assert store.get(db, "ui-check", "task", created["task_id"])["status"] == "WAITING_FEEDBACK"
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind='feedback'").fetchone()[0] == 0


def test_new_result_evidence_submission_preserves_old_binding_and_can_be_confirmed(tmp_path):
    from test_boss_command_api import create_input, send_input, feedback_input
    store, _, _ = service(tmp_path)
    api = BossCommandAPI(store)
    status, created = api.execute("BOSS", "boss.assignment.create", create_input())
    assert status == 200
    status, sent = api.execute("BOSS", "boss.assignment.send", send_input(created))
    assert status == 200
    payload = {key: value for key, value in feedback_input({"task_id": created["task_id"], "version": sent["task_version"]},
        evidence=["meeting-minutes"]).items() if key != "client_request_id"}
    first = store.control("ui-check", "feedback", payload)
    with store.connect() as db:
        old = store.get(db, "ui-check", "feedback", first["feedback"]["feedback_id"])
        document = store.get(db, "ui-check", "document", "meeting-minutes")
        document["version"] = str(int(document["version"]) + 1)
        store.put(db, "ui-check", "document", "meeting-minutes", document)
    second = store.control("ui-check", "feedback", {**payload, "task_version": first["task"]["version"]})
    reopened = ControlStore(store.path)
    with reopened.connect() as db:
        assert reopened.get(db, "ui-check", "feedback", old["feedback_id"]) == old
        assert second["feedback"]["evidence_versions"] == {"meeting-minutes": document["version"]}
    status, _ = BossCommandAPI(reopened).execute("BOSS", "boss.assignment.complete", {"client_request_id": "result-binding-current-complete",
        "task_id": created["task_id"], "task_version": second["task"]["version"], "feedback_id": second["feedback"]["feedback_id"]})
    assert status == 200
    with reopened.connect() as db:
        assert reopened.get(db, "ui-check", "task", created["task_id"])["status"] == "COMPLETED_CONFIRMED"


def test_direct_send_keeps_task_version_increasing_after_a_prior_owner_update(tmp_path):
    from test_boss_command_api import send_input
    store, _, _ = service(tmp_path)
    created = store.invoke("create_assignment", direct_creation(store))
    with store.connect() as db:
        task = store.get(db, "ui-check", "task", created["task_id"])
        task["version"] = str(int(task["version"]) + 1)
        store.put(db, "ui-check", "task", task["task_id"], task)
    content = {key: value for key, value in send_input({**created, "version": task["version"]}).items() if key != "client_request_id"}
    result = store.invoke("send_assignment", authorized_tool(store, "send_assignment", content, "owner-updated-task-send"))
    assert result["task_version"] == str(int(task["version"]) + 1)
