CREATE TABLE agent_legacy_inventory (
    namespace TEXT NOT NULL,
    record_type TEXT NOT NULL CHECK(record_type IN ('SESSION','PLAN')),
    record_id TEXT NOT NULL,
    source_digest TEXT NOT NULL,
    metadata_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY(namespace,record_type,record_id)
);
CREATE TRIGGER agent_legacy_inventory_no_update BEFORE UPDATE ON agent_legacy_inventory
BEGIN SELECT RAISE(ABORT, 'legacy inventory is immutable'); END;
CREATE TRIGGER agent_legacy_inventory_no_delete BEFORE DELETE ON agent_legacy_inventory
BEGIN SELECT RAISE(ABORT, 'legacy inventory is immutable'); END;
