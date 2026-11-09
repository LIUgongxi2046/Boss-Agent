CREATE TABLE agent_migration_inventory (
    migration_version TEXT PRIMARY KEY,
    input_digest TEXT NOT NULL,
    inventory_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TRIGGER agent_migration_inventory_no_update BEFORE UPDATE ON agent_migration_inventory
BEGIN SELECT RAISE(ABORT, 'migration inventory is immutable'); END;
CREATE TRIGGER agent_migration_inventory_no_delete BEFORE DELETE ON agent_migration_inventory
BEGIN SELECT RAISE(ABORT, 'migration inventory is immutable'); END;
