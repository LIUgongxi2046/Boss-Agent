import sys
from pathlib import Path
from uuid import uuid4

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "validation"))

from boss_business_overview import BusinessOverviewAPI
from boss_command_api import BossCommandAPI
from boss_page_api import BossPageAPI
from boss_sector_pack import ensure_sector_pack
from controls import ControlStore
from conversation_agent.presentation import result_text


@pytest.fixture
def store(tmp_path):
    value = ControlStore(tmp_path / "business-review.sqlite")
    value.initialize("ui-check")
    with value.connect() as db:
        ensure_sector_pack(value, db, value.get(db, "ui-check", "initial", "snapshot"))
    return value


def scope():
    return {"legal_entity_id": "entity-1", "region_id": None, "period_start": "2026-10-01", "period_end": "2026-10-31", "timezone": "Asia/Shanghai", "attention": "ALL"}


def test_ten_business_topics_use_saved_monthly_figures(store):
    api = BusinessOverviewAPI(store)
    view = api.read("BOSS", scope())
    assert len(view["topics"]) == 10
    assert all(topic["metrics"] for topic in view["topics"])
    first = view["topics"][0]["metrics"][0]
    with store.connect() as db:
        document = store.get(db, "ui-check", "document", "sector-f14-a")
    assert first["value"] == document["sector_facts"]["metrics"][0]["points"][-1]["value"]
    assert first["change_percent"] is not None
    assert first["source_refs"] == [{"source_id": document["source_id"], "version": "1"}]
    assert api.detail("BOSS", {"scope": scope(), "page_id": "F14", "snapshot_sha256": view["snapshot_sha256"]})["topic"]["metrics"][0] == first


def test_short_period_does_not_include_full_month_figures(store):
    view = BusinessOverviewAPI(store).read("BOSS", {**scope(), "period_end": "2026-10-10"})
    assert all(topic["metrics"] == [] for topic in view["topics"])


def test_business_chat_reports_persisted_metrics_and_processing_advice(store):
    api = BusinessOverviewAPI(store)
    view = api.read("BOSS", scope())
    detail = api.detail("BOSS", {"scope": scope(), "page_id": "F14", "snapshot_sha256": view["snapshot_sha256"]})
    content = "\n".join(result_text("businessOverviewRead", detail))
    for metric in detail["topic"]["metrics"]:
        assert metric["label"] + "：" + metric["value"] + " " + metric["unit"] in content
    assert "较上月" in content and "负责人和处理期限" in content
    assert "sector-f14-a" not in content and "PARTIAL" not in content


def test_withdrawn_business_document_changes_snapshot_and_hides_figures(store):
    api = BusinessOverviewAPI(store)
    before = api.read("BOSS", scope())
    with store.connect() as db:
        source = store.get(db, "ui-check", "document", "sector-f14-a")
        source["withdrawn"] = True
        store.put(db, "ui-check", "document", source["source_id"], source)
    after = api.read("BOSS", scope())
    assert after["snapshot_sha256"] != before["snapshot_sha256"]
    assert after["topics"][0]["metrics"] == []


def test_saved_research_appears_in_library_and_can_be_opened(store):
    api = BossCommandAPI(store)
    status, result = api.execute("BOSS", "boss.research.prepare", {"client_request_id": str(uuid4()), "expected_version": "0",
        "question": "毛利率", "period": "", "country": "", "business_relation": "", "cutoff_date": "2026-12-31",
        "source_refs": [{"source_id": "finance-note", "version": "1"}], "execution_namespace": "ui-check"})
    assert status == 200, result
    status, result = BossPageAPI(store).serve("BOSS", "/api/boss/ui/owner/meeting-library")
    assert status == 200, result
    record = next(record for record in result["records"] if record["kind"] == "research")
    assert record["title"] == "毛利率" and record["source_refs"]
    assert next(action for action in record["actions"] if action["id"] == "open")["page"] == "F09"
    assert next(item for item in result["coverage"] if item["kind"] == "research")["state"] == "COMPLETE"
