import os
import secrets
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4

from hermes_guest_identity import HermesGuestIdentityRegistry
from hermes_guest_systemd import HermesGuestSystemd


run_id = str(uuid4())
identity_directory = Path("/var/lib/boss-vm") / ("cpu-check-" + run_id)
identity_directory.mkdir(mode=0o700)
identities = HermesGuestIdentityRegistry(identity_directory)
_, uid, gid = identities.ensure(run_id)
root = Path("/run") / ("boss-cpu-workspaces-" + run_id)
root.mkdir(mode=0o700)
workspace = root / run_id
workspace.mkdir(mode=0o700)
os.chown(workspace, uid, gid)
role = workspace / "role"
role.write_text("cpu", encoding="ascii")
os.chown(role, uid, gid)
role.chmod(0o600)
manager = HermesGuestSystemd(python=Path(sys.executable).resolve(), entry=Path("/run/boss-checks/guest-identity-probe.py"),
                             engine=Path("/run/boss-checks"), dependencies=Path("/run/boss-deps/linux-target"),
                             workspace_root=root, identities=identities, supervisor_unit="boss-test-cpu.service")
boot_id = Path("/proc/sys/kernel/random/boot_id").read_text(encoding="ascii").strip()
budget = {"rounds": 1, "seconds": 30, "memory_bytes": 134217728, "processes": 32,
          "cpu_percent": 100, "open_files": 64, "files": 16, "file_bytes": 1048576, "cpu_seconds": 1}
bootstrap = {"endpoint": "http://127.0.0.1:19999", "capability": secrets.token_urlsafe(32),
             "provider_capability": secrets.token_urlsafe(32), "run_id": run_id,
             "engine_commit": "903230b1e23e0c496b28e5d2e8c4f2639cd506b6"}
unit, process = manager.launch(run_id, 1, boot_id, budget, bootstrap)
try:
    deadline = time.monotonic() + 15
    while not (workspace / "ready").is_file() and time.monotonic() < deadline:
        if process.poll() is not None:
            raise ValueError("客体 CPU 检查提前结束")
        time.sleep(0.05)
    if not (workspace / "ready").is_file():
        raise TimeoutError("客体 CPU 检查未启动")
    pids = [(workspace / "holder-pid").read_text(encoding="ascii").strip(),
            *(workspace / "child-pids").read_text(encoding="ascii").split()]
    process.wait(timeout=15)
    guard = "boss-cpu-" + run_id + "-1.service"
    output = subprocess.run(["/usr/bin/journalctl", "--unit", guard, "--output=cat", "--no-pager"],
                            check=True, timeout=15, capture_output=True, text=True).stdout.splitlines()
    records = [line for line in output if line.startswith("CPU_BUDGET_REACHED ")]
    if len(records) != 1:
        raise ValueError("客体 CPU 超额记录不可核查")
    usage = int(records[0].split()[1])
    if usage < 1_000_000_000 or usage >= 2_000_000_000:
        raise ValueError("客体 CPU 超额范围不可核查")
    for pid in pids:
        if subprocess.run(["/usr/bin/kill", "-0", pid], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0:
            raise ValueError("客体 CPU 超额后仍有运行进程")
    print("CPU_AGGREGATE_BUDGET_STOPPED", usage, "PROCESSES", len(pids), flush=True)
finally:
    if process.poll() is None:
        manager.stop(run_id, 1)
        process.wait(timeout=15)
