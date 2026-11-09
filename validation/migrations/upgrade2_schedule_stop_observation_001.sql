CREATE TABLE agent_schedule_stop_observations (
    namespace TEXT NOT NULL,
    request_key TEXT NOT NULL,
    lease_owner TEXT NOT NULL,
    lease_epoch INTEGER NOT NULL,
    observer_pid INTEGER NOT NULL,
    cron_path TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    scope TEXT NOT NULL CHECK(scope='LOCAL_OBJECT_ONLY'),
    PRIMARY KEY(namespace,request_key)
);
CREATE TRIGGER agent_schedule_stop_observations_no_update BEFORE UPDATE ON agent_schedule_stop_observations
BEGIN SELECT RAISE(ABORT, 'schedule stop observation is immutable'); END;
CREATE TRIGGER agent_schedule_stop_observations_no_delete BEFORE DELETE ON agent_schedule_stop_observations
BEGIN SELECT RAISE(ABORT, 'schedule stop observation is immutable'); END;
