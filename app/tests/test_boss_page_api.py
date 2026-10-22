"""Unit tests for the same scoped business projections used by the WebUI.

These tests are intended to run in the pinned Python project. A passing unit
test never substitutes for a real Electron/Nanobot/DeepSeek integration check.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "validation"))
from boss_page_api import BossPageAPI  # noqa: E402
from controls import ControlStore  # noqa: E402


@pytest.fixture
def api(tmp_path):
    store = ControlStore(tmp_path / "boss-ui.sqlite")
    store.initialize("ui-check")
    return BossPageAPI(store)


def test_dashboard_is_real_simulated_source_with_no_fake_task(api):
    code, dashboard = api.serve("BOSS", "/api/boss/ui/dashboard")
    assert code == 200
    assert dashboard["source_type"] == "SIMULATED"
    assert dashboard["tasks"] == []  # Not invented from design examples.
    assert dashboard["historical_commitment"]["task_id"] == "historical-1"
    assert dashboard["source_coverage"]["region"] == "region-1"


def test_metrics_reuse_validated_business_tool_and_sources(api):
    code, payload = api.serve("BOSS", "/api/boss/ui/metrics", "products=product-1%2Cproduct-2")
    assert code == 200
    result = payload["result"]
    assert result["sources"][0]["source_type"] == "SIMULATED"
    value = lambda metric, period: next(
        m["value"] for m in result["values"]
        if m["metric_id"] == metric and m["period_scope"] == period
    )
    assert value("revenue", "BASE") == "40000000"
    assert value("revenue", "CURRENT") == "48000000"
    assert value("gross_margin", "BASE") == "10.0"
    assert value("gross_margin", "CURRENT") == "8.00"


def test_denied_role_never_sees_private_dashboard_or_evidence(api):
    for role in (None, "MAINTAINER"):
        for path in ("/api/boss/ui/dashboard", "/api/boss/ui/tasks", "/api/boss/ui/meetings",
                     "/api/boss/ui/evidence", "/api/boss/ui/metrics"):
            status, body = api.serve(role, path, "source=finance-note")
            assert status in (401, 403)
            assert "content" not in body


def test_maintenance_only_returns_technical_metadata(api):
    code, payload = api.serve("MAINTAINER", "/api/boss/ui/maintenance")
    assert code == 200
    assert payload["configured_provider"] == "deepseek"
    assert "credential_ref" not in payload
    assert "memory" not in payload
    assert "private_body" not in payload
    assert api.serve("BOSS", "/api/boss/ui/maintenance")[0] == 403


def test_evidence_is_versioned_scoped_and_withdrawn_can_not_be_read(api):
    code, evidence = api.serve("BOSS", "/api/boss/ui/evidence", "source=finance-note")
    assert code == 200
    assert evidence["version"] == "1"
    assert evidence["source_type"] == "SIMULATED"
    assert api.serve("BOSS", "/api/boss/ui/evidence", "source=missing")[0] == 404
    assert api.serve("BOSS", "/api/boss/ui/metrics", "products=other")[0] == 400
    api.store.control("ui-check", "withdraw", {"source_id": "finance-note", "version": "1"})
    assert api.serve("BOSS", "/api/boss/ui/evidence", "source=finance-note")[0] == 410
    assert api.serve("BOSS", "/api/boss/ui/metrics")[0] == 410


def test_paths_fail_closed(api):
    assert api.serve("BOSS", "/api/boss/ui/admin")[0] == 404
    assert api.serve("MAINTAINER", "/api/boss/ui/admin")[0] == 403


def test_actual_model_health_distinguishes_unobserved_from_configured(api):
    status, output = api.serve("BOSS", "/api/boss/ui/model-health")
    assert status == 200
    assert output["runtime_response_observed"] is False
    assert output["provider"] == "NOT_OBSERVED"
    assert output["reported_usage"] is None
    assert output["cost_total"] is None
    assert output["business_task_completed"] is False
    assert api.serve("MAINTAINER", "/api/boss/ui/model-health")[0] == 403
    assert api.serve("BOSS", "/api/boss/ui/model-usage")[0] == 403


def test_real_transport_diagnostics_only_return_whitelisted_usage(api):
    import json
    log_dir = api.store.path.parent / "diagnostics"
    log_dir.mkdir()
    raw_secret = "SYNTHETIC_PRIVATE_SHOULD_NOT_LEAVE_SERVER"
    (log_dir / "http-requests.json").write_text(json.dumps([
        {"type": "request", "model": "deepseek-flash",
         "input": {"messages": [{"content": raw_secret}]}, "at": "2026-10-22T10:00:00Z"},
        {"type": "stream_metadata", "response_id": "id-1", "model": "deepseek-flash",
         "usage": None, "at": "2026-10-22T10:00:02Z"},
        {"type": "stream_metadata", "response_id": "id-1", "model": "deepseek-flash",
         "usage": {"prompt_tokens": 10, "completion_tokens": 6,
                   "total_tokens": 16, "private": raw_secret},
         "finish_reasons": ["stop"], "at": "2026-10-22T10:00:04Z"},
    ]))
    (log_dir / "events.json").write_text(json.dumps([
        {"type": "tool", "name": "query_metrics", "input": {"body": raw_secret}},
        {"type": "tool_error", "error_present": True, "content": raw_secret},
    ]))
    status, boss = api.serve("BOSS", "/api/boss/ui/model-health")
    assert status == 200
    assert boss["runtime_response_observed"] is True
    assert boss["observed_response_count"] == 1
    assert boss["reported_usage"] == {
        "prompt_tokens": 10, "completion_tokens": 6, "total_tokens": 16
    }
    assert boss["cost_total"] is None
    assert "tool_event_count" not in boss
    assert raw_secret not in json.dumps(boss)
    status, admin = api.serve("MAINTAINER", "/api/boss/ui/model-usage")
    assert status == 200
    assert admin["tool_event_count"] == 1
    assert admin["observed_error_count"] == 1
    assert raw_secret not in json.dumps(admin)
