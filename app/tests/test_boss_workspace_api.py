"""Role boundaries and provenance checks for the next real v6 read pages."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from aiohttp import web

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "validation"))
from boss_page_api import BossPageAPI  # noqa: E402
from controls import ControlStore  # noqa: E402


@pytest.fixture
def api(tmp_path):
    store = ControlStore(tmp_path / "workspace.sqlite")
    store.initialize("ui-check")
    return BossPageAPI(store)


def request(api, role, page, query=""):
    return api.serve(role, "/api/boss/ui/workspace/" + page, query)


@pytest.mark.parametrize("page", [
    "memory", "calendar", "notifications", "authorizations", "decisions",
    "outbox", "sources", "knowledge", "organization", "plans",
])
def test_boss_read_projections_are_role_scoped(api, page):
    status, body = request(api, "BOSS", page)
    assert status == 200
    assert body["source_type"] == "SIMULATED"
    assert body["projection"] == page
    assert body["namespace"] == "ui-check"
    assert request(api, "MAINTAINER", page)[0] == 403
    assert request(api, None, page)[0] == 401


@pytest.mark.parametrize("page", [
    "dataset", "source-index", "tool-catalog", "metric-definitions",
    "relationships", "scheduler", "audit", "system",
])
def test_technical_projections_reject_business_owner(api, page):
    status, body = request(api, "MAINTAINER", page)
    assert status == 200
    assert body["source_type"] == "SIMULATED"
    assert body["projection"] == page
    assert request(api, "BOSS", page)[0] == 403
    assert request(api, None, page)[0] == 401


def test_private_calendar_body_only_visible_to_boss(api):
    status, body = request(api, "BOSS", "calendar")
    assert status == 200
    assert body["calendar"]["visibility"] == "PRIVATE"
    assert body["calendar"]["private_body"] == "获准模拟私人安排"
    for page in ("dataset", "audit", "system", "relationships", "source-index"):
        status, value = request(api, "MAINTAINER", page)
        assert status == 200
        assert "private_body" not in json.dumps(value)
        assert "获准模拟私人安排" not in json.dumps(value)


def test_confirmed_memory_is_owner_only_and_not_a_maintainer_configuration(api):
    status, body = request(api, "BOSS", "memory")
    assert status == 200 and body["effective"]
    assert body["memory"]["confirmation_state"] == "CONFIRMED"
    assert "简报优先展示现金" in body["memory"]["text"]
    assert request(api, "MAINTAINER", "memory")[0] == 403
    assert "memory" not in json.dumps(request(api, "MAINTAINER", "system")[1])


def test_knowledge_search_filters_withdrawn_and_reads_actual_document_versions(api):
    code, data = request(api, "BOSS", "knowledge", "q=%E6%AF%9B%E5%88%A9")
    assert code == 200
    assert any(row["source_id"] == "finance-note" for row in data["results"])
    assert all(row["source_type"] == "SIMULATED" for row in data["results"])
    api.store.control("ui-check", "withdraw", {"source_id": "finance-note", "version": "1"})
    _, after = request(api, "BOSS", "knowledge", "q=%E6%AF%9B%E5%88%A9")
    assert all(item["source_id"] != "finance-note" for item in after["results"])
    _, sources = request(api, "BOSS", "sources")
    source = next(x for x in sources["sources"] if x["source_id"] == "finance-note")
    assert source["withdrawn"] is True
    assert source["content_visible"] is False


def test_authorization_history_does_not_disclose_instruction_or_payload(api):
    api.store.authorize("ui-check", "create_assignment", {"purpose": "SENSITIVE_TEST_PAYLOAD"})
    code, body = request(api, "BOSS", "authorizations")
    assert code == 200
    assert len(body["authorizations"]) == 1
    assert body["secrets_or_payloads_returned"] is False
    assert "SENSITIVE_TEST_PAYLOAD" not in json.dumps(body)
    assert "source_instruction" not in json.dumps(body)
    assert request(api, "MAINTAINER", "authorizations")[0] == 403


def test_technical_catalog_links_actual_domain_schema(api):
    status, catalog = request(api, "MAINTAINER", "tool-catalog")
    assert status == 200
    ops = {x["operation_id"] for x in catalog["operations"]}
    assert {"query_metrics", "read_evidence", "create_assignment", "send_assignment", "read_assignment"} <= ops
    assert all(x["input_schema"].startswith("#/$defs/") for x in catalog["operations"])


def test_notification_page_distinguishes_absent_events_from_real_deliveries(api):
    status, body = request(api, "BOSS", "notifications")
    assert status == 200
    assert body["notifications"] == []
    assert body["events"] == []
    assert body["notification_draft_only"] is True
    assert request(api, "MAINTAINER", "notifications")[0] == 403


def test_action_history_returns_only_persisted_operation_metadata(api):
    code, body = request(api, "BOSS", "decisions")
    assert code == 200
    assert body["history"] == []
    assert not body["raw_action_payload_returned"]
    _, audit = request(api, "MAINTAINER", "audit")
    assert audit["private_values_included"] is False


def test_unknown_and_trailing_paths_fail_closed(api):
    assert api.serve("BOSS", "/api/boss/ui/workspace/calendar/children")[0] == 404
    assert request(api, "BOSS", "does-not-exist")[0] == 403
    assert api.serve("MAINTAINER", "/api/boss/ui/workspace/calendar")[0] == 403
