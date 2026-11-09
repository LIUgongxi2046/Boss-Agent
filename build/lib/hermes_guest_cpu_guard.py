import argparse
import re
import subprocess
import time
from pathlib import Path


parser = argparse.ArgumentParser()
parser.add_argument("unit")
parser.add_argument("cpu_seconds", type=int)
arguments = parser.parse_args()
if re.fullmatch(r"boss-[0-9a-f-]{36}-[1-9][0-9]*\.service", arguments.unit) is None or arguments.cpu_seconds <= 0:
    raise ValueError("客体 CPU 监督参数无效")

deadline = time.monotonic() + 15
observed = False
while True:
    subprocess.run(["/usr/bin/systemd-notify", "WATCHDOG=1"], check=True, timeout=5,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    state = subprocess.run(["/usr/bin/systemctl", "show", arguments.unit, "--property=ActiveState", "--value"],
                           check=True, timeout=5, capture_output=True, text=True).stdout.strip()
    if state == "active":
        observed = True
        value = subprocess.run(["/usr/bin/systemctl", "show", arguments.unit, "--property=CPUUsageNSec", "--value"],
                               check=True, timeout=5, capture_output=True, text=True).stdout.strip()
        if value.isdecimal():
            usage = int(value)
            if usage >= arguments.cpu_seconds * 1_000_000_000:
                group = subprocess.run(["/usr/bin/systemctl", "show", arguments.unit, "--property=ControlGroup", "--value"],
                                       check=True, timeout=5, capture_output=True, text=True).stdout.strip()
                if group != "/system.slice/" + arguments.unit:
                    raise ValueError("客体 CPU 工作控制组不可核查")
                kill = Path("/sys/fs/cgroup") / group.lstrip("/") / "cgroup.kill"
                if not kill.is_file() or kill.is_symlink():
                    raise ValueError("客体 CPU 控制组终止入口不可核查")
                print("CPU_BUDGET_REACHED", usage, flush=True)
                kill.write_text("1\n", encoding="ascii")
                subprocess.run(["/usr/bin/systemctl", "stop", arguments.unit], check=True, timeout=30,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                break
        else:
            raise ValueError("客体 CPU 累计用量不可核查")
    elif state == "activating":
        observed = True
    elif observed:
        break
    elif time.monotonic() >= deadline:
        raise TimeoutError("客体工作服务未启动")
    time.sleep(0.1)
