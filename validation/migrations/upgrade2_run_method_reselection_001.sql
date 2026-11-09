CREATE TABLE agent_run_method_reselections (
    run_id TEXT NOT NULL REFERENCES agent_runs(run_id),
    goal_revision INTEGER NOT NULL CHECK(goal_revision > 1),
    request_key TEXT NOT NULL,
    request_digest TEXT NOT NULL,
    input_id TEXT NOT NULL REFERENCES agent_run_inputs(input_id),
    method TEXT NOT NULL,
    method_sha256 TEXT NOT NULL,
    goal_sha256 TEXT NOT NULL,
    scope_sha256 TEXT NOT NULL,
    PRIMARY KEY(run_id, goal_revision),
    UNIQUE(run_id, request_key)
);
CREATE TRIGGER agent_run_method_reselection_no_update BEFORE UPDATE ON agent_run_method_reselections
BEGIN SELECT RAISE(ABORT, 'run method reselection is immutable'); END;
CREATE TRIGGER agent_run_method_reselection_no_delete BEFORE DELETE ON agent_run_method_reselections
BEGIN SELECT RAISE(ABORT, 'run method reselection is immutable'); END;
