from copy import deepcopy

import pytest
from aiohttp import web

from test_boss_supply_quality import definition, imported, update_record
from controls import ControlStore
from boss_supply_quality import IMPORT_ACTION
from boss_supply_quality import SupplyQualityAPI
from boss_simulation_api import SimulationAPI


@pytest.fixture
def services(tmp_path):
    store = ControlStore(tmp_path / "material-costs.sqlite")
    store.initialize("ui-check")
    api, _ = imported(store)
    return store, api


def reports_input():
    request = definition()["initial_request"]
    source = request["records"][1]["source"]
    records = []
    for kind, amounts in (("INBOUND_RECEIPT", ("20000", "21000")), ("ACTUAL_CONSUMPTION", ("4000", "4300"))):
        for index, total in enumerate(amounts):
            data = {"report_id": "sim-cost-" + kind.lower() + "-" + str(index), "material_id": "sim-material-1", "legal_entity_id": "entity-1", "asset_owner_id": "entity-1", "cost_owner_id": "entity-1", "ownership_type": "COMPANY", "customer_id": None,
                "cost_type": kind, "report_scope_id": "sim-material-cost-scope-1", "cost_basis_id": "sim-reported-direct-material", "scope_description": "SIMULATED：仅当前明确库存的报告成本，用于程序计算验证。未报告成本和企业完整成本尚未提供。",
                "period_start": "2026-10-" + str(19 + index) + "T18:00:00+08:00", "period_end": "2026-10-" + str(20 + index) + "T18:00:00+08:00", "inventory_ids": ["sim-stock-available-1"],
                "quantity": "10" if kind == "INBOUND_RECEIPT" else "2", "total_cost": total, "quantity_unit": "tonne", "currency": "CNY", "state": "REPORTED"}
            records.append({"entity_type": "material_cost_report", "expected_version": "0", "source": deepcopy(source), "data": data})
    return {**request, "client_request_id": "sim-material-cost-reports-v1", "records": records}


def cost_row(api, kind):
    return next(row for row in api.read("BOSS", "SI09")["supply"][0]["cost_reports"] if row["cost_type"] == kind)


def test_reported_inbound_and_actual_consumption_costs_have_independent_basis_and_changes(services):
    _, api = services
    result = api.execute("MAINTAINER", IMPORT_ACTION, reports_input())
    assert result["record_count"] == 4 and result["external_service_invoked"] is False
    inbound, consumption = cost_row(api, "INBOUND_RECEIPT"), cost_row(api, "ACTUAL_CONSUMPTION")
    assert inbound["current"]["unit_cost"] == "2100" and inbound["unit_cost_change"] == "100"
    assert consumption["current"]["unit_cost"] == "2150" and consumption["unit_cost_change"] == "150"
    assert inbound["total_cost_change"] == "1000" and consumption["total_cost_change"] == "300"
    assert inbound["currency"] == "CNY" and inbound["quantity_unit"] == "tonne"
    assert inbound["baseline"]["report_id"] != consumption["baseline"]["report_id"]
    stock = api.read("BOSS", "SI09")["supply"][0]
    assert stock["quote_price_difference"] == "200" and stock["contract_unit_prices"] == ["2050"]
    assert stock["actual_cost_change"] is None
    assert "FULL_ACTUAL_COST_NOT_PROVIDED" in api.read("BOSS", "SI09")["missing_fields"]


@pytest.mark.parametrize("field,value", [("quantity", None), ("quantity", "0"), ("total_cost", None)])
def test_unknown_cost_and_zero_denominator_never_produce_a_reported_unit_cost(services, field, value):
    _, api = services
    payload = reports_input()
    payload["records"][1]["data"][field] = value
    api.execute("MAINTAINER", IMPORT_ACTION, payload)
    row = cost_row(api, "INBOUND_RECEIPT")
    assert row["current"]["unit_cost"] is None and row["unit_cost_change"] is None
    if field == "total_cost":
        assert row["total_cost_change"] is None


@pytest.mark.parametrize("field,value", [("quantity_unit", "kg"), ("currency", "USD"), ("asset_owner_id", "customer-1"), ("cost_owner_id", "customer-1")])
def test_cost_reports_cannot_mix_inventory_units_currency_or_ownership(services, field, value):
    store, api = services
    payload = reports_input()
    payload["records"][0]["data"][field] = value
    with pytest.raises(web.HTTPBadRequest):
        api.execute("MAINTAINER", IMPORT_ACTION, payload)
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind='material_cost_report'").fetchone()[0] == 0


def test_overlapping_cost_report_periods_are_rejected_atomically(services):
    store, api = services
    payload = reports_input()
    payload["records"][1]["data"]["period_start"] = "2026-10-20T17:00:00+08:00"
    with pytest.raises(web.HTTPBadRequest):
        api.execute("MAINTAINER", IMPORT_ACTION, payload)
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind='material_cost_report'").fetchone()[0] == 0


def test_incomparable_cost_periods_keep_reports_and_withhold_changes(services):
    _, api = services
    payload = reports_input()
    payload["records"][1]["data"]["period_start"] = "2026-10-20T19:00:00+08:00"
    api.execute("MAINTAINER", IMPORT_ACTION, payload)
    row = cost_row(api, "INBOUND_RECEIPT")
    assert row["current"]["unit_cost"] == "2100" and row["baseline"]["unit_cost"] == "2000"
    assert row["unit_cost_change"] is row["total_cost_change"] is None and row["comparison_state"] == "INCOMPARABLE_PERIODS"


def test_cost_reports_do_not_change_when_market_quote_changes(services):
    _, api = services
    api.execute("MAINTAINER", IMPORT_ACTION, reports_input())
    before = cost_row(api, "ACTUAL_CONSUMPTION")
    update_record(api, "material_quote", "sim-quote-current-1", {"price": "2400"})
    assert cost_row(api, "ACTUAL_CONSUMPTION") == before


def test_cost_report_adoption_stops_after_its_inventory_source_changes(services):
    _, api = services
    api.execute("MAINTAINER", IMPORT_ACTION, reports_input())
    update_record(api, "inventory_lot", "sim-stock-available-1", {"quantity": "21"})
    view = api.read("BOSS", "SI09")
    assert not any(record["entity_type"] == "material_cost_report" for record in view["records"])
    assert any(record["record_id"].startswith("material_cost_report:") and record["data"] is None for record in view["source_statuses"])


def test_reports_with_different_cost_bases_are_never_combined(services):
    _, api = services
    payload = reports_input()
    payload["records"][0]["data"]["cost_basis_id"] = "sim-other-reported-basis"
    api.execute("MAINTAINER", IMPORT_ACTION, payload)
    rows = [row for row in api.read("BOSS", "SI09")["supply"][0]["cost_reports"] if row["cost_type"] == "INBOUND_RECEIPT"]
    assert len(rows) == 2 and all(row["baseline"] is None and row["unit_cost_change"] is None for row in rows)
    assert {row["cost_basis_id"] for row in rows} == {"sim-other-reported-basis", "sim-reported-direct-material"}


def test_cost_period_cannot_claim_observations_after_source_time(services):
    _, api = services
    payload = reports_input()
    payload["records"][1]["data"]["period_end"] = "2026-10-22T18:00:00+08:00"
    with pytest.raises(web.HTTPBadRequest):
        api.execute("MAINTAINER", IMPORT_ACTION, payload)


def test_single_report_never_creates_a_baseline_or_change_value(services):
    _, api = services
    payload = reports_input()
    payload["records"] = payload["records"][:1]
    api.execute("MAINTAINER", IMPORT_ACTION, payload)
    report = cost_row(api, "INBOUND_RECEIPT")
    assert report["current"]["unit_cost"] == "2000" and report["baseline"] is None
    assert report["comparison_state"] == "NO_BASELINE" and report["unit_cost_change"] is report["total_cost_change"] is None


def test_cost_revision_preserves_source_versions_receipts_and_independent_reopen(services):
    store, api = services
    payload = reports_input()
    initial = api.execute("MAINTAINER", IMPORT_ACTION, payload)
    changed = deepcopy(payload)
    changed["client_request_id"] = "sim-cost-current-revision"
    changed["records"] = [changed["records"][1]]
    changed["records"][0]["expected_version"] = "1"
    changed["records"][0]["data"]["total_cost"] = "22000"
    api.execute("MAINTAINER", IMPORT_ACTION, changed)
    reopened = SupplyQualityAPI(ControlStore(store.path))
    report = cost_row(reopened, "INBOUND_RECEIPT")
    assert report["current"]["unit_cost"] == "2200" and report["unit_cost_change"] == "200"
    assert report["current"]["source_version"] == "2" and report["baseline"]["source_version"] == "1"
    assert reopened.execute("MAINTAINER", IMPORT_ACTION, payload) == initial
    with store.connect() as db:
        record_id = changed["records"][0]["data"]["report_id"]
        assert store.get(db, "ui-check", "material_cost_report_revision", record_id + ":v1")["data"]["total_cost"] == "21000"


def test_report_reversal_keeps_history_and_cannot_reopen_the_same_report(services):
    _, api = services
    payload = reports_input()
    api.execute("MAINTAINER", IMPORT_ACTION, payload)
    reversed_request = deepcopy(payload)
    reversed_request["client_request_id"] = "sim-cost-reported-reversal"
    reversed_request["records"] = [reversed_request["records"][1]]
    reversed_request["records"][0]["expected_version"] = "1"
    reversed_request["records"][0]["data"]["state"] = "REVERSED_REPORTED"
    api.execute("MAINTAINER", IMPORT_ACTION, reversed_request)
    report = cost_row(api, "INBOUND_RECEIPT")
    assert report["current"]["unit_cost"] == "2000" and report["baseline"] is None
    reopen = deepcopy(reversed_request)
    reopen["client_request_id"] = "sim-cost-invalid-reopen"
    reopen["records"][0]["expected_version"] = "2"
    reopen["records"][0]["data"]["state"] = "REPORTED"
    with pytest.raises(web.HTTPConflict):
        api.execute("MAINTAINER", IMPORT_ACTION, reopen)


def test_inventory_reference_order_does_not_change_cost_report_identity(services):
    _, api = services
    payload = reports_input()
    payload["records"] = payload["records"][:1]
    payload["records"][0]["data"]["inventory_ids"] = ["sim-stock-available-1", "sim-stock-pending-1"]
    api.execute("MAINTAINER", IMPORT_ACTION, payload)
    payload["client_request_id"] = "sim-cost-inventory-reference-order"
    payload["records"][0]["expected_version"] = "1"
    payload["records"][0]["data"]["inventory_ids"].reverse()
    result = api.execute("MAINTAINER", IMPORT_ACTION, payload)
    assert result["records"][0]["version"] == "2"


def scoped_reports(cost_owner_id, ownership_type="COMPANY", asset_owner_id="entity-1"):
    payload = reports_input()
    initial = definition()["initial_request"]
    batch = deepcopy(next(row for row in initial["records"] if row["entity_type"] == "production_batch" and row["data"]["batch_id"] == "sim-raw-batch-1"))
    inventory = deepcopy(next(row for row in initial["records"] if row["entity_type"] == "inventory_lot" and row["data"]["inventory_id"] == "sim-stock-available-1"))
    batch["data"].update(batch_id="sim-cost-scoped-batch", cost_owner_id=cost_owner_id, ownership_type=ownership_type, asset_owner_id=asset_owner_id)
    inventory["data"].update(inventory_id="sim-cost-scoped-stock", batch_id="sim-cost-scoped-batch", ownership_type=ownership_type, asset_owner_id=asset_owner_id)
    for row in payload["records"]:
        row["data"].update(cost_owner_id=cost_owner_id, ownership_type=ownership_type, asset_owner_id=asset_owner_id, inventory_ids=["sim-cost-scoped-stock"])
    payload["records"] = [batch, inventory] + payload["records"]
    return payload


def test_unknown_cost_owner_is_preserved_and_stops_cross_period_comparison(services):
    _, api = services
    api.execute("MAINTAINER", IMPORT_ACTION, scoped_reports(None))
    rows = api.read("BOSS", "SI09")["supply"][0]["cost_reports"]
    assert len(rows) == 2 and all(row["cost_owner_id"] is None for row in rows)
    assert all(row["comparison_state"] == "UNKNOWN_COST_OWNER" and row["unit_cost_change"] is row["total_cost_change"] is None for row in rows)


def test_cooperation_assets_keep_cost_owner_separate_and_support_actual_query_filters(services):
    store, api = services
    api.execute("MAINTAINER", IMPORT_ACTION, scoped_reports("entity-1", "COOPERATION", "sim-cooperation-owner"))
    rows = api.read("BOSS", "SI09")["supply"]
    company = next(row for row in rows if row["ownership_type"] == "COMPANY")
    cooperation = next(row for row in rows if row["ownership_type"] == "COOPERATION")
    assert company["cost_reports"] == [] and len(cooperation["cost_reports"]) == 2
    assert cooperation["asset_owner_id"] == "sim-cooperation-owner" and all(row["cost_owner_id"] == "entity-1" for row in cooperation["cost_reports"])
    payload = {"interface_id": "SI09", "object_ids": [], "filters": {"ownership_type": "COOPERATION"}}
    broker = SimulationAPI(store)
    current = broker.query("BOSS", payload)
    assert len(current["records"]) == 5 and all(row["data"]["data"]["ownership_type"] == "COOPERATION" for row in current["records"])
    assert all(row["data"] is None for row in broker.inspect("MAINTAINER", payload)["records"])
