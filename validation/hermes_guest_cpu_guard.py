import argparse
import asyncio
import ctypes
import re
import subprocess
import time
from pathlib import Path

from dbus_next import BusType
from dbus_next.aio import MessageBus

from hermes_guest_slice import work_group


SYSTEMD = "org.freedesktop.systemd1"
UNIT_INTERFACE = SYSTEMD + ".Unit"
SERVICE_INTERFACE = SYSTEMD + ".Service"
PROPERTIES = "org.freedesktop.DBus.Properties"


def notify_watchdog(library):
    if library.sd_notify(0, b"WATCHDOG=1") <= 0:
        raise ValueError("客体 CPU 监督心跳不可核查")


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("unit")
    parser.add_argument("cpu_seconds", type=int)
    arguments = parser.parse_args()
    match = re.fullmatch(r"boss-([0-9a-f-]{36})-([1-9][0-9]*)\.service", arguments.unit)
    if match is None or arguments.cpu_seconds <= 0:
        raise ValueError("客体 CPU 监督参数无效")
    library = ctypes.CDLL("libsystemd.so.0")
    library.sd_notify.argtypes = (ctypes.c_int, ctypes.c_char_p)
    library.sd_notify.restype = ctypes.c_int
    notify_watchdog(library)
    bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
    try:
        manager_xml = await bus.introspect(SYSTEMD, "/org/freedesktop/systemd1")
        manager = bus.get_proxy_object(SYSTEMD, "/org/freedesktop/systemd1", manager_xml).get_interface(SYSTEMD + ".Manager")
        deadline = time.monotonic() + 15
        observed = False
        properties = None
        invocation = None
        unit_path = None
        expected_group = work_group(match.group(1), int(match.group(2)))
        while True:
            units = await manager.call_list_units_by_names([arguments.unit])
            if len(units) > 1 or units and (len(units[0]) != 10 or units[0][0] != arguments.unit):
                raise ValueError("客体 CPU 监督 unit 身份不可核查")
            state = units[0][3] if units else "inactive"
            if state == "active":
                observed = True
                if properties is None:
                    path = units[0][6]
                    xml = await bus.introspect(SYSTEMD, path)
                    properties = bus.get_proxy_object(SYSTEMD, path, xml).get_interface(PROPERTIES)
                    unit_path = path
                elif units[0][6] != unit_path:
                    raise ValueError("客体 CPU 监督 unit 路径已经变化")
                unit = await properties.call_get_all(UNIT_INTERFACE)
                service = await properties.call_get_all(SERVICE_INTERFACE)
                if unit["Id"].value != arguments.unit or unit["ActiveState"].value != "active" or service["ControlGroup"].value != expected_group:
                    raise ValueError("客体 CPU 工作控制组不可核查")
                current = bytes(unit["InvocationID"].value)
                if len(current) != 16 or not any(current) or invocation is not None and current != invocation:
                    raise ValueError("客体 CPU 监督执行身份不可核查")
                invocation = current
                usage = service["CPUUsageNSec"].value
                if type(usage) is not int or not 0 <= usage < 2**64 - 1:
                    raise ValueError("客体 CPU 累计用量不可核查")
                if usage >= arguments.cpu_seconds * 1_000_000_000:
                    kill = Path("/sys/fs/cgroup") / expected_group.lstrip("/") / "cgroup.kill"
                    if not kill.is_file() or kill.is_symlink():
                        raise ValueError("客体 CPU 控制组终止入口不可核查")
                    print("CPU_BUDGET_REACHED", usage, flush=True)
                    kill.write_text("1\n", encoding="ascii")
                    subprocess.run(["/usr/bin/systemctl", "stop", arguments.unit], check=True, timeout=30,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    break
            elif state == "activating":
                observed = True
            elif observed:
                break
            elif time.monotonic() >= deadline:
                raise TimeoutError("客体工作服务未启动")
            notify_watchdog(library)
            await asyncio.sleep(0.1)
    finally:
        bus.disconnect()


asyncio.run(main())
