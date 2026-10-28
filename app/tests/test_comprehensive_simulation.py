import json
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "validation"))

from boss_command_api import BossCommandAPI
from boss_business_overview import BusinessOverviewAPI
from boss_page_api import BossPageAPI
from boss_simulation_api import SimulationAPI
from boss_sector_api import BossSectorAPI
from controls import ControlStore


def populated(tmp_path):
    from boss_comprehensive_simulation import populate

    store = ControlStore(tmp_path / "business.sqlite")
    store.initialize("ui-check")
    result = populate(store, "2026-10-28T09:00:00+08:00")
    return store, result


def test_all_fourteen_interfaces_have_current_records_and_references(tmp_path):
    store, result = populated(tmp_path)
    assert result["source_type"] == "SIMULATED"
    api = SimulationAPI(store)
    for index in range(1, 15):
        view = api.query("BOSS", {"interface_id": f"SI{index:02d}", "object_ids": [], "filters": {}})
        assert view["records"], f"SI{index:02d}"
        assert all(row["content_state"] != "NEEDS_REVIEW" for row in view["records"])
    pages = BossPageAPI(store)
    status, library = pages.serve("BOSS", "/api/boss/ui/owner/meeting-library")
    assert status == 200
    assert {row["kind"] for row in library["records"]} == {"meeting", "document", "approval", "research", "people"}
    assert len([row for row in library["records"] if row["kind"] == "meeting"]) >= 3
    assert pages.serve("MAINTAINER", "/api/boss/ui/tasks")[0] == 403


def test_business_records_are_consistent_anonymous_and_reproducible(tmp_path):
    store, result = populated(tmp_path)
    with store.connect() as db:
        snapshot = store.get(db, "ui-check", "initial", "snapshot")
        bodies = [json.loads(row[0]) for row in db.execute("SELECT body FROM objects WHERE namespace='ui-check'")]
        from business import checksum
        assert db.execute("SELECT snapshot FROM spaces WHERE namespace='ui-check'").fetchone()[0] == checksum(snapshot)
    assert len(snapshot["contacts"]) >= 12
    assert len({row["name"] for row in snapshot["contacts"]}) == len(snapshot["contacts"])
    forbidden = "".join(chr(value) for value in (28023, 22823, 38598, 22242))
    assert forbidden not in json.dumps(bodies, ensure_ascii=False)
    assert snapshot["business_clock"] == "2026-10-28T09:00:00+08:00"
    tasks = BossPageAPI(store).serve("BOSS", "/api/boss/ui/tasks")[1]
    assert len(tasks["tasks"]) >= 10
    assert len(tasks["self_commitments"]) >= 3
    assert len({row["status"] for row in tasks["tasks"]}) >= 4
    for row in tasks["tasks"]:
        assert datetime.fromisoformat(row["due_at"]).tzinfo is not None
        assert row["coordinator_id"] in {person["contact_id"] for person in snapshot["contacts"]}
    for period in snapshot["periods"]:
        rows = [row for row in snapshot["details"] if row["period"] == period]
        assert rows
        assert sum(Decimal(row["revenue_cny"]) for row in rows) > sum(Decimal(row["cost_cny"]) for row in rows)
    assert result["external_delivery"] is False


def test_population_is_idempotent_and_preserves_later_owner_actions(tmp_path):
    from boss_comprehensive_simulation import populate

    store, first = populated(tmp_path)
    with store.connect() as db:
        before = list(db.execute("SELECT kind,id,body FROM objects ORDER BY kind,id"))
    assert populate(store, "2026-10-28T09:00:00+08:00")["dataset_version"] == first["dataset_version"]
    with store.connect() as db:
        assert list(db.execute("SELECT kind,id,body FROM objects ORDER BY kind,id")) == before
    task = BossPageAPI(store).serve("BOSS", "/api/boss/ui/tasks")[1]["tasks"][0]
    status, result = BossCommandAPI(store).execute("BOSS", "boss.assignment.cancel", {
        "client_request_id": "simulation-owner-cancel", "task_id": task["task_id"], "task_version": task["version"], "reason": "本人取消当前模拟交办"})
    assert status == 200, result
    populate(store, "2026-10-28T09:00:00+08:00")
    with store.connect() as db:
        assert store.get(db, "ui-check", "task", task["task_id"])["status"] == "CANCELED"
    with pytest.raises(ValueError, match="时区"):
        populate(store, "2026-10-28T09:00:00")


def test_clock_periods_and_supply_dates_follow_the_requested_simulation_date(tmp_path):
    from boss_comprehensive_simulation import populate

    store = ControlStore(tmp_path / "future.sqlite")
    store.initialize("ui-check")
    populate(store, "2027-01-05T09:00:00+08:00")
    with store.connect() as db:
        snapshot = store.get(db, "ui-check", "initial", "snapshot")
        source = store.get(db, "ui-check", "document", "sector-f14-a")
    assert snapshot["periods"] == {"BASE": ["2026-12-01", "2026-12-31"], "CURRENT": ["2027-01-01", "2027-01-31"]}
    assert source["sector_facts"]["periods"] == ["2026-11", "2026-12", "2027-01"]
    view = SimulationAPI(store).query("BOSS", {"interface_id": "SI09", "object_ids": [], "filters": {}})
    assert all(row["content_state"] != "NEEDS_REVIEW" for row in view["records"])


def test_public_financial_baseline_keeps_report_scope_separate_from_simulation():
    baseline = json.loads((Path(__file__).resolve().parents[2] / "specs/public-business-baseline.json").read_text())
    assert baseline["company_display_name"] == "丰泽农牧集团"
    assert baseline["source_url"].startswith("https://static.cninfo.com.cn/")
    products = baseline["products"]
    for year in ("2024", "2025"):
        assert sum(Decimal(item[year]["revenue_cny"]) for item in products) == Decimal(baseline["consolidated"][year]["revenue_cny"])
        assert sum(Decimal(item[year]["cost_cny"]) for item in products) == Decimal(baseline["consolidated"][year]["cost_cny"])
    assert baseline["simulation_policy"] == "PUBLIC_BASELINE_WITH_SEPARATE_SIMULATED_OPERATIONS"


def test_morning_context_keeps_every_source_and_version_without_repeated_bodies(tmp_path):
    from business import checksum, encode
    from boss_morning import MorningAPI
    from fc03_agent.formal import compact_morning_messages

    store, _ = populated(tmp_path)
    api = MorningAPI(store)
    view = api.query("BOSS", {"date": "2026-10-28", "timezone": "Asia/Shanghai", "session_id": "simulation-context", "client_request_id": "simulation-context-read"})
    outputs = [("todayRead", view)] + [("morningDetailRead", api.detail("BOSS", view["list_id"], item["item_id"])) for item in view["items"]]
    messages = []
    for index, (name, output) in enumerate(outputs):
        call_id = "actual-domain-read-" + str(index)
        messages.extend([{"role": "assistant", "tool_calls": [{"id": call_id, "function": {"name": name}}]},
                         {"role": "tool", "tool_call_id": call_id, "content": encode(output)}])
    before = encode(messages)
    compacted = compact_morning_messages(messages)
    assert encode(messages) == before
    representations = {}

    def restore(value):
        if isinstance(value, dict):
            if "representation_sha256" in value:
                original = representations[value["representation_sha256"]]
                assert checksum(original) == value["representation_sha256"]
                assert all(original[key] == item for key, item in value.items() if key != "representation_sha256")
                return original
            return {key: restore(item) for key, item in value.items()}
        if isinstance(value, list):
            return [restore(item) for item in value]
        return value

    restored = []
    for message in compacted:
        if message["role"] == "tool":
            output = json.loads(message["content"])
            additions = output.pop("source_representations")
            assert not representations.keys() & additions.keys()
            representations.update(additions)
            restored.append(restore(output))
    assert restored == [output for _, output in outputs]
    assert len(encode(compacted)) < len(before)


def test_sector_analysis_receives_current_task_progress_and_submitted_evidence(tmp_path):
    store, _ = populated(tmp_path)
    status, view = BossSectorAPI(store).serve("BOSS", "page=F22")
    assert status == 200
    assert {row["task_status"] for row in view["followups"]} == {"IN_PROGRESS", "RESULT_SUBMITTED"}
    assert all(row["feedback"] for row in view["followups"])
    assert not any("后续动作尚未提供" in value for value in view["missing_fields"])


@pytest.mark.parametrize("use,page,label,unit", [("EGG", "V19-EGG", "产蛋量", "枚"), ("MILK", "V19-MILK", "产奶表现", "公斤/头/日"), ("BEEF", "V19-BEEF", "生长表现", "公斤/头/日")])
def test_bound_business_topic_preserves_its_animal_purpose_and_sources(tmp_path, use, page, label, unit):
    store, _ = populated(tmp_path)
    api = BusinessOverviewAPI(store)
    scope = {"legal_entity_id": "entity-1", "region_id": None, "period_start": "2026-10-01", "period_end": "2026-10-31", "timezone": "Asia/Shanghai", "attention": "ALL"}
    view = api.read("BOSS", scope)
    detail = api.detail("BOSS", {"scope": scope, "page_id": "F19", "use": use, "snapshot_sha256": view["snapshot_sha256"]})
    with store.connect() as db:
        topic = api.topic_in_transaction(db, view, {"page_id": "F19", "use": use})
    assert detail["topic"] == topic
    metric = next(row for row in topic["metrics"] if row["label"] == label)
    assert metric["unit"] == unit
    assert metric["source_refs"][0]["source_id"] == "sector-" + page.lower() + "-a"
    source_ids = {source["source_id"] for source in view["sources"]}
    assert metric["source_refs"][0]["source_id"] in source_ids
    with store.connect() as db:
        source = store.get(db, "ui-check", "document", metric["source_refs"][0]["source_id"])
        source["sector_facts"]["metrics"][0]["points"][-1]["value"] = "999"
        store.put(db, "ui-check", "document", source["source_id"], source)
    assert api.read("BOSS", scope)["snapshot_sha256"] != view["snapshot_sha256"]
