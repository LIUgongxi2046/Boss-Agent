import asyncio
import os
import sys
from pathlib import Path
from uuid import UUID

from dbus_next import BusType
from dbus_next.aio import MessageBus


SYSTEMD = "org.freedesktop.systemd1"
MANAGER_PATH = "/org/freedesktop/systemd1"
UNIT_INTERFACE = "org.freedesktop.systemd1.Unit"
SERVICE_INTERFACE = "org.freedesktop.systemd1.Service"
PROPERTIES = "org.freedesktop.DBus.Properties"


class HermesGuestUnitWatch:
    def __init__(self, bus, manager, run_id, epoch, boot_id):
        self.bus, self.manager = bus, manager
        self.run_id, self.epoch, self.boot_id = run_id, epoch, boot_id
        self.unit = "boss-" + run_id + "-" + str(epoch) + ".service"
        self.event = asyncio.Event()
        self.transferred = False

    @classmethod
    async def prepare(cls, run_id, epoch, boot_id):
        if sys.platform != "linux" or os.geteuid() != 0:
            raise ValueError("客体 unit 监督需要 Linux 系统管理权限")
        if not isinstance(run_id, str) or str(UUID(run_id)) != run_id or type(epoch) is not int or epoch <= 0:
            raise ValueError("客体 unit 身份无效")
        if not isinstance(boot_id, str) or str(UUID(boot_id)) != boot_id or Path("/proc/sys/kernel/random/boot_id").read_text(encoding="ascii").strip() != boot_id:
            raise ValueError("客体启动身份不可核查")
        bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
        ready = False
        try:
            xml = await bus.introspect(SYSTEMD, MANAGER_PATH)
            manager = bus.get_proxy_object(SYSTEMD, MANAGER_PATH, xml).get_interface(SYSTEMD + ".Manager")
            watch = cls(bus, manager, run_id, epoch, boot_id)
            manager.on_unit_new(watch.unit_new)
            await manager.call_subscribe()
            ready = True
            return watch
        finally:
            if not ready:
                bus.disconnect()

    def unit_new(self, unit, path):
        if unit == self.unit:
            self.event.set()

    async def acquire(self):
        await asyncio.wait_for(self.event.wait(), timeout=15)
        path = await self.manager.call_get_unit(self.unit)
        xml = await self.bus.introspect(SYSTEMD, path)
        obj = self.bus.get_proxy_object(SYSTEMD, path, xml)
        reference = obj.get_interface(UNIT_INTERFACE)
        properties = obj.get_interface(PROPERTIES)
        await reference.call_ref()
        result = HermesGuestUnitReference(self.bus, self.unit, self.boot_id, properties, reference)
        async with asyncio.timeout(15):
            while (await properties.call_get(UNIT_INTERFACE, "ActiveState")).value != "active":
                await asyncio.sleep(0.05)
        observed = await result.observe()
        if observed["control_group"] != "/system.slice/" + self.unit or len(observed["invocation"]) != 16 or not any(observed["invocation"]):
            raise ValueError("客体 unit 身份不可核查")
        result.invocation = observed["invocation"]
        self.manager.off_unit_new(self.unit_new)
        await self.manager.call_unsubscribe()
        self.transferred = True
        return result

    def close(self):
        if not self.transferred:
            self.bus.disconnect()


class HermesGuestUnitReference:
    def __init__(self, bus, unit, boot_id, properties, reference):
        self.bus = bus
        self.unit = unit
        self.boot_id = boot_id
        self.properties = properties
        self.reference = reference
        self.invocation = None

    @classmethod
    async def acquire(cls, run_id, epoch, boot_id):
        if sys.platform != "linux" or os.geteuid() != 0:
            raise ValueError("客体 unit 引用需要 Linux 系统管理权限")
        if not isinstance(run_id, str) or str(UUID(run_id)) != run_id or type(epoch) is not int or epoch <= 0:
            raise ValueError("客体 unit 身份无效")
        if not isinstance(boot_id, str) or str(UUID(boot_id)) != boot_id or Path("/proc/sys/kernel/random/boot_id").read_text(encoding="ascii").strip() != boot_id:
            raise ValueError("客体启动身份不可核查")
        unit = "boss-" + run_id + "-" + str(epoch) + ".service"
        bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
        acquired = False
        try:
            manager_xml = await bus.introspect(SYSTEMD, MANAGER_PATH)
            manager = bus.get_proxy_object(SYSTEMD, MANAGER_PATH, manager_xml).get_interface(SYSTEMD + ".Manager")
            path = await manager.call_get_unit(unit)
            unit_xml = await bus.introspect(SYSTEMD, path)
            obj = bus.get_proxy_object(SYSTEMD, path, unit_xml)
            reference = obj.get_interface(UNIT_INTERFACE)
            properties = obj.get_interface(PROPERTIES)
            await reference.call_ref()
            result = cls(bus, unit, boot_id, properties, reference)
            observed = await result.observe()
            if observed["id"] != unit or observed["state"] != "active" or observed["control_group"] != "/system.slice/" + unit:
                raise ValueError("客体 unit 引用与运行不匹配")
            if len(observed["invocation"]) != 16 or not any(observed["invocation"]):
                raise ValueError("客体 unit 执行身份不可核查")
            result.invocation = observed["invocation"]
            acquired = True
            return result
        finally:
            if not acquired:
                bus.disconnect()

    async def observe(self):
        if Path("/proc/sys/kernel/random/boot_id").read_text(encoding="ascii").strip() != self.boot_id:
            raise ValueError("客体启动身份已经变化")
        async with asyncio.timeout(5):
            unit = await self.properties.call_get_all(UNIT_INTERFACE)
            service = await self.properties.call_get_all(SERVICE_INTERFACE)
        invocation = bytes(unit["InvocationID"].value)
        result = {"id": unit["Id"].value, "state": unit["ActiveState"].value,
                  "control_group": service["ControlGroup"].value, "invocation": invocation,
                  "cpu_ns": service["CPUUsageNSec"].value, "kill_mode": service["KillMode"].value,
                  "result": service["Result"].value}
        if result["id"] != self.unit or self.invocation is not None and invocation != self.invocation:
            raise ValueError("客体 unit 执行身份已经变化")
        if type(result["cpu_ns"]) is not int or not 0 <= result["cpu_ns"] < 2**64 - 1:
            raise ValueError("客体 CPU 统计不可核查")
        return result

    async def close(self):
        try:
            async with asyncio.timeout(5):
                await self.reference.call_unref()
        finally:
            self.bus.disconnect()
