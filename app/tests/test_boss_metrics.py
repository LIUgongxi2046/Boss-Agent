import sys
from decimal import Decimal
from pathlib import Path

import pytest
from aiohttp import web

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "validation"))

from business import initial_materials
from boss_metrics import aggregate_metrics
from boss_page_api import BossPageAPI
from controls import ControlStore


def test_approved_details_independently_recompute_comparison():
    rows = initial_materials()["details"]
    base, current = [aggregate_metrics([r for r in rows if r["period"] == p])["metrics"] for p in ("BASE", "CURRENT")]
    assert (current["sales_quantity"][0] / base["sales_quantity"][0] - 1) * 100 == Decimal("20")
    assert (current["revenue"][0] / base["revenue"][0] - 1) * 100 == Decimal("20")
    assert (current["gross_profit"][0] / base["gross_profit"][0] - 1) * 100 == Decimal("-4")
    assert current["gross_margin"][0] - base["gross_margin"][0] == Decimal("-2")
    assert (current["gross_profit_per_tonne"][0] / base["gross_profit_per_tonne"][0] - 1) * 100 == Decimal("-20")
    assert aggregate_metrics([])["metrics"]["revenue"][0] is None
    assert aggregate_metrics([])["missing_fields"] == ["records"]


def test_query_tool_returns_deterministic_changes_with_percentage_point_units(tmp_path):
    store = ControlStore(tmp_path / "metric-change.sqlite")
    store.initialize("ui-check")
    status, response = BossPageAPI(store).serve("BOSS", "/api/boss/ui/metrics")
    assert status == 200
    changes = {row["metric_id"]: row for row in response["result"]["values"] if row["period_scope"] == "CHANGE"}
    assert Decimal(changes["sales_quantity"]["value"]) == Decimal("20")
    assert Decimal(changes["revenue"]["value"]) == Decimal("20")
    assert Decimal(changes["gross_profit"]["value"]) == Decimal("-4")
    assert Decimal(changes["gross_margin"]["value"]) == Decimal("-2")
    assert changes["gross_margin"]["unit"] == "百分点"
    assert Decimal(changes["gross_profit_per_tonne"]["value"]) == Decimal("-20")


def test_query_rejects_incomparable_request_and_withdrawn_source(tmp_path):
    store = ControlStore(tmp_path / "metric-scope.sqlite")
    store.initialize("ui-check")
    status, response = BossPageAPI(store).serve("BOSS", "/api/boss/ui/metrics")
    assert status == 200
    with store.connect() as db:
        data = store.get(db, "ui-check", "initial", "snapshot")
    query = response["result"]
    payload = {
        "envelope": query["envelope"], "question": "查询获准模拟经营指标，并保留原始精度与来源",
        "metric_ids": [row["metric_id"] for row in query["values"] if row["period_scope"] == "BASE"],
        "region_id": data["details"][0]["region_id"], "product_ids": sorted({row["product_id"] for row in data["details"]}),
        "period_start": data["periods"]["CURRENT"][0], "period_end": data["periods"]["CURRENT"][1],
        "comparison_start": data["periods"]["BASE"][0], "comparison_end": data["periods"]["BASE"][1],
        "currency": "CNY", "trade_scope": "EXTERNAL_SALES", "definition_version": "1",
    }
    with pytest.raises(web.HTTPBadRequest):
        store.invoke("query_metrics", {**payload, "currency": "USD"})
    with pytest.raises(web.HTTPBadRequest):
        store.invoke("query_metrics", {**payload, "period_start": data["periods"]["BASE"][0]})
    store.control("ui-check", "withdraw", {"source_id": "finance-note", "version": "1"})
    with pytest.raises(web.HTTPGone):
        store.invoke("query_metrics", payload)
    with pytest.raises(web.HTTPBadRequest):
        aggregate_metrics([data["details"][0], data["details"][0]])
