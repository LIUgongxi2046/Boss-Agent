CREATE TABLE agent_artifact_goals (
    artifact_id TEXT PRIMARY KEY REFERENCES agent_artifacts(artifact_id),
    run_id TEXT NOT NULL REFERENCES agent_runs(run_id),
    goal_revision INTEGER NOT NULL CHECK(goal_revision > 0),
    goal_sha256 TEXT NOT NULL,
    scope_sha256 TEXT NOT NULL,
    event_id TEXT NOT NULL REFERENCES agent_run_events(event_id)
);
CREATE TRIGGER agent_artifact_goal_no_update BEFORE UPDATE ON agent_artifact_goals
BEGIN SELECT RAISE(ABORT, 'artifact goal is immutable'); END;
CREATE TRIGGER agent_artifact_goal_no_delete BEFORE DELETE ON agent_artifact_goals
BEGIN SELECT RAISE(ABORT, 'artifact goal is immutable'); END;
