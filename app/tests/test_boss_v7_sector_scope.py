import sys
from pathlib import Path
from urllib.parse import urlencode

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "validation"))

from boss_sector_api import BossSectorAPI, CATALOGUE
from controls import ControlStore


@pytest.fixture
def store(tmp_path):
    result = ControlStore(tmp_path / "sector-scope.sqlite")
    result.initialize("ui-check")
    return result


def query(**values):
    return urlencode({key: value for key, value in values.items()})


def test_default_projection_matches_frontend_scope_contract(store):
    status, body = BossSectorAPI(store).serve("BOSS", query(page="F15"))
    assert status == 200
    assert body["projection"] == "sector-workspace"
    assert body["page_id"] == "F15" and body["namespace"] == "ui-check"
    assert body["source_type"] == "SIMULATED" and body["dataset_version"] == "1"
    assert body["applied_filters"] == {}
    assert isinstance(body["query_id"], str) and body["query_id"].startswith("F15-")
    assert body["business_clock"] == "2026-10-22T09:00:00+08:00"
    assert len(body["metrics"]) == len(["订单", "渠道库存", "投苗投喂", "回访分子分母"])
    assert body["metrics"][0]["state"] == "SOURCE_NOT_AVAILABLE"
    assert [row["label"] for row in body["coverage"]] == CATALOGUE["F15"]["right"]
    assert body["missing_fields"]
    assert body["sources"] == [] and body["records"] == []
    assert body["availability"] == "SOURCE_NOT_AVAILABLE"


def test_filters_and_overview_reference_are_echoed_and_change_query_id(store):
    api = BossSectorAPI(store)
    _, first = api.serve("BOSS", query(page="F15"))
    overview = {"page_id": "N03", "use": "BROILER", "snapshot_sha256": "abc",
                "scope": {"legal_entity_id": "entity-1", "region_id": "region-1",
                          "period_start": "2026-10-01", "period_end": "2026-10-10",
                          "timezone": "Asia/Shanghai", "attention": []}}
    status, second = api.serve("BOSS", urlencode({"page": "F15", "filters": '{"区域":"华东"}',
                                                  "overview_reference": __import__("json").dumps(overview)}))
    assert status == 200
    assert second["applied_filters"] == {"区域": "华东"}
    assert second["overview_reference"] == overview
    assert second["query_id"] != first["query_id"]


def test_invalid_scope_is_rejected(store):
    api = BossSectorAPI(store)
    assert api.serve("BOSS", query(page="F99"))[0] == 404
    assert api.serve("BOSS", query(page="F15", extra="1"))[0] == 400
    assert api.serve("BOSS", query(page="F15", filters="{bad"))[0] == 400
    assert api.serve("MAINTAINER", query(page="F15"))[0] == 403
    assert api.serve(None, query(page="F15"))[0] == 401
