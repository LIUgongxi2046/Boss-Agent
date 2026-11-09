CREATE TABLE IF NOT EXISTS hermes_schedule_observations (
    namespace TEXT NOT NULL,
    dataset_id TEXT NOT NULL,
    dataset_version TEXT NOT NULL,
    schedule_id TEXT NOT NULL,
    schedule_version TEXT NOT NULL,
    configuration_version TEXT NOT NULL,
    occurrence_at TEXT NOT NULL,
    timezone TEXT NOT NULL,
    expression TEXT NOT NULL,
    business_time TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status='CANDIDATE'),
    PRIMARY KEY(namespace, dataset_id, dataset_version, schedule_id, schedule_version, occurrence_at)
);
CREATE TRIGGER IF NOT EXISTS hermes_schedule_observation_no_update BEFORE UPDATE ON hermes_schedule_observations
BEGIN SELECT RAISE(ABORT, 'schedule observation is immutable'); END;
CREATE TRIGGER IF NOT EXISTS hermes_schedule_observation_no_delete BEFORE DELETE ON hermes_schedule_observations
BEGIN SELECT RAISE(ABORT, 'schedule observation is immutable'); END;
CREATE TABLE IF NOT EXISTS hermes_schedule_plan_candidates (
    namespace TEXT NOT NULL,
    dataset_id TEXT NOT NULL,
    dataset_version TEXT NOT NULL,
    plan_id TEXT NOT NULL,
    plan_version TEXT NOT NULL,
    occurrence_at TEXT NOT NULL,
    schedule_id TEXT NOT NULL,
    schedule_version TEXT NOT NULL,
    timezone TEXT NOT NULL,
    plan_sha256 TEXT NOT NULL,
    occurrence_id TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status='CANDIDATE'),
    PRIMARY KEY(namespace, dataset_id, dataset_version, plan_id, plan_version, occurrence_at),
    FOREIGN KEY(namespace, dataset_id, dataset_version, schedule_id, schedule_version, occurrence_at)
      REFERENCES hermes_schedule_observations(namespace, dataset_id, dataset_version, schedule_id, schedule_version, occurrence_at)
);
CREATE TRIGGER IF NOT EXISTS hermes_schedule_plan_candidate_no_update BEFORE UPDATE ON hermes_schedule_plan_candidates
BEGIN SELECT RAISE(ABORT, 'plan candidate is immutable'); END;
CREATE TRIGGER IF NOT EXISTS hermes_schedule_plan_candidate_no_delete BEFORE DELETE ON hermes_schedule_plan_candidates
BEGIN SELECT RAISE(ABORT, 'plan candidate is immutable'); END;
CREATE TABLE IF NOT EXISTS hermes_schedule_run_links (
    occurrence_id TEXT PRIMARY KEY REFERENCES hermes_schedule_plan_candidates(occurrence_id),
    run_id TEXT NOT NULL UNIQUE REFERENCES agent_runs(run_id),
    created_at TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS hermes_schedule_run_link_no_update BEFORE UPDATE ON hermes_schedule_run_links
BEGIN SELECT RAISE(ABORT, 'schedule run link is immutable'); END;
CREATE TRIGGER IF NOT EXISTS hermes_schedule_run_link_no_delete BEFORE DELETE ON hermes_schedule_run_links
BEGIN SELECT RAISE(ABORT, 'schedule run link is immutable'); END;
CREATE TABLE IF NOT EXISTS hermes_schedule_notification_links (
    occurrence_id TEXT NOT NULL REFERENCES hermes_schedule_run_links(occurrence_id),
    event_id TEXT NOT NULL,
    event_version TEXT NOT NULL,
    dispatch_id TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL CHECK(status IN ('DELIVERED','SUPPRESSED')),
    PRIMARY KEY(occurrence_id, event_id, event_version)
);
CREATE TRIGGER IF NOT EXISTS hermes_schedule_notification_link_no_update BEFORE UPDATE ON hermes_schedule_notification_links
BEGIN SELECT RAISE(ABORT, 'schedule notification link is immutable'); END;
CREATE TRIGGER IF NOT EXISTS hermes_schedule_notification_link_no_delete BEFORE DELETE ON hermes_schedule_notification_links
BEGIN SELECT RAISE(ABORT, 'schedule notification link is immutable'); END;
CREATE TABLE IF NOT EXISTS hermes_schedule_migrations (
    version TEXT PRIMARY KEY,
    sha256 TEXT NOT NULL
);
