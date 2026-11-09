import sqlite3
import multiprocessing

import pytest
from filelock import FileLock

from agent_artifact_workspace import ArtifactWorkspace
from agent_artifacts import ArtifactPreparation
from agent_recovery_preflight import artifact_state_rows, verify_artifact_files_in_transaction
from agent_recovery_checkpoint import AgentRecoveryCheckpoint
from agent_recovery_preflight import AgentRecoveryPreflight
from agent_simulation_snapshot import AgentSimulationSnapshot
from agent_simulation_recovery import AgentSimulationRecovery
from agent_simulation_recovery_journal import AgentSimulationRecoveryJournal
from controls import ControlStore
from test_agent_artifacts import series_prepared


def run_cleanup_trial(database, directory, trial_id):
    store = ControlStore(database)
    checkpoint = AgentRecoveryCheckpoint(AgentRecoveryPreflight(store))
    snapshots = AgentSimulationSnapshot(checkpoint, directory)
    recovery = AgentSimulationRecovery(snapshots, AgentSimulationRecoveryJournal(snapshots))
    recovery.cleanup_trial(trial_id)


def test_snapshot_artifact_files_match_run_directory(series_prepared, tmp_path):
    store, original, run_id = series_prepared
    root = tmp_path / "mapped-artifacts"
    root.mkdir()
    mapping = ArtifactWorkspace(root.resolve())
    directory = mapping.create(run_id)
    service = ArtifactPreparation.for_run_workspace(store, mapping, run_gate=original.run_gate,
        scope_service=original.scope_service, max_files=3, max_bytes=500000)
    artifact = service.create_meeting_brief(run_id, ["simulation-meeting-material"], request_key="recovery-file", format_name="MARKDOWN")
    checkpoint = AgentRecoveryCheckpoint(AgentRecoveryPreflight(store), allow_migration=True)
    snapshots = AgentSimulationSnapshot(checkpoint, tmp_path, allow_migration=True)
    recovery = AgentSimulationRecovery(snapshots, AgentSimulationRecoveryJournal(snapshots, allow_migration=True))
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        checkpoint_id = checkpoint.capture_in_transaction(db, "file-checkpoint")["checkpoint_id"]
    snapshots.create("file-snapshot", "file-checkpoint", checkpoint_id)
    assert recovery.inspect_artifact_files("file-snapshot", mapping, max_age_seconds=300)["verified_files"] == 1
    copied = recovery.create_artifact_backup("file-snapshot", mapping, max_age_seconds=300)
    assert copied["files"] == 1 and copied["restore_state"] == "BLOCKED"
    assert recovery.inspect_artifact_backup("file-snapshot", mapping, max_age_seconds=300) == copied
    backup_file = tmp_path / (copied["snapshot_name"] + ".artifacts") / run_id / artifact["storage_key"]
    content = backup_file.read_bytes()
    backup_file.unlink()
    with pytest.raises((ValueError, FileNotFoundError)):
        recovery.inspect_artifact_backup("file-snapshot", mapping, max_age_seconds=300)
    backup_file.write_bytes(b"changed")
    with pytest.raises(ValueError):
        recovery.inspect_artifact_backup("file-snapshot", mapping, max_age_seconds=300)
    backup_file.write_bytes(content)
    assert recovery.inspect_artifact_backup("file-snapshot", mapping, max_age_seconds=300) == copied
    trial = recovery.create_cleanup_trial("file-snapshot", mapping, max_age_seconds=300)
    assert trial["files"] == 2 and trial["state"] == "PREPARED"
    interrupted_trial = recovery.create_cleanup_trial("file-snapshot", mapping, max_age_seconds=300)
    with pytest.raises(ValueError, match="缺少实际来源撤销影响"):
        recovery.cleanup_trial(trial["trial_id"])
    snapshot_path = tmp_path / "snapshot.sqlite"
    with store.connect() as source, sqlite3.connect(snapshot_path) as snapshot:
        source.backup(snapshot)
    with sqlite3.connect(snapshot_path) as snapshot:
        snapshot.execute("BEGIN")
        rows = artifact_state_rows(snapshot, "ui-check")
        assert any(record[0] == artifact["artifact_id"] and record[-3:] == (str(directory), artifact["storage_key"], artifact["size_bytes"]) for table, record in rows if table == "agent_artifacts")
        assert verify_artifact_files_in_transaction(snapshot, "ui-check", mapping) == {"verified_files": 1, "revoked_records": 0, "pending_records": 0, "restore_state": "BLOCKED"}
        other = tmp_path / "other"
        other.mkdir()
        other_mapping = ArtifactWorkspace(other.resolve())
        other_mapping.create(run_id)
        with pytest.raises(ValueError, match="目录不一致"):
            verify_artifact_files_in_transaction(snapshot, "ui-check", other_mapping)
        (directory / artifact["storage_key"]).write_bytes(b"changed")
        with pytest.raises(ValueError):
            verify_artifact_files_in_transaction(snapshot, "ui-check", mapping)
    with pytest.raises(ValueError):
        recovery.inspect_artifact_files("file-snapshot", mapping, max_age_seconds=300)
    store.control("ui-check", "withdraw", {"source_id": "simulation-meeting-material", "version": "1"})
    replay = recovery.inspect_withdrawal_replay("file-snapshot")
    assert replay["new_withdrawal_events"] == 1
    assert replay["affected_artifacts"] == 1
    assert replay["database_backup_cleanup"] == replay["artifact_backup_cleanup"] == replay["restore_state"] == "BLOCKED"
    assert recovery.inspect_withdrawal_replay("file-snapshot") == replay
    interrupted_path = tmp_path / "cleanup-trials" / interrupted_trial["trial_id"]
    interrupted_payload = interrupted_path / "payload"
    interrupted_payload.chmod(0o500)
    try:
        failed = multiprocessing.get_context("spawn").Process(target=run_cleanup_trial, args=(store.path, tmp_path, interrupted_trial["trial_id"]))
        failed.start()
        failed.join(30)
        assert failed.exitcode is not None and failed.exitcode != 0
    finally:
        interrupted_payload.chmod(0o700)
    with sqlite3.connect(interrupted_path / "journal.sqlite") as db:
        assert db.execute("SELECT state FROM cleanup_trial").fetchone() == ("CLEANING",)
    assert (interrupted_payload / "database.sqlite").is_file()
    assert not (interrupted_payload / "artifacts" / run_id / artifact["storage_key"]).exists()
    assert recovery.cleanup_trial(interrupted_trial["trial_id"])["state"] == "COMPLETED"
    assert not (interrupted_payload / "database.sqlite").exists()
    with sqlite3.connect(interrupted_path / "journal.sqlite") as db:
        assert db.execute("SELECT state FROM cleanup_trial").fetchone() == ("COMPLETED",)
    trial_path = tmp_path / "cleanup-trials" / trial["trial_id"]
    with FileLock(str(trial_path / "cleanup.lock"), timeout=10):
        process = multiprocessing.get_context("spawn").Process(target=run_cleanup_trial, args=(store.path, tmp_path, trial["trial_id"]))
        process.start()
        process.join(1)
        assert process.is_alive()
        process.terminate()
        process.join(20)
        assert process.exitcode is not None
    with sqlite3.connect(trial_path / "journal.sqlite") as db:
        assert db.execute("SELECT state FROM cleanup_trial").fetchone() == ("PREPARED",)
    cleaned = recovery.cleanup_trial(trial["trial_id"])
    assert cleaned["state"] == "COMPLETED" and cleaned["removed_files"] == 2 and cleaned["restore_state"] == "BLOCKED"
    assert recovery.cleanup_trial(trial["trial_id"]) == cleaned
    assert backup_file.read_bytes() == content
    with pytest.raises(ValueError, match="当前状态已经变化"):
        recovery.inspect_artifact_files("file-snapshot", mapping, max_age_seconds=300)
    with pytest.raises(ValueError, match="当前状态已经变化"):
        recovery.inspect_artifact_backup("file-snapshot", mapping, max_age_seconds=300)
