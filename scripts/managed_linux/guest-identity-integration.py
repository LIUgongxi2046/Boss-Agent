import hashlib
import json
import os
import secrets
import sys
import time
from pathlib import Path
from uuid import uuid4

from hermes_guest_identity import HermesGuestIdentityRegistry
from hermes_guest_systemd import HermesGuestSystemd


def wait_for(path, process):
    deadline = time.monotonic() + 15
    while not path.is_file() and time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("客体技术进程提前结束")
        time.sleep(0.1)
    if not path.is_file():
        raise TimeoutError("客体技术检查等待超时")


def main():
    identity_parent = Path("/var/lib/boss-vm")
    identity_parent.mkdir(mode=0o700, exist_ok=True)
    identity_directory = identity_parent / "identity-check"
    identity_directory.mkdir(mode=0o700, exist_ok=True)
    registry = HermesGuestIdentityRegistry(identity_directory)
    first, second = str(uuid4()), str(uuid4())
    first_user, first_uid, first_gid = registry.ensure(first)
    second_user, second_uid, second_gid = registry.ensure(second)
    if first_uid == second_uid or first_user == second_user:
        raise ValueError("不同运行账号未隔离")
    reopened = HermesGuestIdentityRegistry(identity_directory)
    if reopened.ensure(first) != (first_user, first_uid, first_gid) or reopened.ensure(second) != (second_user, second_uid, second_gid):
        raise ValueError("持久账号登记不一致")
    boot_id = Path("/proc/sys/kernel/random/boot_id").read_text(encoding="ascii").strip()
    digest = hashlib.sha256(b"guest identity integration").hexdigest()
    workspace_identity = {"root_run_id": first, "root_epoch": 1, "max_files": 16, "max_bytes": 1048576}
    unit, created = registry.reserve_start(first, 1, boot_id, digest, workspace_identity)
    if not created or reopened.reserve_start(first, 1, boot_id, digest, workspace_identity) != (unit, False):
        raise ValueError("持久启动记录不一致")
    root = Path("/run/boss-identity-workspaces")
    root.mkdir(mode=0o700)
    for run_id, role, uid, gid in ((first, "holder", first_uid, first_gid), (second, "checker", second_uid, second_gid)):
        workspace = root / run_id
        workspace.mkdir(mode=0o700)
        os.chown(workspace, uid, gid)
        for name, content in (("role", role), ("own-file", "own"), ("target", str(root / first / "own-file"))):
            path = workspace / name
            path.write_text(content, encoding="ascii")
            os.chown(path, uid, gid)
            path.chmod(0o600)
    manager = HermesGuestSystemd(python=Path(sys.executable).resolve(), entry=Path("/run/boss-checks/guest-identity-probe.py"),
                                 engine=Path("/run/boss-checks"), dependencies=Path("/run/boss-deps/linux-target"), workspace_root=root,
                                 identities=registry, supervisor_unit="boss-test-identity.service")
    budget = {"rounds": 1, "seconds": 30, "memory_bytes": 134217728, "processes": 32,
              "cpu_percent": 100, "open_files": 64, "files": 16, "file_bytes": 1048576, "cpu_seconds": 10}
    def bootstrap(run_id):
        return {"endpoint": "http://127.0.0.1:19999", "capability": secrets.token_urlsafe(32),
                "provider_capability": secrets.token_urlsafe(32), "run_id": run_id,
                "engine_commit": "903230b1e23e0c496b28e5d2e8c4f2639cd506b6"}
    first_unit, first_process = manager.launch(first, 1, boot_id, budget, bootstrap(first))
    try:
        wait_for(root / first / "ready", first_process)
        holder_pid = (root / first / "holder-pid").read_text(encoding="ascii")
        target = root / second / "holder-pid"
        target.write_text(holder_pid, encoding="ascii")
        os.chown(target, second_uid, second_gid)
        target.chmod(0o600)
        second_unit, second_process = manager.launch(second, 1, boot_id, budget, bootstrap(second))
        try:
            wait_for(root / second / "result.json", second_process)
            result = json.loads((root / second / "result.json").read_text(encoding="utf-8"))
            if result != {"uid": second_uid, "own_workspace": True, "cross_workspace": True, "cross_root": True,
                          "cross_environ": True, "cross_memory": True, "cross_descriptors": True, "cross_signal": True}:
                raise ValueError("逐运行隔离检查未通过")
            print("DISTINCT_RUN_UIDS", first_uid, second_uid, flush=True)
            print("OWN_ACCESS_ALLOWED CROSS_WORKSPACE_REJECTED CROSS_PROCESS_ACCESS_REJECTED CROSS_SIGNAL_REJECTED", flush=True)
            print("PERSISTENT_IDENTITY_AND_CONTROL_REOPENED", flush=True)
        finally:
            manager.stop(second, 1)
            second_process.wait(timeout=15)
    finally:
        manager.stop(first, 1)
        first_process.wait(timeout=15)
    registry.mark_stopped(first, 1, boot_id)
    if first_unit != unit or second_unit != "boss-" + second + "-1.service":
        raise ValueError("运行 unit 不匹配")
    print("GUEST_IDENTITY_INTEGRATION_OK", flush=True)


if __name__ == "__main__":
    main()
