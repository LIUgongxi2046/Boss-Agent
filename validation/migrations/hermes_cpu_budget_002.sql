CREATE TABLE hermes_cpu_unknown_exits (
    run_id TEXT NOT NULL,
    request_key TEXT NOT NULL,
    lease_epoch INTEGER NOT NULL CHECK(lease_epoch > 0),
    vm_id TEXT NOT NULL,
    boot_id TEXT NOT NULL,
    unit TEXT NOT NULL,
    state TEXT NOT NULL CHECK(state = 'UNKNOWN'),
    cpu_ns INTEGER CHECK(cpu_ns IS NULL),
    PRIMARY KEY(run_id, request_key),
    FOREIGN KEY(run_id, request_key) REFERENCES hermes_cpu_reservations(run_id, request_key)
);
CREATE TRIGGER hermes_cpu_unknown_exits_no_update BEFORE UPDATE ON hermes_cpu_unknown_exits
BEGIN SELECT RAISE(ABORT, 'unknown exit is immutable'); END;
CREATE TRIGGER hermes_cpu_unknown_exits_no_delete BEFORE DELETE ON hermes_cpu_unknown_exits
BEGIN SELECT RAISE(ABORT, 'unknown exit is durable'); END;
