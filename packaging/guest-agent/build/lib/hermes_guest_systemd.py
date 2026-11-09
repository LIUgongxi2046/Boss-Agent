import json
import os
import re
import subprocess
import sys
from pathlib import Path
from uuid import UUID

from hermes_guest_identity import HermesGuestIdentityRegistry
from hermes_guest_slice import slice_name, work_group
from hermes_guest_workspace_directory import prepare_private_workspace
from hermes_guest_workspace_service import HermesGuestWorkspaceService


class HermesGuestSystemd:
    def __init__(self, *, python, entry, engine, dependencies, workspace_root, identities, supervisor_unit, workspace_service=None):
        if sys.platform != "linux" or os.geteuid() != 0:
            raise ValueError("客体运行管理需要 Linux 系统管理权限")
        self.python, self.entry, self.engine, self.dependencies, self.workspace_root = map(
            Path, (python, entry, engine, dependencies, workspace_root))
        for path in (self.python, self.entry, self.engine, self.dependencies, self.workspace_root):
            if not path.is_absolute() or path.resolve(strict=True) != path or any(character.isspace() or character == ":" for character in str(path)):
                raise ValueError("客体运行路径不可核查")
        if not self.python.is_file() or not os.access(self.python, os.X_OK) or not self.entry.is_file() or not self.engine.is_dir() or not self.dependencies.is_dir() or not self.workspace_root.is_dir():
            raise ValueError("客体运行文件不可核查")
        self.adapter = Path(__file__).resolve(strict=True).parent
        if self.entry != self.adapter / "hermes_engine_entry.py":
            raise ValueError("客体引擎入口与适配目录不一致")
        adapter_info = self.adapter.stat()
        if adapter_info.st_uid != 0 or adapter_info.st_mode & 0o022:
            raise ValueError("客体引擎适配目录权限无效")
        for name in ("hermes_engine_entry.py", "hermes_tool_registration.py", "hermes_transport_client.py", "hermes_tool_names.py"):
            item = self.adapter / name
            if item.is_symlink() or not item.is_file() or item.resolve(strict=True) != item or item.stat().st_uid != 0 or item.stat().st_mode & 0o022:
                raise ValueError("客体引擎适配文件不可核查")
        if not isinstance(identities, HermesGuestIdentityRegistry):
            raise ValueError("客体运行需要持久账号登记")
        if not isinstance(workspace_service, HermesGuestWorkspaceService) or workspace_service.identities is not identities or workspace_service.root != self.workspace_root:
            raise ValueError("客体运行需要受管工作区服务")
        if not isinstance(supervisor_unit, str) or re.fullmatch(r"boss-[a-z0-9-]+\.service", supervisor_unit) is None:
            raise ValueError("客体监督服务无效")
        info = self.workspace_root.stat()
        if info.st_uid != 0 or info.st_mode & 0o077:
            raise ValueError("客体工作区根目录权限无效")
        self.identities = identities
        self.supervisor_unit = supervisor_unit
        self.workspace_service = workspace_service
        self.cpu_guard = Path(__file__).with_name("hermes_guest_cpu_guard.py")
        if not self.cpu_guard.is_file() or self.cpu_guard.is_symlink() or self.cpu_guard.resolve(strict=True) != self.cpu_guard:
            raise ValueError("客体 CPU 监督程序不可核查")

    def require_managed_workspace(self, run_id, epoch, boot_id, workspace):
        return self.workspace_service.require(run_id, epoch, boot_id, workspace)

    def prepare_managed_workspace(self, run_id, epoch, boot_id, workspace):
        return self.workspace_service.prepare(run_id, epoch, boot_id, workspace)

    def require_private_network(self, unit, proxy_unit):
        identities = []
        for name in (unit, proxy_unit):
            result = subprocess.run(["/usr/bin/systemctl", "show", name, "--property=MainPID", "--value"],
                                    check=True, capture_output=True, text=True, timeout=15)
            pid = int(result.stdout.strip())
            if pid <= 0:
                raise ValueError("客体网络服务进程不可核查")
            identities.append(os.stat("/proc/" + str(pid) + "/ns/net").st_ino)
        own = os.stat("/proc/self/ns/net").st_ino
        if identities[0] != identities[1] or identities[0] == own:
            raise ValueError("客体运行网络范围不可核查")

    def require_mounted_workspace(self, unit, workspace):
        result = subprocess.run(["/usr/bin/systemctl", "show", unit, "--property=MainPID", "--value"],
                                check=True, capture_output=True, text=True, timeout=15)
        pid = int(result.stdout.strip())
        if pid <= 0:
            raise ValueError("客体工作区进程不可核查")
        expected = os.stat(workspace)
        mounted = os.stat("/proc/" + str(pid) + "/root/mnt")
        if (expected.st_dev, expected.st_ino) != (mounted.st_dev, mounted.st_ino):
            raise ValueError("客体运行工作区挂载身份不匹配")

    def launch(self, run_id, epoch, boot_id, budget, bootstrap, *, workspace, proxy_unit, defer_bootstrap=False):
        managed_workspace, workspace_unit, workspace_guard_unit = self.require_managed_workspace(run_id, epoch, boot_id, workspace)
        if proxy_unit != "boss-runtime-proxy-" + run_id + "-" + str(epoch) + ".service":
            raise ValueError("客体运行代理身份不匹配")
        proxy_state = subprocess.run(["/usr/bin/systemctl", "show", proxy_unit, "--property=ActiveState", "--value"],
                                     check=True, capture_output=True, text=True, timeout=15)
        if proxy_state.stdout.strip() != "active":
            raise ValueError("客体运行代理尚未就绪")
        if type(defer_bootstrap) is not bool:
            raise ValueError("客体启动方式无效")
        for value in (run_id, boot_id):
            if not isinstance(value, str) or str(UUID(value)) != value:
                raise ValueError("客体运行身份无效")
        if Path("/proc/sys/kernel/random/boot_id").read_text(encoding="ascii").strip() != boot_id:
            raise ValueError("客体启动身份已经变化")
        if type(epoch) is not int or epoch <= 0:
            raise ValueError("客体租约版本无效")
        fields = {"rounds", "seconds", "memory_bytes", "processes", "cpu_percent", "open_files", "files", "file_bytes", "cpu_seconds"}
        if not isinstance(budget, dict) or set(budget) != fields or any(type(value) is not int or value <= 0 for value in budget.values()):
            raise ValueError("客体运行额度无效")
        required_bootstrap = {"endpoint", "capability", "provider_capability", "run_id", "engine_commit"}
        if not isinstance(bootstrap, dict) or set(bootstrap) not in (required_bootstrap, required_bootstrap | {"technical_check"}) or bootstrap["run_id"] != run_id:
            raise ValueError("客体启动信息无效")
        if "technical_check" in bootstrap:
            check = bootstrap["technical_check"]
            if not isinstance(check, dict) or set(check) != {"query", "path", "content", "hold_seconds"} or not isinstance(check["query"], dict) or not isinstance(check["path"], str) or not isinstance(check["content"], str) or type(check["hold_seconds"]) is not int or not 0 <= check["hold_seconds"] <= 20:
                raise ValueError("客体技术检查输入无效")
        encoded = json.dumps(bootstrap, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
        if len(encoded) > 4096:
            raise ValueError("客体启动信息过长")
        supervisor = subprocess.run(["/usr/bin/systemctl", "show", self.supervisor_unit, "--property=MainPID", "--value"],
                                    check=True, timeout=15, capture_output=True, text=True)
        if supervisor.stdout.strip() != str(os.getpid()):
            raise ValueError("客体监督服务身份不匹配")
        user, uid, gid = self.identities.ensure(run_id)
        workspace = prepare_private_workspace(managed_workspace.parent, run_id, uid, gid)
        if workspace != managed_workspace:
            raise ValueError("客体运行工作区身份不匹配")
        unit = "boss-" + run_id + "-" + str(epoch) + ".service"
        guard_unit = "boss-cpu-" + run_id + "-" + str(epoch) + ".service"
        run_slice = slice_name(run_id, epoch)
        slice_path = Path("/sys/fs/cgroup") / run_slice
        if slice_path.exists():
            raise ValueError("客体 slice 控制组已经存在")
        subprocess.run(["/usr/bin/systemctl", "start", run_slice], check=True, timeout=15,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        info = slice_path.stat()
        if not slice_path.is_dir() or info.st_uid != 0 or info.st_gid != 0 or info.st_mode & 0o022 or any(item.is_dir() for item in slice_path.iterdir()) or (slice_path / "cgroup.procs").read_text(encoding="ascii").strip():
            raise ValueError("客体 slice 权限不可核查")
        self.identities.record_exclusive_slice(run_id, epoch, boot_id)
        guard_command = ["/usr/bin/systemd-run", "--unit=" + guard_unit, "--property=Type=exec",
                         "--property=WatchdogSec=1s", "--property=NotifyAccess=all",
                         "--property=BindsTo=" + self.supervisor_unit, "--property=After=" + self.supervisor_unit,
                         str(self.python), str(self.cpu_guard), unit, str(budget["cpu_seconds"])]
        subprocess.run(guard_command, check=True, timeout=15, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        properties = ["Type=exec", "ExitType=cgroup", "KillMode=control-group", "TimeoutStopSec=5s", "SendSIGKILL=yes", "User=" + user,
                      "BindsTo=" + self.supervisor_unit, "After=" + self.supervisor_unit,
                      "BindsTo=" + workspace_unit, "After=" + workspace_unit,
                      "BindsTo=" + workspace_guard_unit, "After=" + workspace_guard_unit,
                      "BindsTo=" + proxy_unit, "After=" + proxy_unit, "JoinsNamespaceOf=" + proxy_unit,
                      "BindsTo=" + guard_unit, "After=" + guard_unit, "CPUAccounting=yes",
                      "WorkingDirectory=/mnt", "NoNewPrivileges=yes", "InaccessiblePaths=/tmp /var/tmp",
                      "Environment=TMPDIR=/mnt/.temporary", "Environment=HOME=/mnt",
                      "Environment=HERMES_HOME=/mnt/.hermes",
                      "Environment=PYTHONPATH=" + str(self.dependencies) + ":" + str(self.adapter), "Environment=PYTHONDONTWRITEBYTECODE=1",
                      "ProtectSystem=strict", "ProtectHome=yes", "RestrictSUIDSGID=yes", "PrivateUsers=yes",
                      "PrivateDevices=yes", "PrivateIPC=yes", "PrivateNetwork=yes", "TemporaryFileSystem=/dev/shm:mode=1777,size=" + str(budget["memory_bytes"]),
                      "ProtectProc=invisible", "ProcSubset=pid",
                      "TemporaryFileSystem=/run:ro",
                      "BindReadOnlyPaths=" + " ".join(map(str, (self.dependencies, self.engine, self.entry, self.adapter))),
                      "TemporaryFileSystem=" + str(self.workspace_root) + ":ro", "BindPaths=" + str(workspace) + ":/mnt",
                      "MemoryMax=" + str(budget["memory_bytes"]),
                      "TasksMax=" + str(budget["processes"]), "CPUQuota=" + str(budget["cpu_percent"]) + "%",
                      "RuntimeMaxSec=" + str(budget["seconds"]), "LimitNOFILE=" + str(budget["open_files"]),
                      "LimitFSIZE=" + str(budget["file_bytes"]), "LimitCPU=" + str(budget["cpu_seconds"])]
        command = ["/usr/bin/systemd-run", "--wait", "--pipe", "--unit=" + unit, "--slice=" + run_slice]
        for value in properties:
            command.append("--property=" + value)
        command.extend([str(self.python), str(self.entry), str(self.engine), "--max-rounds", str(budget["rounds"]),
                        "--max-seconds", str(budget["seconds"])])
        started = False
        try:
            process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                       close_fds=True, start_new_session=True)
            if defer_bootstrap:
                started = True
                return unit, process, encoded
            try:
                process.stdin.write(encoded)
            finally:
                process.stdin.close()
            started = True
            return unit, process
        finally:
            if not started:
                subprocess.run(["/usr/bin/systemctl", "stop", guard_unit], check=True, timeout=30,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def stop(self, run_id, epoch, *, missing_is_unknown=False):
        if not isinstance(run_id, str) or str(UUID(run_id)) != run_id or type(epoch) is not int or epoch <= 0 or type(missing_is_unknown) is not bool:
            raise ValueError("客体运行身份无效")
        unit = "boss-" + run_id + "-" + str(epoch) + ".service"
        load = subprocess.run(["/usr/bin/systemctl", "show", unit, "--property=LoadState", "--value"],
                              check=True, timeout=15, capture_output=True, text=True).stdout.strip()
        if load == "not-found":
            if missing_is_unknown:
                return "UNKNOWN"
            raise ValueError("客体工作服务尚未登记")
        if load != "loaded":
            raise ValueError("客体工作服务状态不可核查")
        subprocess.run(["/usr/bin/systemctl", "stop", unit], check=True, timeout=30, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return "UNKNOWN"

    def cpu_usage(self, run_id, epoch):
        if not isinstance(run_id, str) or str(UUID(run_id)) != run_id or type(epoch) is not int or epoch <= 0:
            raise ValueError("客体 CPU 运行身份无效")
        unit = "boss-" + run_id + "-" + str(epoch) + ".service"

        def property_value(name):
            return subprocess.run(["/usr/bin/systemctl", "show", unit, "--property=" + name, "--value"],
                                  check=True, timeout=15, capture_output=True, text=True).stdout.strip()

        if property_value("ActiveState") != "active" or property_value("ControlGroup") != work_group(run_id, epoch):
            raise ValueError("客体 CPU 控制组不可核查")
        value = property_value("CPUUsageNSec")
        if not value.isdecimal():
            raise ValueError("客体 CPU 累计用量不可核查")
        if property_value("ActiveState") != "active" or property_value("ControlGroup") != work_group(run_id, epoch):
            raise ValueError("客体 CPU 控制组已经变化")
        return int(value)

    def slice_cpu_usage(self, run_id, epoch):
        unit = "boss-" + run_id + "-" + str(epoch) + ".service"
        group_unit = slice_name(run_id, epoch)

        def property_value(target, name):
            return subprocess.run(["/usr/bin/systemctl", "show", target, "--property=" + name, "--value"],
                                  check=True, timeout=15, capture_output=True, text=True).stdout.strip()

        if property_value(unit, "ActiveState") != "active" or property_value(unit, "ControlGroup") != work_group(run_id, epoch):
            raise ValueError("客体工作控制组不可核查")
        if property_value(group_unit, "ActiveState") != "active" or property_value(group_unit, "ControlGroup") != "/" + group_unit:
            raise ValueError("客体 slice 控制组不可核查")
        value = property_value(group_unit, "CPUUsageNSec")
        if not value.isdecimal():
            raise ValueError("客体 slice CPU 累计用量不可核查")
        if property_value(unit, "ActiveState") != "active" or property_value(unit, "ControlGroup") != work_group(run_id, epoch):
            raise ValueError("客体工作控制组已经变化")
        return int(value)

    def final_slice_cpu_usage(self, run_id, epoch):
        group = slice_name(run_id, epoch)
        path = Path("/sys/fs/cgroup") / group

        def property_value(name):
            return subprocess.run(["/usr/bin/systemctl", "show", group, "--property=" + name, "--value"],
                                  check=True, timeout=15, capture_output=True, text=True).stdout.strip()

        info = path.stat()
        if not path.is_dir() or info.st_uid != 0 or info.st_gid != 0 or info.st_mode & 0o022:
            raise ValueError("客体最终 slice 权限不可核查")
        if property_value("ActiveState") != "active" or property_value("ControlGroup") != "/" + group or property_value("TasksCurrent") != "0":
            raise ValueError("客体最终 slice 状态不可核查")
        value = property_value("CPUUsageNSec")
        if not value.isdecimal() or not 0 <= int(value) < 2**63:
            raise ValueError("客体最终 slice CPU 不可核查")
        if property_value("ActiveState") != "active" or property_value("ControlGroup") != "/" + group or property_value("TasksCurrent") != "0":
            raise ValueError("客体最终 slice 状态已经变化")
        return int(value)

    def cleanup_final_slice(self, run_id, epoch, boot_id):
        receipt = self.identities.read_final_exit(run_id, epoch, boot_id)
        group = slice_name(run_id, epoch)
        if receipt["slice"] != group:
            raise ValueError("客体清理 slice 身份不匹配")
        if Path("/proc/sys/kernel/random/boot_id").read_text(encoding="ascii").strip() != boot_id and (Path("/sys/fs/cgroup") / group).exists():
            raise ValueError("客体启动已经变化，不能清理同名 slice")
        if not (Path("/sys/fs/cgroup") / group).exists():
            return
        subprocess.run(["/usr/bin/systemctl", "stop", group], check=True, timeout=30,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if (Path("/sys/fs/cgroup") / group).exists():
            raise ValueError("客体 slice 控制组尚未清理")
