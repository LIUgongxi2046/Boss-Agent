"""PRD agricultural page-coverage assertions without imaginary KPI data."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"validation"))
from boss_page_api import BossPageAPI  # noqa: E402
from boss_sector_api import SECTORS  # noqa: E402
from controls import ControlStore  # noqa: E402


@pytest.fixture
def api(tmp_path):
    store=ControlStore(tmp_path/"sector.sqlite")
    store.initialize("ui-check")
    return BossPageAPI(store)


@pytest.mark.parametrize("page", list(SECTORS))
def test_sector_page_matches_approved_v7_and_returns_null_unknown_metrics(api,page):
    status,result=api.serve("BOSS","/api/boss/ui/sector","page="+page)
    assert status==200
    assert result["page_id"]==page
    assert result["source_type"]=="SIMULATED"
    assert result["dataset_version"]=="1"
    assert result["design_filters"]
    assert len(result["metrics"])>=3
    assert all(x["value"] is None and x["unit"] is None for x in result["metrics"])
    assert result["sector_kpi_calculations_supported"] is False
    assert result["sector_specific_dataset_available"] is False
    from_disk=json.loads((ROOT/"Boss-Agent-Desktop-Complete-v7/meta/页面配置.json").read_text())
    assert result["title"].startswith(from_disk[page]["title"])
    expected_html=(ROOT/"Boss-Agent-Desktop-Complete-v7/pages"/
                   (page+"-"+from_disk[page]["title"]+".html")).read_text()
    for field in result["design_filters"]:
        assert "class=\"filteritem\">"+field+"<strong>" in expected_html


def test_only_f14_has_related_water_feed_source_not_raw_material_cost(api):
    for page in SECTORS:
        _,data=api.serve("BOSS","/api/boss/ui/sector","page="+page)
        sources=data["related_source_refs"]
        if page=="F14":
            assert len(sources)==1
            assert sources[0]["source_id"]=="finance-note"
            assert "not_evidence_for" in sources[0]
        else:
            assert sources==[]


def test_withdrawn_feed_source_is_no_longer_related_to_sector(api):
    assert api.store.control("ui-check","withdraw",
                             {"source_id":"finance-note","version":"1"})["withdrawn"]
    _,response=api.serve("BOSS","/api/boss/ui/sector","page=F14")
    assert response["related_source_refs"]==[]
    assert response["sector_kpi_calculations_supported"] is False


def test_sector_role_and_query_are_closed(api):
    assert api.serve("MAINTAINER","/api/boss/ui/sector","page=F14")[0]==403
    assert api.serve(None,"/api/boss/ui/sector","page=F14")[0]==401
    assert api.serve("BOSS","/api/boss/ui/sector","page=unknown")[0]==404
    assert api.serve("BOSS","/api/boss/ui/sector","page=F14&page=F15")[0]==400
    assert api.serve("BOSS","/api/boss/ui/sector","page=F14&private=1")[0]==400
