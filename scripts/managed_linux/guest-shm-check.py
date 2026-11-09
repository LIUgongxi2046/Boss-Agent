import os
import secrets
import sys
import time
from pathlib import Path
from uuid import uuid4

from hermes_guest_identity import HermesGuestIdentityRegistry
from hermes_guest_systemd import HermesGuestSystemd


run_id = str(uuid4())
identity_directory = Path("/var/lib/boss-vm") / ("shm-check-" + run_id)
identity_directory.mkdir(mode=0o700)
identities = HermesGuestIdentityRegistry(identity_directory)
_, uid, gid = identities.ensure(run_id)
root = Path("/run") / ("boss-shm-workspaces-" + run_id)
root.mkdir(mode=0o700)
workspace = root / run_id
workspace.mkdir(mode=0o700)
os.chown(workspace, uid, gid)
role = workspace / "role"
role.write_text("shm", encoding="ascii")
os.chown(role, uid, gid)
role.chmod(0o600)
manager = HermesGuestSystemd(python=Path(sys.executable).resolve(), entry=Path("/run/boss-checks/guest-identity-probe.py"),
                             engine=Path("/run/boss-checks"), dependencies=Path("/run/boss-deps/linux-target"),
                             workspace_root=root, identities=identities, supervisor_unit="boss-test-shm.service")
boot_id = Path("/proc/sys/kernel/random/boot_id").read_text(encoding="ascii").strip()
budget = {"rounds": 1, "seconds": 30, "memory_bytes": 134217728, "processes": 32,
          "cpu_percent": 100, "open_files": 64, "files": 16, "file_bytes": 1048576, "cpu_seconds": 10}
bootstrap = {"endpoint": "http://127.0.0.1:19999", "capability": secrets.token_urlsafe(32),
             "provider_capability": secrets.token_urlsafe(32), "run_id": run_id,
             "engine_commit": "903230b1e23e0c496b28e5d2e8c4f2639cd506b6"}
unit, process = manager.launch(run_id, 1, boot_id, budget, bootstrap)
try:
    deadline = time.monotonic() + 15
    while not (workspace / "ready").is_file() and time.monotonic() < deadline:
        if process.poll() is not None:
            raise ValueError("客体共享内存检查提前结束")
        time.sleep(0.1)
    if not (workspace / "ready").is_file():
        raise TimeoutError("客体共享内存检查未启动")
    result = (workspace / "shared-memory-result").read_text(encoding="ascii")
    if (result != "allowed" or (Path("/dev/shm") / ("boss-" + run_id)).exists()
            or (workspace / "ipc-namespace").read_text(encoding="ascii") == os.readlink("/proc/self/ns/ipc")):
        raise ValueError("客体共享内存范围不可核查")
    print("GUEST_PRIVATE_SHARED_MEMORY_OK", flush=True)
    if (workspace / "system-bus-result").read_text(encoding="ascii") != "denied":
        raise ValueError("客体系统服务范围不可核查")
    print("GUEST_SYSTEM_BUS_DENIED", flush=True)
finally:
    manager.stop(run_id, 1)
    process.wait(timeout=15)
