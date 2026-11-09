import os
import secrets
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4

from hermes_guest_identity import HermesGuestIdentityRegistry
from hermes_guest_systemd import HermesGuestSystemd


check_id = str(uuid4())
identity_directory = Path("/var/lib/boss-vm") / ("cpu-isolation-" + check_id)
identity_directory.mkdir(mode=0o700)
identities = HermesGuestIdentityRegistry(identity_directory)
root = Path("/run") / ("boss-cpu-isolation-" + check_id)
root.mkdir(mode=0o700)
manager = HermesGuestSystemd(python=Path(sys.executable).resolve(), entry=Path("/run/boss-checks/guest-identity-probe.py"),
                             engine=Path("/run/boss-checks"), dependencies=Path("/run/boss-deps/linux-target"),
                             workspace_root=root, identities=identities, supervisor_unit="boss-test-cpu-isolation.service")
boot_id = Path("/proc/sys/kernel/random/boot_id").read_text(encoding="ascii").strip()
base = {"rounds": 1, "seconds": 30, "memory_bytes": 134217728, "processes": 32,
        "cpu_percent": 100, "open_files": 64, "files": 16, "file_bytes": 1048576, "cpu_seconds": 10}


def start(role, cpu_seconds):
    run_id = str(uuid4())
    _, uid, gid = identities.ensure(run_id)
    workspace = root / run_id
    workspace.mkdir(mode=0o700)
    os.chown(workspace, uid, gid)
    marker = workspace / "role"
    marker.write_text(role, encoding="ascii")
    os.chown(marker, uid, gid)
    marker.chmod(0o600)
    bootstrap = {"endpoint": "http://127.0.0.1:19999", "capability": secrets.token_urlsafe(32),
                 "provider_capability": secrets.token_urlsafe(32), "run_id": run_id,
                 "engine_commit": "903230b1e23e0c496b28e5d2e8c4f2639cd506b6"}
    unit, process = manager.launch(run_id, 1, boot_id, {**base, "cpu_seconds": cpu_seconds}, bootstrap)
    return run_id, workspace, unit, process


def wait_ready(workspace, process):
    deadline = time.monotonic() + 15
    while not (workspace / "ready").is_file() and time.monotonic() < deadline:
        if process.poll() is not None:
            raise ValueError("客体运行提前结束")
        time.sleep(0.05)
    if not (workspace / "ready").is_file():
        raise TimeoutError("客体运行未准备完成")


holder = start("holder", 10)
worker = None
try:
    wait_ready(holder[1], holder[3])
    worker = start("cpu", 1)
    wait_ready(worker[1], worker[3])
    pids = [(worker[1] / "holder-pid").read_text(encoding="ascii").strip(),
            *(worker[1] / "child-pids").read_text(encoding="ascii").split()]
    worker[3].wait(timeout=15)
    guard = "boss-cpu-" + worker[0] + "-1.service"
    journal = subprocess.run(["/usr/bin/journalctl", "--unit", guard, "--output=cat", "--no-pager"],
                             check=True, timeout=15, capture_output=True, text=True).stdout.splitlines()
    if len(pids) != 3 or sum(line.startswith("CPU_BUDGET_REACHED ") for line in journal) != 1:
        raise ValueError("CPU 额度终止记录不可核查")
    for pid in pids:
        result = subprocess.run(["/usr/bin/kill", "-0", pid], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if result.returncode == 0:
            raise ValueError("CPU 额度终止后仍有运行进程")
    if holder[3].poll() is not None:
        raise ValueError("其他运行意外退出")
    subprocess.run(["/usr/bin/systemctl", "is-active", "--quiet", holder[2]], check=True, timeout=5)
    pid = (holder[1] / "holder-pid").read_text(encoding="ascii").strip()
    subprocess.run(["/usr/bin/kill", "-0", pid], check=True, timeout=5)
    print("CPU_LIMIT_OTHER_RUN_ACTIVE", flush=True)
finally:
    if worker is not None and worker[3].poll() is None:
        manager.stop(worker[0], 1)
        worker[3].wait(timeout=15)
    if holder[3].poll() is None:
        manager.stop(holder[0], 1)
        holder[3].wait(timeout=15)
