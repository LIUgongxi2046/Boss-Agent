CREATE TABLE agent_artifact_workspaces (
    run_id TEXT PRIMARY KEY REFERENCES agent_runs(run_id),
    root_path TEXT NOT NULL,
    root_device INTEGER NOT NULL,
    root_inode INTEGER NOT NULL,
    directory_device INTEGER NOT NULL,
    directory_inode INTEGER NOT NULL
);
