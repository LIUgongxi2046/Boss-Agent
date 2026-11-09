CREATE TABLE agent_run_object_scopes (
    run_id TEXT NOT NULL REFERENCES agent_runs(run_id),
    goal_revision INTEGER NOT NULL CHECK(goal_revision > 0),
    request_key TEXT NOT NULL,
    request_digest TEXT NOT NULL,
    goal_sha256 TEXT NOT NULL,
    source_scope_sha256 TEXT NOT NULL,
    objects TEXT NOT NULL,
    objects_sha256 TEXT NOT NULL,
    PRIMARY KEY(run_id, goal_revision),
    UNIQUE(run_id, request_key)
);
CREATE TRIGGER agent_run_object_scope_no_update BEFORE UPDATE ON agent_run_object_scopes
BEGIN SELECT RAISE(ABORT, 'run object scope is immutable'); END;
CREATE TRIGGER agent_run_object_scope_no_delete BEFORE DELETE ON agent_run_object_scopes
BEGIN SELECT RAISE(ABORT, 'run object scope is immutable'); END;
