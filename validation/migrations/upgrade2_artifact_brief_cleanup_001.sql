CREATE TABLE agent_artifact_brief_cleanup (
    artifact_id TEXT PRIMARY KEY REFERENCES agent_file_reservations(artifact_id),
    run_id TEXT NOT NULL REFERENCES agent_runs(run_id),
    source_id TEXT NOT NULL,
    withdrawal_event_id TEXT NOT NULL,
    cleaned_at TEXT NOT NULL
);
CREATE TRIGGER agent_artifact_brief_cleanup_no_update BEFORE UPDATE ON agent_artifact_brief_cleanup
BEGIN SELECT RAISE(ABORT, 'artifact brief cleanup is immutable'); END;
CREATE TRIGGER agent_artifact_brief_cleanup_no_delete BEFORE DELETE ON agent_artifact_brief_cleanup
BEGIN SELECT RAISE(ABORT, 'artifact brief cleanup is immutable'); END;
DROP TRIGGER agent_artifact_briefs_no_delete;
CREATE TRIGGER agent_artifact_briefs_no_delete BEFORE DELETE ON agent_artifact_briefs
WHEN NOT EXISTS (
    SELECT 1 FROM agent_artifact_brief_cleanup c
    JOIN agent_file_reservations f ON f.artifact_id=c.artifact_id AND f.run_id=c.run_id
    JOIN agent_runs r ON r.run_id=c.run_id
    JOIN objects e ON e.namespace=r.space_id AND e.kind='source_withdrawal_event' AND e.id=c.withdrawal_event_id
    WHERE c.artifact_id=OLD.artifact_id AND json_extract(e.body,'$.source_id')=c.source_id
      AND json_extract(e.body,'$.result')='WITHDRAWN'
      AND (
        EXISTS (SELECT 1 FROM agent_artifacts a WHERE a.artifact_id=c.artifact_id AND a.status='REVOKED'
          AND (EXISTS (SELECT 1 FROM agent_artifact_revocations x WHERE x.artifact_id=a.artifact_id AND x.reason='SOURCE_WITHDRAWN' AND x.source_id=c.source_id)
               OR EXISTS (SELECT 1 FROM json_each(OLD.snapshot,'$.source_refs') j WHERE json_extract(j.value,'$.source_id')=c.source_id)))
        OR EXISTS (SELECT 1 FROM agent_artifact_pending p JOIN agent_artifact_versions v ON v.artifact_id=p.artifact_id
          WHERE p.artifact_id=c.artifact_id AND p.content=X'' AND p.sha256='e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855'
          AND (EXISTS (SELECT 1 FROM json_each(OLD.snapshot,'$.source_refs') j WHERE json_extract(j.value,'$.source_id')=c.source_id)
               OR EXISTS (SELECT 1 FROM agent_artifact_revocations x WHERE x.artifact_id=v.previous_artifact_id AND x.reason='SOURCE_WITHDRAWN' AND x.source_id=c.source_id)))
      )
)
BEGIN SELECT RAISE(ABORT, 'artifact brief cleanup requires withdrawal'); END;
