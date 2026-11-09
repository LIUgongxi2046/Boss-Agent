import json
import os
import re
import subprocess
import sys
from pathlib import Path
from uuid import UUID

from hermes_guest_identity import HermesGuestIdentityRegistry


class HermesGuestSystemd:
    def __init__(self, *, python, entry, engine, dependencies, workspace_root, identities, supervisor_unit):
        if sys.platform != "linux" or os.geteuid() != 0:
            raise ValueError("客体运行管理需要 Linux 系统管理权限")
        self.python, self.entry, self.engine, self.dependencies, self.workspace_root = map(
            Path, (python, entry, engine, dependencies, workspace_root))
        for path in (self.python, self.entry, self.engine, self.dependencies, self.workspace_root):
            if not path.is_absolute() or path.resolve(strict=True) != path or any(character.isspace() or character == ":" for character in str(path)):
                raise ValueError("客体运行路径不可核查")
        if not self.python.is_file() or not os.access(self.python, os.X_OK) or not self.entry.is_file() or not self.engine.is_dir() or not self.dependencies.is_dir() or not self.workspace_root.is_dir():
            raise ValueError("客体运行文件不可核查")
        if not isinstance(identities, HermesGuestIdentityRegistry):
            raise ValueError("客体运行需要持久账号登记")
        if not isinstance(supervisor_unit, str) or re.fullmatch(r"boss-[a-z0-9-]+\.service", supervisor_unit) is None:
            raise ValueError("客体监督服务无效")
        info = self.workspace_root.stat()
        if info.st_uid != 0 or info.st_mode & 0o077:
            raise ValueError("客体工作区根目录权限无效")
        self.identities = identities
        self.supervisor_unit = supervisor_unit
        self.cpu_guard = Path(__file__).with_name("hermes_guest_cpu_guard.py")
        if not self.cpu_guard.is_file() or self.cpu_guard.is_symlink() or self.cpu_guard.resolve(strict=True) != self.cpu_guard:
            raise ValueError("客体 CPU 监督程序不可核查")

    def launch(self, run_id, epoch, boot_id, budget, bootstrap, *, defer_bootstrap=False):
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
        if not isinstance(bootstrap, dict) or set(bootstrap) != {"endpoint", "capability", "provider_capability", "run_id", "engine_commit"} or bootstrap["run_id"] != run_id:
            raise ValueError("客体启动信息无效")
        encoded = json.dumps(bootstrap, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
        if len(encoded) > 4096:
            raise ValueError("客体启动信息过长")
        supervisor = subprocess.run(["/usr/bin/systemctl", "show", self.supervisor_unit, "--property=MainPID", "--value"],
                                    check=True, timeout=15, capture_output=True, text=True)
        if supervisor.stdout.strip() != str(os.getpid()):
            raise ValueError("客体监督服务身份不匹配")
        user, uid, gid = self.identities.ensure(run_id)
        workspace = self.workspace_root / run_id
        if not workspace.exists():
            workspace.mkdir(mode=0o700)
        if workspace.is_symlink() or not workspace.is_dir() or workspace.resolve(strict=True) != workspace:
            raise ValueError("客体工作区不可核查")
        descriptor = os.open(workspace, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            info = os.fstat(descriptor)
            if info.st_uid == 0 and not os.listdir(descriptor) and not info.st_mode & 0o077:
                os.fchown(descriptor, uid, gid)
            info = os.fstat(descriptor)
        finally:
            os.close(descriptor)
        if info.st_uid != uid or info.st_gid != gid or info.st_mode & 0o077:
            raise ValueError("客体工作区权限不可核查")
        temporary = workspace / ".temporary"
        if not temporary.exists():
            temporary.mkdir(mode=0o700)
            descriptor = os.open(temporary, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                if os.fstat(descriptor).st_uid != 0:
                    raise ValueError("客体临时目录归属不可核查")
                os.fchown(descriptor, uid, gid)
            finally:
                os.close(descriptor)
        if temporary.is_symlink() or not temporary.is_dir() or temporary.resolve(strict=True) != temporary:
            raise ValueError("客体临时目录不可核查")
        info = temporary.stat()
        if info.st_uid != uid or info.st_gid != gid or info.st_mode & 0o077:
            raise ValueError("客体临时目录权限不可核查")
        unit = "boss-" + run_id + "-" + str(epoch) + ".service"
        guard_unit = "boss-cpu-" + run_id + "-" + str(epoch) + ".service"
        guard_command = ["/usr/bin/systemd-run", "--unit=" + guard_unit, "--property=Type=exec",
                         "--property=WatchdogSec=1s", "--property=NotifyAccess=all",
                         "--property=BindsTo=" + self.supervisor_unit, "--property=After=" + self.supervisor_unit,
                         str(self.python), str(self.cpu_guard), unit, str(budget["cpu_seconds"])]
        subprocess.run(guard_command, check=True, timeout=15, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        properties = ["Type=exec", "KillMode=control-group", "User=" + user,
                      "BindsTo=" + self.supervisor_unit, "After=" + self.supervisor_unit,
                      "BindsTo=" + guard_unit, "After=" + guard_unit, "CPUAccounting=yes",
                      "WorkingDirectory=/mnt", "NoNewPrivileges=yes", "InaccessiblePaths=/tmp /var/tmp",
                      "Environment=TMPDIR=/mnt/.temporary", "Environment=HOME=/mnt",
                      "Environment=HERMES_HOME=/mnt/.hermes",
                      "Environment=PYTHONPATH=" + str(self.dependencies), "Environment=PYTHONDONTWRITEBYTECODE=1",
                      "ProtectSystem=strict", "ProtectHome=yes", "RestrictSUIDSGID=yes", "PrivateUsers=yes",
                      "PrivateDevices=yes", "PrivateIPC=yes", "TemporaryFileSystem=/dev/shm:mode=1777,size=" + str(budget["memory_bytes"]),
                      "ProtectProc=invisible", "ProcSubset=pid",
                      "TemporaryFileSystem=/run:ro",
                      "BindReadOnlyPaths=" + " ".join(map(str, (self.dependencies, self.engine, self.entry))),
                      "TemporaryFileSystem=" + str(self.workspace_root) + ":ro", "BindPaths=" + str(workspace) + ":/mnt",
                      "MemoryMax=" + str(budget["memory_bytes"]),
                      "TasksMax=" + str(budget["processes"]), "CPUQuota=" + str(budget["cpu_percent"]) + "%",
                      "RuntimeMaxSec=" + str(budget["seconds"]), "LimitNOFILE=" + str(budget["open_files"]),
                      "LimitFSIZE=" + str(budget["file_bytes"]), "LimitCPU=" + str(budget["cpu_seconds"])]
        command = ["/usr/bin/systemd-run", "--wait", "--pipe", "--unit=" + unit]
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

    def stop(self, run_id, epoch):
        if not isinstance(run_id, str) or str(UUID(run_id)) != run_id or type(epoch) is not int or epoch <= 0:
            raise ValueError("客体运行身份无效")
        unit = "boss-" + run_id + "-" + str(epoch) + ".service"
        subprocess.run(["/usr/bin/systemctl", "stop", unit], check=True, timeout=30, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return "UNKNOWN"

    def cpu_usage(self, run_id, epoch):
        if not isinstance(run_id, str) or str(UUID(run_id)) != run_id or type(epoch) is not int or epoch <= 0:
            raise ValueError("客体 CPU 运行身份无效")
        unit = "boss-" + run_id + "-" + str(epoch) + ".service"

        def property_value(name):
            return subprocess.run(["/usr/bin/systemctl", "show", unit, "--property=" + name, "--value"],
                                  check=True, timeout=15, capture_output=True, text=True).stdout.strip()

        if property_value("ActiveState") != "active" or property_value("ControlGroup") != "/system.slice/" + unit:
            raise ValueError("客体 CPU 控制组不可核查")
        value = property_value("CPUUsageNSec")
        if not value.isdecimal():
            raise ValueError("客体 CPU 累计用量不可核查")
        if property_value("ActiveState") != "active" or property_value("ControlGroup") != "/system.slice/" + unit:
            raise ValueError("客体 CPU 控制组已经变化")
        return int(value)
