CREATE TABLE hermes_cpu_exit_observations (
    run_id TEXT NOT NULL,
    request_key TEXT NOT NULL,
    lease_epoch INTEGER NOT NULL CHECK(lease_epoch > 0),
    vm_id TEXT NOT NULL,
    boot_id TEXT NOT NULL,
    unit TEXT NOT NULL,
    invocation TEXT NOT NULL,
    unit_state TEXT NOT NULL,
    control_group TEXT NOT NULL,
    cpu_ns INTEGER NOT NULL CHECK(cpu_ns >= 0),
    kill_mode TEXT NOT NULL,
    result TEXT NOT NULL,
    state TEXT NOT NULL CHECK(state = 'UNKNOWN'),
    PRIMARY KEY(run_id, request_key),
    FOREIGN KEY(run_id, request_key) REFERENCES hermes_cpu_unknown_exits(run_id, request_key)
);
CREATE TRIGGER hermes_cpu_exit_observations_no_update BEFORE UPDATE ON hermes_cpu_exit_observations
BEGIN SELECT RAISE(ABORT, 'exit observation is immutable'); END;
CREATE TRIGGER hermes_cpu_exit_observations_no_delete BEFORE DELETE ON hermes_cpu_exit_observations
BEGIN SELECT RAISE(ABORT, 'exit observation is durable'); END;
