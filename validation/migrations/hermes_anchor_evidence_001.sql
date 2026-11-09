CREATE TABLE hermes_anchor_evidence (
    run_id TEXT NOT NULL,
    request_key TEXT NOT NULL,
    anchor_pid INTEGER NOT NULL CHECK (anchor_pid > 0),
    engine_pid INTEGER NOT NULL CHECK (engine_pid > 0 AND engine_pid <> anchor_pid),
    supervisor_pid INTEGER NOT NULL CHECK (supervisor_pid > 0),
    lease_owner TEXT NOT NULL,
    lease_epoch INTEGER NOT NULL CHECK (lease_epoch > 0),
    recorded_at TEXT NOT NULL,
    PRIMARY KEY (run_id, request_key),
    FOREIGN KEY (run_id, request_key) REFERENCES hermes_process_evidence(run_id, request_key)
);

CREATE TRIGGER hermes_anchor_evidence_no_update BEFORE UPDATE ON hermes_anchor_evidence
BEGIN SELECT RAISE(ABORT, 'anchor evidence is immutable'); END;

CREATE TRIGGER hermes_anchor_evidence_no_delete BEFORE DELETE ON hermes_anchor_evidence
BEGIN SELECT RAISE(ABORT, 'anchor evidence is immutable'); END;
