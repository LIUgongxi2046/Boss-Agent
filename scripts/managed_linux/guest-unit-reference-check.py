import asyncio
import os
import subprocess
from pathlib import Path
from uuid import uuid4

from hermes_guest_unit_reference import HermesGuestUnitReference


async def main():
    run_id = str(uuid4())
    unit = "boss-" + run_id + "-1.service"
    boot_id = Path("/proc/sys/kernel/random/boot_id").read_text(encoding="ascii").strip()
    subprocess.run(["/usr/bin/systemd-run", "--unit=" + unit, "--property=Type=exec",
                    "--property=CPUAccounting=yes", "--property=KillMode=control-group",
                    "/usr/bin/sleep", "30"], check=True, timeout=15)
    reference = None
    try:
        reference = await HermesGuestUnitReference.acquire(run_id, 1, boot_id)
        active = await reference.observe()
        if active["state"] != "active" or active["kill_mode"] != "control-group":
            raise ValueError("活动 unit 状态不可核查")
        group = Path("/sys/fs/cgroup") / active["control_group"].lstrip("/")
        descriptor = os.open(group / "cgroup.events", os.O_RDONLY | os.O_CLOEXEC)
        try:
            print("CGROUP_ACTIVE_EVENTS", repr(os.read(descriptor, 4096)), flush=True)
            subprocess.run(["/usr/bin/systemctl", "stop", unit], check=True, timeout=30)
            final = await reference.observe()
            print("SYSTEMD_FINAL_OBSERVATION", repr(final), flush=True)
            os.lseek(descriptor, 0, os.SEEK_SET)
            print("CGROUP_STOPPED_EVENTS", repr(os.read(descriptor, 4096)), flush=True)
        finally:
            os.close(descriptor)
        if final["state"] not in {"inactive", "failed"} or final["cpu_ns"] < active["cpu_ns"]:
            raise ValueError("退出后的 unit 统计不可核查")
        print("SYSTEMD_REFERENCE_CPU", active["cpu_ns"], final["cpu_ns"], "STATE", final["state"],
              "GROUP", repr(final["control_group"]), "RESULT", final["result"], flush=True)
    finally:
        if reference is not None:
            await reference.close()
        subprocess.run(["/usr/bin/systemctl", "stop", unit], check=True, timeout=30)


asyncio.run(main())
