CREATE TABLE hermes_cpu_sources (
    run_id TEXT NOT NULL,
    request_key TEXT NOT NULL,
    source TEXT NOT NULL CHECK(source IN ('UNIT_CPU_NSEC_LEGACY', 'SLICE_CPU_NSEC_V1')),
    PRIMARY KEY(run_id, request_key),
    FOREIGN KEY(run_id, request_key) REFERENCES hermes_cpu_reservations(run_id, request_key)
);
INSERT INTO hermes_cpu_sources SELECT run_id, request_key, 'UNIT_CPU_NSEC_LEGACY' FROM hermes_cpu_reservations;
CREATE TRIGGER hermes_cpu_sources_no_update BEFORE UPDATE ON hermes_cpu_sources
BEGIN SELECT RAISE(ABORT, 'cpu source is immutable'); END;
CREATE TRIGGER hermes_cpu_sources_no_delete BEFORE DELETE ON hermes_cpu_sources
BEGIN SELECT RAISE(ABORT, 'cpu source is durable'); END;
