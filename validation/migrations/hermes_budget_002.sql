CREATE TABLE hermes_usage_revisions (
    root_run_id TEXT PRIMARY KEY REFERENCES hermes_model_budgets(root_run_id),
    revision INTEGER NOT NULL CHECK(revision > 0)
);
CREATE TRIGGER hermes_usage_revision_no_delete BEFORE DELETE ON hermes_usage_revisions
BEGIN SELECT RAISE(ABORT, 'usage revision is durable'); END;
