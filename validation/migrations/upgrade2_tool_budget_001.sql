CREATE TABLE agent_tool_budgets (
    root_run_id TEXT PRIMARY KEY REFERENCES agent_runs(run_id),
    max_tools INTEGER NOT NULL CHECK(max_tools > 0)
);
CREATE TABLE agent_tool_reservations (
    run_id TEXT NOT NULL REFERENCES agent_runs(run_id),
    request_key TEXT NOT NULL,
    root_run_id TEXT NOT NULL REFERENCES agent_tool_budgets(root_run_id),
    request_digest TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    lease_epoch INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY(run_id, request_key)
);
CREATE TRIGGER agent_tool_budget_no_update BEFORE UPDATE ON agent_tool_budgets
BEGIN SELECT RAISE(ABORT, 'tool budget is immutable'); END;
CREATE TRIGGER agent_tool_budget_no_delete BEFORE DELETE ON agent_tool_budgets
BEGIN SELECT RAISE(ABORT, 'tool budget is immutable'); END;
CREATE TRIGGER agent_tool_reservation_no_update BEFORE UPDATE ON agent_tool_reservations
BEGIN SELECT RAISE(ABORT, 'tool reservation is immutable'); END;
CREATE TRIGGER agent_tool_reservation_no_delete BEFORE DELETE ON agent_tool_reservations
BEGIN SELECT RAISE(ABORT, 'tool reservation is immutable'); END;
