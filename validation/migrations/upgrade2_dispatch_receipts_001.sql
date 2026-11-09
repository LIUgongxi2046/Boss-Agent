CREATE TABLE agent_dispatch_receipts (
    run_id TEXT NOT NULL REFERENCES agent_runs(run_id),
    request_key TEXT NOT NULL,
    request_digest TEXT NOT NULL,
    lease_owner TEXT NOT NULL,
    lease_epoch INTEGER NOT NULL,
    expected_revision INTEGER NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('ACCEPTED', 'COMPLETED', 'UNKNOWN')),
    result TEXT,
    PRIMARY KEY (run_id, request_key)
);
