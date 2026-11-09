import multiprocessing
import os
import sqlite3

import pytest

from agent_plan_handover import AgentPlanHandover
from agent_run_store import RunStore
from agent_schedule_occurrence_gate import AgentScheduleOccurrenceGate
from business import checksum
from controls import ControlStore
from hermes_schedule_adapter import HermesScheduleAdapter


def interrupted_handover(path):
    store = ControlStore(path)
    handover = AgentPlanHandover(store)
    db = store.connect()
    db.execute("BEGIN IMMEDIATE")
    handover.capture_in_transaction(db, "interrupted")
    os._exit(17)


def test_plan_handover_captures_disabled_scope_and_detects_changes(tmp_path):
    store = ControlStore(tmp_path / "business.sqlite")
    store.initialize("ui-check")
    RunStore(store.path)
    handover = AgentPlanHandover(store, allow_migration=True)
    with store.connect() as db:
        initial = store.get(db, "ui-check", "initial", "snapshot")
        event = {"event_id": "technical-event", "version": "1", "owner_plan_id": "technical-plan", "state": "PENDING"}
        plan = {"plan_id": "technical-plan", "version": "1", "owner_id": initial["owner_id"], "source_type": "SIMULATED",
                "state": "PAUSED", "event_ids": ["technical-event"], "event_versions": {"technical-event": "1"}}
        store.put(db, "ui-check", "event", "technical-event", event)
        store.put(db, "ui-check", "owner_plan", "technical-plan", plan)
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        result = handover.capture_in_transaction(db, "handover")
        assert result["created"] is True
        manifest = result["manifest"]
        assert manifest["plan_count"] == 1 and manifest["activation"] == "DISABLED"
        assert {"PLAN_AUTHORIZATION_MISSING", "STOP_CONDITIONS_MISSING", "PLAN_BUDGET_MISSING_OR_INVALID", "OLD_DRIVER_STOP_UNVERIFIED", "UNIQUE_SCHEDULER_LEASE_UNVERIFIED"}.issubset(manifest["conditions"])
        assert handover.capture_in_transaction(db, "handover")["created"] is False
    reopened = AgentPlanHandover(ControlStore(store.path))
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        assert reopened.capture_in_transaction(db, "handover")["source_digest"] == result["source_digest"]
        event["version"] = "2"
        store.put(db, "ui-check", "event", "technical-event", event)
        with pytest.raises(ValueError, match="事件版本已经变化"):
            reopened.capture_in_transaction(db, "handover")
        db.rollback()
    with store.connect() as db:
        assert store.get(db, "ui-check", "owner_plan", "technical-plan") == plan
        assert db.execute("SELECT count(*) FROM agent_plan_handovers").fetchone() == (1,)


def test_interrupted_handover_remains_uncommitted(tmp_path):
    store = ControlStore(tmp_path / "business.sqlite")
    store.initialize("ui-check")
    RunStore(store.path)
    handover = AgentPlanHandover(store, allow_migration=True)
    process = multiprocessing.get_context("spawn").Process(target=interrupted_handover, args=(store.path,))
    process.start()
    try:
        process.join(timeout=60)
        assert process.exitcode == 17
    finally:
        if process.is_alive():
            process.terminate()
            process.join(timeout=10)
            assert not process.is_alive()
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        assert db.execute("SELECT count(*) FROM agent_plan_handovers").fetchone() == (0,)
        result = handover.capture_in_transaction(db, "interrupted")
        assert result["manifest"]["plan_count"] == 0
        assert result["manifest"]["activation"] == "DISABLED"
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("DELETE FROM agent_plan_handovers")


def test_existing_schedule_projection_is_included_in_handover(tmp_path):
    store = ControlStore(tmp_path / "business.sqlite")
    store.initialize("ui-check")
    RunStore(store.path)
    HermesScheduleAdapter(store).install_schema()
    handover = AgentPlanHandover(store, allow_migration=True)
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        result = handover.capture_in_transaction(db, "with-schedule")
        assert "HERMES_SCHEDULE_NOT_INSTALLED" not in result["manifest"]["conditions"]
        assert result["manifest"]["activation"] == "DISABLED"
        assert db.execute("SELECT count(*) FROM hermes_schedule_plan_candidates").fetchone() == (0,)
        tables = ("hermes_schedule_observations", "hermes_schedule_plan_candidates", "hermes_schedule_run_links", "hermes_schedule_notification_links", "hermes_schedule_run_budgets")
        projections = [[table, db.execute("SELECT * FROM " + table + " ORDER BY rowid").fetchall()] for table in tables]
        assert result["manifest"]["projection_sha256"] == checksum(projections)
        assert "OCCURRENCE_GATE_NOT_INSTALLED" in result["manifest"]["conditions"]
    AgentScheduleOccurrenceGate(store, allow_migration=True)
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        with pytest.raises(ValueError, match="原资料已经变化"):
            handover.capture_in_transaction(db, "with-schedule")
        updated = handover.capture_in_transaction(db, "with-occurrence-gate")
        projections.append(["agent_schedule_occurrence_gate", db.execute("SELECT * FROM agent_schedule_occurrence_gate WHERE namespace=? ORDER BY rowid", ("ui-check",)).fetchall()])
        assert updated["manifest"]["projection_sha256"] == checksum(projections)
        assert "OCCURRENCE_GATE_NOT_INSTALLED" not in updated["manifest"]["conditions"]
        assert handover.capture_in_transaction(db, "with-occurrence-gate")["created"] is False
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute("UPDATE agent_schema_migrations SET sha256=? WHERE version=?", ("invalid", "upgrade2_schedule_occurrence_gate_001"))
        with pytest.raises(ValueError, match="门禁迁移摘要"):
            handover.capture_in_transaction(db, "invalid-migration")
        db.rollback()
