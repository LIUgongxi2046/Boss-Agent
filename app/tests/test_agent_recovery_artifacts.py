from uuid import uuid4

import pytest

from agent_recovery_checkpoint import AgentRecoveryCheckpoint
from agent_recovery_preflight import AgentRecoveryPreflight
from agent_simulation_recovery import AgentSimulationRecovery
from agent_simulation_recovery_journal import AgentSimulationRecoveryJournal
from agent_simulation_snapshot import AgentSimulationSnapshot
from test_agent_artifacts import series_prepared


SOURCE = "simulation-meeting-material"


def test_snapshot_before_withdrawal_exposes_artifact_state_change(series_prepared, tmp_path):
    store, service, run_id = series_prepared
    first = service.create_meeting_brief(run_id, [SOURCE], request_key="recovery-artifact-v1", format_name="MARKDOWN")
    second = service.create_meeting_brief(run_id, [SOURCE], request_key="recovery-artifact-v2", format_name="MARKDOWN",
                                         previous_artifact_id=first["artifact_id"], expected_version=1)
    preflight = AgentRecoveryPreflight(store)
    checkpoint = AgentRecoveryCheckpoint(preflight, allow_migration=True)
    snapshots = AgentSimulationSnapshot(checkpoint, tmp_path, allow_migration=True)
    journal = AgentSimulationRecoveryJournal(snapshots, allow_migration=True)
    recovery = AgentSimulationRecovery(snapshots, journal)
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        checkpoint_id = checkpoint.capture_in_transaction(db, "artifact-before")["checkpoint_id"]
    snapshots.create("artifact-before", "artifact-before", checkpoint_id)
    with store.connect() as db:
        document = store.get(db, "ui-check", "document", SOURCE)
    assert store.control("ui-check", "withdraw", {"source_id": SOURCE, "version": document["version"]})["withdrawn"] is True
    delta = recovery.inspect_privacy_delta("artifact-before")
    assert delta["artifact_state_available"] is True
    assert delta["artifact_state_matches_current"] is False
    assert delta["artifact_changed_records"] >= 2
    assert delta["artifact_current_only_records"] >= 2
    assert delta["artifact_snapshot_only_records"] == 0
    assert delta["changed_records"]["document"] >= 1
    assert delta["missing_current_records"]["source_withdrawal_event"] >= 1
    assert delta["source_history_complete"] is False
    assert delta["state_matches_current"] is False
    assert delta["restore_state"] == "BLOCKED"
    assert recovery.inspect_privacy_delta("artifact-before") == delta
    with pytest.raises(ValueError, match="当前状态已经变化"):
        recovery.preflight("artifact-before", max_age_seconds=300)
    with pytest.raises(ValueError, match="本人身份服务"):
        recovery.restore(None, None, "artifact-before", str(uuid4()), max_age_seconds=300)
    assert not (tmp_path / "recovery").exists()


def test_delta_counts_snapshot_only_artifacts_and_revocations_when_current_tables_are_missing(series_prepared, tmp_path):
    store, service, run_id = series_prepared
    first = service.create_meeting_brief(run_id, [SOURCE], request_key="recovery-direction-v1", format_name="MARKDOWN")
    service.create_meeting_brief(run_id, [SOURCE], request_key="recovery-direction-v2", format_name="MARKDOWN",
                                 previous_artifact_id=first["artifact_id"], expected_version=1)
    preflight = AgentRecoveryPreflight(store)
    checkpoint = AgentRecoveryCheckpoint(preflight, allow_migration=True)
    snapshots = AgentSimulationSnapshot(checkpoint, tmp_path, allow_migration=True)
    journal = AgentSimulationRecoveryJournal(snapshots, allow_migration=True)
    recovery = AgentSimulationRecovery(snapshots, journal)
    with store.connect() as db:
        document = store.get(db, "ui-check", "document", SOURCE)
    assert store.control("ui-check", "withdraw", {"source_id": SOURCE, "version": document["version"]})["withdrawn"] is True
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        checkpoint_id = checkpoint.capture_in_transaction(db, "artifact-direction")["checkpoint_id"]
    snapshots.create("artifact-direction", "artifact-direction", checkpoint_id)
    with store.connect() as db:
        db.execute("PRAGMA foreign_keys=OFF")
        for table in ("agent_artifact_publications", "agent_artifact_revocations", "agent_artifact_versions", "agent_artifacts"):
            db.execute("DROP TABLE " + table)
    delta = recovery.inspect_privacy_delta("artifact-direction")
    assert delta["artifact_state_available"] is False
    assert delta["artifact_state_reason"] == "CURRENT_ARTIFACT_TABLES_MISSING"
    assert delta["artifact_state_matches_current"] is False
    assert delta["artifact_changed_records"] == 0
    assert delta["artifact_current_only_records"] == 0
    assert delta["artifact_snapshot_only_records"] >= 6
    assert delta["state_matches_current"] is False
    assert delta["restore_state"] == "BLOCKED"
    with pytest.raises(ValueError, match="当前状态已经变化"):
        recovery.preflight("artifact-direction", max_age_seconds=300)
    with pytest.raises(ValueError, match="本人身份服务"):
        recovery.restore(None, None, "artifact-direction", str(uuid4()), max_age_seconds=300)
    assert not (tmp_path / "recovery").exists()


def test_partial_artifact_tables_are_rejected(series_prepared, tmp_path):
    store, service, run_id = series_prepared
    service.create_meeting_brief(run_id, [SOURCE], request_key="recovery-partial-v1", format_name="MARKDOWN")
    preflight = AgentRecoveryPreflight(store)
    checkpoint = AgentRecoveryCheckpoint(preflight, allow_migration=True)
    snapshots = AgentSimulationSnapshot(checkpoint, tmp_path, allow_migration=True)
    journal = AgentSimulationRecoveryJournal(snapshots, allow_migration=True)
    recovery = AgentSimulationRecovery(snapshots, journal)
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        checkpoint_id = checkpoint.capture_in_transaction(db, "artifact-partial")["checkpoint_id"]
    snapshots.create("artifact-partial", "artifact-partial", checkpoint_id)
    with store.connect() as db:
        db.execute("PRAGMA foreign_keys=OFF")
        db.execute("DROP TABLE agent_artifact_revocations")
    with pytest.raises(ValueError, match="成果状态表不完整"):
        recovery.inspect_privacy_delta("artifact-partial")


def test_snapshot_after_withdrawal_matches_artifact_state_but_restore_stays_blocked(series_prepared, tmp_path):
    store, service, run_id = series_prepared
    first = service.create_meeting_brief(run_id, [SOURCE], request_key="recovery-after-v1", format_name="MARKDOWN")
    service.create_meeting_brief(run_id, [SOURCE], request_key="recovery-after-v2", format_name="MARKDOWN",
                                 previous_artifact_id=first["artifact_id"], expected_version=1)
    preflight = AgentRecoveryPreflight(store)
    checkpoint = AgentRecoveryCheckpoint(preflight, allow_migration=True)
    snapshots = AgentSimulationSnapshot(checkpoint, tmp_path, allow_migration=True)
    journal = AgentSimulationRecoveryJournal(snapshots, allow_migration=True)
    recovery = AgentSimulationRecovery(snapshots, journal)
    with store.connect() as db:
        document = store.get(db, "ui-check", "document", SOURCE)
    assert store.control("ui-check", "withdraw", {"source_id": SOURCE, "version": document["version"]})["withdrawn"] is True
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        checkpoint_id = checkpoint.capture_in_transaction(db, "artifact-after")["checkpoint_id"]
    snapshots.create("artifact-after", "artifact-after", checkpoint_id)
    delta = recovery.inspect_privacy_delta("artifact-after")
    assert delta["artifact_state_available"] is True
    assert delta["artifact_state_matches_current"] is True
    assert delta["artifact_changed_records"] == 0
    assert delta["artifact_current_only_records"] == 0
    assert delta["artifact_snapshot_only_records"] == 0
    checked = recovery.preflight("artifact-after", max_age_seconds=300)
    assert checked["restore_state"] == "BLOCKED"
    assert checked["reason"] == "DELETION_LEDGER_COMPLETENESS_UNVERIFIED"
    assert recovery.preflight("artifact-after", max_age_seconds=300) == checked
    assert recovery.inspect_privacy_delta("artifact-after") == delta
    target_id = str(uuid4())
    assert recovery.journal.record_blocked("artifact-after", target_id, checked) == {"state": "BLOCKED", "created": True}
    assert recovery.journal.inspect_target(target_id) == {"state": "ABSENT", "cleanup": "NONE"}
    with pytest.raises(ValueError, match="本人身份服务"):
        recovery.restore(None, None, "artifact-after", str(uuid4()), max_age_seconds=300)
    assert not (tmp_path / "recovery").exists()
