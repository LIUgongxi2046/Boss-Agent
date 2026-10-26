import sys
from pathlib import Path
from uuid import uuid4

import pytest
from aiohttp import web

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "validation"))

from boss_command_api import BossCommandAPI
from boss_v7_technical import TechnicalWorkspaceAPI
from controls import ControlStore


@pytest.fixture
def store(tmp_path):
    result = ControlStore(tmp_path / "simulation-events.sqlite")
    result.initialize("ui-check")
    return result


def read(store, role="MAINTAINER"):
    return TechnicalWorkspaceAPI(store).read(role, "/api/boss/ui/admin/technical/simulation-events", "")


def payload(store, action="inject", **changes):
    projection = read(store)
    target = projection["targets"][0]
    source = next(row for row in projection["sources"] if row["id"] == "finance-note")
    values = {
        "client_request_id": str(uuid4()), "namespace": projection["namespace"],
        "dataset_id": projection["dataset_id"], "dataset_version": projection["dataset_version"],
        "event_type": "business-event", "target_id": target["id"], "target_version": target["version"],
        "author_id": "coordinator-1", "author_version": "1",
        "source_id": source["id"], "source_version": source["version"], "source_at": source["as_of"],
        "event_at": "2026-10-22T10:00:00+08:00", "content": "模拟事件内容",
        "expected_clock_version": projection["business_clock"]["version"],
    }
    if action == "advance-clock":
        return {"client_request_id": values["client_request_id"], "namespace": values["namespace"],
                "dataset_id": values["dataset_id"], "dataset_version": values["dataset_version"],
                "expected_clock_version": values["expected_clock_version"],
                "at": "2026-10-22T10:00:00+08:00"}
    values.update(changes)
    return values


def test_projection_exposes_versions_authors_sources_and_clock(store):
    projection = read(store)
    assert projection["projection"] == "simulation-events"
    assert projection["dataset_id"] == "selection"
    assert projection["business_clock"]["version"] == "1"
    assert projection["targets"][0]["id"] == "event-1"
    assert any(row["id"] == "coordinator-1" for row in projection["authors"])
    source = next(row for row in projection["sources"] if row["id"] == "finance-note")
    assert source["state"] == "CURRENT" and source["version"] == "1"
    assert projection["allowed_actions"] == ["inject", "reply", "advance-clock"]
    assert projection["records"] == []


def test_inject_and_reply_record_outcomes_without_claiming_effects(store):
    status, receipt = BossCommandAPI(store).execute("MAINTAINER", "boss.technical.simulation-events.inject",
                                                    payload(store))
    assert status == 200, receipt
    result = receipt["result"]
    assert result["saved"]["state"] == "RECORDED"
    assert result["tasks"]["state"] == "NOT_TRIGGERED"
    assert result["notifications"]["state"] == "NOT_TRIGGERED"
    assert result["agent"]["state"] == "NOT_REQUESTED"
    status, receipt = BossCommandAPI(store).execute("MAINTAINER", "boss.technical.simulation-events.reply",
                                                    payload(store))
    assert status == 200, receipt
    projection = read(store)
    assert len(projection["records"]) == 2
    assert {row["action"] for row in projection["records"]} == {"inject", "reply"}


def test_stale_source_version_is_rejected(store):
    values = payload(store, source_version="stale")
    status, body = BossCommandAPI(store).execute("MAINTAINER", "boss.technical.simulation-events.inject", values)
    assert status == 409, body
    assert read(store)["records"] == []


def test_clock_advance_uses_current_version_and_moves_forward(store):
    values = payload(store, action="advance-clock")
    status, receipt = BossCommandAPI(store).execute("MAINTAINER", "boss.technical.simulation-events.advance-clock", values)
    assert status == 200, receipt
    assert receipt["result"]["version"] == "2"
    projection = read(store)
    assert projection["business_clock"]["at"] == "2026-10-22T10:00:00+08:00"
    assert projection["business_clock"]["version"] == "2"
    stale = payload(store, action="advance-clock")
    stale["expected_clock_version"] = "1"
    status, body = BossCommandAPI(store).execute("MAINTAINER", "boss.technical.simulation-events.advance-clock", stale)
    assert status == 409, body


def test_owner_role_is_rejected(store):
    with pytest.raises(web.HTTPForbidden):
        read(store, "BOSS")
