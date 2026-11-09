CREATE TABLE agent_simulation_snapshots (
    namespace TEXT NOT NULL,
    request_key TEXT NOT NULL,
    checkpoint_request_key TEXT NOT NULL,
    checkpoint_id TEXT NOT NULL,
    snapshot_name TEXT NOT NULL UNIQUE,
    snapshot_sha256 TEXT NOT NULL,
    manifest_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY(namespace,request_key)
);
CREATE TRIGGER agent_simulation_snapshots_no_update BEFORE UPDATE ON agent_simulation_snapshots
BEGIN SELECT RAISE(ABORT, 'simulation snapshot is immutable'); END;
CREATE TRIGGER agent_simulation_snapshots_no_delete BEFORE DELETE ON agent_simulation_snapshots
BEGIN SELECT RAISE(ABORT, 'simulation snapshot is immutable'); END;
