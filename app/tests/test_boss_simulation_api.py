import json
import sqlite3
import sys
from pathlib import Path
from urllib.parse import urlencode

import pytest
from aiohttp import web
from jsonschema import Draft202012Validator, FormatChecker

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "validation"))

from boss_command_api import BossCommandAPI
from boss_page_api import BossPageAPI
from boss_simulation_api import KINDS, SCHEMA, SimulationAPI
from business import checksum, initial_materials
from controls import ControlStore
from test_boss_command_api import create_input
from test_boss_message_calendar import calendar_input
from test_boss_message_calendar import msg_input
from test_boss_meeting_approval import decide_input, minutes_input, seed_input
from test_boss_owner_preferences import act, confirm_input, goals
from test_boss_people import draft
from test_boss_research import request
from test_boss_travel import review_input


@pytest.fixture
def store(tmp_path):
    store = ControlStore(tmp_path / "simulation-api.sqlite")
    store.initialize("ui-check")
    return store


def query(interface="SI07", ids=None, **filters):
    return {"interface_id": interface, "object_ids": ids or [], "filters": filters}


def validate(result):
    Draft202012Validator(SCHEMA, format_checker=FormatChecker()).validate(result)


def content_rows(result, kind=None):
    return [record for record in result["records"] if kind is None or record["entity_type"] == kind]


@pytest.mark.parametrize("interface", KINDS)
def test_each_interface_reads_current_approved_data_and_independent_metadata(store, interface):
    api = SimulationAPI(store)
    with store.connect() as db:
        before = db.execute("SELECT namespace,kind,id,body FROM objects ORDER BY namespace,kind,id").fetchall()
    result = api.query("BOSS", query(interface))
    validate(result)
    technical = api.inspect("MAINTAINER", query(interface))
    validate(technical)
    assert result["execution_namespace"] == technical["execution_namespace"] == "ui-check"
    assert result["dataset_id"] == "selection" and result["dataset_version"] == "1"
    assert result["missing_fields"] and result["availability"] in ("PARTIAL", "UNAVAILABLE")
    assert all(record["data"] is None and record["content_state"] == "METADATA_ONLY" for record in technical["records"])
    assert all(not record["business_authorization_granted"] for record in result["records"])
    assert technical["sources"] == []
    private = initial_materials()["private_calendar"]["private_body"]
    assert private not in json.dumps(technical, ensure_ascii=False)
    assert initial_materials()["documents"][0]["content"] not in json.dumps(technical, ensure_ascii=False)
    with store.connect() as db:
        assert before == db.execute("SELECT namespace,kind,id,body FROM objects ORDER BY namespace,kind,id").fetchall()
        assert db.execute("SELECT COUNT(*) FROM audit").fetchone()[0] == 0


def test_sales_and_finance_filters_use_exact_approved_period_and_dimensions(store):
    api = SimulationAPI(store)
    result = api.query("BOSS", query(period_start="2026-10-01", period_end="2026-10-10", region_id="region-1",
        product_ids=["product-1"], legal_entity_id="entity-1", customer_id="customer-1", currency="CNY", source_version="1"))
    rows = content_rows(result)
    assert len(rows) == 1 and rows[0]["object_id"] == "CURRENT-0"
    assert rows[0]["data"]["revenue_cny"] == "12000000"
    assert result["business_as_of"] == "2026-10-10T23:59:59+08:00"
    assert result["sources"] == [{"source_id": "finance-note", "version": "1"}]
    assert len(api.inspect("MAINTAINER", query(period_start="2026-10-01", period_end="2026-10-10", customer_id="customer-1"))["records"]) == 1
    finance = api.query("BOSS", query("SI08", ids=["metric_detail:BASE-0"]))
    assert finance["records"][0]["data"]["cost_cny"] == "9000000"
    assert "CASH_NOT_PROVIDED" in finance["missing_fields"]
    for interface in ("SI07", "SI08"):
        unmatched = api.query("BOSS", query(interface, customer_id="unknown-customer"))
        assert unmatched["records"] == [] and unmatched["availability"] == "UNAVAILABLE"


@pytest.mark.parametrize("payload", [
    query(period_start="2026-10-01"), query(period_start="2026-10-02", period_end="2026-10-10"),
    query(period_start="2026-09-01", period_end="2026-10-10"), query(currency="USD"), query(product_ids=[]),
    query(batch_id="unprovided-batch"), query("SI03", period_start="2026-10-01", period_end="2026-10-10"),
    query("SI09", purpose="unknown-purpose"), {**query(), "execution_namespace": "ui-check"},
    {**query(), "owner_id": "boss-1"}, {**query(), "dataset_id": "selection"},
    {**query(), "object_ids": ["BASE-0", "BASE-0"]}, query("SI00"),
])
def test_invalid_or_unsupported_filters_fail_without_ignoring_fields(store, payload):
    for operation, role in ((SimulationAPI(store).query, "BOSS"), (SimulationAPI(store).inspect, "MAINTAINER")):
        with pytest.raises(web.HTTPBadRequest):
            operation(role, payload)


@pytest.mark.parametrize("role,status", [(None, web.HTTPUnauthorized), ("ANONYMOUS", web.HTTPUnauthorized), ("MAINTAINER", web.HTTPForbidden)])
def test_content_access_requires_authenticated_owner(store, role, status):
    with pytest.raises(status):
        SimulationAPI(store).query(role, query("SI03"))


def test_owner_cannot_impersonate_technical_inspection(store):
    with pytest.raises(web.HTTPForbidden):
        SimulationAPI(store).inspect("BOSS", query())


def test_current_calendar_and_deleted_memory_are_not_replaced_by_initial_text(store):
    commands = BossCommandAPI(store)
    status, saved = commands.execute("BOSS", "boss.calendar.save", {"client_request_id": "simulation-calendar-save", **calendar_input()})
    assert status == 200
    api = SimulationAPI(ControlStore(store.path))
    current = content_rows(api.query("BOSS", query("SI03")), "private_calendar")
    assert len(current) == 1 and current[0]["version"] == saved["version"]
    assert checksum(current[0]["data"]["private_body"]) == checksum(calendar_input()["private_body"])
    assert commands.execute("BOSS", "boss.calendar.delete", {"client_request_id": "simulation-calendar-delete", "expected_version": saved["version"]})[0] == 200
    assert commands.execute("BOSS", "boss.memory.delete", {"client_request_id": "simulation-memory-delete", "expected_version": "1"})[0] == 200
    assert content_rows(api.query("BOSS", query("SI03")), "private_calendar")[0]["data"] is None
    assert content_rows(api.query("BOSS", query("SI13")), "memory")[0]["data"] is None


def test_revoked_source_stops_details_documents_and_cached_meeting_text(store):
    commands = BossCommandAPI(store)
    assert commands.execute("BOSS", "boss.meeting.brief.prepare", {"client_request_id": "simulation-meeting-prepare", "meeting_id": "meeting-1", "meeting_version": "1", "expected_version": "0"})[0] == 200
    assert content_rows(SimulationAPI(store).query("BOSS", query("SI05")), "meeting_brief")[0]["data"] is not None
    store.control("ui-check", "withdraw", {"source_id": "finance-note", "version": "1"})
    api = SimulationAPI(ControlStore(store.path))
    for interface, kind in (("SI07", "metric_detail"), ("SI08", "metric_detail"), ("SI05", "meeting_brief")):
        result = api.query("BOSS", query(interface))
        assert all(row["data"] is None for row in content_rows(result, kind))
        assert result["availability"] == "PARTIAL"
        assert any(ref["status"] == "WITHDRAWN" for row in content_rows(result, kind) for ref in row["source_refs"])
    assert content_rows(api.query("BOSS", query("SI13", ids=["finance-note"])), "document")[0]["data"] is None
    technical = api.inspect("MAINTAINER", query("SI13", ids=["finance-note"]))
    assert technical["records"][0]["state"] == "WITHDRAWN" and technical["records"][0]["data"] is None


def test_current_source_version_filter_does_not_return_other_versions_or_memory(store):
    from test_boss_assignment_sources import revise_finance
    revise_finance(store)
    api = SimulationAPI(store)
    assert api.query("BOSS", query(source_version="1"))["records"] == []
    assert api.inspect("MAINTAINER", query(source_version="1"))["records"] == []
    assert len(api.query("BOSS", query(source_version="2"))["records"]) == 8
    metadata = api.inspect("MAINTAINER", query("SI13", source_version="2"))
    assert [record["object_id"] for record in metadata["records"]] == ["finance-note"]


def test_source_scope_never_exposes_foreign_document_body_or_finance_rows(store):
    with store.connect() as db:
        document = store.get(db, "ui-check", "document", "finance-note")
        document["access_scope"] = "different-owner"
        store.put(db, "ui-check", "document", "finance-note", document)
    api = SimulationAPI(store)
    assert api.query("BOSS", query("SI13", ids=["finance-note"]))["records"] == []
    assert api.inspect("MAINTAINER", query("SI13", ids=["finance-note"]))["records"] == []
    assert all(record["data"] is None for record in api.query("BOSS", query())["records"])


def test_owner_profile_uses_current_confirmed_scope_and_revocation(store):
    commands, api = BossCommandAPI(store), SimulationAPI(store)
    assert content_rows(api.query("BOSS", query("SI01")), "profile")[0]["data"]["goals"] == []
    prepared = act(commands, "boss.owner.goals.save", "simulation-goals-save", **goals())[1]
    confirmed = act(commands, "boss.owner.goals.confirm", "simulation-goals-confirm", **confirm_input(prepared))[1]
    assert content_rows(api.query("BOSS", query("SI01")), "profile")[0]["data"]["goals"] == goals()["goals"]
    assert commands.execute("BOSS", "boss.authorization.revoke", {"client_request_id": "simulation-goals-revoke", "authorization_id": confirmed["authorization_id"], "expected_version": "1", "reason": "停止后续采用"})[0] == 200
    result = api.query("BOSS", query("SI01"))
    assert content_rows(result, "profile")[0]["data"]["goals"] == []
    assert content_rows(result, "owner_goals_active")[0]["data"] is None


def test_actual_records_reload_without_reexecuting_actions_and_reset_isolates_them(store, tmp_path):
    commands, api = BossCommandAPI(store), SimulationAPI(store)
    created = commands.execute("BOSS", "boss.assignment.create", create_input())[1]
    assert commands.execute("BOSS", "boss.people.prepare", {"client_request_id": "simulation-person-prepare", **draft()})[0] == 200
    assert commands.execute("BOSS", "boss.travel.review", {"client_request_id": "simulation-travel-review", **review_input()})[0] == 200
    assert request(commands)[0] == 200
    for interface in ("SI02", "SI03", "SI06", "SI12"):
        first = api.query("BOSS", query(interface))
        validate(first)
        second = SimulationAPI(ControlStore(store.path)).query("BOSS", query(interface))
        assert first["records"] == second["records"]
    with store.connect() as db:
        before = db.execute("SELECT COUNT(*) FROM idempotency").fetchone()[0]
        db.execute("BEGIN")
        assert api.project_in_transaction("BOSS", db, query("SI06", ids=[created["task_id"]]))["records"][0]["object_id"] == created["task_id"]
        db.rollback()
        assert db.execute("SELECT COUNT(*) FROM idempotency").fetchone()[0] == before
    backup_path = tmp_path / "simulation-query-backup.sqlite"
    with store.connect() as db, sqlite3.connect(backup_path) as backup:
        db.backup(backup)
    assert SimulationAPI(ControlStore(backup_path)).query("BOSS", query("SI06"))["records"] == api.query("BOSS", query("SI06"))["records"]
    store.control("ui-check", "reset", {"namespace": "new-simulation-query"})
    result = api.query("BOSS", query("SI06", ids=[created["task_id"]]))
    assert result["execution_namespace"] == "new-simulation-query" and result["records"] == []
    assert api.query("BOSS", query("SI01"))["records"][0]["data"]["goals"] == []


def test_ambiguous_active_space_fails_instead_of_selecting_a_namespace(store):
    store.initialize("another-active-space")
    with pytest.raises(web.HTTPConflict):
        SimulationAPI(store).query("BOSS", query())


def test_message_minutes_approval_and_notification_queries_read_actual_objects(store):
    commands, api = BossCommandAPI(store), SimulationAPI(store)
    status, saved = commands.execute("BOSS", "boss.message.draft.save", {"client_request_id": "simulation-message-save", **msg_input()})
    assert status == 200
    draft_row = api.query("BOSS", query("SI04", ids=[saved["draft_id"]]))["records"][0]["data"]
    status, sent = commands.execute("BOSS", "boss.message.send", {"client_request_id": "simulation-message-send", "draft_id": saved["draft_id"],
        "expected_version": saved["version"], "recipient_id": draft_row["recipient_id"], "expected_content_sha256": draft_row["content_sha256"]})
    assert status == 200
    assert commands.execute("MAINTAINER", "boss.simulation.message.reply", {"client_request_id": "simulation-message-reply",
        "message_id": sent["message_id"], "author_contact_id": "coordinator-1", "text": "合成反馈：还缺少证明"})[0] == 200
    assert commands.execute("BOSS", "boss.minutes.save", minutes_input())[0] == 200
    assert commands.execute("MAINTAINER", "boss.simulation.application.seed", seed_input())[0] == 200
    assert commands.execute("BOSS", "boss.approval.decide", decide_input())[0] == 200
    assert commands.execute("MAINTAINER", "boss.simulation.event.seed", {"client_request_id": "simulation-event-seed", "event_id": "event-1"})[0] == 200
    assert commands.execute("MAINTAINER", "boss.simulation.clock.advance", {"client_request_id": "simulation-event-clock", "at": "2026-10-24T18:00:00+08:00"})[0] == 200
    assert store.dispatch_due("ui-check")[0]["state"] == "DELIVERED"
    for interface, kinds in (("SI04", {"message_draft", "message_outbox", "message_reply"}), ("SI05", {"meeting", "minutes"}),
                             ("SI11", {"application", "application_decision"}), ("SI14", {"event", "dispatch", "delivery", "notification"})):
        result = SimulationAPI(ControlStore(store.path)).query("BOSS", query(interface))
        validate(result)
        assert kinds <= {record["entity_type"] for record in result["records"]}
        assert all(record["data"] is not None for record in result["records"])
        technical = api.inspect("MAINTAINER", query(interface))
        validate(technical)
        assert {row["record_id"] for row in technical["records"]} == {row["record_id"] for row in result["records"]}
        for row in result["records"]:
            assert row["data"].get("funds_transferred", False) is False
            assert row["data"].get("external_channel_invoked", False) is False


@pytest.mark.parametrize("state", ["RECEIVED", "INCOMPLETE", "CONFLICTED", "SUPERSEDED", "EXPIRED"])
def test_noncurrent_source_states_withhold_current_content_without_hiding_metadata(store, state):
    with store.connect() as db:
        document = store.get(db, "ui-check", "document", "finance-note")
        if state == "EXPIRED":
            document["valid_until"] = "2026-10-21T09:00:00+08:00"
        else:
            document["validity_state"] = state
        store.put(db, "ui-check", "document", "finance-note", document)
    result = SimulationAPI(store).query("BOSS", query())
    validate(result)
    assert len(result["records"]) == 8
    assert all(row["data"] is None and row["source_refs"][0]["status"] == state for row in result["records"])


def test_cached_source_metadata_and_owner_goals_are_rechecked_before_returning_brief_text(store):
    commands, api = BossCommandAPI(store), SimulationAPI(store)
    assert commands.execute("BOSS", "boss.meeting.brief.prepare", {"client_request_id": "simulation-current-brief", "meeting_id": "meeting-1", "meeting_version": "1", "expected_version": "0"})[0] == 200
    with store.connect() as db:
        source = store.get(db, "ui-check", "document", "finance-note")
        source["valid_until"] = "2026-12-31T09:00:00+08:00"
        store.put(db, "ui-check", "document", "finance-note", source)
    assert content_rows(api.query("BOSS", query("SI05")), "meeting_brief")[0]["data"] is None
    assert commands.execute("BOSS", "boss.meeting.brief.prepare", {"client_request_id": "simulation-updated-brief", "meeting_id": "meeting-1", "meeting_version": "1", "expected_version": "1"})[0] == 200
    assert content_rows(api.query("BOSS", query("SI05")), "meeting_brief")[0]["data"] is not None
    prepared = act(commands, "boss.owner.goals.save", "simulation-brief-goals", **goals())[1]
    assert act(commands, "boss.owner.goals.confirm", "simulation-brief-confirm", **confirm_input(prepared))[0] == 200
    assert content_rows(api.query("BOSS", query("SI05")), "meeting_brief")[0]["data"] is None


def test_foreign_task_binding_is_rejected_without_exposing_task_body(store):
    created = BossCommandAPI(store).execute("BOSS", "boss.assignment.create", create_input())[1]
    with store.connect() as db:
        binding = store.get(db, "ui-check", "assignment_source_binding", created["task_id"])
        binding["owner_id"] = "different-owner"
        store.put(db, "ui-check", "assignment_source_binding", created["task_id"], binding)
    with pytest.raises(web.HTTPForbidden):
        SimulationAPI(store).query("BOSS", query("SI06", ids=[created["task_id"]]))


def test_saved_query_reuses_actual_source_and_detail_binding_without_new_query(store):
    status, response = BossPageAPI(store).serve("BOSS", "/api/boss/ui/metrics")
    assert status == 200
    saved = response["result"]
    api = SimulationAPI(store)
    before = api.query("BOSS", query(ids=[saved["query_id"]]))
    validate(before)
    assert before["records"][0]["data"] == saved
    assert before["business_as_of"] == saved["sources"][0]["business_as_of"]
    assert api.query("BOSS", query(ids=[saved["query_id"]], customer_id="customer-1"))["records"] == []
    assert api.inspect("MAINTAINER", query(ids=[saved["query_id"]], customer_id="customer-1"))["records"] == []
    with store.connect() as db:
        source = store.get(db, "ui-check", "document", "finance-note")
        source["valid_until"] = "2026-12-31T09:00:00+08:00"
        store.put(db, "ui-check", "document", "finance-note", source)
    stale = api.query("BOSS", query(ids=[saved["query_id"]]))
    assert stale["records"][0]["data"] is None and stale["records"][0]["source_refs"][0]["status"] == "CHANGED"
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind='query'").fetchone()[0] == 1


def test_http_adapter_uses_existing_get_channel_with_explicit_array_parameters(store):
    api = SimulationAPI(store)
    parameters = urlencode({"interface_id": "SI07", "object_ids": ["BASE-0", "CURRENT-0"], "product_ids": ["product-1"], "region_id": "region-1"}, doseq=True)
    content = api.query_http("BOSS", parameters)
    assert {row["object_id"] for row in content["records"]} == {"BASE-0", "CURRENT-0"}
    metadata = api.inspect_http("MAINTAINER", parameters)
    validate(content)
    validate(metadata)
    assert [row["record_id"] for row in metadata["records"]] == [row["record_id"] for row in content["records"]]
    assert api.query_http("BOSS", "interface_id=SI07&object_ids=BASE-0%2CCURRENT-0")["records"] == []
    with pytest.raises(web.HTTPForbidden):
        api.query_http("MAINTAINER", parameters)
    with pytest.raises(web.HTTPRequestURITooLong):
        api.query_http("BOSS", "interface_id=SI07&object_ids=" + "x" * 4096)


@pytest.mark.parametrize("parameters", ["", "interface_id=SI07&interface_id=SI08", "interface_id=SI07&region_id=region-1&region_id=region-1",
    "interface_id=SI07&object_ids=", "interface_id=SI07&product_ids=", "interface_id=SI07&owner_id=boss-1", "interface_id=SI03&period_start=2026-10-01&period_end=2026-10-10"])
def test_http_query_rejects_missing_duplicate_empty_and_unsupported_parameters(store, parameters):
    with pytest.raises(web.HTTPBadRequest):
        SimulationAPI(store).query_http("BOSS", parameters)


def test_current_space_cannot_relabel_unapproved_owner_or_dataset_as_selection(store):
    with store.connect() as db:
        initial = store.get(db, "ui-check", "initial", "snapshot")
        initial["dataset_id"] = "unapproved-dataset"
        store.put(db, "ui-check", "initial", "snapshot", initial)
    for operation, role in ((SimulationAPI(store).query, "BOSS"), (SimulationAPI(store).inspect, "MAINTAINER")):
        with pytest.raises(web.HTTPForbidden):
            operation(role, query())


def test_explicit_unknown_source_validity_does_not_become_valid_metadata(store):
    with store.connect() as db:
        document = store.get(db, "ui-check", "document", "finance-note")
        document["validity_state"] = None
        store.put(db, "ui-check", "document", "finance-note", document)
    api = SimulationAPI(store)
    for operation, role in ((api.query, "BOSS"), (api.inspect, "MAINTAINER")):
        with pytest.raises(web.HTTPConflict):
            operation(role, query("SI13", ids=["finance-note"]))


def test_business_identifiers_select_memory_minutes_and_brief_records_for_both_roles(store):
    commands, api = BossCommandAPI(store), SimulationAPI(store)
    status, brief = commands.execute("BOSS", "boss.meeting.brief.prepare", {"client_request_id": "simulation-business-brief", "meeting_id": "meeting-1", "meeting_version": "1", "expected_version": "0"})
    assert status == 200
    status, minute = commands.execute("BOSS", "boss.minutes.save", minutes_input())
    assert status == 200
    memory_id = initial_materials()["memory"]["memory_id"]
    for interface, kind, identifier in (("SI13", "memory", memory_id), ("SI05", "minutes", minute["minute_id"]), ("SI05", "meeting_brief", brief["brief_id"])):
        current = api.query("BOSS", query(interface, ids=[identifier]))
        technical = api.inspect("MAINTAINER", query(interface, ids=[identifier]))
        assert len(current["records"]) == len(technical["records"]) == 1
        assert current["records"][0]["object_id"] == technical["records"][0]["object_id"] == identifier
        assert current["records"][0]["record_id"] == kind + ":" + identifier
        assert current["records"][0]["data"] is not None
        validate(current)
        validate(technical)


def test_query_capacity_rejects_incomplete_candidate_scan_and_allows_exact_object_read(store):
    pages, api = BossPageAPI(store), SimulationAPI(store)
    for _ in range(1001):
        status, result = pages.serve("BOSS", "/api/boss/ui/metrics")
        assert status == 200
    saved = result["result"]
    for operation, role in ((api.query, "BOSS"), (api.inspect, "MAINTAINER")):
        with pytest.raises(web.HTTPRequestEntityTooLarge):
            operation(role, query(product_ids=["product-1"]))
    exact = api.query("BOSS", query(ids=[saved["query_id"]]))
    assert len(exact["records"]) == 1 and exact["records"][0]["data"] == saved
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind='query'").fetchone()[0] == 1001
