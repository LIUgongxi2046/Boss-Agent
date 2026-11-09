CREATE TABLE hermes_model_budgets (
    root_run_id TEXT PRIMARY KEY REFERENCES agent_runs(run_id),
    request_limit INTEGER NOT NULL CHECK(request_limit > 0)
);

CREATE TABLE hermes_model_requests (
    request_id TEXT PRIMARY KEY,
    root_run_id TEXT NOT NULL REFERENCES hermes_model_budgets(root_run_id),
    run_id TEXT NOT NULL REFERENCES agent_runs(run_id),
    lease_epoch INTEGER NOT NULL CHECK(lease_epoch > 0),
    state TEXT NOT NULL CHECK(state IN ('UNKNOWN', 'COMPLETED')),
    usage TEXT
);

CREATE INDEX hermes_model_requests_root ON hermes_model_requests(root_run_id);
