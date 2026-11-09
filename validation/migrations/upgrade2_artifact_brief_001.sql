CREATE TABLE agent_artifact_briefs (
    artifact_id TEXT PRIMARY KEY REFERENCES agent_file_reservations(artifact_id),
    snapshot TEXT NOT NULL,
    snapshot_sha256 TEXT NOT NULL
);
CREATE TRIGGER agent_artifact_briefs_no_update BEFORE UPDATE ON agent_artifact_briefs
BEGIN SELECT RAISE(ABORT, 'artifact brief is immutable'); END;
CREATE TRIGGER agent_artifact_briefs_no_delete BEFORE DELETE ON agent_artifact_briefs
BEGIN SELECT RAISE(ABORT, 'artifact brief is immutable'); END;
