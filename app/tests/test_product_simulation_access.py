import sys
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "validation"))

from boss_page_api import BossPageAPI
from boss_simulation_api import KINDS, SCHEMA, SimulationAPI
from test_boss_simulation_api import store


@pytest.mark.parametrize("interface", KINDS)
def test_public_simulation_queries_and_metadata_use_current_domain_without_writes(store, interface):
    pages = BossPageAPI(store)
    with store.connect() as db:
        before = tuple(db.iterdump())
    for role, endpoint in [("BOSS", "simulation-query"), ("MAINTAINER", "simulation-inspect")]:
        code, result = pages.serve(role, "/api/boss/ui/" + endpoint, "interface_id=" + interface)
        assert code == 200
        Draft202012Validator(SCHEMA, format_checker=FormatChecker()).validate(result)
        actual = SimulationAPI(store).query_http(role, "interface_id=" + interface) if role == "BOSS" else SimulationAPI(store).inspect_http(role, "interface_id=" + interface)
        assert {key: value for key, value in result.items() if key != "read_at"} == {key: value for key, value in actual.items() if key != "read_at"}
        if role == "MAINTAINER":
            assert all(record["data"] is None for record in result["records"])
    with store.connect() as db:
        assert tuple(db.iterdump()) == before


@pytest.mark.parametrize("role,path,status", [(None, "simulation-query", 401), (None, "simulation-inspect", 401),
    ("MAINTAINER", "simulation-query", 403), ("BOSS", "simulation-inspect", 403)])
def test_public_simulation_role_boundaries(store, role, path, status):
    assert BossPageAPI(store).serve(role, "/api/boss/ui/" + path, "interface_id=SI13")[0] == status


@pytest.mark.parametrize("query", ["", "interface_id=", "interface_id=SI13&interface_id=SI07",
    "interface_id=SI13&owner_id=boss-1", "interface_id=SI13&namespace=ui-check", "interface_id=SI03&currency=CNY"])
def test_public_simulation_strict_queries(store, query):
    for role, endpoint in [("BOSS", "simulation-query"), ("MAINTAINER", "simulation-inspect")]:
        assert BossPageAPI(store).serve(role, "/api/boss/ui/" + endpoint, query)[0] == 400
