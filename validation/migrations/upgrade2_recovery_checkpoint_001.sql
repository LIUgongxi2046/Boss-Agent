CREATE TABLE agent_recovery_checkpoints (
    namespace TEXT NOT NULL,
    request_key TEXT NOT NULL,
    checkpoint_id TEXT NOT NULL UNIQUE,
    state_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY(namespace,request_key)
);
CREATE TRIGGER agent_recovery_checkpoints_no_update BEFORE UPDATE ON agent_recovery_checkpoints
BEGIN SELECT RAISE(ABORT, 'recovery checkpoint is immutable'); END;
CREATE TRIGGER agent_recovery_checkpoints_no_delete BEFORE DELETE ON agent_recovery_checkpoints
BEGIN SELECT RAISE(ABORT, 'recovery checkpoint is immutable'); END;
