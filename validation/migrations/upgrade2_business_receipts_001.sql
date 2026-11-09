CREATE TABLE agent_run_business_receipts (
    run_id TEXT NOT NULL REFERENCES agent_runs(run_id),
    goal_revision INTEGER NOT NULL CHECK(goal_revision > 0),
    intent_id TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    space_id TEXT NOT NULL,
    decision_request_key TEXT NOT NULL,
    action TEXT NOT NULL,
    object_id TEXT NOT NULL,
    object_revision TEXT NOT NULL,
    payload_digest TEXT NOT NULL,
    decision_digest TEXT NOT NULL,
    receipt_digest TEXT NOT NULL,
    PRIMARY KEY(run_id, goal_revision, intent_id),
    UNIQUE(intent_id),
    FOREIGN KEY(run_id, goal_revision) REFERENCES agent_run_requirements(run_id, goal_revision)
);
CREATE TRIGGER agent_run_business_receipts_no_update BEFORE UPDATE ON agent_run_business_receipts
BEGIN SELECT RAISE(ABORT, 'business receipts are immutable'); END;
CREATE TRIGGER agent_run_business_receipts_no_delete BEFORE DELETE ON agent_run_business_receipts
BEGIN SELECT RAISE(ABORT, 'business receipts are immutable'); END;
