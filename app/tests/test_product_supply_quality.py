import sys
from pathlib import Path
from urllib.parse import urlencode

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "validation"))

from boss_command_api import BossCommandAPI
from boss_page_api import BossPageAPI
from boss_supply_quality import IMPORT_ACTION
from test_boss_supply_quality import definition, store
from test_boss_external_adoption import SOURCE, REFERENCES, change_dependencies
from test_boss_meeting_changes import draft_input, confirmation
from boss_meetings import MeetingAPI


def receipt(pages, role, action, key):
    return pages.serve(role, "/api/boss/ui/supply-quality-receipt", urlencode({"action": action, "client_request_id": key}))


@pytest.mark.parametrize("interface", ["SI09", "SI10"])
def test_public_supply_quality_explicit_import_and_role_scoped_receipt(store, interface):
    pages, commands = BossPageAPI(store), BossCommandAPI(store)
    code, view = pages.serve("BOSS", "/api/boss/ui/supply-quality", "interface_id=" + interface)
    assert code == 200, view
    assert view["records"] == [] and view["availability"] == "UNAVAILABLE"
    request = definition()["initial_request"]
    code, result = commands.execute("MAINTAINER", IMPORT_ACTION, request)
    assert code == 200 and result["state"] == "SUCCESS", result
    assert commands.execute("MAINTAINER", IMPORT_ACTION, request) == (code, result)
    code, view = pages.serve("BOSS", "/api/boss/ui/supply-quality", "interface_id=" + interface)
    assert code == 200 and view["records"] and view["external_service_invoked"] is False
    assert receipt(pages, "MAINTAINER", IMPORT_ACTION, request["client_request_id"])[1]["result"] == result
    assert receipt(pages, "BOSS", IMPORT_ACTION, request["client_request_id"])[0] == 403
    assert commands.execute("BOSS", IMPORT_ACTION, request)[0] == 403
    assert pages.serve("MAINTAINER", "/api/boss/ui/supply-quality", "interface_id=" + interface)[0] == 403
    assert pages.serve(None, "/api/boss/ui/supply-quality", "interface_id=" + interface)[0] == 401


@pytest.mark.parametrize("section,status,state", [("empty_request", 200, "EMPTY"), ("failed_request", 502, "FAILED"), ("timeout_request", 504, "TIMED_OUT")])
def test_public_supply_quality_import_preserves_actual_outcome_and_receipt(store, section, status, state):
    pages, commands = BossPageAPI(store), BossCommandAPI(store)
    request = definition()[section]
    response = commands.execute("MAINTAINER", IMPORT_ACTION, request)
    assert response[0] == status, response
    assert commands.execute("MAINTAINER", IMPORT_ACTION, request) == response
    code, saved = receipt(pages, "MAINTAINER", IMPORT_ACTION, request["client_request_id"])
    assert code == 200 and saved["outcome"] == "RECORDED" and saved["result"]["state"] == state
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind IN ('inventory_lot','task','authorization','outbox')").fetchone()[0] == 0


@pytest.mark.parametrize("query", ["", "interface_id=", "interface_id=SI09&interface_id=SI10", "interface_id=SI09&namespace=ui-check", "interface_id=SI13"])
def test_public_supply_quality_rejects_invalid_scope(store, query):
    assert BossPageAPI(store).serve("BOSS", "/api/boss/ui/supply-quality", query)[0] == 400


def test_public_source_consumers_require_current_external_dependencies(store):
    from boss_supply_quality import SupplyQualityAPI

    external = SupplyQualityAPI(store)
    assert BossCommandAPI(store).execute("MAINTAINER", IMPORT_ACTION, definition()["initial_request"])[0] == 200
    pages = BossPageAPI(store)
    assert pages.serve("BOSS", "/api/boss/ui/evidence", urlencode({"source": SOURCE}))[0] == 200
    assert MeetingAPI(store).execute("BOSS", "draft.save", draft_input(source_refs=REFERENCES))["state"]
    change_dependencies(external)
    code, result = pages.serve("BOSS", "/api/boss/ui/evidence", urlencode({"source": SOURCE}))
    assert code == 409 and "content" not in result, result
    code, result = pages.serve("BOSS", "/api/boss/ui/workspace/knowledge", "q=SIMULATED")
    assert code == 200, result
    assert all(row["source_id"] != SOURCE for row in result["results"])


def test_public_saved_minutes_and_research_hide_noncurrent_external_body(store):
    from boss_supply_quality import SupplyQualityAPI

    commands, pages, meetings = BossCommandAPI(store), BossPageAPI(store), MeetingAPI(store)
    assert commands.execute("MAINTAINER", IMPORT_ACTION, definition()["initial_request"])[0] == 200
    saved = meetings.execute("BOSS", "draft.save", draft_input(source_refs=REFERENCES))
    scheduled = meetings.execute("BOSS", "confirm", confirmation(saved))
    code, minute = commands.execute("BOSS", "boss.minutes.save", {"client_request_id": "public-external-minute-save",
        "meeting_id": "meeting-1", "meeting_version": scheduled["version"], "source_id": SOURCE, "source_version": "1", "expected_version": "0",
        "entries": [{"kind": "OPINION", "text": "当前模拟品质资料需要专业核查", "source_anchor": "SIMULATED"}]})
    assert code == 200, minute
    code, research = commands.execute("BOSS", "boss.research.prepare", {"client_request_id": "public-external-research-prepare",
        "expected_version": "0", "question": "SIMULATED", "period": "", "country": "", "business_relation": "", "cutoff_date": "2026-10-23"})
    assert code == 200, research
    before = pages.serve("BOSS", "/api/boss/ui/workspace/research")[1]
    assert any(row["source_id"] == SOURCE for row in before["report"]["matched_sources"])
    change_dependencies(SupplyQualityAPI(store))
    code, minutes = pages.serve("BOSS", "/api/boss/ui/workspace/minutes")
    assert code == 200 and minutes["minute"]["source_reference_state"] == "NEEDS_REVIEW"
    assert all(row["text"] == row["source_anchor"] == "" for row in minutes["minute"]["entries"])
    code, current = pages.serve("BOSS", "/api/boss/ui/workspace/research")
    assert code == 200 and current["current_reference_state"] == "NEEDS_REVIEW"
    assert all(row["source_id"] != SOURCE for row in current["report"]["matched_sources"])
    issue = next(row for row in current["report"]["source_issues"] if row["source_id"] == SOURCE)
    assert issue["adoption_state"] == "NEEDS_REIMPORT" and issue["validity_state"] == "VALID"
    with store.connect() as db:
        assert store.get(db, "ui-check", "minutes", "meeting-1")["entries"][0]["text"] == "当前模拟品质资料需要专业核查"


def test_unrelated_external_dependency_does_not_invalidate_current_research_quotes(store):
    from boss_supply_quality import SupplyQualityAPI

    commands, pages = BossCommandAPI(store), BossPageAPI(store)
    assert commands.execute("MAINTAINER", IMPORT_ACTION, definition()["initial_request"])[0] == 200
    code, result = commands.execute("BOSS", "boss.research.prepare", {"client_request_id": "public-finance-research-prepare",
        "expected_version": "0", "question": "合成水产饲料外销明细", "period": "", "country": "", "business_relation": "", "cutoff_date": "2026-10-23"})
    assert code == 200, result
    before = pages.serve("BOSS", "/api/boss/ui/workspace/research")[1]
    assert before["current_reference_state"] == "CURRENT_SOURCE_EXCERPTS"
    assert {row["source_id"] for row in before["report"]["matched_sources"]} == {"finance-note"}
    change_dependencies(SupplyQualityAPI(store))
    code, current = pages.serve("BOSS", "/api/boss/ui/workspace/research")
    assert code == 200 and current["current_reference_state"] == "CURRENT_SOURCE_EXCERPTS"
    assert current["report"]["matched_sources"] == before["report"]["matched_sources"]
    assert current["report"]["source_issues"] == []
