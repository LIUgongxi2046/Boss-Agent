import sqlite3

from agent_artifact_api import artifact_goal_revision_in_transaction
from agent_artifact_goal import AgentArtifactGoal
from agent_artifacts import ArtifactPreparation
from agent_simulation_migration_install import install_simulation_migrations
from test_agent_run_result import setup_result


def test_installer_preserves_old_artifact_and_records_new_goal(tmp_path):
    store, runs, results, sink = setup_result(tmp_path, full_sources=True)
    workspace = tmp_path / "artifacts"
    workspace.mkdir()
    runs.configure_file_budget(sink.config.run_id, sink.lease_owner, sink.config.lease_epoch, 2, 400000)
    preparation = ArtifactPreparation(store, workspace, run_gate=sink, scope_service=results.scope, max_files=2, max_bytes=400000)
    old = preparation.create_meeting_brief(sink.config.run_id, ["simulation-meeting-material"], request_key="before-install", format_name="MARKDOWN")
    installed = install_simulation_migrations(store.path)
    assert "upgrade2_artifact_goal_001" in installed["installed"]
    assert install_simulation_migrations(store.path)["installed"] == []
    AgentArtifactGoal(runs)
    new = preparation.create_meeting_brief(sink.config.run_id, ["simulation-meeting-material"], request_key="after-install", format_name="MARKDOWN")
    assert preparation.create_meeting_brief(sink.config.run_id, ["simulation-meeting-material"], request_key="after-install", format_name="MARKDOWN") == new
    with runs.connect() as db:
        db.execute("BEGIN")
        db.row_factory = sqlite3.Row
        old_record = db.execute("SELECT * FROM agent_artifacts WHERE artifact_id=?", (old["artifact_id"],)).fetchone()
        new_record = db.execute("SELECT * FROM agent_artifacts WHERE artifact_id=?", (new["artifact_id"],)).fetchone()
        db.row_factory = None
        assert artifact_goal_revision_in_transaction(db, old_record) is None
        assert artifact_goal_revision_in_transaction(db, new_record) == 1
