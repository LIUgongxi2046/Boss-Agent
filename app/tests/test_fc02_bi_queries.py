from copy import deepcopy
from decimal import Decimal

import pytest
from aiohttp import web

from test_boss_tool_sources import service
from controls import ControlStore


def request(key="fc02-current", **overrides):
    return {"query_mode": "SCOPED", "envelope": {"request_id": key, "session_id": "fc02-session", "owner_id": "boss-1", "execution_namespace": "ui-check", "dataset_id": "selection", "dataset_version": "1"},
        "question": "查询当前明确范围的经营变化", "metric_ids": ["sales_quantity", "revenue", "gross_profit", "gross_margin", "gross_profit_per_tonne"],
        "region_id": "region-1", "product_ids": ["product-1", "product-2"], "legal_entity_id": "entity-1",
        "period_start": "2026-10-01", "period_end": "2026-10-10", "comparison_start": "2026-09-01", "comparison_end": "2026-09-10",
        "currency": "CNY", "quantity_unit": "tonne", "trade_scope": "EXTERNAL_SALES", "definition_version": "1", "business_basis": "SELECTION_REPORTED", "settlement_state": "SETTLED", **overrides}


def changes(result):
    return {row["metric_id"]: Decimal(row["value"]) if row["value"] is not None else None for row in result["values"] if row["period_scope"] == "CHANGE"}


def test_fc02_scoped_query_persists_snapshot_and_replays_one_request(tmp_path):
    store, _, _ = service(tmp_path)
    payload = request()
    with store.connect() as db:
        original_count = db.execute("SELECT COUNT(*) FROM objects WHERE kind='query'").fetchone()[0]
    first = store.invoke("query_metrics", payload)
    assert changes(first) == dict(zip(payload["metric_ids"], map(Decimal, ("20", "20", "-4", "-2", "-20"))))
    assert first["context_snapshot"]["legal_entity_id"] == "entity-1"
    assert first["comparison"]["state"] == "COMPARABLE"
    assert first["coverage"]["delayed_regions"] is None and first["coverage"]["unsynchronized_regions"] is None
    assert ControlStore(store.path).invoke("query_metrics", payload) == first
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind='query'").fetchone()[0] == original_count + 1
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind='authorization'").fetchone()[0] == 0
    with pytest.raises(web.HTTPConflict):
        store.invoke("query_metrics", {**payload, "product_ids": ["product-1"]})


@pytest.mark.parametrize("overrides", [
    {"currency": "USD"}, {"trade_scope": "INTERNAL_CONSUMPTION"}, {"legal_entity_id": "unprovided-entity"},
    {"region_id": "unprovided-region"}, {"quantity_unit": "kg"}, {"definition_version": "unprovided-definition"},
])
def test_fc02_unprovided_legal_filters_produce_unknown_not_baseline(tmp_path, overrides):
    store, _, _ = service(tmp_path)
    result = store.invoke("query_metrics", request(**overrides))
    assert all(row["value"] is None for row in result["values"])
    assert result["coverage"]["state"] == "UNAVAILABLE"
    assert result["detail_refs"] == []
    if "definition_version" in overrides:
        assert all(row["formula"] == "DEFINITION_NOT_PROVIDED" for row in result["values"] if row["period_scope"] != "CHANGE")


def test_fc02_incomparable_scope_keeps_period_values_and_withholds_changes(tmp_path):
    store, _, _ = service(tmp_path)
    result = store.invoke("query_metrics", request(comparison_scope={"currency": "USD"}))
    assert result["comparison"]["state"] == "INCOMPARABLE"
    assert "currency" in result["comparison"]["reasons"]
    assert all(value is None for value in changes(result).values())


def test_fc02_precise_ratios_aggregate_numerators_and_reject_duplicates(tmp_path):
    from boss_metrics import aggregate_metrics
    store, _, _ = service(tmp_path)
    with store.connect() as db:
        initial = store.get(db, "ui-check", "initial", "snapshot")
    rows = deepcopy(initial["details"][:2])
    rows[0].update(revenue_cny="10000000000000000000000000000.123456789", cost_cny="1")
    rows[1].update(revenue_cny="1", cost_cny="1")
    total = aggregate_metrics(rows)["metrics"]
    assert str(total["revenue"][0]) == "10000000000000000000000000001.123456789"
    assert total["gross_margin"][0] != sum(aggregate_metrics([row])["metrics"]["gross_margin"][0] for row in rows) / 2
    with pytest.raises(web.HTTPBadRequest):
        aggregate_metrics(rows + rows)


def test_fc02_followup_receipt_history_and_evidence_reopen(tmp_path):
    from boss_bi_queries import BIQueryAPI
    store, _, _ = service(tmp_path)
    parent = store.invoke("query_metrics", request())
    api = BIQueryAPI(ControlStore(store.path))
    follow = {"envelope": request("fc02-follow")["envelope"], "parent_query_id": parent["query_id"], "question": "仅查询product-1", "overrides": {"product_ids": ["product-1"]}}
    child = api.follow_up("BOSS", follow)
    assert child["parent_query_id"] == parent["query_id"] and child["overridden_fields"] == ["product_ids"]
    assert len(child["detail_refs"]) == 4 and len(parent["detail_refs"]) == 8
    assert api.follow_up("BOSS", follow) == child
    assert api.read("BOSS", child["query_id"])["result"] == child
    assert api.receipt("BOSS", "fc02-session", "fc02-follow")["query"]["result"] == child
    evidence = store.invoke("read_evidence", {"envelope": request("fc02-evidence")["envelope"], "query_id": child["query_id"], "detail_refs": child["detail_refs"], "source_ids": ["finance-note"]})
    assert {row["record_id"] for row in evidence["original_records"]} == set(child["detail_refs"]) | {"finance-note"}
    store.control("ui-check", "withdraw", {"source_id": "finance-note", "version": "1"})
    with pytest.raises(web.HTTPGone):
        api.read("BOSS", child["query_id"])
    assert api.read("BOSS", child["query_id"], historical=True)["adoption_state"] == "HISTORICAL_REQUIRES_REQUERY"
    assert api.receipt("BOSS", "fc02-session", "fc02-follow")["outcome"] == "RECORDED"


@pytest.mark.parametrize("field,value", [("owner_id", "other"), ("dataset_id", "other"), ("dataset_version", "2")])
def test_fc02_rejects_scope_escalation_without_query_write(tmp_path, field, value):
    store, _, _ = service(tmp_path)
    payload = request()
    payload["envelope"][field] = value
    with pytest.raises(web.HTTPForbidden):
        store.invoke("query_metrics", payload)


@pytest.mark.parametrize("role,error", [(None, web.HTTPUnauthorized), ("MAINTAINER", web.HTTPForbidden)])
def test_fc02_protected_history_and_receipts_enforce_role(tmp_path, role, error):
    from boss_bi_queries import BIQueryAPI
    store, _, _ = service(tmp_path)
    api = BIQueryAPI(store)
    with pytest.raises(error):
        api.receipt(role, "fc02-session", "unknown")
    with pytest.raises(error):
        api.read(role, "unknown", historical=True)


def test_fc02_concurrent_same_request_creates_one_query(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    store, _, _ = service(tmp_path)
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: store.invoke("query_metrics", request()), range(2)))
    assert results[0] == results[1]


def test_fc02_incomplete_region_scope_withholds_global_comparison(tmp_path):
    store, _, _ = service(tmp_path)
    result = store.invoke("query_metrics", request(region_ids=["region-1", "unprovided-region"]))
    assert result["coverage"]["missing_regions"] == ["unprovided-region"]
    assert all(value is None for value in changes(result).values())
    assert any(row["value"] is not None for row in result["values"] if row["period_scope"] == "CURRENT")


def test_fc02_dimensions_and_unknown_receipt_are_read_only(tmp_path):
    from boss_bi_queries import BIQueryAPI
    store, _, _ = service(tmp_path)
    with store.connect() as db:
        before = db.execute("SELECT kind,id,body FROM objects ORDER BY kind,id").fetchall()
    api = BIQueryAPI(store)
    dimensions = api.dimensions("BOSS")
    assert dimensions["available_dimensions"]["currency"] == ["CNY"]
    assert dimensions["available_dimensions"]["product_id"] == ["product-1", "product-2"]
    assert api.receipt("BOSS", "fc02-session", "unknown")["outcome"] == "NOT_FOUND_IN_CURRENT_STORE"
    with store.connect() as db:
        assert db.execute("SELECT kind,id,body FROM objects ORDER BY kind,id").fetchall() == before


def test_fc02_changed_definition_blocks_current_read_and_preserves_original_snapshot(tmp_path):
    from boss_bi_queries import BIQueryAPI
    store, _, _ = service(tmp_path)
    result = store.invoke("query_metrics", request())
    with store.connect() as db:
        data = store.get(db, "ui-check", "initial", "snapshot")
        data["metric_definitions"][0]["definition_version"] = "2"
        store.put(db, "ui-check", "initial", "snapshot", data)
    api = BIQueryAPI(ControlStore(store.path))
    with pytest.raises(web.HTTPConflict):
        api.read("BOSS", result["query_id"])
    history = api.read("BOSS", result["query_id"], historical=True)
    assert history["result"] == result and history["adoption_state"] == "HISTORICAL_REQUIRES_REQUERY"


def test_fc02_same_period_is_incomparable_and_empty_result_can_open_source(tmp_path):
    store, _, _ = service(tmp_path)
    same = store.invoke("query_metrics", request(comparison_start="2026-10-01", comparison_end="2026-10-10"))
    assert "overlapping_periods" in same["comparison"]["reasons"]
    assert all(value is None for value in changes(same).values())
    empty = store.invoke("query_metrics", request("fc02-empty", currency="USD"))
    evidence = store.invoke("read_evidence", {"envelope": request("fc02-empty-source")["envelope"], "query_id": empty["query_id"], "source_ids": ["finance-note"], "detail_refs": []})
    assert [row["record_id"] for row in evidence["original_records"]] == ["finance-note"]


def test_fc02_mixed_ownership_cannot_produce_combined_totals(tmp_path):
    from boss_bi_queries import _aggregate
    store, _, _ = service(tmp_path)
    with store.connect() as db:
        rows = deepcopy(store.get(db, "ui-check", "initial", "snapshot")["details"][:2])
    rows[0].update(ownership_type="COMPANY", asset_owner_id="entity-1", cost_owner_id="entity-1")
    rows[1].update(ownership_type="CUSTOMER", asset_owner_id="customer-1", cost_owner_id="customer-1")
    metrics, missing = _aggregate(rows, request())
    assert "INCOMPATIBLE_OWNERSHIP_SCOPE" in missing
    assert all(value[0] is None for value in metrics.values())
