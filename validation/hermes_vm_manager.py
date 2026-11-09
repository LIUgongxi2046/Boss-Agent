import hashlib
import fcntl
import json
import os
import re
import stat
import subprocess
from pathlib import Path

from hermes_vm_channel import HermesVMServerTLS
from hermes_vm_credentials import load_vm_credential_pair, vm_id_from_machine_sha256
from hermes_vm_host import HermesVMControlClient, HermesVMHostClient
from hermes_vm_identity import HermesVMRunAccess, HermesVMRunBindings


_MANAGER_TOKEN = object()


def require_guest_policy(guest_policy):
    if not isinstance(guest_policy, dict) or set(guest_policy) != {"memory_bytes", "processes", "cpu_percent"} or any(type(value) is not int or value <= 0 for value in guest_policy.values()):
        raise ValueError("虚拟机运行配置无效")
    if guest_policy["memory_bytes"] > 2 * 1024 * 1024 * 1024 or guest_policy["cpu_percent"] > 200:
        raise ValueError("虚拟机客体资源额度超出环境范围")


def require_diagnostic_stderr(descriptor):
    if descriptor is None:
        return subprocess.DEVNULL
    if type(descriptor) is not int:
        raise ValueError("虚拟机诊断文件描述符无效")
    info = os.fstat(descriptor)
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077 or info.st_nlink != 1:
        raise ValueError("虚拟机诊断文件权限无效")
    if fcntl.fcntl(descriptor, fcntl.F_GETFL) & os.O_ACCMODE == os.O_RDONLY:
        raise ValueError("虚拟机诊断文件不可写")
    return descriptor


def require_workspace_ports(ports, runtime_port, control_port):
    if not isinstance(ports, (list, tuple)) or len(ports) > 16:
        raise ValueError("虚拟机工作区通信端口无效")
    pairs = []
    for pair in ports:
        if not isinstance(pair, (list, tuple)) or len(pair) != 2:
            raise ValueError("虚拟机工作区通信端口无效")
        guest, host = pair
        if type(guest) is not int or not 1026 <= guest <= 0xffffffff or type(host) is not int or not 1 <= host <= 65535 or host in {runtime_port, control_port}:
            raise ValueError("虚拟机工作区通信端口无效")
        pairs.append((guest, host))
    if len({pair[0] for pair in pairs}) != len(pairs) or len({pair[1] for pair in pairs}) != len(pairs):
        raise ValueError("虚拟机工作区通信端口重复")
    return tuple(pairs)


def require_workspace_port_sets(forwards, reverse, runtime_port, control_port):
    forwards = require_workspace_ports(forwards, runtime_port, control_port)
    reverse = require_workspace_ports(reverse, runtime_port, control_port)
    if {item[0] for item in forwards} & {item[0] for item in reverse} or {item[1] for item in forwards} & {item[1] for item in reverse}:
        raise ValueError("虚拟机工作区通信端口重复")
    return forwards, reverse


class HermesVMLock:
    def __init__(self, directory):
        directory = Path(directory)
        if not directory.is_absolute() or directory.resolve(strict=True) != directory or not directory.is_dir():
            raise ValueError("虚拟机锁目录不可核查")
        info = directory.stat()
        if info.st_uid != os.getuid() or info.st_mode & 0o022:
            raise ValueError("虚拟机锁目录权限无效")
        descriptor = os.open(directory / "manager.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        acquired = False
        try:
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
                raise ValueError("虚拟机管理锁权限无效")
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            acquired = True
            self.descriptor = descriptor
        finally:
            if not acquired:
                os.close(descriptor)

    def require(self):
        os.fstat(self.descriptor)
        fcntl.flock(self.descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def close(self):
        fcntl.flock(self.descriptor, fcntl.LOCK_UN)
        os.close(self.descriptor)
        self.descriptor = -1


class HermesVMManager:
    def __init__(self, process, executable, directory, shared_directory, executable_sha256,
                 credentials_directory, runtime_port, control_port, guest_policy, *, workspace_ports=(), workspace_reverse_ports=(), vm_lock=None, token=None):
        if token is not _MANAGER_TOKEN:
            raise ValueError("虚拟机宿主进程必须由管理器创建")
        if not isinstance(vm_lock, HermesVMLock):
            raise ValueError("虚拟机管理锁不可核查")
        vm_lock.require()
        if type(runtime_port) is not int or not 1 <= runtime_port <= 65535 or type(control_port) is not int or not 1 <= control_port <= 65535 or runtime_port == control_port:
            raise ValueError("虚拟机通信端口无效")
        executable, directory, shared_directory = map(Path, (executable, directory, shared_directory))
        if not isinstance(process, subprocess.Popen) or process.poll() is not None:
            raise ValueError("虚拟机管理需要活动宿主进程")
        for path in (executable, directory, shared_directory):
            if not path.is_absolute() or path.resolve(strict=True) != path:
                raise ValueError("虚拟机管理路径不可核查")
        if not executable.is_file() or not directory.is_dir() or not shared_directory.is_dir():
            raise ValueError("虚拟机管理文件不可核查")
        if not isinstance(executable_sha256, str) or not re.fullmatch("[0-9a-f]{64}", executable_sha256):
            raise ValueError("虚拟机管理程序摘要无效")
        with executable.open("rb") as source:
            if hashlib.file_digest(source, "sha256").hexdigest() != executable_sha256:
                raise ValueError("虚拟机管理程序摘要不匹配")
        if not isinstance(process.args, (list, tuple)) or list(process.args) != [str(executable), str(directory), str(shared_directory)]:
            raise ValueError("虚拟机宿主进程参数不匹配")
        subprocess.run(["/usr/bin/codesign", "--verify", "--strict", str(executable)], check=True, timeout=15,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        result = subprocess.run([str(executable), "--check-identity", str(directory / "machine-identity")],
                                check=True, timeout=15, capture_output=True, text=True)
        fields = result.stdout.strip().split()
        if len(fields) != 2 or fields[0] != "VM_IDENTITY_SHA256" or re.fullmatch("[0-9a-f]{64}", fields[1]) is None:
            raise ValueError("虚拟机机器身份不可核查")
        vm_id = vm_id_from_machine_sha256(fields[1])
        credentials_directory = Path(credentials_directory)
        if not credentials_directory.is_absolute() or credentials_directory.resolve(strict=True) != credentials_directory or shared_directory != credentials_directory / "guest":
            raise ValueError("虚拟机客体共享与凭据目录不匹配")
        credentials, _ = load_vm_credential_pair(credentials_directory, vm_id)
        require_guest_policy(guest_policy)
        self.control = HermesVMControlClient(credentials.client, credentials.peer_name, credentials.peer_sha256, control_port)
        self.process, self.vm_id = process, vm_id
        self.runtime_context, self.guest_runtime_sha256 = credentials.server, credentials.peer_sha256
        self.guest_policy = dict(guest_policy)
        self.runtime_port = runtime_port
        self.workspace_ports, self.workspace_reverse_ports = require_workspace_port_sets(workspace_ports, workspace_reverse_ports, runtime_port, control_port)
        self.vm_lock = vm_lock

    @classmethod
    def start(cls, executable, directory, credentials_directory, executable_sha256, runtime_port, control_port, guest_policy,
              *, dependencies_directory, engine_directory, workspace_ports=(), workspace_reverse_ports=(), diagnostic_stderr=None):
        diagnostic_stderr = require_diagnostic_stderr(diagnostic_stderr)
        if type(runtime_port) is not int or not 1 <= runtime_port <= 65535 or type(control_port) is not int or not 1 <= control_port <= 65535 or runtime_port == control_port:
            raise ValueError("虚拟机通信端口无效")
        require_guest_policy(guest_policy)
        workspace_ports, workspace_reverse_ports = require_workspace_port_sets(workspace_ports, workspace_reverse_ports, runtime_port, control_port)
        executable, directory, credentials_directory, dependencies_directory, engine_directory = map(
            Path, (executable, directory, credentials_directory, dependencies_directory, engine_directory))
        shared_directory = credentials_directory / "guest"
        for path in (executable, directory, credentials_directory, shared_directory, dependencies_directory, engine_directory):
            if not path.is_absolute() or path.resolve(strict=True) != path:
                raise ValueError("虚拟机管理路径不可核查")
        for path in (dependencies_directory, engine_directory):
            info = path.stat()
            if not path.is_dir() or info.st_uid != os.getuid() or info.st_mode & 0o022:
                raise ValueError("虚拟机只读共享目录不可核查")
        if not isinstance(executable_sha256, str) or re.fullmatch("[0-9a-f]{64}", executable_sha256) is None:
            raise ValueError("虚拟机管理程序摘要无效")
        with executable.open("rb") as source:
            if hashlib.file_digest(source, "sha256").hexdigest() != executable_sha256:
                raise ValueError("虚拟机管理程序摘要不匹配")
        subprocess.run(["/usr/bin/codesign", "--verify", "--strict", str(executable)], check=True, timeout=15,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        result = subprocess.run([str(executable), "--check-identity", str(directory / "machine-identity")],
                                check=True, timeout=15, capture_output=True, text=True)
        fields = result.stdout.strip().split()
        if len(fields) != 2 or fields[0] != "VM_IDENTITY_SHA256":
            raise ValueError("虚拟机机器身份不可核查")
        load_vm_credential_pair(credentials_directory, vm_id_from_machine_sha256(fields[1]))
        vm_lock = HermesVMLock(directory)
        accepted = False
        process = None
        try:
            environment = {"PATH": "/usr/bin:/bin", "BOSS_VSOCK_FORWARD_PORT": str(runtime_port),
                           "BOSS_VSOCK_CONTROL_PORT": str(control_port),
                           "BOSS_VSOCK_DEPENDENCIES": str(dependencies_directory),
                           "BOSS_VSOCK_ENGINE": str(engine_directory)}
            if workspace_ports:
                environment["BOSS_VSOCK_WORKSPACE_PORTS"] = json.dumps(
                    [{"guest_port": guest, "host_port": host} for guest, host in workspace_ports], separators=(",", ":"))
            if workspace_reverse_ports:
                environment["BOSS_VSOCK_WORKSPACE_REVERSE_PORTS"] = json.dumps(
                    [{"guest_port": guest, "host_port": host} for guest, host in workspace_reverse_ports], separators=(",", ":"))
            process = subprocess.Popen([str(executable), str(directory), str(shared_directory)], env=environment,
                                       stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=diagnostic_stderr,
                                       close_fds=True, pass_fds=(vm_lock.descriptor,), start_new_session=True)
            manager = cls(process, executable, directory, shared_directory, executable_sha256,
                          credentials_directory, runtime_port, control_port, guest_policy,
                          workspace_ports=workspace_ports, workspace_reverse_ports=workspace_reverse_ports, vm_lock=vm_lock, token=_MANAGER_TOKEN)
            accepted = True
            return manager
        finally:
            if not accepted:
                if process is not None and process.poll() is None:
                    process.terminate()
                    process.wait(timeout=15)
                vm_lock.close()

    def require_live(self, access):
        if not isinstance(access, HermesVMRunAccess) or access.vm_id != self.vm_id or self.process.poll() is not None:
            raise ValueError("虚拟机宿主进程或机器身份不可核查")
        self.vm_lock.require()

    def require_workspace_port(self, access, guest_port):
        self.require_live(access)
        access.require_workspace_context()
        ports = [host for guest, host in self.workspace_ports if guest == guest_port]
        if len(ports) != 1:
            raise ValueError("虚拟机工作区通信端口未配置")
        return ports[0]

    def require_workspace_reverse_port(self, access, guest_port):
        self.require_live(access)
        access.require_workspace_context()
        ports = [host for guest, host in self.workspace_reverse_ports if guest == guest_port]
        if len(ports) != 1:
            raise ValueError("虚拟机工作区反向通信端口未配置")
        return ports[0]

    def release_stopped(self):
        if self.process.poll() is None:
            raise ValueError("虚拟机宿主进程仍在运行")
        self.vm_lock.close()

    def stop(self):
        if self.process.poll() is not None:
            raise ValueError("虚拟机宿主进程已经结束")
        self.process.terminate()
        if self.process.wait(timeout=30) != 0:
            raise ValueError("虚拟机未正常关闭")
        self.release_stopped()

    def prepare(self, sink, request_key, workspace, budget):
        if self.process.poll() is not None:
            raise ValueError("虚拟机宿主进程已经结束")
        boot_id = self.control.identity()
        if self.process.poll() is not None:
            raise ValueError("虚拟机宿主进程已经结束")
        access = HermesVMRunAccess(HermesVMRunBindings(sink.store), sink.config.run_id, request_key,
                                   sink.lease_owner, sink.config.lease_epoch, self.vm_id, boot_id, workspace)
        host = HermesVMHostClient(access, self.control.context, self.control.guest_name,
                                  self.control.guest_certificate_sha256, self.control.control_port)
        server_tls = HermesVMServerTLS(self.runtime_context, self.guest_runtime_sha256, access)
        from hermes_cpu_budget import vm_cpu_allocation_seconds
        guest_budget = {**self.guest_policy, "rounds": budget["rounds"], "seconds": budget["seconds"],
                        "open_files": budget["open_files"], "files": budget["files"], "file_bytes": budget["file_bytes"],
                        "cpu_seconds": vm_cpu_allocation_seconds(budget)}
        return host, server_tls, guest_budget
