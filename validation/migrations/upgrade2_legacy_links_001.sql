CREATE TABLE agent_legacy_run_links (
    run_id TEXT PRIMARY KEY REFERENCES agent_runs(run_id),
    namespace TEXT NOT NULL,
    record_type TEXT NOT NULL CHECK(record_type='SESSION'),
    session_id TEXT NOT NULL,
    source_digest TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(namespace,record_type,session_id) REFERENCES agent_legacy_inventory(namespace,record_type,record_id)
);
CREATE TRIGGER agent_legacy_run_links_no_update BEFORE UPDATE ON agent_legacy_run_links
BEGIN SELECT RAISE(ABORT, 'legacy run link is immutable'); END;
CREATE TRIGGER agent_legacy_run_links_no_delete BEFORE DELETE ON agent_legacy_run_links
BEGIN SELECT RAISE(ABORT, 'legacy run link is immutable'); END;
