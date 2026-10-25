import json
from pathlib import Path
import sys

import pytest
from aiohttp import web
from jsonschema import Draft202012Validator

from test_menu_n02_context_references import ControlStore, BossCommandAPI

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "validation"))
from boss_business_overview import BusinessOverviewAPI, SCHEMA
from test_boss_command_api import create_input


@pytest.fixture
def store(tmp_path):
    value = ControlStore(tmp_path / "overview.sqlite")
    value.initialize("ui-check")
    return value


def scope(region=None):
    return {"legal_entity_id":"entity-1", "region_id":region, "period_start":"2026-10-01", "period_end":"2026-10-10", "timezone":"Asia/Shanghai", "attention":"ALL"}


def snapshot(store):
    with store.connect() as db:
        return (db.execute("SELECT * FROM objects ORDER BY namespace,kind,id").fetchall(), db.execute("SELECT * FROM audit").fetchall(), db.execute("SELECT * FROM idempotency").fetchall())


def test_real_scope_metrics_topics_and_readonly_restore(store):
    api = BusinessOverviewAPI(store)
    before = snapshot(store)
    result = api.read("BOSS", scope())
    assert [row["page_id"] for row in result["topics"]] == ["F"+str(index) for index in range(14,24)]
    assert next(row for row in result["metrics"] if row["metric_id"] == "gross_margin")["value"] == "8.00"
    assert all(row["availability"] == "SOURCE_NOT_AVAILABLE" for row in result["topics"])
    assert result["topics"][0]["related_sales_source_refs"]
    assert result["topics"][5]["uses"] == ["BROILER","EGG","MILK","BEEF"]
    assert result["query_handoff"]["legal_entity_id"] == scope()["legal_entity_id"]
    assert api.read("BOSS",{**scope(),"period_start":"2026-09-01","period_end":"2026-09-10"})["query_handoff_unavailable_reason"] == "NO_PRIOR_COMPARISON_PERIOD"
    assert api.detail("BOSS", {"scope":scope(),"page_id":"F14","snapshot_sha256":result["snapshot_sha256"]})["topic"] == result["topics"][0]
    restored = BusinessOverviewAPI(ControlStore(store.path)).read("BOSS", scope())
    assert restored["snapshot_sha256"] == result["snapshot_sha256"] and snapshot(store) == before
    Draft202012Validator.check_schema(SCHEMA)


@pytest.mark.parametrize("field,value", [("legal_entity_id","unknown"),("region_id","unknown"),("period_start","2026-10-03"),("timezone","UTC"),("attention","风险较高"),("owner_id","other")])
def test_invalid_or_unsupported_filters_are_rejected(store,field,value):
    with pytest.raises(web.HTTPBadRequest):
        BusinessOverviewAPI(store).read("BOSS", {**scope(),field:value})


def test_roles_and_source_withdrawal_never_report_current_values(store):
    api = BusinessOverviewAPI(store)
    for role,error in ((None,web.HTTPUnauthorized),("MAINTAINER",web.HTTPForbidden)):
        with pytest.raises(error):
            api.read(role,scope())
    previous = api.read("BOSS",scope())
    store.control("ui-check","withdraw",{"source_id":"finance-note","version":"1"})
    current = api.read("BOSS",scope())
    assert all(row["value"] is None for row in current["metrics"]) and current["query_handoff"] is None
    with pytest.raises(web.HTTPConflict):
        api.detail("BOSS",{"scope":scope(),"page_id":"F14","snapshot_sha256":previous["snapshot_sha256"]})


def test_approved_supply_quality_import_is_adopted_with_explicit_scope_limits(store):
    from test_boss_supply_quality import imported
    service, result = imported(store)
    api = BusinessOverviewAPI(store)
    result = api.read("BOSS",scope())
    assert result["topics"][0]["availability"] == "PARTIAL" and result["topics"][7]["availability"] == "PARTIAL"
    assert result["topics"][2]["availability"] == "SOURCE_NOT_AVAILABLE"
    assert result["unclassified_records"]
    dimensions = api.dimensions("BOSS")
    recorded = next(row for row in dimensions["periods"] if row["id"].startswith("recorded-"))
    report_scope = {**scope(),"period_start":recorded["period_start"],"period_end":recorded["period_end"]}
    assert api.read("BOSS",report_scope)["metric_coverage"]["state"] == "UNAVAILABLE"
    regional = api.read("BOSS",scope("region-1"))
    assert regional["excluded_records"] and not regional["topics"][0]["records"]
    source_id = result["topics"][0]["records"][0]["source_refs"][0]["source_id"]
    store.control("ui-check","withdraw",{"source_id":source_id,"version":"1"})
    before = snapshot(store)
    review = api.read("BOSS",{**scope(),"attention":"SOURCE_REVIEW"})
    assert any(row["adoption_state"] == "NEEDS_REVIEW" for topic in review["topics"] for row in topic["records"])
    assert snapshot(store) == before


def test_formal_task_association_has_current_version_without_creation(store):
    code,task = BossCommandAPI(store).execute("BOSS","boss.assignment.create",create_input("n03-associated-task"))
    assert code == 200
    before = snapshot(store)
    result = BusinessOverviewAPI(store).read("BOSS",scope())
    linked = next(row for row in result["associations"] if row["id"] == task["task_id"])
    assert linked["version"] == task["version"] and linked["relation"] == "EXPLICIT_SOURCE_REFERENCE"
    assert snapshot(store) == before


def test_formal_alerts_keep_independent_states_and_scope_without_dispatch(store):
    from test_fc04_domain import configure, load
    assert BossCommandAPI(store).execute("MAINTAINER","boss.simulation.event.seed",{"client_request_id":"n03-alert-seed","event_id":"event-1"})[0] == 200
    configure(store)
    load(store,"RESOURCE_SHORTAGE")
    before = snapshot(store)
    api = BusinessOverviewAPI(store)
    result = api.read("BOSS",scope())
    assert result["alerts"] and result["alerts"][0]["facts"]["participation_reason"]
    assert "notification" in result["alerts"][0] and "business_rule" in result["alerts"][0]
    assert api.read("BOSS",{**scope(),"period_start":"2026-09-01","period_end":"2026-09-10"})["alert_scope_exclusions"]["scope"] == 1
    assert snapshot(store) == before
    store.control("ui-check","withdraw",{"source_id":"finance-note","version":"1"})
    reviewed = api.read("BOSS",{**scope(),"attention":"SOURCE_REVIEW"})
    assert reviewed["alerts"][0]["adoption_state"] == "NEEDS_REVIEW" and reviewed["alerts"][0]["facts"] is None
