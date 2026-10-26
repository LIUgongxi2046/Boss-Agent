import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "validation"))

from business import now
from boss_v7_runs import read_runs
from controls import ControlStore


@pytest.fixture
def store(tmp_path):
    result = ControlStore(tmp_path / "authorization-summary.sqlite")
    result.initialize("ui-check")
    return result


def insert(store, *, task=True, authorization=True, source_state="CURRENT"):
    with store.connect() as db:
        if task:
            store.put(db, "ui-check", "task", "task-1", {
                "task_id": "task-1", "version": "1", "purpose": "核查当前交办",
                "status": "OPEN", "source_reference_state": source_state,
            })
        if authorization:
            store.put(db, "ui-check", "authorization", "auth-1", {
                "authorization_id": "auth-1", "action": "complete_assignment",
                "target_id": "task-1", "payload": {"task_id": "task-1"},
                "valid_until": (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
                "revoked": False, "version": "1",
            })
        store.put(db, "ui-check", "runtime_run", "run-1", {
            "run_id": "run-1", "namespace": "ui-check", "dataset_id": "selection",
            "status": "SUCCEEDED", "started_at": now(), "finished_at": now(),
            "stop_reason": None, "goal": "核查当前交办",
            "runtime": {"provider": "deepseek", "model_id": "deepseek-flash"},
            "model_requests": [], "tool_results": [], "tool_errors": [],
            "owner_task_links": [{"task_id": "task-1"}] if task else [],
            "conversation_context": {},
        })


def read(store):
    with store.connect() as db:
        snapshot = store.get(db, "ui-check", "initial", "snapshot")
        return read_runs(store, db, snapshot)


def test_valid_authorization_is_reported_for_bound_task(store):
    insert(store)
    summary = read(store)[0]["authorization_summary"]
    assert summary["state"] == "AUTHORIZED"
    assert summary["coverage"] == "COMPLETE"
    assert summary["target_label"] == "task-1 · 核查当前交办"
    assert summary["waiting_inputs"] == []


def test_revoked_authorization_and_stale_source_need_input(store):
    insert(store, authorization=False, source_state="NEEDS_REVIEW")
    summary = read(store)[0]["authorization_summary"]
    assert summary["state"] == "MISSING_AUTHORIZATION"
    assert summary["coverage"] == "PARTIAL"
    assert "缺少本人对当前动作的有效授权" in summary["waiting_inputs"]
    assert "当前依据需要重新核查" in summary["waiting_inputs"]


def test_run_without_bound_task_has_no_authorization_summary(store):
    insert(store, task=False, authorization=False)
    assert read(store)[0]["authorization_summary"] is None
