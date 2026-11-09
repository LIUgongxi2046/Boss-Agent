import sqlite3

import pytest

from agent_artifact_api import artifact_goal_revision_in_transaction
from agent_artifact_goal import AgentArtifactGoal
from agent_artifacts import ArtifactPreparation
from test_agent_run_result import setup_result


def test_legacy_artifact_goal_is_unknown_after_new_input(tmp_path):
    store, runs, results, sink = setup_result(tmp_path, full_sources=True)
    workspace = tmp_path / "artifacts"
    workspace.mkdir()
    runs.configure_file_budget(sink.config.run_id, sink.lease_owner, sink.config.lease_epoch, 1, 200000)
    preparation = ArtifactPreparation(store, workspace, run_gate=sink, scope_service=results.scope, max_files=1, max_bytes=200000)
    artifact = preparation.create_meeting_brief(sink.config.run_id, ["simulation-meeting-material"], request_key="legacy-file", format_name="MARKDOWN")
    with runs.connect() as db:
        db.row_factory = sqlite3.Row
        record = db.execute("SELECT * FROM agent_artifacts WHERE artifact_id=?", (artifact["artifact_id"],)).fetchone()
        db.row_factory = None
        with pytest.raises(ValueError, match="当前事务"):
            artifact_goal_revision_in_transaction(db, record)
        db.execute("BEGIN")
        assert artifact_goal_revision_in_transaction(db, record) is None
    runs.add_input(sink.config.run_id, 1, "new-goal", "补充会议要求")
    with runs.connect() as db:
        db.execute("BEGIN")
        db.row_factory = sqlite3.Row
        record = db.execute("SELECT * FROM agent_artifacts WHERE artifact_id=?", (artifact["artifact_id"],)).fetchone()
        db.row_factory = None
        assert artifact_goal_revision_in_transaction(db, record) is None


def test_created_artifact_preserves_original_goal_revision(tmp_path):
    store, runs, results, sink = setup_result(tmp_path, full_sources=True)
    AgentArtifactGoal(runs, allow_migration=True)
    workspace = tmp_path / "current-artifacts"
    workspace.mkdir()
    runs.configure_file_budget(sink.config.run_id, sink.lease_owner, sink.config.lease_epoch, 1, 200000)
    preparation = ArtifactPreparation(store, workspace, run_gate=sink, scope_service=results.scope, max_files=1, max_bytes=200000)
    artifact = preparation.create_meeting_brief(sink.config.run_id, ["simulation-meeting-material"], request_key="new-file", format_name="MARKDOWN")
    assert preparation.create_meeting_brief(sink.config.run_id, ["simulation-meeting-material"], request_key="new-file", format_name="MARKDOWN") == artifact
    with runs.connect() as db:
        db.execute("BEGIN")
        db.row_factory = sqlite3.Row
        record = db.execute("SELECT * FROM agent_artifacts WHERE artifact_id=?", (artifact["artifact_id"],)).fetchone()
        db.row_factory = None
        assert artifact_goal_revision_in_transaction(db, record) == 1
    runs.add_input(sink.config.run_id, 1, "next-goal", "补充会议要求")
    with runs.connect() as db:
        db.execute("BEGIN")
        db.row_factory = sqlite3.Row
        record = db.execute("SELECT * FROM agent_artifacts WHERE artifact_id=?", (artifact["artifact_id"],)).fetchone()
        db.row_factory = None
        assert artifact_goal_revision_in_transaction(db, record) == 1
