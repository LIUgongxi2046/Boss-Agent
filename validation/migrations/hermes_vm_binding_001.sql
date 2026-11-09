CREATE TABLE hermes_vm_workspace_ownership (
    workspace_device INTEGER NOT NULL,
    workspace_inode INTEGER NOT NULL,
    run_id TEXT NOT NULL REFERENCES agent_runs(run_id),
    PRIMARY KEY (workspace_device, workspace_inode),
    UNIQUE (workspace_device, workspace_inode, run_id)
);
CREATE TRIGGER hermes_vm_workspace_ownership_no_update BEFORE UPDATE ON hermes_vm_workspace_ownership
BEGIN SELECT RAISE(ABORT, 'vm workspace ownership is immutable'); END;
CREATE TRIGGER hermes_vm_workspace_ownership_no_delete BEFORE DELETE ON hermes_vm_workspace_ownership
BEGIN SELECT RAISE(ABORT, 'vm workspace ownership is immutable'); END;
CREATE TABLE hermes_vm_run_bindings (
    run_id TEXT NOT NULL,
    request_key TEXT NOT NULL,
    lease_owner TEXT NOT NULL,
    lease_epoch INTEGER NOT NULL CHECK (lease_epoch > 0),
    vm_id TEXT NOT NULL,
    boot_id TEXT NOT NULL,
    unit_name TEXT NOT NULL,
    workspace_device INTEGER NOT NULL,
    workspace_inode INTEGER NOT NULL,
    PRIMARY KEY (run_id, request_key),
    UNIQUE (vm_id, boot_id, unit_name),
    FOREIGN KEY (run_id, request_key) REFERENCES hermes_process_evidence(run_id, request_key),
    FOREIGN KEY (workspace_device, workspace_inode, run_id) REFERENCES hermes_vm_workspace_ownership(workspace_device, workspace_inode, run_id)
);
CREATE TRIGGER hermes_vm_run_bindings_no_update BEFORE UPDATE ON hermes_vm_run_bindings
BEGIN SELECT RAISE(ABORT, 'vm run binding is immutable'); END;
CREATE TRIGGER hermes_vm_run_bindings_no_delete BEFORE DELETE ON hermes_vm_run_bindings
BEGIN SELECT RAISE(ABORT, 'vm run binding is immutable'); END;
