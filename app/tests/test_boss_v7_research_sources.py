import sys
from pathlib import Path
from uuid import uuid4

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "validation"))

from boss_command_api import BossCommandAPI
from boss_research import project
from controls import ControlStore


@pytest.fixture
def store(tmp_path):
    result = ControlStore(tmp_path / "research-sources.sqlite")
    result.initialize("ui-check")
    return result


def read(store):
    with store.connect() as db:
        snapshot = store.get(db, "ui-check", "initial", "snapshot")
        return project(db, snapshot)


def prepare(store, expected="0", **extra):
    payload = {"client_request_id": str(uuid4()), "expected_version": expected,
               "question": "毛利率", "period": "", "country": "", "business_relation": "",
               "cutoff_date": "2026-12-31", **extra}
    return BossCommandAPI(store).execute("BOSS", "boss.research.prepare", payload)


def test_projection_offers_current_sources_for_selection(store):
    projection = read(store)
    assert projection["source_selection_available"] is True
    assert projection["execution_namespace"] == "ui-check"
    assert projection["data_version"] == "1"
    sources = {row["source_id"]: row for row in projection["available_sources"]}
    assert sources["finance-note"]["reference_state"] == "CURRENT"
    assert sources["meeting-minutes"]["reference_state"] == "CURRENT"


def test_selected_sources_are_persisted_and_restrict_matching(store):
    status, result = prepare(store, source_refs=[{"source_id": "finance-note", "version": "1"}],
                             execution_namespace="ui-check")
    assert status == 200, result
    projection = read(store)
    report = projection["report"]
    assert report["scope"]["source_refs"] == [{"source_id": "finance-note", "version": "1"}]
    assert report["matched_sources"]
    assert {row["source_id"] for row in report["matched_sources"]} == {"finance-note"}
    assert report["coverage"]["rejected"]["not_selected"] >= 1


def test_unavailable_selection_and_plain_prepare_are_handled(store):
    status, body = prepare(store, source_refs=[{"source_id": "missing", "version": "1"}])
    assert status in (400, 409), body
    status, result = prepare(store)
    assert status == 200, result
    status, result = prepare(store, expected="1")
    assert status == 200, result
