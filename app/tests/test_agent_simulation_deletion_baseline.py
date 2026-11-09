import json
import sqlite3

import pytest

from agent_run_store import RunStore
from agent_simulation_deletion_baseline import SimulationDeletionBaseline
from agent_recovery_checkpoint import AgentRecoveryCheckpoint
from agent_recovery_preflight import AgentRecoveryPreflight
from agent_simulation_recovery import AgentSimulationRecovery
from agent_simulation_recovery_journal import AgentSimulationRecoveryJournal
from agent_simulation_snapshot import AgentSimulationSnapshot
from controls import ControlStore


@pytest.mark.parametrize("change", ["missing", "altered"])
def test_simulated_baseline_tracks_actual_source_history(tmp_path, change):
    store = ControlStore(tmp_path / "business.sqlite")
    store.initialize("ui-check")
    RunStore(store.path)
    service = SimulationDeletionBaseline(store, allow_migration=True)
    first = service.capture("before-withdrawal")
    assert first["event_count"] == 0 and first["history_complete"] is False
    assert service.capture("before-withdrawal")["baseline_id"] == first["baseline_id"]
    store.control("ui-check", "withdraw", {"source_id": "finance-note", "version": "1"})
    assert service.inspect(first["baseline_id"])["new_events"] == 1
    with pytest.raises(ValueError, match="内容已经变化"):
        service.capture("before-withdrawal")
    second = service.capture("after-withdrawal")
    assert second["event_count"] == 1 and service.inspect(second["baseline_id"])["new_events"] == 0
    assert service.capture("after-withdrawal")["created"] is False
    with store.connect() as db:
        row = db.execute("SELECT id,body FROM objects WHERE namespace=? AND kind='source_withdrawal_event'", ("ui-check",)).fetchone()
        if change == "missing":
            db.execute("DELETE FROM objects WHERE namespace=? AND kind='source_withdrawal_event' AND id=?", ("ui-check", row[0]))
        else:
            event = json.loads(row[1])
            event["inspection_change"] = "changed"
            db.execute("UPDATE objects SET body=? WHERE namespace=? AND kind='source_withdrawal_event' AND id=?", (json.dumps(event, sort_keys=True, separators=(",", ":")), "ui-check", row[0]))
    with pytest.raises(ValueError):
        service.inspect(second["baseline_id"])
    with pytest.raises(ValueError):
        service.capture("after-change")


def test_baseline_migration_objects_are_immutable(tmp_path):
    store = ControlStore(tmp_path / "business.sqlite")
    store.initialize("ui-check")
    RunStore(store.path)
    service = SimulationDeletionBaseline(store, allow_migration=True)
    baseline = service.capture("immutable")
    with store.connect() as db, pytest.raises(sqlite3.IntegrityError, match="immutable baseline"):
        db.execute("DELETE FROM agent_simulation_deletion_baselines WHERE baseline_id=?", (baseline["baseline_id"],))
    assert service.inspect(baseline["baseline_id"])["restore_state"] == "BLOCKED"


def test_baseline_bound_to_simulated_snapshot_and_preflight(tmp_path):
    store = ControlStore(tmp_path / "business.sqlite")
    store.initialize("ui-check")
    RunStore(store.path)
    checkpoint = AgentRecoveryCheckpoint(AgentRecoveryPreflight(store), allow_migration=True)
    snapshots = AgentSimulationSnapshot(checkpoint, tmp_path, allow_migration=True)
    recovery = AgentSimulationRecovery(snapshots, AgentSimulationRecoveryJournal(snapshots, allow_migration=True))
    baseline_service = SimulationDeletionBaseline(store, allow_migration=True)
    baseline = baseline_service.capture("baseline")
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        checkpoint_id = checkpoint.capture_in_transaction(db, "checkpoint")["checkpoint_id"]
    snapshots.create("snapshot", "checkpoint", checkpoint_id)
    with pytest.raises(ValueError, match="关联不符"):
        recovery.preflight("snapshot", max_age_seconds=300, baseline_id=baseline["baseline_id"])
    assert baseline_service.bind_snapshot(snapshots, "snapshot", baseline["baseline_id"])["created"] is True
    assert baseline_service.bind_snapshot(snapshots, "snapshot", baseline["baseline_id"])["created"] is False
    checked = recovery.preflight("snapshot", max_age_seconds=300, baseline_id=baseline["baseline_id"])
    assert checked["deletion_baseline"]["new_events"] == 0 and checked["restore_state"] == "BLOCKED"
    store.control("ui-check", "withdraw", {"source_id": "finance-note", "version": "1"})
    with pytest.raises(ValueError, match="删除事件"):
        recovery.preflight("snapshot", max_age_seconds=300, baseline_id=baseline["baseline_id"])


@pytest.mark.parametrize("change", ["missing", "altered"])
def test_snapshot_event_tampering_is_rejected(tmp_path, change):
    store = ControlStore(tmp_path / "business.sqlite")
    store.initialize("ui-check")
    RunStore(store.path)
    store.control("ui-check", "withdraw", {"source_id": "finance-note", "version": "1"})
    checkpoint = AgentRecoveryCheckpoint(AgentRecoveryPreflight(store), allow_migration=True)
    snapshots = AgentSimulationSnapshot(checkpoint, tmp_path, allow_migration=True)
    baseline_service = SimulationDeletionBaseline(store, allow_migration=True)
    baseline = baseline_service.capture("baseline")
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        checkpoint_id = checkpoint.capture_in_transaction(db, "checkpoint")["checkpoint_id"]
    saved = snapshots.create("snapshot", "checkpoint", checkpoint_id)
    with sqlite3.connect(tmp_path / saved["snapshot_name"]) as db:
        if change == "missing":
            db.execute("DELETE FROM objects WHERE namespace=? AND kind='source_withdrawal_event'", ("ui-check",))
        else:
            row = db.execute("SELECT id,body FROM objects WHERE namespace=? AND kind='source_withdrawal_event'", ("ui-check",)).fetchone()
            event = json.loads(row[1])
            event["inspection_change"] = "changed"
            db.execute("UPDATE objects SET body=? WHERE namespace=? AND kind='source_withdrawal_event' AND id=?", (json.dumps(event), "ui-check", row[0]))
    with pytest.raises(ValueError, match="快照摘要不符"):
        baseline_service.bind_snapshot(snapshots, "snapshot", baseline["baseline_id"])


def test_snapshot_before_baseline_cannot_be_bound(tmp_path):
    store = ControlStore(tmp_path / "business.sqlite")
    store.initialize("ui-check")
    RunStore(store.path)
    checkpoint = AgentRecoveryCheckpoint(AgentRecoveryPreflight(store), allow_migration=True)
    snapshots = AgentSimulationSnapshot(checkpoint, tmp_path, allow_migration=True)
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        checkpoint_id = checkpoint.capture_in_transaction(db, "old-checkpoint")["checkpoint_id"]
    snapshots.create("old-snapshot", "old-checkpoint", checkpoint_id)
    baseline_service = SimulationDeletionBaseline(store, allow_migration=True)
    baseline = baseline_service.capture("later-baseline")
    with pytest.raises((ValueError, sqlite3.OperationalError)):
        baseline_service.bind_snapshot(snapshots, "old-snapshot", baseline["baseline_id"])
