from pathlib import Path
import sys

import pytest
from aiohttp import web

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "validation"))

from boss_command_api import BossCommandAPI
from boss_morning import MorningAPI, QUERY_ACTION, ORDER_ACTION
from boss_alert_rules import BusinessAlertRulesAPI
from controls import ControlStore
from test_fc03_morning import DAY, query, order
from test_fc04_domain import ready, load, handle, clock, rules, configure


@pytest.fixture
def store(tmp_path):
    result = ControlStore(tmp_path / "menu-f01.sqlite")
    result.initialize("ui-check")
    assert BossCommandAPI(result).execute("MAINTAINER", "boss.simulation.event.seed", {
        "client_request_id": "menu-f01-current-event", "event_id": "event-1"})[0] == 200
    return result


def test_each_approved_input_reports_its_own_provided_scope_and_unknown_total(store):
    from test_boss_self_commitments import create
    from test_boss_meeting_approval import seed_input
    commands = BossCommandAPI(store)
    assert create(commands)[0] == 200
    assert commands.execute("MAINTAINER", "boss.simulation.application.seed", seed_input())[0] == 200
    view = query(MorningAPI(store))
    coverage = {row["kind"]: row for row in view["input_coverage"]}
    assert set(coverage) == {"owner_goals", "task", "self_commitment", "application", "meeting", "event", "private_calendar", "travel_plan"}
    assert coverage["owner_goals"]["state"] == "NOT_SET"
    assert coverage["application"]["provided_count"] == 1
    assert coverage["application"]["included_count"] == 1
    assert coverage["travel_plan"]["state"] == "NO_RECORDS_IN_PROVIDED_SCOPE"
    assert coverage["travel_plan"]["provided_count"] == 0
    assert all(row["reported_total"] is None for row in coverage.values())
    assert sum(view["category_counts"].values()) == len(view["items"])
    assert view["category_counts"]["DECIDE"] == 1
    assert view["coverage_state"] == "PARTIAL"


def test_business_alert_priority_uses_current_domain_rule_and_handler(store):
    rules(store, important=True)
    active = configure(store)
    load(store, "RESOURCE_SHORTAGE")
    morning = MorningAPI(store)
    current = query(morning)
    event = next(item for item in current["items"] if item["object_id"] == "business-alert-1")
    assert event["important"] is True and event["category"] == "COORDINATE"
    assert event["coordinator_id"] == "coordinator-1"
    assert event["risk_evaluations"][0]["phase"] == "IMMEDIATE"
    assert event["risk_evaluations"][0]["rule_version"] == active["version"]
    assert "跨职责资源不足" in event["reason"]
    BusinessAlertRulesAPI(store).execute("MAINTAINER", "disable", {
        "client_request_id": "menu-f01-disable-business-rule", "expected_version": active["version"]})
    after = morning.read("BOSS", DAY)
    same = next(item for item in after["items"] if item["object_id"] == "business-alert-1")
    assert same["important"] is False
    assert same["risk_evaluations"][0]["reason"] == "RULE_NOT_ENABLED"
    with pytest.raises(web.HTTPConflict):
        morning.detail("BOSS", current["list_id"], event["item_id"])


def test_linked_alert_and_assignment_have_one_item_with_same_version_sources_and_meeting(store):
    ready(store)
    linked, _ = handle(store, "meeting.link", meeting_id="meeting-1", meeting_version="1")
    assignment, _ = handle(store, "assignment.create", purpose="核查当前经营依据", coordinator_id="coordinator-1",
        due_at="2026-10-24T17:00:00+08:00", timezone="Asia/Shanghai", evidence_requirements=["当前原始资料与处理情况"])
    morning = MorningAPI(store)
    current = query(morning)
    assert not any(item["item_id"] == "event:business-alert-1" for item in current["items"])
    target = next(item for item in current["items"] if item["object_id"] == assignment["task_id"])
    assert target["related_meetings"] == [{"kind": "meeting", "id": linked["meeting_id"], "version": linked["meeting_version"]}]
    assert {("event", "business-alert-1"), ("document", "fc04-observation:business-alert-1")} <= {(ref["kind"], ref["id"]) for ref in target["source_refs"]}
    assert len({(ref["kind"], ref["id"]) for ref in target["source_refs"]}) == len(target["source_refs"])
    assert any(measure["kind"] == "task" and measure["id"] == assignment["task_id"] and measure["state"] == "OPEN" for measure in target["existing_measures"])
    detail = morning.detail("BOSS", current["list_id"], target["item_id"])
    assert {doc["source_id"] for doc in detail["documents"]} == {"finance-note", "fc04-observation:business-alert-1", "meeting-minutes"}
    assert any(row["reference"]["kind"] == "meeting" and row["data"]["version"] == "1" for row in detail["objects"])
    with store.connect() as db:
        assert store.get(db, "ui-check", "task", assignment["task_id"])["status"] == "OPEN"
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind='outbox'").fetchone()[0] == 0
    store.control("ui-check", "withdraw", {"source_id": "finance-note", "version": "1"})
    with pytest.raises(web.HTTPConflict):
        morning.detail("BOSS", current["list_id"], target["item_id"])
    assert not any(ref["id"] == "fc04-observation:business-alert-1" for item in morning.read("BOSS", DAY)["items"] for ref in item["source_refs"])


def test_business_risk_loses_priority_when_continuous_observation_is_not_current(store):
    rules(store, important=True)
    configure(store)
    load(store, "RESOURCE_SHORTAGE")
    clock(store, "2026-10-22T09:06:00+08:00")
    view = query(MorningAPI(store))
    event = next(item for item in view["items"] if item["object_id"] == "business-alert-1")
    assert event["important"] is False
    assert event["risk_evaluations"][0]["reason"] == "OBSERVATION_NOT_UPDATED"
    assert "RISK_REQUIRES_REVIEW:business-alert-1" in view["missing_sources"]


def test_source_data_cutoff_is_separate_from_new_observation_and_query_time(store):
    ready(store)
    current = query(MorningAPI(store))
    sources = {row["source_id"]: row for row in current["source_statuses"]}
    generated = sources["fc04-observation:business-alert-1"]
    assert generated["observed_at"] == "2026-10-22T09:00:00+08:00"
    assert generated["data_as_of"] == "2026-10-10T23:59:59+08:00"
    assert sources["finance-note"]["data_as_of"] == generated["data_as_of"]
    assert sources["meeting-minutes"]["data_as_of"] is None
    assert current["data_as_of"] is None
    assert generated["data_as_of"] != current["read_at"]
    from boss_meetings import MeetingAPI
    from test_boss_meeting_changes import draft_input, confirmation
    meetings = MeetingAPI(store)
    draft = meetings.execute("BOSS", "draft.save", draft_input())
    meetings.execute("BOSS", "confirm", confirmation(draft))
    with_meeting = query(MorningAPI(store), key="menu-f01-unknown-meeting-cutoff")
    assert any(row["source_id"] == "meeting-minutes" and row["data_as_of"] is None for row in with_meeting["source_statuses"])
    assert with_meeting["data_as_of"] is None


def test_revoked_saved_order_stops_current_adoption_and_keeps_original_receipt(store):
    morning = MorningAPI(store)
    current = query(morning)
    saved = morning.reorder("BOSS", order(current))
    assert [item["item_id"] for item in morning.read("BOSS", DAY)["items"]] == saved["item_ids"]
    code, result = BossCommandAPI(store).execute("BOSS", "boss.authorization.revoke", {
        "client_request_id": "menu-f01-revoke-order", "authorization_id": saved["authorization_id"], "expected_version": "1", "reason": "停止继续采用此次序"})
    assert code == 200, result
    restored = MorningAPI(ControlStore(store.path))
    after = restored.read("BOSS", DAY)
    assert [item["item_id"] for item in after["items"]] == [item["item_id"] for item in current["items"]]
    assert after["order_version"] == saved["version"] and after["order_state"] == "REVOKED"
    assert restored.receipt("BOSS", ORDER_ACTION, "morning-owner-order")["result"] == saved
    assert restored.receipt("BOSS", QUERY_ACTION, "menu-f01-not-recorded")["outcome"] == "NOT_FOUND_IN_CURRENT_STORE"
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM idempotency WHERE key='menu-f01-not-recorded'").fetchone()[0] == 0


def test_complete_scope_keeps_actual_confirmed_travel_and_private_location(store):
    from test_boss_travel import action, review_input, confirm_input
    from test_boss_message_calendar import calendar_input
    commands = BossCommandAPI(store)
    assert commands.execute("BOSS", "boss.calendar.save", {"client_request_id": "menu-f01-private-location", **calendar_input()})[0] == 200
    code, draft = action(commands, "boss.travel.review", "menu-f01-travel-review", **review_input(
        starts_at="2026-10-24T16:45:00+08:00", ends_at="2026-10-24T19:15:00+08:00"))
    assert code == 200, draft
    code, confirmed = action(commands, "boss.travel.confirm", "menu-f01-travel-confirm", **confirm_input(draft))
    assert code == 200, confirmed
    morning = MorningAPI(store)
    current = query(morning)
    trip = next(item for item in current["items"] if item["object_id"] == confirmed["travel_id"])
    private = next(item for item in current["items"] if item["kind"] == "private_calendar")
    assert private["location"] == calendar_input()["location"]
    assert private["timezone"] == trip["timezone"] == "Asia/Shanghai"
    assert trip["starts_at"] == "2026-10-24T16:15:00+08:00"
    assert trip["ends_at"] == "2026-10-24T19:45:00+08:00"
    assert any(set(conflict["item_ids"]) == {trip["item_id"], private["item_id"]} for conflict in current["conflicts"])
    assert "TRANSPORT_SOURCE_NOT_PROVIDED:" + trip["object_id"] in current["missing_sources"]
    detail = morning.detail("BOSS", current["list_id"], trip["item_id"])
    assert detail["objects"][0]["data"]["current"]["destination"] == review_input()["destination"]
    assert any(row["kind"] == "travel_plan" and row["included_count"] == 1 for row in current["input_coverage"])


def test_actual_sqlite_save_failure_preserves_list_and_commits_no_order_or_authority(store):
    import sqlite3
    morning = MorningAPI(store)
    current = query(morning)
    with store.connect() as db:
        before = db.execute("SELECT COUNT(*) FROM objects WHERE kind='authorization'").fetchone()[0]
        db.execute("CREATE TRIGGER menu_f01_reject_order_receipt BEFORE INSERT ON idempotency WHEN NEW.operation='boss.today.reorder' BEGIN SELECT RAISE(ABORT,'MENU_F01_SAVE_FAILURE'); END")
    with pytest.raises(sqlite3.IntegrityError, match="MENU_F01_SAVE_FAILURE"):
        morning.reorder("BOSS", order(current))
    restored = MorningAPI(ControlStore(store.path))
    assert restored.read_list("BOSS", current["list_id"])["result"] == current
    assert restored.receipt("BOSS", ORDER_ACTION, "morning-owner-order")["outcome"] == "NOT_FOUND_IN_CURRENT_STORE"
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind='authorization'").fetchone()[0] == before
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind='today_order'").fetchone()[0] == 0
        db.execute("DROP TRIGGER menu_f01_reject_order_receipt")


def test_saved_current_list_and_order_survive_an_independent_read_only_process(store):
    import json
    import os
    import subprocess
    morning = MorningAPI(store)
    current = query(morning)
    saved = morning.reorder("BOSS", order(current))
    root = Path(__file__).resolve().parents[2]
    process = subprocess.run([sys.executable, str(root / "validation/check_menu_f01_restart.py"), "--database", str(store.path),
        "--list-id", current["list_id"], "--query-id", "morning-query", "--order-id", "morning-owner-order"], cwd=root, check=True, capture_output=True, text=True)
    result = json.loads(process.stdout)
    assert result["status"] == "PASS" and result["pid"] != os.getpid()
    assert result["list_id"] == current["list_id"] and result["snapshot_sha256"] == current["snapshot_sha256"]
    assert result["item_ids"] == saved["item_ids"] and result["order_version"] == saved["version"]
    assert result["business_changes"] == 0


def test_new_event_version_requires_review_of_earlier_meeting_link(store):
    ready(store)
    handle(store, "meeting.link", meeting_id="meeting-1", meeting_version="1")
    morning = MorningAPI(store)
    previous = query(morning)
    clock(store, "2026-10-22T09:05:00+08:00")
    load(store, "RESOURCE_SHORTAGE")
    current = morning.read("BOSS", DAY)
    event = next(item for item in current["items"] if item["object_id"] == "business-alert-1")
    assert event["related_meetings"] == []
    assert "MEETING_LINK_REQUIRES_REVIEW:business-alert-1" in current["missing_sources"]
    with pytest.raises(web.HTTPConflict):
        morning.read_list("BOSS", previous["list_id"])
    history = morning.read_list("BOSS", previous["list_id"], historical=True)
    assert history["result"]["input_coverage"] == [] and history["result"]["category_counts"] is None


def test_legacy_saved_order_uses_the_same_current_owner_revocation(store):
    from boss_today import TodayAPI
    today = TodayAPI(store)
    current = today.read("BOSS")
    payload = {"client_request_id": "menu-f01-legacy-order", "expected_version": current["order_version"],
        "snapshot_sha256": current["snapshot_sha256"], "item_ids": [item["item_id"] for item in reversed(current["items"])]}
    saved = today.reorder("BOSS", payload)
    code, result = BossCommandAPI(store).execute("BOSS", "boss.authorization.revoke", {
        "client_request_id": "menu-f01-revoke-legacy-order", "authorization_id": saved["authorization_id"], "expected_version": "1", "reason": "停止继续采用原次序"})
    assert code == 200, result
    assert today.read("BOSS")["order_state"] == "REVOKED"
    morning = MorningAPI(store).read("BOSS", {"date": current["date"], "timezone": current["timezone"]})
    assert morning["order_state"] == "REVOKED" and morning["order_version"] == saved["version"]
    assert [item["item_id"] for item in today.read("BOSS")["items"]] == [item["item_id"] for item in current["items"]]
