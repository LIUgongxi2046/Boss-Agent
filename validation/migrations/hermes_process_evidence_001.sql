CREATE TABLE hermes_process_evidence (
    run_id TEXT NOT NULL,
    request_key TEXT NOT NULL,
    request_digest TEXT NOT NULL,
    lease_owner TEXT NOT NULL,
    lease_epoch INTEGER NOT NULL,
    actor_id TEXT NOT NULL,
    space_id TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('STARTING', 'RUNNING', 'UNKNOWN', 'EXITED')),
    pid INTEGER,
    supervisor_pid INTEGER NOT NULL,
    exit_code INTEGER,
    exit_scope TEXT CHECK (exit_scope IS NULL OR exit_scope = 'LEADER_ONLY'),
    updated_at TEXT NOT NULL,
    PRIMARY KEY (run_id, request_key),
    FOREIGN KEY (run_id, request_key) REFERENCES agent_concurrency_reservations(run_id, request_key)
);
CREATE TRIGGER hermes_process_evidence_no_delete BEFORE DELETE ON hermes_process_evidence
BEGIN SELECT RAISE(ABORT, 'process evidence is immutable'); END;
CREATE TRIGGER hermes_process_evidence_guard BEFORE UPDATE ON hermes_process_evidence
WHEN NEW.run_id IS NOT OLD.run_id OR NEW.request_key IS NOT OLD.request_key
 OR NEW.request_digest IS NOT OLD.request_digest OR NEW.lease_owner IS NOT OLD.lease_owner
 OR NEW.lease_epoch IS NOT OLD.lease_epoch OR NEW.actor_id IS NOT OLD.actor_id
 OR NEW.space_id IS NOT OLD.space_id OR NEW.supervisor_pid IS NOT OLD.supervisor_pid
 OR (OLD.pid IS NOT NULL AND NEW.pid IS NOT OLD.pid)
 OR OLD.state = 'EXITED'
 OR NOT ((OLD.state = 'STARTING' AND NEW.state IN ('RUNNING', 'UNKNOWN'))
      OR (OLD.state = 'RUNNING' AND NEW.state IN ('UNKNOWN', 'EXITED'))
      OR (OLD.state = 'UNKNOWN' AND NEW.state = 'EXITED'))
BEGIN SELECT RAISE(ABORT, 'process evidence transition is invalid'); END;
