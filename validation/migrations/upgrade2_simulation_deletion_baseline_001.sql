CREATE TABLE agent_simulation_deletion_baselines (
    baseline_id TEXT PRIMARY KEY,
    namespace TEXT NOT NULL,
    request_key TEXT NOT NULL,
    event_count INTEGER NOT NULL,
    events_sha256 TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(namespace, request_key)
);
CREATE TABLE agent_simulation_deletion_baseline_events (
    baseline_id TEXT NOT NULL REFERENCES agent_simulation_deletion_baselines(baseline_id),
    kind TEXT NOT NULL,
    event_id TEXT NOT NULL,
    body_sha256 TEXT NOT NULL,
    PRIMARY KEY(baseline_id, kind, event_id)
);
CREATE TABLE agent_simulation_deletion_baseline_snapshots (
    namespace TEXT NOT NULL,
    snapshot_request_key TEXT NOT NULL,
    checkpoint_id TEXT NOT NULL,
    snapshot_sha256 TEXT NOT NULL,
    baseline_id TEXT NOT NULL REFERENCES agent_simulation_deletion_baselines(baseline_id),
    PRIMARY KEY(namespace, snapshot_request_key)
);
CREATE TRIGGER agent_simulation_deletion_baselines_no_update BEFORE UPDATE ON agent_simulation_deletion_baselines BEGIN SELECT RAISE(ABORT, 'immutable baseline'); END;
CREATE TRIGGER agent_simulation_deletion_baselines_no_delete BEFORE DELETE ON agent_simulation_deletion_baselines BEGIN SELECT RAISE(ABORT, 'immutable baseline'); END;
CREATE TRIGGER agent_simulation_deletion_baseline_events_no_update BEFORE UPDATE ON agent_simulation_deletion_baseline_events BEGIN SELECT RAISE(ABORT, 'immutable baseline event'); END;
CREATE TRIGGER agent_simulation_deletion_baseline_events_no_delete BEFORE DELETE ON agent_simulation_deletion_baseline_events BEGIN SELECT RAISE(ABORT, 'immutable baseline event'); END;
CREATE TRIGGER agent_simulation_deletion_baseline_snapshots_no_update BEFORE UPDATE ON agent_simulation_deletion_baseline_snapshots BEGIN SELECT RAISE(ABORT, 'immutable baseline snapshot'); END;
CREATE TRIGGER agent_simulation_deletion_baseline_snapshots_no_delete BEFORE DELETE ON agent_simulation_deletion_baseline_snapshots BEGIN SELECT RAISE(ABORT, 'immutable baseline snapshot'); END;
