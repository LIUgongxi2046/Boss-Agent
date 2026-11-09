CREATE TABLE agent_simulation_recovery_requests (
    namespace TEXT NOT NULL,
    request_key TEXT NOT NULL,
    snapshot_name TEXT NOT NULL,
    snapshot_sha256 TEXT NOT NULL,
    checkpoint_id TEXT NOT NULL,
    target_id TEXT NOT NULL,
    state TEXT NOT NULL CHECK(state='BLOCKED'),
    created_at TEXT NOT NULL,
    PRIMARY KEY(namespace,request_key)
);
CREATE TRIGGER agent_simulation_recovery_requests_no_update BEFORE UPDATE ON agent_simulation_recovery_requests
BEGIN SELECT RAISE(ABORT, 'simulation recovery request is immutable'); END;
CREATE TRIGGER agent_simulation_recovery_requests_no_delete BEFORE DELETE ON agent_simulation_recovery_requests
BEGIN SELECT RAISE(ABORT, 'simulation recovery request is immutable'); END;
