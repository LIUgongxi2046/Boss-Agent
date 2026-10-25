from decimal import Decimal
from pathlib import Path
import sys

import pytest
from aiohttp import web

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "validation"))

from business import checksum
from controls import ControlStore
from test_fc02_bi_queries import request


@pytest.fixture
def store(tmp_path):
    service = ControlStore(tmp_path / "bi-scenarios.sqlite")
    service.initialize("ui-check")
    return service


def load(store, scenario_id, expected_version="0", key=None):
    from boss_bi_scenarios import BIScenarioAPI
    return BIScenarioAPI(store).load("MAINTAINER", {"client_request_id": key or "load-" + scenario_id + "-" + expected_version,
        "mode": "SIMULATED", "scenario_id": scenario_id, "generator_version": "FC02-BI-1", "seed": 20261024, "expected_version": expected_version})


def query(store, scenario_id, key="scenario-query", **fields):
    return store.invoke("query_metrics", request(key, **{"scenario_id": scenario_id, "business_basis": "SIMULATED_BOUNDARY", **fields}))


def current(result, metric):
    return next(row["value"] for row in result["values"] if row["period_scope"] == "CURRENT" and row["metric_id"] == metric)


def test_scenario_query_requires_formal_load(store):
    with pytest.raises(web.HTTPNotFound):
        query(store, "weighted-ratios")


def test_weighted_ratios_load_replay_and_preserved_default_snapshot(store):
    with store.connect() as db:
        before = checksum(store.get(db, "ui-check", "initial", "snapshot"))
    receipt = load(store, "weighted-ratios")
    assert load(store, "weighted-ratios") == receipt
    result = query(store, "weighted-ratios")
    assert Decimal(current(result, "gross_margin")) == Decimal("14")
    assert Decimal(current(result, "gross_profit_per_tonne")) == Decimal("14")
    assert Decimal(current(result, "gross_margin")) != Decimal("30")
    assert result["sources"][0]["source_id"] != "finance-note"
    with store.connect() as db:
        assert checksum(store.get(db, "ui-check", "initial", "snapshot")) == before
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind='authorization'").fetchone()[0] == 0


@pytest.mark.parametrize("scenario_id,expected", [
    ("zero-denominators", {"sales_quantity": "0", "revenue": "0", "gross_margin": None, "gross_profit_per_tonne": None}),
    ("missing-numbers", {"sales_quantity": None, "revenue": "100", "gross_profit": None, "gross_margin": None}),
    ("unsynchronized-records", {"sales_quantity": None, "revenue": None, "gross_profit": None}),
])
def test_formal_zero_missing_and_unsynchronized_inputs(store, scenario_id, expected):
    load(store, scenario_id)
    result = query(store, scenario_id)
    assert all(current(result, metric) == value for metric, value in expected.items())
    if scenario_id == "zero-denominators":
        assert "CURRENT:gross_margin:ZERO_DENOMINATOR_UNDEFINED" in result["missing_fields"]
    if scenario_id == "unsynchronized-records":
        assert result["coverage"]["unsynchronized_regions"] == ["region-1"]
        assert "incomplete_coverage" in result["comparison"]["reasons"]


def test_delayed_source_preserves_observed_values_and_withholds_global_change(store):
    load(store, "delayed-records")
    result = query(store, "delayed-records")
    assert result["coverage"]["delayed_regions"] == ["region-1"]
    assert current(result, "revenue") == "100"
    assert all(row["value"] is None for row in result["values"] if row["period_scope"] == "CHANGE")


def test_both_bases_have_exact_current_sources_and_truthful_authorship(store):
    load(store, "basis-conflict")
    results = [query(store, "basis-conflict", key=basis, business_basis=basis,
        source_ids=["sim-bi:basis-conflict:" + basis]) for basis in ("FINANCIAL_REPORTED", "BUSINESS_REPORTED")]
    assert [current(result, "revenue") for result in results] == ["100", "120"]
    assert [current(result, "gross_margin") for result in results] == ["30.0", "40.0"]
    for result, basis in zip(results, ("FINANCIAL_REPORTED", "BUSINESS_REPORTED")):
        source_id = "sim-bi:basis-conflict:" + basis
        assert [source["source_id"] for source in result["sources"]] == [source_id]
        evidence = store.invoke("read_evidence", {"envelope": request("read-" + basis)["envelope"], "query_id": result["query_id"], "detail_refs": result["detail_refs"], "source_ids": [source_id]})
        document = next(row["content"] for row in evidence["original_records"] if row["record_id"] == source_id)
        assert document["author_kind"] == "SIMULATED_GENERATOR" and document["business_basis"] == basis
        assert document["real_enterprise_data"] is document["third_party_authorization"] is False
        assert document["access_scope"] == "boss-1" and document["valid_until"] > document["valid_from"]
        assert document["generator_parameters"]["seed"] == 20261024
    with pytest.raises(web.HTTPForbidden):
        query(store, "basis-conflict", key="wrong-source", business_basis="FINANCIAL_REPORTED", source_ids=["finance-note"])


def test_rebuilt_services_keep_scenario_query_receipts_and_version_history(store):
    from boss_bi_queries import BIQueryAPI
    from boss_bi_scenarios import BIScenarioAPI
    receipt = load(store, "weighted-ratios")
    original = query(store, "weighted-ratios")
    reopened = ControlStore(store.path)
    api = BIQueryAPI(reopened)
    assert api.read("BOSS", original["query_id"])["result"] == original
    assert BIScenarioAPI(reopened).receipt("MAINTAINER", receipt["client_request_id"])["result"] == receipt
    load(reopened, "weighted-ratios", expected_version="1")
    with pytest.raises(web.HTTPConflict):
        api.read("BOSS", original["query_id"])
    assert api.read("BOSS", original["query_id"], historical=True)["result"] == original
    assert api.receipt("BOSS", "fc02-session", "scenario-query")["query"]["adoption_state"] == "HISTORICAL_REQUIRES_REQUERY"


def test_withdrawn_source_blocks_new_use_without_blocking_other_basis(store):
    from boss_bi_queries import BIQueryAPI
    load(store, "basis-conflict")
    financial = query(store, "basis-conflict", business_basis="FINANCIAL_REPORTED")
    source_id = financial["sources"][0]["source_id"]
    store.control("ui-check", "withdraw", {"source_id": source_id, "version": "1"})
    with pytest.raises(web.HTTPGone):
        query(store, "basis-conflict", key="withdrawn", business_basis="FINANCIAL_REPORTED")
    business = query(store, "basis-conflict", key="other-basis", business_basis="BUSINESS_REPORTED")
    assert current(business, "revenue") == "120"
    assert BIQueryAPI(store).read("BOSS", financial["query_id"], historical=True)["adoption_state"] == "HISTORICAL_REQUIRES_REQUERY"
    with pytest.raises(web.HTTPGone):
        load(store, "basis-conflict", expected_version="1")


@pytest.mark.parametrize("role,error", [(None, web.HTTPUnauthorized), ("BOSS", web.HTTPForbidden)])
def test_only_authenticated_maintainer_loads_scenarios(store, role, error):
    from boss_bi_scenarios import BIScenarioAPI
    with pytest.raises(error):
        BIScenarioAPI(store).load(role, {})


def test_formal_schema_rejects_client_record_replacement_and_scope_injection(store):
    from boss_bi_scenarios import BIScenarioAPI
    payload = {"client_request_id": "input-check", "mode": "SIMULATED", "scenario_id": "weighted-ratios", "generator_version": "FC02-BI-1", "seed": 20261024, "expected_version": "0"}
    for extra in ({"records": []}, {"owner_id": "other"}, {"mode": "REAL"}, {"seed": 0}):
        with pytest.raises(web.HTTPBadRequest):
            BIScenarioAPI(store).load("MAINTAINER", {**payload, **extra})
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind='bi_scenario'").fetchone()[0] == 0


def test_concurrent_load_and_cas_use_one_version(store):
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: load(store, "weighted-ratios"), range(2)))
    assert results[0] == results[1]
    with pytest.raises(web.HTTPConflict):
        load(store, "weighted-ratios", key="new-key-stale-version")


def test_simulation_projection_uses_scenario_record_and_source_binding(store):
    from boss_simulation_api import SimulationAPI
    load(store, "weighted-ratios")
    result = query(store, "weighted-ratios")
    projection = SimulationAPI(store).query("BOSS", {"interface_id": "SI07", "object_ids": [result["query_id"]], "filters": {}})
    assert projection["records"][0]["data"] == result
    assert projection["records"][0]["source_refs"][0]["source_id"] == result["sources"][0]["source_id"]


def test_expired_scene_source_is_rejected_after_formal_clock_change(store):
    from boss_bi_queries import BIQueryAPI
    load(store, "weighted-ratios")
    result = query(store, "weighted-ratios")
    store.control("ui-check", "clock", {"at": "2026-12-24T09:00:00+08:00"})
    with pytest.raises(web.HTTPGone):
        query(store, "weighted-ratios", key="expired-input")
    assert BIQueryAPI(store).read("BOSS", result["query_id"], historical=True)["adoption_state"] == "HISTORICAL_REQUIRES_REQUERY"


def test_reset_preserves_old_receipt_and_rejects_cross_space_request_reuse(store):
    receipt = load(store, "weighted-ratios")
    store.control("ui-check", "reset", {"namespace": "fc02-new-space"})
    with pytest.raises(web.HTTPConflict):
        load(store, "weighted-ratios")
    with store.connect() as db:
        assert len(store.get(db, "fc02-new-space", "initial", "snapshot")["details"]) == 8
        assert db.execute("SELECT COUNT(*) FROM idempotency WHERE namespace='ui-check' AND key=?", (receipt["client_request_id"],)).fetchone()[0] == 1


def test_generated_records_are_reproducible_from_formal_parameters(store, tmp_path):
    other = ControlStore(tmp_path / "independent.sqlite")
    other.initialize("ui-check")
    first, second = load(store, "weighted-ratios"), load(other, "weighted-ratios")
    assert first["manifest_sha256"] == second["manifest_sha256"]
    with store.connect() as one, other.connect() as two:
        assert store.get(one, "ui-check", "bi_scenario", "weighted-ratios")["records"] == other.get(two, "ui-check", "bi_scenario", "weighted-ratios")["records"]


def test_baseline_source_selector_cannot_claim_foreign_comparison_source(store):
    with pytest.raises(web.HTTPForbidden):
        store.invoke("query_metrics", request(comparison_scope={"source_ids": ["foreign-source"]}))
