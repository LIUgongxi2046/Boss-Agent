CREATE TABLE agent_schedule_occurrence_gate (
    occurrence_id TEXT PRIMARY KEY,
    namespace TEXT NOT NULL,
    dataset_id TEXT NOT NULL,
    dataset_version TEXT NOT NULL,
    plan_id TEXT NOT NULL,
    plan_version TEXT NOT NULL,
    occurrence_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(namespace, dataset_id, dataset_version, plan_id, plan_version, occurrence_at)
);
CREATE TRIGGER agent_schedule_occurrence_gate_no_update BEFORE UPDATE ON agent_schedule_occurrence_gate
BEGIN SELECT RAISE(ABORT, 'schedule occurrence gate is immutable'); END;
CREATE TRIGGER agent_schedule_occurrence_gate_no_delete BEFORE DELETE ON agent_schedule_occurrence_gate
BEGIN SELECT RAISE(ABORT, 'schedule occurrence gate is immutable'); END;
