import json
import sys
from pathlib import Path
from urllib.parse import urlencode

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "validation"))

from boss_command_api import BossCommandAPI
from boss_sector_api import BossSectorAPI, CATALOGUE, query_id_for
from boss_sector_pack import ensure_sector_pack
from controls import ControlStore


@pytest.fixture
def store(tmp_path):
    result = ControlStore(tmp_path / "sector-scope.sqlite")
    result.initialize("ui-check")
    return result


def seed(store):
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        snapshot = store.get(db, "ui-check", "initial", "snapshot")
        ensure_sector_pack(store, db, snapshot)


def query(**values):
    return urlencode({key: value for key, value in values.items()})


def test_default_projection_matches_frontend_scope_contract(store):
    status, body = BossSectorAPI(store).serve("BOSS", query(page="F15"))
    assert status == 200
    assert body["projection"] == "sector-workspace"
    assert body["page_id"] == "F15" and body["namespace"] == "ui-check"
    assert body["source_type"] == "SIMULATED" and body["dataset_version"] == "1"
    assert body["applied_filters"] == {}
    assert isinstance(body["query_id"], str) and body["query_id"].startswith("F15-")
    assert body["business_clock"] == "2026-10-22T09:00:00+08:00"
    assert len(body["metrics"]) == len(["订单", "渠道库存", "投苗投喂", "回访分子分母"])
    assert body["metrics"][0]["state"] == "SOURCE_NOT_AVAILABLE"
    assert [row["label"] for row in body["coverage"]] == CATALOGUE["F15"]["right"]
    assert body["missing_fields"]
    assert body["sources"] == [] and body["records"] == []
    assert body["availability"] == "SOURCE_NOT_AVAILABLE"


def test_pack_provides_metrics_trend_and_source(store):
    seed(store)
    status, body = BossSectorAPI(store).serve("BOSS", query(page="F15"))
    assert status == 200
    assert body["availability"] == "SIMULATED_METRICS_ONLY"
    assert body["sector_specific_dataset_available"] is True
    first = body["metrics"][0]
    assert first["value"] is not None and first["unit"] == "吨"
    assert first["period"] == "2026-10"
    assert first["source_ids"] == ["sector-f15-a"]
    assert first["state"] == "SIMULATED"
    expected_total = round(sum(float(row["values"]["订单"]) for row in body["records"]), 2)
    assert abs(float(first["value"]) - expected_total) < 0.01
    assert body["trend"]["metric_id"] == first["label"]
    assert [point["period"] for point in body["trend"]["points"]] == ["2026-08", "2026-09", "2026-10"]
    assert body["sources"][0]["source_id"] == "sector-f15-a"
    assert set(body["filter_options"]) == {"区域", "品种", "阶段", "比较周期"}
    assert body["filter_options"]["区域"][0]["id"] == "华东"
    assert all(row["state"] == "SIMULATED" for row in body["coverage"])
    assert any("明细" in field for field in body["missing_fields"])
    assert len(body["records"]) == 6
    assert body["records"][0]["state"] == "SIMULATED"
    assert body["records"][0]["source_ids"] == ["sector-f15-a"]
    assert body["sections"] and all(row["state"] == "SIMULATED" for row in body["sections"])


def test_filters_and_overview_reference_are_echoed_and_change_query_id(store):
    seed(store)
    api = BossSectorAPI(store)
    _, first = api.serve("BOSS", query(page="F15"))
    overview = {"page_id": "N03", "use": "BROILER", "snapshot_sha256": "abc",
                "scope": {"legal_entity_id": "entity-1", "region_id": "region-1",
                          "period_start": "2026-10-01", "period_end": "2026-10-10",
                          "timezone": "Asia/Shanghai", "attention": []}}
    status, second = api.serve("BOSS", urlencode({"page": "F15", "filters": '{"区域":"华东"}',
                                                  "overview_reference": json.dumps(overview)}))
    assert status == 200
    assert second["applied_filters"] == {"区域": "华东"}
    assert second["overview_reference"] == overview
    assert second["query_id"] != first["query_id"]
    assert 0 < len(second["records"]) < len(first["records"])
    assert all(row["values"]["区域"] == "华东" for row in second["records"])
    expected_total = round(sum(float(row["values"]["订单"]) for row in second["records"]), 2)
    metric = next(row for row in second["metrics"] if row["label"] == "订单")
    assert abs(float(metric["value"]) - expected_total) < 0.01
    assert metric["value"] != next(row for row in first["metrics"] if row["label"] == "订单")["value"]


def test_owner_decision_is_saved_and_listed_for_current_query(store):
    seed(store)
    payload = {"client_request_id": str(__import__("uuid").uuid4()), "page_id": "F22",
               "execution_namespace": "ui-check", "dataset_version": "1",
               "query_id": query_id_for("F22", {}, None), "action_code": "记录资源决定",
               "filters": {}, "overview_reference": None,
               "source_refs": [{"source_id": "sector-f22-a", "version": "1"}],
               "purpose": "核查交付缺口", "decision": "按当前范围继续观察"}
    status, receipt = BossCommandAPI(store).execute("BOSS", "boss.sector.decision.save", payload)
    assert status == 200, receipt
    record_id = receipt["record_id"]
    projection = BossSectorAPI(store).serve("BOSS", query(page="F22"))[1]
    assert any(row["record_id"] == record_id and row["kind"] == "DECISION" for row in projection["followups"])
    assert any(action["kind"] == "DECISION" and action["allowed"] for action in projection["followup_actions"])
    assert all(action["allowed"] for action in projection["followup_actions"])


def test_owner_coordination_creates_task_and_followup(store):
    seed(store)
    payload = {"client_request_id": str(__import__("uuid").uuid4()), "page_id": "F15",
               "execution_namespace": "ui-check", "dataset_version": "1",
               "query_id": query_id_for("F15", {}, None), "action_code": "交办", "filters": {},
               "overview_reference": None,
               "source_refs": [{"source_id": "sector-f15-a", "version": "1"}],
               "purpose": "协调季节供货", "timezone": "Asia/Shanghai",
               "coordinator_id": "coordinator-1", "coordinator_version": "1",
               "due_at": "2026-10-25T10:00:00+08:00", "expected_output": "供货计划",
               "evidence_requirements": "批次回访记录\n库存明细"}
    status, receipt = BossCommandAPI(store).execute("BOSS", "boss.sector.coordinate.create", payload)
    assert status == 200, receipt
    with store.connect() as db:
        task = store.get(db, "ui-check", "task", receipt["task_id"])
    assert task["status"] == "OPEN"
    assert task["related_meeting_id"] == "meeting-1"
    assert task["source_refs"] == ["sector-f15-a"]
    projection = BossSectorAPI(store).serve("BOSS", query(page="F15"))[1]
    follow = next(row for row in projection["followups"] if row["record_id"] == receipt["record_id"])
    assert follow["task_id"] == receipt["task_id"]
    assert any(action["kind"] == "COORDINATE" and action["allowed"] for action in projection["followup_actions"])
    bad = {**payload, "client_request_id": str(__import__("uuid").uuid4()),
           "coordinator_id": "finance-1"}
    status, body = BossCommandAPI(store).execute("BOSS", "boss.sector.coordinate.create", bad)
    assert status == 400, body


def test_owner_review_request_is_recorded_without_plan(store):
    seed(store)
    payload = {"client_request_id": str(__import__("uuid").uuid4()), "page_id": "F15",
               "execution_namespace": "ui-check", "dataset_version": "1",
               "query_id": query_id_for("F15", {}, None), "action_code": "安排复查",
               "filters": {}, "overview_reference": None,
               "source_refs": [{"source_id": "sector-f15-a", "version": "1"}],
               "purpose": "复查季节供货", "timezone": "Asia/Shanghai",
               "coordinator_id": "coordinator-1", "coordinator_version": "1",
               "due_at": "2026-10-25T10:00:00+08:00", "expected_output": "复查记录",
               "evidence_requirements": "批次回访记录"}
    status, receipt = BossCommandAPI(store).execute("BOSS", "boss.sector.review.schedule", payload)
    assert status == 200, receipt
    assert receipt["kind"] == "REVIEW" and receipt["state"] == "REVIEW_SCHEDULED"
    assert receipt["plan_id"] and receipt["task_id"] is None
    assert receipt["record_version"] == "1" and receipt["page_id"] == "F15"
    assert receipt["execution_namespace"] == "ui-check" and receipt["action_code"] == "安排复查"
    assert receipt["messages_sent"] == 0 and receipt["external_channel_invoked"] is False
    projection = BossSectorAPI(store).serve("BOSS", query(page="F15"))[1]
    follow = next(row for row in projection["followups"] if row["record_id"] == receipt["record_id"])
    assert follow["kind"] == "REVIEW" and follow["plan_id"] == receipt["plan_id"]
    assert any(action["kind"] == "REVIEW" and action["allowed"] for action in projection["followup_actions"])
    with store.connect() as db:
        plan = store.get(db, "ui-check", "owner_plan", receipt["plan_id"])
        event_id = plan["event_ids"][0]
        store.control_clock(db, "ui-check", {"at": "2026-10-25T10:00:00+08:00"})
        store.dispatch_due_in_transaction(db, "ui-check")
        notification = db.execute("SELECT body FROM objects WHERE namespace=? AND kind='notification' AND id=?",
                                  ("ui-check", event_id + ":1")).fetchone()
    assert notification is not None
    assert json.loads(notification[0])["event_id"] == event_id


def test_owner_meeting_draft_is_saved_without_meeting_or_message(store):
    seed(store)
    payload = {"client_request_id": str(__import__("uuid").uuid4()), "page_id": "F22",
               "execution_namespace": "ui-check", "dataset_version": "1",
               "query_id": query_id_for("F22", {}, None), "action_code": "准备跨时区会议",
               "filters": {}, "overview_reference": None,
               "source_refs": [{"source_id": "sector-f22-a", "version": "1"}],
               "purpose": "讨论交付缺口", "timezone": "Asia/Shanghai",
               "attendee_refs": [{"contact_id": "coordinator-1", "version": "1"}],
               "starts_at": "2026-10-25T10:00:00+08:00", "ends_at": "2026-10-25T11:00:00+08:00",
               "location": "线上会议"}
    status, receipt = BossCommandAPI(store).execute("BOSS", "boss.sector.meeting.prepare", payload)
    assert status == 200, receipt
    assert receipt["kind"] == "MEETING" and receipt["state"] == "DRAFT_SAVED"
    assert receipt["meeting_id"] is None and receipt["message_sent"] is False
    projection = BossSectorAPI(store).serve("BOSS", query(page="F22"))[1]
    follow = next(row for row in projection["followups"] if row["record_id"] == receipt["record_id"])
    assert follow["kind"] == "MEETING"
    assert any(action["kind"] == "MEETING" and action["allowed"] for action in projection["followup_actions"])
    bad = {**payload, "client_request_id": str(__import__("uuid").uuid4()),
           "attendee_refs": [{"contact_id": "missing", "version": "1"}]}
    status, body = BossCommandAPI(store).execute("BOSS", "boss.sector.meeting.prepare", bad)
    assert status == 409, body


def test_stale_query_and_other_roles_are_rejected(store):
    seed(store)
    payload = {"client_request_id": str(__import__("uuid").uuid4()), "page_id": "F22",
               "execution_namespace": "ui-check", "dataset_version": "1",
               "query_id": "F22-stale", "action_code": "记录资源决定", "filters": {},
               "overview_reference": None, "source_refs": [{"source_id": "sector-f22-a", "version": "1"}],
               "purpose": "核查", "decision": "维持"}
    status, body = BossCommandAPI(store).execute("BOSS", "boss.sector.decision.save", payload)
    assert status == 409, body
    status, body = BossCommandAPI(store).execute("MAINTAINER", "boss.sector.decision.save", payload)
    assert status == 403, body


def test_invalid_scope_is_rejected(store):
    api = BossSectorAPI(store)
    assert api.serve("BOSS", query(page="F99"))[0] == 404
    assert api.serve("BOSS", query(page="F15", extra="1"))[0] == 400
    assert api.serve("BOSS", query(page="F15", filters="{bad"))[0] == 400
    assert api.serve("BOSS", query(page="F15", filters='{"未知条件":"值"}'))[0] == 400
    assert api.serve("MAINTAINER", query(page="F15"))[0] == 403
    assert api.serve(None, query(page="F15"))[0] == 401
