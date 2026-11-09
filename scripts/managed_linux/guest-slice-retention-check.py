import subprocess
import time
from pathlib import Path
from uuid import uuid4


name = "bossproof" + uuid4().hex
slice_name = name + ".slice"
service = name + ".service"
group = Path("/sys/fs/cgroup") / slice_name
subprocess.run(["/usr/bin/systemctl", "start", slice_name], check=True, timeout=15)
try:
    subprocess.run(["/usr/bin/systemd-run", "--unit=" + service, "--slice=" + slice_name,
                    "--property=Type=exec", "--property=ExitType=cgroup", "--property=CPUAccounting=yes",
                    "/bin/sh", "-c", "sleep 4 & exit 0"], check=True, timeout=15)
    time.sleep(1)
    print("SLICE_RUNNING_EVENTS", repr((group / "cgroup.events").read_text()), flush=True)
    active = subprocess.run(["/usr/bin/systemctl", "show", service, "--property=ActiveState", "--value"],
                            check=True, timeout=15, capture_output=True, text=True).stdout.strip()
    if active != "active":
        raise ValueError("子进程运行时服务状态不可核查")
    main_pid = subprocess.run(["/usr/bin/systemctl", "show", service, "--property=MainPID", "--value"],
                              check=True, timeout=15, capture_output=True, text=True).stdout.strip()
    if main_pid != "0":
        raise ValueError("主进程尚未退出")
    print("CHILD_SERVICE_ACTIVE", active, flush=True)
    time.sleep(6)
    print("SLICE_FINAL_EVENTS", repr((group / "cgroup.events").read_text()), flush=True)
    print("SLICE_FINAL_CPU", repr((group / "cpu.stat").read_text()), flush=True)
    for property_name in ("TasksCurrent", "CPUUsageNSec"):
        value = subprocess.run(["/usr/bin/systemctl", "show", slice_name, "--property=" + property_name, "--value"],
                               check=True, timeout=15, capture_output=True, text=True).stdout.strip()
        print("SLICE_FINAL_" + property_name.upper(), value, flush=True)
        if not value.isdecimal() or property_name == "TasksCurrent" and value != "0":
            raise ValueError("slice 最终统计不可核查")
finally:
    subprocess.run(["/usr/bin/systemctl", "stop", slice_name], check=True, timeout=30)
