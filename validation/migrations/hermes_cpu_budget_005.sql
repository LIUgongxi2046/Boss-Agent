CREATE TABLE hermes_cpu_final_exits (
    run_id TEXT NOT NULL,
    request_key TEXT NOT NULL,
    lease_epoch INTEGER NOT NULL,
    vm_id TEXT NOT NULL,
    boot_id TEXT NOT NULL,
    unit TEXT NOT NULL,
    invocation TEXT NOT NULL,
    slice TEXT NOT NULL,
    cpu_ns INTEGER NOT NULL CHECK(cpu_ns >= 0),
    source TEXT NOT NULL CHECK(source = 'SLICE_CPU_NSEC_V1'),
    PRIMARY KEY(run_id, request_key),
    FOREIGN KEY(run_id, request_key) REFERENCES hermes_cpu_exit_observations(run_id, request_key)
);
CREATE TRIGGER hermes_cpu_final_exits_no_update BEFORE UPDATE ON hermes_cpu_final_exits
BEGIN SELECT RAISE(ABORT, 'final exit is immutable'); END;
CREATE TRIGGER hermes_cpu_final_exits_no_delete BEFORE DELETE ON hermes_cpu_final_exits
BEGIN SELECT RAISE(ABORT, 'final exit is durable'); END;
