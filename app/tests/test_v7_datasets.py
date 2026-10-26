import sys
from decimal import Decimal
from pathlib import Path
from uuid import uuid4
from urllib.parse import urlsplit

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "validation"))

from boss_command_api import BossCommandAPI
from boss_dataset_generator import GENERATOR_VERSION, RELATIONSHIP_VERSION, generate_facts
from boss_page_api import BossPageAPI
from boss_v7_datasets import CATALOG, KIND
from business import checksum
from controls import ControlStore


@pytest.fixture
def services(tmp_path):
    store = ControlStore(tmp_path / "datasets.sqlite")
    store.initialize("ui-check")
    return store, BossCommandAPI(store), BossPageAPI(store)


def conditions(**changes):
    return {"seed": 20261026, "scale": "SMALL", "period_start": "2026-09", "period_end": "2026-10",
            "generator_version": GENERATOR_VERSION, "relationship_version": RELATIONSHIP_VERSION, **changes}


def write(api, action, payload, role="MAINTAINER", request_id=None):
    return api.execute(role, "boss.technical.datasets." + action, {"client_request_id": request_id or str(uuid4()), **payload})


def read(pages, suffix="", role="MAINTAINER"):
    target = urlsplit("/api/boss/ui/admin/technical/datasets" + suffix)
    return pages.serve(role, target.path, target.query)


def test_generated_candidates_are_repeatable_and_do_not_change_current_owner_data(services):
    store, api, pages = services
    with store.connect() as db:
        before = db.execute("SELECT kind,id,body FROM objects WHERE namespace='ui-check' ORDER BY kind,id").fetchall()
    assert read(pages)[1]["datasets"] == []
    request_id = str(uuid4())
    status, receipt = write(api, "generate", conditions(), request_id=request_id)
    assert status == 200, receipt
    assert write(api, "generate", conditions(), request_id=request_id) == (status, receipt)
    identifier = receipt["result"]["dataset_id"]
    assert read(pages, "/requests/" + request_id) == (status, receipt)
    status, reused = write(api, "generate", conditions())
    assert status == 200 and reused["result"]["reused"] is True
    assert reused["result"]["dataset_id"] == identifier
    projection = read(pages)[1]
    assert projection["current"]["dataset_id"] == "selection"
    assert projection["history"] == [] and len(projection["datasets"]) == 1
    dataset = projection["datasets"][0]
    assert dataset["state"] == "VALIDATED"
    assert all(check["state"] == "PASSED" for check in dataset["checks"])
    assert "facts" not in dataset
    with store.connect() as db:
        assert before == db.execute("SELECT kind,id,body FROM objects WHERE namespace='ui-check' ORDER BY kind,id").fetchall()
        assert db.execute("SELECT namespace FROM spaces WHERE active=1").fetchall() == [("ui-check",)]
        candidate = dataset["candidate_namespace"]
        for kind in ("memory", "authorization", "task", "outbox", "runtime_run"):
            assert db.execute("SELECT count(*) FROM objects WHERE namespace=? AND kind=?", (candidate, kind)).fetchone()[0] == 0
        item = store.get(db, CATALOG, KIND, identifier)
        assert checksum(item["facts"]) == dataset["facts_sha256"]
        assert item["facts"] == generate_facts(conditions())
    result = write(api, "validate", {"dataset_id": identifier, "expected_dataset_version": "1"})
    assert result[0] == 200, result


@pytest.mark.parametrize("scale,groups", [("SMALL", 1), ("MEDIUM", 4), ("LARGE", 16)])
def test_scales_generate_real_distinct_entities_with_balanced_financial_details(services, scale, groups):
    store, api, pages = services
    code, receipt = write(api, "generate", conditions(scale=scale, period_start="2024-02", period_end="2024-02"))
    assert code == 200, receipt
    identifier = receipt["result"]["dataset_id"]
    dataset = read(pages)[1]["datasets"][0]
    assert dataset["counts"]["financial_detail"] == 8 * groups
    assert dataset["counts"]["production_batch"] == 2 * groups
    assert dataset["counts"]["quality_trace"] == 2 * groups
    with store.connect() as db:
        initial = store.get(db, dataset["candidate_namespace"], "initial", "snapshot")
        assert initial["periods"]["CURRENT"] == ["2024-02-01", "2024-02-29"]
        assert initial["periods"]["BASE"] == ["2024-01-03", "2024-01-31"]
        assert len({row["legal_entity_id"] for row in initial["details"]}) == groups
        for period, totals in dataset["totals"].items():
            for field, total in totals.items():
                assert Decimal(total) == sum(Decimal(row[field]) for row in initial["details"] if row["period"] == period)
    first = read(pages, "/" + identifier + "/records?kind=financial_detail&offset=0")
    assert first[0] == 200, first
    assert first[1]["total"] == 8 * groups
    assert first[1]["records"] == initial["details"][:25]
    if groups == 16:
        second = read(pages, "/" + identifier + "/records?kind=financial_detail&offset=25")
        assert second[1]["records"] == initial["details"][25:50]
    assert write(api, "validate", {"dataset_id": identifier, "expected_dataset_version": "1"})[0] == 200


def test_seed_changes_facts_and_candidate_isolation(services):
    store, api, pages = services
    first = write(api, "generate", conditions(seed=1))[1]["result"]["dataset_id"]
    second = write(api, "generate", conditions(seed=2))[1]["result"]["dataset_id"]
    assert first != second
    a = read(pages, "/" + first + "/records")[1]
    b = read(pages, "/" + second + "/records")[1]
    assert a["records"] != b["records"]
    assert a["facts_sha256"] != b["facts_sha256"]
    for identifier in (first, second):
        assert write(api, "validate", {"dataset_id": identifier, "expected_dataset_version": "1"})[0] == 200
    with store.connect() as db:
        assert db.execute("SELECT count(*) FROM spaces WHERE active=0").fetchone()[0] == 2


@pytest.mark.parametrize("change", [
    {"seed": True}, {"seed": -1}, {"seed": 9007199254740992}, {"scale": "UNKNOWN"},
    {"period_start": "2026-13"}, {"period_start": "2026-11"}, {"period_end": "2030-10"},
    {"generator_version": "unknown"}, {"relationship_version": "unknown"}, {"owner_confirmed": True},
])
def test_invalid_parameters_do_not_create_partial_candidates(services, change):
    store, api, pages = services
    assert write(api, "generate", conditions(**change))[0] == 400
    assert read(pages)[1]["datasets"] == []
    with store.connect() as db:
        assert db.execute("SELECT count(*) FROM spaces").fetchone()[0] == 1


def test_candidate_integrity_and_owner_permissions_are_enforced(services):
    store, api, pages = services
    assert write(api, "generate", conditions(), role="BOSS")[0] == 403
    assert read(pages, role="BOSS")[0] == 403
    code, receipt = write(api, "generate", conditions())
    assert code == 200, receipt
    identifier = receipt["result"]["dataset_id"]
    assert read(pages, "/" + identifier + "/records", role="BOSS")[0] == 403
    assert write(api, "validate", {"dataset_id": identifier, "expected_dataset_version": "2"})[0] == 409
    for query in ("offset=-1", "offset=invalid", "kind=memory", "kind=financial_detail&kind=contact"):
        assert read(pages, "/" + identifier + "/records?" + query)[0] == 400
    with store.connect() as db:
        item = store.get(db, CATALOG, KIND, identifier)
        namespace = item["candidate_namespace"]
        source = store.get(db, namespace, "document", "finance-note")
        source["version"] = "2"
        store.put(db, namespace, "document", "finance-note", source)
    assert write(api, "validate", {"dataset_id": identifier, "expected_dataset_version": "1"})[0] == 409
    assert write(api, "generate", conditions())[0] == 409
    assert read(pages)[1]["datasets"][0]["state"] == "NEEDS_REVIEW"
    assert read(pages, "/" + identifier + "/records")[0] == 409


def test_namespace_transition_cannot_report_success_without_runtime_support(services):
    store, api, pages = services
    code, receipt = write(api, "generate", conditions())
    assert code == 200, receipt
    identifier = receipt["result"]["dataset_id"]
    projection = read(pages)[1]
    assert projection["transition_available"] is False and projection["reset_impact"] is None
    assert projection["inspection_available"] is False
    for action in ("load", "reset"):
        result = write(api, action, {"dataset_id": identifier, "expected_dataset_version": "1", "expected_namespace": "ui-check", "confirmed": True})
        assert result[0] == 409, result
    assert write(api, "inspect-reset", {"expected_namespace": "ui-check"})[0] == 503
    assert read(pages)[1]["current"]["namespace"] == "ui-check"
    with store.connect() as db:
        assert db.execute("SELECT namespace FROM spaces WHERE active=1").fetchall() == [("ui-check",)]
