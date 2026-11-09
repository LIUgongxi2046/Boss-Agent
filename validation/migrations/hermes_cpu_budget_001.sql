CREATE TABLE hermes_cpu_budgets (
    root_run_id TEXT PRIMARY KEY REFERENCES agent_runs(run_id),
    limit_ns INTEGER NOT NULL CHECK(limit_ns > 0)
);
CREATE TABLE hermes_cpu_reservations (
    run_id TEXT NOT NULL,
    request_key TEXT NOT NULL,
    root_run_id TEXT NOT NULL REFERENCES hermes_cpu_budgets(root_run_id),
    lease_epoch INTEGER NOT NULL CHECK(lease_epoch > 0),
    reserved_ns INTEGER NOT NULL CHECK(reserved_ns > 0),
    observed_ns INTEGER NOT NULL DEFAULT 0 CHECK(observed_ns >= 0),
    PRIMARY KEY(run_id, request_key),
    FOREIGN KEY(run_id, request_key) REFERENCES hermes_vm_run_bindings(run_id, request_key)
);
CREATE TABLE hermes_cpu_samples (
    run_id TEXT NOT NULL,
    request_key TEXT NOT NULL,
    sample_id TEXT NOT NULL,
    cpu_ns INTEGER NOT NULL CHECK(cpu_ns >= 0),
    PRIMARY KEY(run_id, request_key, sample_id),
    FOREIGN KEY(run_id, request_key) REFERENCES hermes_cpu_reservations(run_id, request_key)
);
CREATE TRIGGER hermes_cpu_budget_no_update BEFORE UPDATE ON hermes_cpu_budgets
BEGIN SELECT RAISE(ABORT, 'cpu budget is immutable'); END;
CREATE TRIGGER hermes_cpu_budget_no_delete BEFORE DELETE ON hermes_cpu_budgets
BEGIN SELECT RAISE(ABORT, 'cpu budget is immutable'); END;
CREATE TRIGGER hermes_cpu_reservation_guard BEFORE UPDATE ON hermes_cpu_reservations
WHEN NEW.run_id IS NOT OLD.run_id OR NEW.request_key IS NOT OLD.request_key OR NEW.root_run_id IS NOT OLD.root_run_id OR NEW.lease_epoch IS NOT OLD.lease_epoch OR NEW.reserved_ns IS NOT OLD.reserved_ns OR NEW.observed_ns < OLD.observed_ns
BEGIN SELECT RAISE(ABORT, 'cpu reservation is immutable'); END;
CREATE TRIGGER hermes_cpu_reservation_no_delete BEFORE DELETE ON hermes_cpu_reservations
BEGIN SELECT RAISE(ABORT, 'cpu reservation is durable'); END;
CREATE TRIGGER hermes_cpu_sample_no_update BEFORE UPDATE ON hermes_cpu_samples
BEGIN SELECT RAISE(ABORT, 'cpu sample is immutable'); END;
CREATE TRIGGER hermes_cpu_sample_no_delete BEFORE DELETE ON hermes_cpu_samples
BEGIN SELECT RAISE(ABORT, 'cpu sample is durable'); END;
