from pathlib import Path
import sys

import pytest
from aiohttp import web

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "validation"))

from boss_today import TodayAPI
from controls import ControlStore
from boss_morning import MorningAPI, QUERY_ACTION, ORDER_ACTION
from boss_command_api import BossCommandAPI
from business import checksum

DAY = {"date": "2026-10-24", "timezone": "Asia/Shanghai"}


def query(api, key="morning-query", **day):
    return api.query("BOSS", {"client_request_id": key, "session_id": "morning-session", **DAY, **day})


def order(view, key="morning-owner-order", **changes):
    return {"client_request_id": key, "list_id": view["list_id"], "date": view["date"], "timezone": view["timezone"],
            "expected_version": view["order_version"], "snapshot_sha256": view["snapshot_sha256"], "item_ids": [item["item_id"] for item in reversed(view["items"])], **changes}


@pytest.fixture
def store(tmp_path):
    value = ControlStore(tmp_path / "morning.sqlite")
    value.initialize("ui-check")
    return value


def test_explicit_day_and_iana_timezone_drive_real_scope(store):
    today = TodayAPI(store)
    first = today.read("BOSS", {"date": "2026-10-23", "timezone": "Asia/Shanghai"})
    second = today.read("BOSS", {"date": "2026-10-24", "timezone": "Asia/Shanghai"})
    assert first["date"] != second["date"]
    assert first["day_start"] == "2026-10-23T00:00:00+08:00"
    assert {item["object_id"] for item in first["items"]} != {item["object_id"] for item in second["items"]}
    assert "meeting-1" in {item["object_id"] for item in first["items"]}
    assert "private-1" in {item["object_id"] for item in second["items"]}


@pytest.mark.parametrize("day", [{"date": "invalid", "timezone": "Asia/Shanghai"}, {"date": "2026-10-24", "timezone": "unknown"}, {"date": "2026-10-24"}, {**DAY, "owner_id": "other"}, {**DAY, "namespace": "other"}])
def test_day_schema_rejects_invalid_or_untrusted_scope(store, day):
    with pytest.raises(web.HTTPBadRequest):
        MorningAPI(store).read("BOSS", day)


def test_persistent_list_details_order_receipt_and_service_reopen(store):
    api = MorningAPI(store)
    view = query(api)
    assert view["profile"]["owner_confirmation"] == "NOT_CONFIRMED"
    assert "OWNER_GOALS_NOT_SET" in view["missing_sources"]
    assert query(api) == view
    private = next(item for item in view["items"] if item["kind"] == "private_calendar")
    detail = api.detail("BOSS", view["list_id"], private["item_id"])
    assert detail["list_version"] == view["list_version"]
    assert detail["objects"][0]["data"]["visibility"] == "PRIVATE"
    request = order(view)
    saved = TodayAPI(store).reorder("BOSS", request)
    assert saved["version"] == "1" and saved["date"] == DAY["date"]
    assert api.reorder("BOSS", request) == saved
    restored = MorningAPI(ControlStore(store.path))
    assert [item["item_id"] for item in restored.read("BOSS", DAY)["items"]] == request["item_ids"]
    assert restored.read_list("BOSS", view["list_id"])["current_order"]["item_ids"] == request["item_ids"]
    assert restored.receipt("BOSS", ORDER_ACTION, request["client_request_id"])["result"] == saved
    assert restored.receipt("BOSS", QUERY_ACTION, "morning-query")["result"]["list_id"] == view["list_id"]
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind='morning_list'").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind IN ('task','outbox','application_decision')").fetchone()[0] == 0


def test_order_checks_day_timezone_set_cas_and_request_digest(store):
    api = MorningAPI(store)
    view = query(api)
    for fields, error in (({"date": "2026-10-23"}, web.HTTPConflict), ({"timezone": "UTC"}, web.HTTPConflict),
                          ({"item_ids": []}, web.HTTPBadRequest), ({"item_ids": [view["items"][0]["item_id"]] * 2}, web.HTTPBadRequest)):
        with pytest.raises(error):
            api.reorder("BOSS", order(view, **fields))
    saved = api.reorder("BOSS", order(view))
    with pytest.raises(web.HTTPConflict):
        api.reorder("BOSS", order(view, key="stale-order"))
    with pytest.raises(web.HTTPConflict):
        api.reorder("BOSS", order(view, item_ids=[item["item_id"] for item in view["items"]]))
    other = api.read("BOSS", {"date": "2026-10-24", "timezone": "UTC"})
    assert other["order_version"] == "0"
    assert api.receipt("BOSS", ORDER_ACTION, "morning-owner-order")["result"] == saved


@pytest.mark.parametrize("role,error", [(None, web.HTTPUnauthorized), ("MAINTAINER", web.HTTPForbidden)])
def test_private_list_and_derived_details_enforce_role(store, role, error):
    api = MorningAPI(store)
    view = query(api)
    for operation in (lambda: api.read(role, DAY), lambda: api.read_list(role, view["list_id"], True),
                      lambda: api.detail(role, view["list_id"], view["items"][0]["item_id"]), lambda: api.reorder(role, {}),
                      lambda: api.receipt(role, QUERY_ACTION, "morning-query")):
        with pytest.raises(error):
            operation()


def test_known_meeting_and_private_intervals_produce_actual_overlap(store):
    from boss_meetings import MeetingAPI
    from test_boss_meeting_changes import draft_input, confirmation
    meetings = MeetingAPI(store)
    draft = meetings.execute("BOSS", "draft.save", draft_input())
    meetings.execute("BOSS", "confirm", confirmation(draft))
    view = query(MorningAPI(store))
    assert view["conflict_state"] == "CONFLICTS_FOUND"
    assert view["conflicts"][0]["starts_at"] == "2026-10-24T18:00:00+08:00"
    assert view["conflicts"][0]["ends_at"] == "2026-10-24T19:00:00+08:00"
    meeting = next(item for item in view["items"] if item["kind"] == "meeting")
    detail = MorningAPI(store).detail("BOSS", view["list_id"], meeting["item_id"])
    assert {doc["source_id"] for doc in detail["documents"]} == {"finance-note", "meeting-minutes"}
    store.control("ui-check", "withdraw", {"source_id": "finance-note", "version": "1"})
    with pytest.raises(web.HTTPConflict):
        MorningAPI(store).detail("BOSS", view["list_id"], meeting["item_id"])
    history = MorningAPI(store).read_list("BOSS", view["list_id"], historical=True)
    assert history["adoption_state"] == "HISTORICAL_REQUIRES_REQUERY" and history["result"]["items"] == []


def test_real_commitment_event_dedup_and_current_rule_priority(store):
    from test_boss_self_commitments import create
    commands = BossCommandAPI(store)
    code, created = create(commands, importance="IMPORTANT")
    assert code == 200
    store.control("ui-check", "rules", {"version": "1", "cooldown_seconds": 0, "quiet_start": 22, "quiet_end": 7, "timezone": "Asia/Shanghai", "important_escalation": True})
    view = query(MorningAPI(store), date="2026-10-23")
    commitment = next(item for item in view["items"] if item["object_id"] == created["commitment_id"])
    assert commitment["important"] is True
    assert {ref["kind"] for ref in commitment["source_refs"]} == {"self_commitment", "event"}
    assert not any(item["kind"] == "event" and item["object_id"] == created["due_event"]["event_id"] for item in view["items"])
    store.control("ui-check", "rules", {"version": "2", "cooldown_seconds": 0, "quiet_start": 22, "quiet_end": 7, "timezone": "Asia/Shanghai", "important_escalation": False})
    assert not any(item["important"] for item in MorningAPI(store).read("BOSS", {"date": "2026-10-23", "timezone": "Asia/Shanghai"})["items"])


def test_formal_coverage_load_source_version_and_expiry_preserve_initial(store):
    from boss_morning_inputs import MorningInputAPI
    inputs = MorningInputAPI(store)
    payload = {**DAY, "client_request_id": "morning-explicit-coverage", "mode": "SIMULATED", "generator_version": "FC03-COVERAGE-1", "seed": 20261024, "expected_version": "0"}
    with store.connect() as db:
        original = checksum(store.get(db, "ui-check", "initial", "snapshot"))
    saved = inputs.load("MAINTAINER", payload)
    assert inputs.load("MAINTAINER", payload) == saved
    view = query(MorningAPI(store))
    assert [row["state"] for row in view["source_coverage"]] == ["NOT_UPDATED", "UNSYNCHRONIZED"]
    assert view["coverage_state"] == "PARTIAL"
    document = MorningAPI(store).source("BOSS", view["list_id"], saved["source_id"])["document"]
    assert document["author_kind"] == "SIMULATED_GENERATOR"
    assert document["real_enterprise_data"] is document["third_party_authorization"] is False
    assert document["business_authorization_granted"] is False
    assert inputs.receipt("MAINTAINER", payload["client_request_id"])["result"] == saved
    with pytest.raises(web.HTTPForbidden):
        inputs.load("BOSS", payload)
    with pytest.raises(web.HTTPBadRequest):
        inputs.load("MAINTAINER", {**payload, "owner_id": "other"})
    inputs.load("MAINTAINER", {**payload, "client_request_id": "coverage-revision", "expected_version": "1"})
    with pytest.raises(web.HTTPConflict):
        MorningAPI(store).read_list("BOSS", view["list_id"])
    store.control("ui-check", "clock", {"at": "2026-12-24T09:00:00+08:00"})
    expired = MorningAPI(store).read("BOSS", DAY)
    assert expired["source_coverage"] == []
    assert any(value.startswith("SOURCE_EXPIRED:") for value in expired["missing_sources"])
    with store.connect() as db:
        assert checksum(store.get(db, "ui-check", "initial", "snapshot")) == original


def test_real_approval_state_and_current_source_are_read_without_deciding(store):
    from test_boss_meeting_approval import seed_input, decide_input
    commands, morning = BossCommandAPI(store), MorningAPI(store)
    assert commands.execute("MAINTAINER", "boss.simulation.application.seed", seed_input())[0] == 200
    view = query(morning)
    application = next(item for item in view["items"] if item["kind"] == "application")
    assert application["category"] == "DECIDE" and application["coordinator_id"] == "boss-1"
    assert morning.detail("BOSS", view["list_id"], application["item_id"])["documents"][0]["source_id"] == "application-1-attachment"
    with store.connect() as db:
        assert store.get(db, "ui-check", "application", "application-1")["state"] == "PENDING_DECISION"
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind='authorization'").fetchone()[0] == 0
    assert commands.execute("BOSS", "boss.approval.decide", decide_input())[0] == 200
    current = morning.read("BOSS", DAY)
    assert not any(item["kind"] == "application" for item in current["items"])
    assert any(row["kind"] == "application" and row["reason"] == "TERMINAL_OR_NOT_ACTIVE" for row in current["excluded_items"])


def test_concurrent_order_cas_and_query_idempotency(store):
    from concurrent.futures import ThreadPoolExecutor
    morning = MorningAPI(store)
    with ThreadPoolExecutor(max_workers=2) as executor:
        views = list(executor.map(lambda _: query(morning), range(2)))
    assert views[0] == views[1]
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(morning.reorder, "BOSS", order(views[0], key=key)) for key in ("concurrent-order-a", "concurrent-order-b")]
    assert sum(future.exception() is None for future in futures) == 1
    assert all(future.exception() is None or isinstance(future.exception(), web.HTTPConflict) for future in futures)
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind='authorization'").fetchone()[0] == 1


def test_private_deletion_redacts_history_and_reset_cannot_adopt_old_list(store):
    from test_boss_message_calendar import calendar_input
    commands = BossCommandAPI(store)
    assert commands.execute("BOSS", "boss.calendar.save", {"client_request_id": "morning-private-save", **calendar_input()})[0] == 200
    api = MorningAPI(store)
    view = query(api)
    assert commands.execute("BOSS", "boss.calendar.delete", {"client_request_id": "morning-private-delete", "expected_version": "2"})[0] == 200
    with pytest.raises(web.HTTPConflict):
        api.read_list("BOSS", view["list_id"])
    history = api.read_list("BOSS", view["list_id"], historical=True)
    assert history["result"]["items"] == [] and history["result"]["conflicts"] == []
    assert history["result"]["conflict_state"] == "INSUFFICIENT_EVIDENCE"
    assert "私人地点" not in str(history) and "隐私事项" not in str(history)
    assert history["binding_references"]
    store.control("ui-check", "reset", {"namespace": "morning-new-space"})
    with pytest.raises(web.HTTPNotFound):
        api.read_list("BOSS", view["list_id"], historical=True)
    assert api.receipt("BOSS", QUERY_ACTION, "morning-query")["outcome"] == "NOT_FOUND_IN_CURRENT_STORE"
    with pytest.raises(web.HTTPConflict):
        query(api)


def test_actual_cross_midnight_and_dst_boundaries(store):
    from datetime import datetime, timezone
    from boss_meetings import MeetingAPI
    from test_boss_meeting_changes import draft_input, confirmation
    from test_boss_message_calendar import calendar_input
    meetings = MeetingAPI(store)
    saved = meetings.execute("BOSS", "draft.save", draft_input(starts_at="2026-10-24T23:30:00+08:00", ends_at="2026-10-25T00:30:00+08:00"))
    meetings.execute("BOSS", "confirm", confirmation(saved))
    code, result = BossCommandAPI(store).execute("BOSS", "boss.calendar.save", {"client_request_id": "midnight-private", **calendar_input(
        starts_at="2026-10-24T23:45:00+08:00", ends_at="2026-10-25T00:15:00+08:00", acknowledge_conflict=True)})
    assert code == 200, result
    first, second = MorningAPI(store).read("BOSS", DAY), MorningAPI(store).read("BOSS", {**DAY, "date": "2026-10-25"})
    assert first["conflicts"][0]["ends_at"] == "2026-10-25T00:00:00+08:00"
    assert second["conflicts"][0]["starts_at"] == "2026-10-25T00:00:00+08:00"
    dst = MorningAPI(store).read("BOSS", {"date": "2026-11-01", "timezone": "America/New_York"})
    duration = datetime.fromisoformat(dst["day_end"]).astimezone(timezone.utc) - datetime.fromisoformat(dst["day_start"]).astimezone(timezone.utc)
    assert duration.total_seconds() == 25 * 3600


def test_confirmed_daily_goal_changes_current_priority_and_revocation_stops_adoption(store):
    from test_boss_self_commitments import create
    from test_boss_owner_preferences import goals, confirm_input
    commands, morning = BossCommandAPI(store), MorningAPI(store)
    code, commitment = create(commands, purpose="本人核对本周经营证据")
    assert code == 200
    before = query(morning)
    assert before["profile"]["goals"] == []
    code, draft = commands.execute("BOSS", "boss.owner.goals.save", {
        "client_request_id": "morning-goal-draft", **goals(scope="DAILY_BRIEF", goals=["经营证据"])})
    assert code == 200, draft
    assert morning.read("BOSS", DAY)["profile"]["goals"] == []
    code, confirmed = commands.execute("BOSS", "boss.owner.goals.confirm", {
        "client_request_id": "morning-goal-confirm", **confirm_input(draft)})
    assert code == 200, confirmed
    current = query(morning, key="morning-with-confirmed-goal")
    item = next(item for item in current["items"] if item["object_id"] == commitment["commitment_id"])
    assert item["goal_matches"] == ["经营证据"]
    assert "MATCHES_CONFIRMED_OWNER_GOAL" in item["sorting_reasons"]
    assert current["profile"]["active_version"] == confirmed["version"]
    with pytest.raises(web.HTTPConflict):
        morning.read_list("BOSS", before["list_id"])
    code, revoked = commands.execute("BOSS", "boss.authorization.revoke", {
        "client_request_id": "morning-goal-revoke", "authorization_id": confirmed["authorization_id"],
        "expected_version": "1", "reason": "停止后续采用"})
    assert code == 200, revoked
    assert morning.read("BOSS", DAY)["profile"]["owner_confirmation"] == "NOT_CONFIRMED"
    with pytest.raises(web.HTTPConflict):
        morning.read_list("BOSS", current["list_id"])


def test_meeting_preparation_deadline_adds_future_meeting_with_original_materials(store):
    from boss_meetings import MeetingAPI
    from test_boss_meeting_changes import draft_input, confirmation
    meetings = MeetingAPI(store)
    draft = meetings.execute("BOSS", "draft.save", draft_input(
        starts_at="2026-10-25T10:00:00+08:00", ends_at="2026-10-25T11:00:00+08:00",
        preparation_due_at="2026-10-24T16:00:00+08:00"))
    meetings.execute("BOSS", "confirm", confirmation(draft))
    morning = MorningAPI(store)
    previous = morning.read("BOSS", {**DAY, "date": "2026-10-23"})
    assert not any(item["kind"] == "meeting" for item in previous["items"])
    view = query(morning)
    meeting = next(item for item in view["items"] if item["kind"] == "meeting")
    assert meeting["due_at"] == "2026-10-24T16:00:00+08:00"
    assert "DUE_WITHIN_SELECTED_DAY" in meeting["sorting_reasons"]
    detail = morning.detail("BOSS", view["list_id"], meeting["item_id"])
    assert {document["source_id"] for document in detail["documents"]} == {"finance-note", "meeting-minutes"}
    assert not any(meeting["item_id"] in conflict["item_ids"] for conflict in view["conflicts"])


def test_existing_plan_and_reminder_remain_actual_read_only_measures(store):
    from boss_owner_plans import OwnerPlansAPI
    from test_boss_owner_plans import create
    commands, plans, morning = BossCommandAPI(store), OwnerPlansAPI(store), MorningAPI(store)
    assert commands.execute("MAINTAINER", "boss.simulation.event.seed", {
        "client_request_id": "morning-event-input", "event_id": "event-1"})[0] == 200
    saved = create(plans)
    assert commands.execute("BOSS", "boss.reminder.ack", {
        "client_request_id": "morning-reminder-ack", "event_id": "event-1", "event_version": "1", "reminder_version": "0"})[0] == 200
    view = query(morning)
    target = next(item for item in view["items"] if item["object_id"] == "historical-1")
    assert {measure["kind"] for measure in target["existing_measures"]} == {"owner_plan", "reminder"}
    assert {measure["state"] for measure in target["existing_measures"]} == {"ACTIVE", "ACKNOWLEDGED"}
    detail = morning.detail("BOSS", view["list_id"], target["item_id"])
    assert any(row["reference"]["id"] == saved["plan_id"] for row in detail["objects"])
    assert plans.read("BOSS")["plans"][0]["state"] == "ACTIVE"
    with store.connect() as db:
        assert store.get(db, "ui-check", "reminder", "event-1")["state"] == "ACKNOWLEDGED"
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind IN ('outbox','dispatch','notification')").fetchone()[0] == 0


def test_saved_order_keeps_new_items_and_current_risk_before_personal_position(store):
    from test_boss_self_commitments import create
    commands, morning = BossCommandAPI(store), MorningAPI(store)
    view = query(morning)
    saved = morning.reorder("BOSS", order(view))
    code, created = create(commands, importance="IMPORTANT")
    assert code == 200, created
    store.control("ui-check", "rules", {"version": "1", "cooldown_seconds": 0, "quiet_start": 22, "quiet_end": 7,
        "timezone": "Asia/Shanghai", "important_escalation": True})
    current = morning.read("BOSS", DAY)
    assert current["items"][0]["object_id"] == created["commitment_id"]
    assert "NEW_ITEM_DEFAULT_ORDER" in current["items"][0]["sorting_reasons"]
    assert [item["item_id"] for item in current["items"] if item["item_id"] in saved["item_ids"]] == saved["item_ids"]
    assert morning.receipt("BOSS", ORDER_ACTION, "morning-owner-order")["result"] == saved
    with pytest.raises(web.HTTPConflict):
        morning.read_list("BOSS", view["list_id"])


def test_formal_schema_and_openapi_extension_reference_the_actual_domain(store):
    import json
    import yaml
    from jsonschema import Draft202012Validator
    root = Path(__file__).resolve().parents[2]
    schema = json.loads((root / "specs/morning.schema.json").read_text())
    Draft202012Validator.check_schema(schema)
    api = yaml.safe_load((root / "specs/openapi.yaml").read_text())["x-fc03-morning"]
    assert api["query_action"] == QUERY_ACTION and api["reorder_action"] == ORDER_ACTION
    for key in ("day_schema", "query_schema", "result_schema", "list_schema", "detail_schema", "source_schema",
                "reorder_schema", "reorder_result_schema", "receipt_schema", "coverage_input_schema", "coverage_result_schema"):
        filename, reference = api[key].split("#")
        assert filename == "morning.schema.json" and reference.removeprefix("/$defs/") in schema["$defs"]
    result = query(MorningAPI(store))
    assert result["list_id"] and result["list_version"] == "1"
