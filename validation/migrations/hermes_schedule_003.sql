CREATE TABLE hermes_schedule_run_budgets (
    occurrence_id TEXT PRIMARY KEY REFERENCES hermes_schedule_run_links(occurrence_id),
    plan_id TEXT NOT NULL,
    plan_version TEXT NOT NULL,
    authorization_id TEXT NOT NULL,
    budget TEXT NOT NULL,
    budget_sha256 TEXT NOT NULL
);
CREATE TRIGGER hermes_schedule_run_budget_no_update BEFORE UPDATE ON hermes_schedule_run_budgets
BEGIN SELECT RAISE(ABORT, 'schedule run budget is immutable'); END;
CREATE TRIGGER hermes_schedule_run_budget_no_delete BEFORE DELETE ON hermes_schedule_run_budgets
BEGIN SELECT RAISE(ABORT, 'schedule run budget is immutable'); END;
