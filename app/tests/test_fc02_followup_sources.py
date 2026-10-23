from decimal import Decimal
from uuid import uuid4

import pytest
from aiohttp import web

from test_fc02_bi_scenarios import store, load, current
from test_fc02_bi_queries import request
from boss_bi_queries import BIQueryAPI
from controls import ControlStore
from business import checksum


def follow_up(parent, key=None, scenario="weighted-ratios"):
    return {"envelope": request(key or "followup-repair-" + str(uuid4()))["envelope"], "parent_query_id": parent["query_id"], "question": "按明确正式场景继续查询",
            "overrides": {"scenario_id": scenario, "source_ids": ["sim-bi:" + scenario + ":SIMULATED_BOUNDARY"], "business_basis": "SIMULATED_BOUNDARY"}}


def test_default_parent_to_formal_scenario_keeps_parent_binding_and_inherits_periods(store):
    load(store, "weighted-ratios")
    parent = store.invoke("query_metrics", request("repair-default-parent"))
    with store.connect() as db:
        snapshot = checksum(store.get(db, "ui-check", "initial", "snapshot"))
    api = BIQueryAPI(store)
    payload = follow_up(parent)
    child = api.follow_up("BOSS", payload)
    assert child["query_id"] != parent["query_id"] and child["parent_query_id"] == parent["query_id"]
    assert child["overridden_fields"] == ["business_basis", "scenario_id", "source_ids"]
    for field in ("period_start", "period_end", "comparison_start", "comparison_end", "product_ids", "metric_ids", "region_id", "legal_entity_id"):
        assert child["context_snapshot"][field] == parent["context_snapshot"][field]
    assert Decimal(current(child, "gross_margin")) == Decimal("14")
    assert len(child["detail_refs"]) == 4 and len(parent["detail_refs"]) == 8
    assert api.read("BOSS", parent["query_id"])["result"] == parent
    assert api.follow_up("BOSS", payload) == child
    reopened = BIQueryAPI(ControlStore(store.path))
    assert reopened.receipt("BOSS", "fc02-session", payload["envelope"]["request_id"])["query"]["result"] == child
    with store.connect() as db:
        assert checksum(store.get(db, "ui-check", "initial", "snapshot")) == snapshot
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind='query'").fetchone()[0] == 2
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind IN ('task','authorization','outbox')").fetchone()[0] == 0


@pytest.mark.parametrize("which", ["parent", "child"])
def test_followup_rejects_withdrawn_parent_or_child_source_without_child_write(store, which):
    load(store, "weighted-ratios")
    parent = store.invoke("query_metrics", request("withdrawal-parent"))
    source = "finance-note" if which == "parent" else "sim-bi:weighted-ratios:SIMULATED_BOUNDARY"
    store.control("ui-check", "withdraw", {"source_id": source, "version": "1"})
    with pytest.raises(web.HTTPGone):
        BIQueryAPI(store).follow_up("BOSS", follow_up(parent, key="withdrawal-new-intent"))
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind='query'").fetchone()[0] == 1


@pytest.mark.parametrize("change,error", [("revision", web.HTTPConflict), ("expiry", web.HTTPGone)])
def test_parent_scenario_binding_rejects_revision_or_expiry_before_new_child_source(store, change, error):
    load(store, "weighted-ratios")
    parent = store.invoke("query_metrics", request("scenario-parent-" + change, scenario_id="weighted-ratios",
        source_ids=["sim-bi:weighted-ratios:SIMULATED_BOUNDARY"], business_basis="SIMULATED_BOUNDARY"))
    if change == "revision":
        load(store, "weighted-ratios", expected_version="1")
    else:
        store.control("ui-check", "clock", {"at": "2026-12-24T09:00:00+08:00"})
    load(store, "zero-denominators")
    with pytest.raises(error):
        BIQueryAPI(store).follow_up("BOSS", follow_up(parent, scenario="zero-denominators"))
    assert BIQueryAPI(store).dimensions("BOSS", "zero-denominators")["scenario_id"] == "zero-denominators"
    assert BIQueryAPI(store).read("BOSS", parent["query_id"], historical=True)["adoption_state"] == "HISTORICAL_REQUIRES_REQUERY"
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind='query'").fetchone()[0] == 1


def test_cross_scenario_followup_uses_own_sources_and_rejects_wrong_session_or_conflicting_key(store):
    load(store, "weighted-ratios")
    load(store, "zero-denominators")
    api = BIQueryAPI(store)
    parent = store.invoke("query_metrics", request("scenario-parent", scenario_id="weighted-ratios",
        source_ids=["sim-bi:weighted-ratios:SIMULATED_BOUNDARY"], business_basis="SIMULATED_BOUNDARY"))
    payload = follow_up(parent, scenario="zero-denominators")
    child = api.follow_up("BOSS", payload)
    assert child["sources"][0]["source_id"] == "sim-bi:zero-denominators:SIMULATED_BOUNDARY"
    assert current(child, "gross_margin") is None
    assert api.read("BOSS", parent["query_id"])["result"] == parent
    with pytest.raises(web.HTTPConflict):
        api.follow_up("BOSS", {**payload, "overrides": {**payload["overrides"], "product_ids": ["product-1"]}})
    other_session = follow_up(parent)
    other_session["envelope"]["session_id"] = "different-session"
    with pytest.raises(web.HTTPForbidden):
        api.follow_up("BOSS", other_session)
    evidence = store.invoke("read_evidence", {"envelope": request("child-evidence")["envelope"], "query_id": child["query_id"],
        "source_ids": [child["sources"][0]["source_id"]], "detail_refs": child["detail_refs"]})
    assert all(item["content"].get("source_id") == child["sources"][0]["source_id"] for item in evidence["original_records"])
