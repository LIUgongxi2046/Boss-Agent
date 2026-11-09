import asyncio
import hashlib
import sqlite3
import sys
from dataclasses import replace
from pathlib import Path

import pytest
from aiohttp import web

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "validation"))
from boss_comprehensive_simulation import populate
from boss_supply_quality import SupplyQualityAPI
from controls import ControlStore
from hermes_business_tools import HermesBusinessTools, ReceiptBinding
from hermes_bridge import EngineEventSink, EngineRunConfig
from agent_run_store import RunStore
from sop_write_tools.fc01 import Fc01Context, content_digest


def database_digest(path):
    with sqlite3.connect(path) as db:
        return hashlib.sha256("\n".join(db.iterdump()).encode()).hexdigest()


def test_preparation_receipt_and_scope_on_independent_simulated_store(tmp_path):
    path = tmp_path / "business.sqlite"
    store = ControlStore(path)
    store.initialize("ui-check")
    populate(store, "2026-10-28T10:00:00+08:00")
    view = SupplyQualityAPI(store).read("BOSS", "SI10")
    origin = view["events"][0]
    params = {"interface_id": "SI10", "origin_entity_type": origin["entity_type"], "origin_record_id": origin["record_id"], "origin_version": origin["version"], "review_sha256": view["review_sha256"], "purpose": "核查品质事件并提交当前依据", "coordinator_id": "coordinator-1", "due_at": "2026-10-30T17:00:00+08:00", "timezone": "Asia/Shanghai", "evidence_requirements": ["专业核查记录"]}
    current = [Fc01Context("BOSS", "boss-1", "ui-check", "selection", "1", "u2-request-001", "u2-session-001", frozenset({"bossSupplyQualityPrepare"}), True, frozenset({("bossSupplyQualityPrepare", content_digest(params))}), ())]
    receipt = ReceiptBinding("boss.assignment.send", "COMPREHENSIVE-20261028-1-send-0")
    run_store = RunStore(tmp_path / "runs.sqlite")
    run_id = run_store.create_run("boss-1", "ui-check", "request-1", "digest-1")
    lease = run_store.acquire_lease(run_id, 0, "worker-1", 60)
    run_store.transition(run_id, run_store.read_run(run_id)["revision"], "RUNNING", "worker-1", lease["epoch"])
    config = EngineRunConfig(run_id, lease["epoch"], "903230b1e23e0c496b28e5d2e8c4f2639cd506b6", "http://127.0.0.1:1234", 3)
    gate = EngineEventSink(run_store, config, "worker-1")
    tools = HermesBusinessTools(store, lambda: current[0], lambda: params, lambda: receipt, run_gate=gate)
    before = database_digest(path)
    prepared = asyncio.run(tools.prepare())
    assert prepared["source_refs"] and prepared["owner_decision_required"]
    assert prepared["business_authority_granted"] is False
    found = tools.receipt()
    assert found["outcome"] == "RECORDED" and found["write_performed_by_lookup"] is False
    assert tools.receipt()["result"] == found["result"]
    absent = HermesBusinessTools(store, lambda: current[0], lambda: params, lambda: ReceiptBinding("boss.assignment.send", "unmatched-request-001"), run_gate=gate)
    unknown = absent.receipt()
    assert unknown["outcome"] == "NOT_FOUND_IN_CURRENT_STORE"
    assert unknown["not_proof_of_failed_delivery"] is True
    assert "safe_same_key_retry" not in unknown
    altered = HermesBusinessTools(store, lambda: current[0], lambda: {**params, "purpose": "修改内容"}, lambda: receipt, run_gate=gate)
    with pytest.raises(web.HTTPForbidden):
        asyncio.run(altered.prepare())
    denied = HermesBusinessTools(store, lambda: current[0], lambda: params, lambda: ReceiptBinding("boss.assignment.create", receipt.client_request_id), run_gate=gate)
    with pytest.raises(web.HTTPForbidden):
        denied.receipt()
    current[0] = replace(current[0], role="MAINTAINER")
    with pytest.raises(web.HTTPForbidden):
        asyncio.run(tools.prepare())
    with pytest.raises(web.HTTPForbidden):
        tools.receipt()
    current[0] = replace(current[0], role="BOSS")
    def cancel_during_prepare():
        run_store.cancel(run_id, run_store.read_run(run_id)["revision"])
        return params

    inflight = HermesBusinessTools(store, lambda: current[0], cancel_during_prepare, lambda: receipt, run_gate=gate)
    with pytest.raises(ValueError):
        asyncio.run(inflight.prepare())
    with pytest.raises(ValueError):
        asyncio.run(tools.prepare())
    with pytest.raises(ValueError):
        tools.receipt()
    assert database_digest(path) == before
