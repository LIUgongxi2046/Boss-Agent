CREATE TABLE agent_concurrency_budgets (
    root_run_id TEXT PRIMARY KEY REFERENCES agent_runs(run_id),
    max_concurrency INTEGER NOT NULL CHECK(max_concurrency > 0)
);
CREATE TABLE agent_concurrency_reservations (
    run_id TEXT NOT NULL REFERENCES agent_runs(run_id),
    request_key TEXT NOT NULL,
    root_run_id TEXT NOT NULL REFERENCES agent_concurrency_budgets(root_run_id),
    request_digest TEXT NOT NULL,
    lease_owner TEXT NOT NULL,
    lease_epoch INTEGER NOT NULL CHECK(lease_epoch > 0),
    state TEXT NOT NULL CHECK(state IN ('ACTIVE','UNKNOWN','RELEASED')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY(run_id, request_key)
);
CREATE INDEX agent_concurrency_by_root ON agent_concurrency_reservations(root_run_id, state);
CREATE TRIGGER agent_concurrency_budget_no_update BEFORE UPDATE ON agent_concurrency_budgets
BEGIN SELECT RAISE(ABORT, 'concurrency budget is immutable'); END;
CREATE TRIGGER agent_concurrency_budget_no_delete BEFORE DELETE ON agent_concurrency_budgets
BEGIN SELECT RAISE(ABORT, 'concurrency budget is immutable'); END;
CREATE TRIGGER agent_concurrency_reservation_no_delete BEFORE DELETE ON agent_concurrency_reservations
BEGIN SELECT RAISE(ABORT, 'concurrency reservation is immutable'); END;
CREATE TRIGGER agent_concurrency_reservation_transition BEFORE UPDATE ON agent_concurrency_reservations
WHEN NEW.run_id IS NOT OLD.run_id OR NEW.request_key IS NOT OLD.request_key
  OR NEW.root_run_id IS NOT OLD.root_run_id OR NEW.request_digest IS NOT OLD.request_digest
  OR NEW.lease_owner IS NOT OLD.lease_owner OR NEW.lease_epoch IS NOT OLD.lease_epoch
  OR NEW.created_at IS NOT OLD.created_at OR OLD.state <> 'ACTIVE'
  OR NEW.state NOT IN ('UNKNOWN','RELEASED')
BEGIN SELECT RAISE(ABORT, 'concurrency reservation is immutable'); END;
