CREATE TABLE agent_plan_handovers (
    namespace TEXT NOT NULL,
    request_key TEXT NOT NULL,
    source_digest TEXT NOT NULL,
    manifest_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY(namespace,request_key)
);
CREATE TRIGGER agent_plan_handovers_no_update BEFORE UPDATE ON agent_plan_handovers
BEGIN SELECT RAISE(ABORT, 'plan handover is immutable'); END;
CREATE TRIGGER agent_plan_handovers_no_delete BEFORE DELETE ON agent_plan_handovers
BEGIN SELECT RAISE(ABORT, 'plan handover is immutable'); END;
