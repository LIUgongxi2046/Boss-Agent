import os
import select
import subprocess
import time
from pathlib import Path

group = Path("/sys/fs/cgroup/boss-tree-probe")
if group.exists():
    raise ValueError("检查 cgroup 已存在")
manager = subprocess.Popen(["bash", "/mnt/boss-probe/guest-manager-probe.sh"])
descriptor = os.pidfd_open(manager.pid)
poller = select.poll()
poller.register(descriptor, select.POLLIN)
print("MANAGER_PID", manager.pid, flush=True)
events = poller.poll(300000)
if not events:
    raise TimeoutError("管理进程检查超时")
returncode = manager.wait()
os.close(descriptor)
(group / "cgroup.kill").write_text("1")
deadline = time.monotonic() + 5
while "populated 0\n" not in (group / "cgroup.events").read_text():
    if time.monotonic() >= deadline:
        raise TimeoutError("受管进程退出尚未确认")
    time.sleep(0.01)
print("MANAGER_RETURN", returncode, flush=True)
print("GUARDIAN_RECLAIMED", flush=True)
