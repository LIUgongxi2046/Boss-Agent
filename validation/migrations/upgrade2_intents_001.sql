CREATE TABLE agent_intents (
    intent_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES agent_runs(run_id),
    actor_id TEXT NOT NULL,
    space_id TEXT NOT NULL,
    request_key TEXT NOT NULL,
    request_digest TEXT NOT NULL,
    action TEXT NOT NULL,
    object_id TEXT NOT NULL,
    expected_revision TEXT NOT NULL,
    scope_revision TEXT NOT NULL,
    payload_digest TEXT NOT NULL,
    client_request_id TEXT NOT NULL UNIQUE,
    preview TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('WAITING_CONFIRMATION', 'REJECTED', 'EXPIRED', 'AUTHORIZED', 'EXECUTING', 'SUCCEEDED', 'FAILED', 'UNKNOWN')),
    authorization_id TEXT,
    result_ref TEXT,
    created_at TEXT NOT NULL,
    revision INTEGER NOT NULL DEFAULT 0,
    UNIQUE(run_id, request_key)
);
CREATE TABLE agent_intent_decisions (
    actor_id TEXT NOT NULL,
    space_id TEXT NOT NULL,
    request_key TEXT NOT NULL,
    request_digest TEXT NOT NULL,
    intent_id TEXT NOT NULL REFERENCES agent_intents(intent_id),
    receipt TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY(actor_id, space_id, request_key)
);
