CREATE TABLE agent_run_method_selections (
    run_id TEXT PRIMARY KEY REFERENCES agent_runs(run_id),
    goal_revision INTEGER NOT NULL CHECK(goal_revision = 1),
    method TEXT NOT NULL,
    method_sha256 TEXT NOT NULL,
    goal_sha256 TEXT NOT NULL,
    scope_sha256 TEXT NOT NULL
);
CREATE TRIGGER agent_run_method_selection_no_update BEFORE UPDATE ON agent_run_method_selections
BEGIN SELECT RAISE(ABORT, 'run method selection is immutable'); END;
CREATE TRIGGER agent_run_method_selection_no_delete BEFORE DELETE ON agent_run_method_selections
BEGIN SELECT RAISE(ABORT, 'run method selection is immutable'); END;
