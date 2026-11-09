CREATE TABLE hermes_schedule_previews (
    preview_id TEXT PRIMARY KEY,
    owner_id TEXT NOT NULL,
    namespace TEXT NOT NULL,
    plan_id TEXT NOT NULL,
    plan_sha256 TEXT NOT NULL,
    payload_sha256 TEXT NOT NULL,
    preview TEXT NOT NULL,
    created_at TEXT NOT NULL,
    decision TEXT CHECK(decision IN ('CONFIRM','REJECT')),
    authorization_id TEXT,
    decision_request_id TEXT UNIQUE,
    decided_at TEXT,
    CHECK((decision IS NULL AND authorization_id IS NULL AND decision_request_id IS NULL AND decided_at IS NULL)
       OR (decision='REJECT' AND authorization_id IS NULL AND decision_request_id IS NOT NULL AND decided_at IS NOT NULL)
       OR (decision='CONFIRM' AND authorization_id IS NOT NULL AND decision_request_id IS NOT NULL AND decided_at IS NOT NULL))
);
CREATE TRIGGER hermes_schedule_preview_no_delete BEFORE DELETE ON hermes_schedule_previews
BEGIN SELECT RAISE(ABORT, 'schedule preview is immutable'); END;
CREATE TRIGGER hermes_schedule_preview_update_once BEFORE UPDATE ON hermes_schedule_previews
WHEN OLD.decision IS NOT NULL OR NEW.preview_id != OLD.preview_id OR NEW.owner_id != OLD.owner_id
  OR NEW.namespace != OLD.namespace OR NEW.plan_id != OLD.plan_id OR NEW.plan_sha256 != OLD.plan_sha256
  OR NEW.payload_sha256 != OLD.payload_sha256 OR NEW.preview != OLD.preview OR NEW.created_at != OLD.created_at
BEGIN SELECT RAISE(ABORT, 'schedule preview is immutable'); END;
