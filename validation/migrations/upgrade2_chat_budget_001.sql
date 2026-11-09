CREATE TABLE agent_chat_budget_configs (
    version INTEGER PRIMARY KEY CHECK(version > 0),
    request_key TEXT NOT NULL UNIQUE,
    budget TEXT NOT NULL,
    budget_sha256 TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE agent_chat_run_budgets (
    run_id TEXT PRIMARY KEY REFERENCES agent_runs(run_id),
    config_version INTEGER NOT NULL REFERENCES agent_chat_budget_configs(version),
    budget_sha256 TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TRIGGER agent_chat_budget_config_no_update BEFORE UPDATE ON agent_chat_budget_configs
BEGIN SELECT RAISE(ABORT, 'chat budget config is immutable'); END;
CREATE TRIGGER agent_chat_budget_config_no_delete BEFORE DELETE ON agent_chat_budget_configs
BEGIN SELECT RAISE(ABORT, 'chat budget config is immutable'); END;
CREATE TRIGGER agent_chat_run_budget_no_update BEFORE UPDATE ON agent_chat_run_budgets
BEGIN SELECT RAISE(ABORT, 'chat run budget is immutable'); END;
CREATE TRIGGER agent_chat_run_budget_no_delete BEFORE DELETE ON agent_chat_run_budgets
BEGIN SELECT RAISE(ABORT, 'chat run budget is immutable'); END;
