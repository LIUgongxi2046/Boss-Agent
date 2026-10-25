from urllib.parse import urlencode

import pytest

from test_boss_page_api import api
from boss_page_api import BossPageAPI
from controls import ControlStore


@pytest.mark.parametrize("query", ["products=product-1&owner_id=other", "products=product-1&namespace=other", "products=product-1&dataset_id=other", "products=product-1&products=product-2"])
def test_public_bi_rejects_extra_scope_or_repeated_values_before_query(api, query):
    with api.store.connect() as db:
        before = tuple(db.iterdump())
    assert api.serve("BOSS", "/api/boss/ui/metrics", query)[0] == 400
    with api.store.connect() as db:
        assert tuple(db.iterdump()) == before


def test_public_bi_evidence_reads_only_current_query_details_and_reopens_database(api):
    code, queried = api.serve("BOSS", "/api/boss/ui/metrics", "products=product-1")
    assert code == 200
    query = queried["result"]
    reopened = BossPageAPI(ControlStore(api.store.path))
    route = "/api/boss/ui/metrics-evidence"
    code, evidence = reopened.serve("BOSS", route, urlencode({"query_id":query["query_id"]}))
    assert code == 200, evidence
    assert evidence["query_id"] == query["query_id"] and evidence["source_type"] == "SIMULATED"
    rows = [row for row in evidence["result"]["original_records"] if row["record_id"] in query["detail_refs"]]
    assert {row["record_id"] for row in rows} == set(query["detail_refs"])
    assert all(row["content"]["product_id"] == "product-1" for row in rows)
    assert evidence["result"]["sources"][0]["version"] == query["sources"][0]["version"]
    assert reopened.serve("MAINTAINER", route, urlencode({"query_id":query["query_id"]}))[0] == 403
    assert reopened.serve(None, route, urlencode({"query_id":query["query_id"]}))[0] == 401
    assert reopened.serve("BOSS", route, urlencode({"query_id":query["query_id"],"owner_id":"other"}))[0] == 400
    api.store.control("ui-check", "withdraw", {"source_id":"finance-note","version":"1"})
    assert reopened.serve("BOSS", route, urlencode({"query_id":query["query_id"]}))[0] == 410
    with api.store.connect() as db:
        assert api.store.get(db,"ui-check","query",query["query_id"])["detail_refs"] == query["detail_refs"]
