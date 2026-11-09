CREATE TABLE IF NOT EXISTS agent_schema_migrations (
    version TEXT PRIMARY KEY,
    sha256 TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS agent_runs (
    run_id TEXT PRIMARY KEY,
    parent_run_id TEXT REFERENCES agent_runs(run_id),
    actor_id TEXT NOT NULL,
    space_id TEXT NOT NULL,
    conversation_id TEXT,
    goal TEXT,
    selected_refs TEXT,
    scope_proof TEXT,
    revision INTEGER NOT NULL,
    status TEXT NOT NULL,
    goal_revision INTEGER NOT NULL,
    applied_goal_revision INTEGER NOT NULL,
    last_input_seq INTEGER NOT NULL,
    cancel_requested_at TEXT,
    lease_owner TEXT,
    lease_epoch INTEGER NOT NULL,
    lease_expires_at TEXT,
    last_event_seq INTEGER NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS agent_request_keys (
    actor_id TEXT NOT NULL,
    space_id TEXT NOT NULL,
    request_key TEXT NOT NULL,
    request_digest TEXT NOT NULL,
    run_id TEXT NOT NULL REFERENCES agent_runs(run_id),
    PRIMARY KEY(actor_id, space_id, request_key)
);
CREATE TABLE IF NOT EXISTS agent_run_events (
    event_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES agent_runs(run_id),
    seq INTEGER NOT NULL,
    origin_event_id TEXT NOT NULL,
    lease_epoch INTEGER NOT NULL,
    type TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    trace_id TEXT NOT NULL,
    payload_version INTEGER NOT NULL,
    payload TEXT NOT NULL,
    UNIQUE(run_id, seq),
    UNIQUE(run_id, lease_epoch, origin_event_id)
);
CREATE TABLE IF NOT EXISTS agent_run_inputs (
    input_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES agent_runs(run_id),
    input_seq INTEGER NOT NULL,
    goal_revision INTEGER NOT NULL,
    request_key TEXT NOT NULL,
    content TEXT NOT NULL,
    applied_event_id TEXT REFERENCES agent_run_events(event_id),
    UNIQUE(run_id, input_seq),
    UNIQUE(run_id, request_key)
);
CREATE TABLE IF NOT EXISTS agent_run_operations (
    run_id TEXT NOT NULL REFERENCES agent_runs(run_id),
    request_key TEXT NOT NULL,
    operation TEXT NOT NULL,
    expected_revision INTEGER NOT NULL,
    receipt TEXT NOT NULL,
    PRIMARY KEY(run_id, request_key)
);
CREATE TABLE IF NOT EXISTS agent_api_requests (
    actor_id TEXT NOT NULL,
    space_id TEXT NOT NULL,
    request_key TEXT NOT NULL,
    request_digest TEXT NOT NULL,
    run_id TEXT NOT NULL REFERENCES agent_runs(run_id),
    operation TEXT NOT NULL CHECK(operation IN ('create', 'inputs', 'cancel')),
    receipt TEXT NOT NULL,
    PRIMARY KEY(actor_id, space_id, request_key)
);
CREATE TABLE IF NOT EXISTS agent_file_budgets (
    root_run_id TEXT PRIMARY KEY REFERENCES agent_runs(run_id),
    max_files INTEGER NOT NULL CHECK(max_files > 0),
    max_bytes INTEGER NOT NULL CHECK(max_bytes > 0)
);
CREATE TABLE IF NOT EXISTS agent_file_reservations (
    artifact_id TEXT PRIMARY KEY,
    root_run_id TEXT NOT NULL REFERENCES agent_file_budgets(root_run_id),
    run_id TEXT NOT NULL REFERENCES agent_runs(run_id),
    request_key TEXT NOT NULL,
    request_digest TEXT NOT NULL,
    size_bytes INTEGER NOT NULL CHECK(size_bytes > 0),
    status TEXT NOT NULL CHECK(status IN ('RESERVED','COMPLETED','RELEASED')),
    UNIQUE(run_id, request_key)
);
CREATE TRIGGER IF NOT EXISTS agent_file_reservation_no_delete BEFORE DELETE ON agent_file_reservations
BEGIN SELECT RAISE(ABORT, 'file reservation is immutable'); END;
CREATE TRIGGER IF NOT EXISTS agent_file_reservation_restrict_update BEFORE UPDATE ON agent_file_reservations
WHEN OLD.status <> 'RESERVED' OR NEW.status NOT IN ('COMPLETED','RELEASED') OR
     NEW.artifact_id IS NOT OLD.artifact_id OR NEW.root_run_id IS NOT OLD.root_run_id OR
     NEW.run_id IS NOT OLD.run_id OR NEW.request_key IS NOT OLD.request_key OR
     NEW.request_digest IS NOT OLD.request_digest OR NEW.size_bytes IS NOT OLD.size_bytes
BEGIN SELECT RAISE(ABORT, 'file reservation is immutable'); END;
CREATE TABLE IF NOT EXISTS agent_artifacts (
    artifact_id TEXT PRIMARY KEY REFERENCES agent_file_reservations(artifact_id),
    run_id TEXT NOT NULL REFERENCES agent_runs(run_id),
    version INTEGER NOT NULL,
    media_type TEXT NOT NULL,
    workspace TEXT NOT NULL,
    storage_key TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    source_refs TEXT NOT NULL,
    context TEXT NOT NULL,
    verification_status TEXT NOT NULL,
    status TEXT NOT NULL,
    UNIQUE(workspace, storage_key)
);
CREATE TABLE IF NOT EXISTS agent_artifact_versions (
    artifact_id TEXT PRIMARY KEY REFERENCES agent_file_reservations(artifact_id),
    series_id TEXT NOT NULL,
    version INTEGER NOT NULL CHECK(version > 0),
    previous_artifact_id TEXT UNIQUE REFERENCES agent_artifacts(artifact_id),
    UNIQUE(series_id, version),
    CHECK((version = 1 AND artifact_id = series_id AND previous_artifact_id IS NULL) OR
          (version > 1 AND previous_artifact_id IS NOT NULL))
);
CREATE TRIGGER IF NOT EXISTS agent_artifact_no_replace BEFORE INSERT ON agent_artifacts
WHEN EXISTS (SELECT 1 FROM agent_artifacts WHERE artifact_id=NEW.artifact_id OR (workspace=NEW.workspace AND storage_key=NEW.storage_key))
BEGIN SELECT RAISE(ABORT, 'artifact already exists'); END;
CREATE TABLE IF NOT EXISTS agent_artifact_pending (
    artifact_id TEXT PRIMARY KEY REFERENCES agent_file_reservations(artifact_id),
    workspace TEXT NOT NULL,
    format_name TEXT NOT NULL,
    content BLOB NOT NULL,
    sha256 TEXT NOT NULL,
    source_refs TEXT NOT NULL,
    context TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS agent_artifact_pending_no_update BEFORE UPDATE ON agent_artifact_pending
BEGIN SELECT RAISE(ABORT, 'artifact pending content is immutable'); END;
CREATE TRIGGER IF NOT EXISTS agent_artifact_version_no_update BEFORE UPDATE ON agent_artifact_versions
BEGIN SELECT RAISE(ABORT, 'artifact version is immutable'); END;
CREATE TRIGGER IF NOT EXISTS agent_artifact_version_no_delete BEFORE DELETE ON agent_artifact_versions
WHEN NOT EXISTS (SELECT 1 FROM agent_file_reservations r WHERE r.artifact_id=OLD.artifact_id AND r.status='RELEASED')
  OR EXISTS (SELECT 1 FROM agent_artifacts a WHERE a.artifact_id=OLD.artifact_id)
BEGIN SELECT RAISE(ABORT, 'artifact version is immutable'); END;
CREATE TABLE IF NOT EXISTS agent_artifact_revocations (
    artifact_id TEXT PRIMARY KEY REFERENCES agent_artifacts(artifact_id),
    reason TEXT NOT NULL CHECK(reason IN ('SERVICE_REQUEST','SOURCE_WITHDRAWN')),
    source_id TEXT,
    revoked_at TEXT NOT NULL,
    CHECK((reason='SERVICE_REQUEST' AND source_id IS NULL) OR (reason='SOURCE_WITHDRAWN' AND source_id IS NOT NULL))
);
CREATE TABLE IF NOT EXISTS agent_artifact_publications (
    artifact_id TEXT PRIMARY KEY REFERENCES agent_artifacts(artifact_id),
    run_id TEXT NOT NULL REFERENCES agent_runs(run_id),
    version INTEGER NOT NULL CHECK(version > 0),
    sha256 TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    published_at TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS agent_artifact_publication_no_update BEFORE UPDATE ON agent_artifact_publications
BEGIN SELECT RAISE(ABORT, 'artifact publication is immutable'); END;
CREATE TRIGGER IF NOT EXISTS agent_artifact_publication_no_delete BEFORE DELETE ON agent_artifact_publications
BEGIN SELECT RAISE(ABORT, 'artifact publication is immutable'); END;
CREATE TRIGGER IF NOT EXISTS agent_verified_artifact_no_content_update BEFORE UPDATE ON agent_artifacts
WHEN OLD.status = 'VERIFIED' AND (
    NEW.status NOT IN ('PUBLISHED','REVOKED') OR
    NEW.artifact_id IS NOT OLD.artifact_id OR NEW.run_id IS NOT OLD.run_id OR
    NEW.version IS NOT OLD.version OR NEW.media_type IS NOT OLD.media_type OR
    NEW.workspace IS NOT OLD.workspace OR NEW.storage_key IS NOT OLD.storage_key OR
    NEW.sha256 IS NOT OLD.sha256 OR NEW.size_bytes IS NOT OLD.size_bytes OR
    NEW.source_refs IS NOT OLD.source_refs OR NEW.context IS NOT OLD.context OR
    NEW.verification_status IS NOT OLD.verification_status OR
    (NEW.status = 'PUBLISHED' AND NOT EXISTS (
        SELECT 1 FROM agent_artifact_publications p JOIN agent_runs r ON r.run_id=p.run_id
        WHERE p.artifact_id=OLD.artifact_id AND p.run_id=OLD.run_id AND p.version=OLD.version
          AND p.sha256=OLD.sha256 AND p.actor_id=r.actor_id
    ))
) BEGIN SELECT RAISE(ABORT, 'verified artifact is immutable'); END;
CREATE TRIGGER IF NOT EXISTS agent_verified_artifact_no_delete BEFORE DELETE ON agent_artifacts
WHEN OLD.status = 'VERIFIED' BEGIN SELECT RAISE(ABORT, 'verified artifact is immutable'); END;
CREATE TABLE IF NOT EXISTS agent_task_artifact_refs (
    task_id TEXT NOT NULL,
    artifact_id TEXT NOT NULL REFERENCES agent_artifacts(artifact_id),
    run_id TEXT NOT NULL REFERENCES agent_runs(run_id),
    intent_id TEXT NOT NULL,
    artifact_version INTEGER NOT NULL CHECK(artifact_version > 0),
    PRIMARY KEY(task_id, artifact_id)
);
CREATE TRIGGER IF NOT EXISTS agent_task_artifact_ref_no_update BEFORE UPDATE ON agent_task_artifact_refs
BEGIN SELECT RAISE(ABORT, 'artifact task reference is immutable'); END;
CREATE TRIGGER IF NOT EXISTS agent_task_artifact_ref_no_delete BEFORE DELETE ON agent_task_artifact_refs
BEGIN SELECT RAISE(ABORT, 'artifact task reference is immutable'); END;
CREATE TRIGGER IF NOT EXISTS agent_artifact_revocation_no_update BEFORE UPDATE ON agent_artifact_revocations
BEGIN SELECT RAISE(ABORT, 'artifact revocation is immutable'); END;
CREATE TRIGGER IF NOT EXISTS agent_artifact_revocation_no_delete BEFORE DELETE ON agent_artifact_revocations
BEGIN SELECT RAISE(ABORT, 'artifact revocation is immutable'); END;
CREATE TRIGGER IF NOT EXISTS agent_published_artifact_no_update BEFORE UPDATE ON agent_artifacts
WHEN OLD.status IN ('PUBLISHED','REVOKED') AND (
    OLD.status <> 'PUBLISHED' OR NEW.status <> 'REVOKED' OR
    NEW.artifact_id IS NOT OLD.artifact_id OR NEW.run_id IS NOT OLD.run_id OR
    NEW.version IS NOT OLD.version OR NEW.media_type IS NOT OLD.media_type OR
    NEW.workspace IS NOT OLD.workspace OR NEW.storage_key IS NOT OLD.storage_key OR
    NEW.sha256 IS NOT OLD.sha256 OR NEW.size_bytes IS NOT OLD.size_bytes OR
    NEW.source_refs IS NOT OLD.source_refs OR NEW.context IS NOT OLD.context OR
    NEW.verification_status IS NOT OLD.verification_status
) BEGIN SELECT RAISE(ABORT, 'published artifact is immutable'); END;
CREATE TRIGGER IF NOT EXISTS agent_published_artifact_no_delete BEFORE DELETE ON agent_artifacts
WHEN OLD.status IN ('PUBLISHED','REVOKED') BEGIN SELECT RAISE(ABORT, 'published artifact is immutable'); END;
