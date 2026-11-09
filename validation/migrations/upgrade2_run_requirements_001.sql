CREATE TABLE agent_run_requirements (
    run_id TEXT NOT NULL REFERENCES agent_runs(run_id),
    goal_revision INTEGER NOT NULL CHECK(goal_revision > 0),
    request_key TEXT NOT NULL,
    required_outputs TEXT NOT NULL,
    requirements_sha256 TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY(run_id, goal_revision)
);
CREATE TRIGGER agent_run_requirements_no_update BEFORE UPDATE ON agent_run_requirements
BEGIN SELECT RAISE(ABORT, 'run requirements are immutable'); END;
CREATE TRIGGER agent_run_requirements_no_delete BEFORE DELETE ON agent_run_requirements
BEGIN SELECT RAISE(ABORT, 'run requirements are immutable'); END;
