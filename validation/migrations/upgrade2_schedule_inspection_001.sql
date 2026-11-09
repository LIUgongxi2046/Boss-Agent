CREATE TABLE agent_schedule_inspection_leases (
    namespace TEXT PRIMARY KEY,
    owner TEXT NOT NULL,
    epoch INTEGER NOT NULL CHECK(epoch > 0),
    expires_at TEXT NOT NULL,
    purpose TEXT NOT NULL CHECK(purpose='INSPECTION_ONLY')
);
