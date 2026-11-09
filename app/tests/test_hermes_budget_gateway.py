from concurrent.futures import ThreadPoolExecutor
import asyncio
import secrets
import socket
import sqlite3
import sys
from pathlib import Path

import pytest
import httpx
from aiohttp import web

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "validation"))
from agent_run_store import RunStore
from hermes_bridge import EngineEventSink, EngineRunConfig
from hermes_budget_gateway import BudgetStore, ProviderGateway, RunBoundBudgetStore
from hermes_runtime_transport import record_vm_usage_if_current


@pytest.mark.parametrize("state", ["RUNNING", "CANCEL_REQUESTED", "RELEASED"])
def test_vm_usage_snapshot_preserves_unknown_and_respects_lease(tmp_path, state):
    store = RunStore(tmp_path / "runs.sqlite")
    run_id = store.create_run("boss-1", "space-1", "vm-usage", "digest")
    lease = store.acquire_lease(run_id, 0, "worker", 60)
    store.transition(run_id, lease["revision"], "RUNNING", "worker", lease["epoch"])
    config = EngineRunConfig(run_id, lease["epoch"], "903230b1e23e0c496b28e5d2e8c4f2639cd506b6", "http://127.0.0.1:1234", 1)
    sink = EngineEventSink(store, config, "worker")
    budget = RunBoundBudgetStore(sink, allow_migration=True)
    budget.reserve()
    if state == "CANCEL_REQUESTED":
        store.cancel(run_id, store.read_run(run_id)["revision"])
    elif state == "RELEASED":
        store.release_lease(run_id, "worker", lease["epoch"])
    result = record_vm_usage_if_current(sink, budget)
    if state == "RELEASED":
        assert result is None
    else:
        assert result["payload"]["snapshot_final"] is False
        assert result["payload"]["requests_used"] == 1
        assert result["payload"]["total_tokens"] is None
        assert record_vm_usage_if_current(sink, budget) == result


def test_offline_gateway_rejects_before_budget_reservation(tmp_path):
    async def exercise():
        store = BudgetStore(tmp_path / "budget.sqlite", "technical-run", 1)
        capability = secrets.token_urlsafe(32)
        gateway = ProviderGateway(store, capability, None, offline=True)
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        listener.setblocking(False)
        endpoint = "http://127.0.0.1:" + str(listener.getsockname()[1]) + "/chat/completions"
        runner = web.AppRunner(gateway.application())
        await runner.setup()
        await web.SockSite(runner, listener).start()
        try:
            async with httpx.AsyncClient(trust_env=False) as client:
                assert (await client.post(endpoint, json={})).status_code == 401
                response = await client.post(endpoint, json={"model": "deepseek-flash"}, headers={"Authorization": "Bearer " + capability})
                assert response.status_code == 503 and response.text == "模型入口离线不可用"
            assert store.usage_report()["requests_used"] == 0
            with sqlite3.connect(store.path) as db:
                assert db.execute("SELECT count(*) FROM requests").fetchone() == (0,)
        finally:
            gateway.close()
            await runner.cleanup()
            listener.close()

    asyncio.run(exercise())


def test_reservation_survives_reopen_and_preserves_unknown(tmp_path):
    path = tmp_path / "budget.sqlite"
    first = BudgetStore(path, "run-a", 1)
    second = BudgetStore(path, "run-a", 1)
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(store.reserve) for store in (first, second)]
        results = [future.exception() for future in futures]
    assert sum(error is None for error in results) == 1
    assert sum(isinstance(error, web.HTTPTooManyRequests) for error in results) == 1
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT state,usage FROM requests").fetchall() == [("UNKNOWN", None)]
    reopened = BudgetStore(path, "run-a", 1)
    with pytest.raises(web.HTTPTooManyRequests):
        reopened.reserve()
    with pytest.raises(ValueError):
        BudgetStore(path, "run-a", 2)
    report = reopened.usage_report()
    assert report["requests_used"] == 1
    assert report["known_total_tokens"] == 0
    assert report["total_tokens"] is None
    assert report["cost"] is None


def test_usage_report_counts_each_completed_request(tmp_path):
    store = BudgetStore(tmp_path / "tokens.sqlite", "run-b", 3)
    first, second = store.reserve(), store.reserve()
    store.complete(first, {"total_tokens": 4866})
    store.complete(second, {"total_tokens": 5039})
    report = store.usage_report()
    assert report["requests_used"] == 2
    assert report["total_tokens"] == 9905
    assert report["cost"] is None


def test_parent_and_child_share_budget_and_parent_cancellation_blocks_requests(tmp_path):
    store = RunStore(tmp_path / "runs.sqlite")
    parent = store.create_run("boss-1", "space-1", "parent", "parent-digest")
    parent_lease = store.acquire_lease(parent, 0, "parent-worker", 60)
    store.transition(parent, store.read_run(parent)["revision"], "RUNNING", "parent-worker", parent_lease["epoch"])
    child = store.create_child_run(parent, "parent-worker", parent_lease["epoch"], "child", "child-digest")
    child_lease = store.acquire_lease(child, 0, "child-worker", 60)
    store.transition(child, store.read_run(child)["revision"], "RUNNING", "child-worker", child_lease["epoch"])

    def budget(run_id, lease, owner):
        config = EngineRunConfig(run_id, lease["epoch"], "903230b1e23e0c496b28e5d2e8c4f2639cd506b6", "http://127.0.0.1:1234", 2)
        return RunBoundBudgetStore(EngineEventSink(store, config, owner), allow_migration=run_id == parent)

    parent_budget = budget(parent, parent_lease, "parent-worker")
    child_budget = budget(child, child_lease, "child-worker")
    with ThreadPoolExecutor(max_workers=2) as executor:
        requests = list(executor.map(lambda item: item.reserve(), (parent_budget, child_budget)))
    assert len(set(requests)) == 2
    assert child_budget.usage_report()["run_id"] == parent
    assert parent_budget.usage_report()["requests_used"] == 2
    with pytest.raises(web.HTTPTooManyRequests):
        child_budget.reserve()
    store.cancel(parent, store.read_run(parent)["revision"])
    with pytest.raises(ValueError):
        parent_budget.reserve()
    with pytest.raises(ValueError):
        child_budget.reserve()
    assert parent_budget.usage_report()["requests_used"] == 2


def test_run_budget_refuses_lost_lease(tmp_path):
    store = RunStore(tmp_path / "runs.sqlite")
    run_id = store.create_run("boss-1", "space-1", "lease", "lease-digest")
    lease = store.acquire_lease(run_id, 0, "worker", 60)
    store.transition(run_id, store.read_run(run_id)["revision"], "RUNNING", "worker", lease["epoch"])
    config = EngineRunConfig(run_id, lease["epoch"], "903230b1e23e0c496b28e5d2e8c4f2639cd506b6", "http://127.0.0.1:1234", 1)
    budget = RunBoundBudgetStore(EngineEventSink(store, config, "worker"), allow_migration=True)
    store.release_lease(run_id, "worker", lease["epoch"])
    with pytest.raises(ValueError):
        budget.reserve()
    assert budget.usage_report()["requests_used"] == 0


def test_versioned_budget_migration_and_reopen(tmp_path):
    path = tmp_path / "runs.sqlite"
    store = RunStore(path)
    run_id = store.create_run("boss-1", "space-1", "migration", "digest")
    lease = store.acquire_lease(run_id, 0, "worker", 60)
    store.transition(run_id, store.read_run(run_id)["revision"], "RUNNING", "worker", lease["epoch"])
    config = EngineRunConfig(run_id, lease["epoch"], "903230b1e23e0c496b28e5d2e8c4f2639cd506b6", "http://127.0.0.1:1234", 1)
    sink = EngineEventSink(store, config, "worker")
    with pytest.raises(ValueError, match="迁移"):
        RunBoundBudgetStore(sink)
    budget = RunBoundBudgetStore(sink, allow_migration=True)
    request_id = budget.reserve()
    reopened = RunBoundBudgetStore(EngineEventSink(RunStore(path, allow_migration=False), config, "worker"))
    assert reopened.usage_report()["requests_used"] == 1
    assert reopened.usage_report()["total_tokens"] is None
    with pytest.raises(web.HTTPTooManyRequests):
        reopened.reserve()
    reopened.complete(request_id, None)
    assert budget.usage_report()["requests"][0]["state"] == "COMPLETED"
    assert budget.usage_report()["total_tokens"] is None
    with store.connect() as db:
        db.execute("UPDATE agent_schema_migrations SET sha256='invalid' WHERE version='hermes_budget_001'")
    with pytest.raises(ValueError, match="摘要"):
        RunBoundBudgetStore(sink)


def test_usage_report_marks_unknown_usage_and_blocks_at_request_limit(tmp_path):
    store = BudgetStore(tmp_path / "q06.sqlite", "run-q06", 2)
    first = store.reserve()
    store.complete(first, None)
    report = store.usage_report()
    assert report["requests_used"] == 1
    assert report["remaining_requests"] == 1
    assert report["request_limit_reached"] is False
    assert report["known_requests"] == 0
    assert report["unknown_requests"] == 1
    assert report["usage_state"] == "UNKNOWN"
    assert report["total_tokens"] is None
    assert report["cost"] is None and report["cost_state"] == "UNKNOWN"
    second = store.reserve()
    store.complete(second, {"total_tokens": 7})
    report = store.usage_report()
    assert report["requests_used"] == 2
    assert report["remaining_requests"] == 0
    assert report["request_limit_reached"] is True
    assert report["known_requests"] == 1
    assert report["unknown_requests"] == 1
    assert report["usage_state"] == "PARTIAL"
    assert report["total_tokens"] is None
    assert report["known_total_tokens"] == 7
    assert report["requests"][0]["usage_state"] == "UNKNOWN"
    assert report["requests"][1]["usage_state"] == "KNOWN"
    with pytest.raises(web.HTTPTooManyRequests):
        store.reserve()
