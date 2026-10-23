import json
import sys
from pathlib import Path

import pytest
from aiohttp import web

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "validation"))

from boss_runtime_records import runtime_records
from controls import ControlStore


@pytest.fixture
def recorded_store(tmp_path):
    evidence = json.loads((ROOT / "evidence/T16/runtime-version-ui/runtime-version-adoption.json").read_text())
    assert evidence["status"] == "PASS"
    store = ControlStore(tmp_path / "runtime-query.sqlite")
    store.initialize("ui-check")
    with store.connect() as db:
        for stage in evidence["stages"]:
            row = stage["runtime_record"]
            assert row["model_requests"][0]["response_ids"] and row["namespace"] == "ui-check"
            store.put(db, "ui-check", "runtime_run", row["run_id"], row)
    return store


def test_query_real_runtime_metadata_by_provider_dataset_and_status(recorded_store):
    result = runtime_records(recorded_store, "MAINTAINER", query={"provider": "deepseek", "dataset_id": "selection", "status": "SUCCEEDED"})
    assert result["source_type"] == "RUNTIME_RECORD" and result["matched_count"] == 2
    assert len(result["runs"]) == 2 and result["next_cursor"] is None
    assert result["private_body_available_here"] is False
    assert all(row["usage"]["prompt_cache_hit_tokens"] is not None for row in result["runs"])
    assert runtime_records(recorded_store, "MAINTAINER", query={"status": "FAILED"})["runs"] == []


def test_keyset_pagination_uses_existing_real_run_ids(recorded_store):
    first = runtime_records(recorded_store, "BOSS", query={"limit": "1"})
    assert len(first["runs"]) == 1 and first["matched_count"] == 2
    second = runtime_records(recorded_store, "BOSS", query={"limit": "1", **first["next_cursor"]})
    assert len(second["runs"]) == 1 and second["next_cursor"] is None
    assert first["runs"][0]["run_id"] != second["runs"][0]["run_id"]
    assert second["matched_count"] == 2


def test_exact_run_and_real_time_query_reopens_database(recorded_store):
    current = runtime_records(recorded_store, "BOSS")["runs"][0]
    reopened = ControlStore(recorded_store.path)
    assert runtime_records(reopened, "MAINTAINER", run_id=current["run_id"])["runs"] == [current]
    result = runtime_records(reopened, "MAINTAINER", query={
        "started_from": current["started_at"], "started_until": current["started_at"],
    })
    assert result["runs"] == [current]


@pytest.mark.parametrize("query", [
    {"namespace": "another-space"}, {"limit": "0"}, {"limit": "101"}, {"status": "FINISHED"},
    {"started_from": "not-a-time"}, {"cursor_run_id": "missing-time"},
    {"started_from": "2026-10-24T00:00:00Z", "started_until": "2026-10-23T00:00:00Z"},
])
def test_runtime_query_rejects_invalid_or_out_of_scope_input(recorded_store, query):
    with pytest.raises(web.HTTPBadRequest):
        runtime_records(recorded_store, "MAINTAINER", query=query)
