import fcntl
import hashlib
import json
import os
import re
import sqlite3
import stat
import subprocess
import sys
import threading
from pathlib import Path
from uuid import UUID

from hermes_guest_identity import HermesGuestIdentityRegistry
from hermes_guest_workspace_directory import prepare_private_workspace


class HermesGuestWorkspaceService:
    def __init__(self, root, binary, binary_sha256, identities, supervisor_unit):
        if sys.platform != "linux" or os.geteuid() != 0:
            raise ValueError("受管工作区需要 Linux 系统管理权限")
        self.root, self.binary = Path(root), Path(binary)
        for path in (self.root, self.binary):
            if not path.is_absolute() or path.resolve(strict=True) != path:
                raise ValueError("受管工作区路径不可核查")
        if not self.root.is_dir() or not self.binary.is_file() or not os.access(self.binary, os.X_OK):
            raise ValueError("受管工作区文件不可核查")
        info = self.root.stat()
        if info.st_uid != 0 or stat.S_IMODE(info.st_mode) != 0o700:
            raise ValueError("受管工作区根目录权限无效")
        info = self.binary.stat()
        if info.st_uid != 0 or info.st_mode & 0o022 or not isinstance(binary_sha256, str) or len(binary_sha256) != 64:
            raise ValueError("受管工作区程序身份无效")
        with self.binary.open("rb") as source:
            if hashlib.file_digest(source, "sha256").hexdigest() != binary_sha256:
                raise ValueError("受管工作区程序摘要不匹配")
        if not isinstance(identities, HermesGuestIdentityRegistry):
            raise ValueError("受管工作区需要持久身份登记")
        if not isinstance(supervisor_unit, str) or re.fullmatch(r"boss-[a-z0-9-]+\.service", supervisor_unit) is None:
            raise ValueError("受管工作区监督服务无效")
        self.identities, self.supervisor_unit = identities, supervisor_unit
        self.domains = {}
        self.runs = {}
        self.lock = threading.RLock()

    def _command(self, *args):
        return subprocess.run([str(self.binary), *map(str, args)], check=True, timeout=120)

    @staticmethod
    def _systemctl(*args):
        return subprocess.run(["/usr/bin/systemctl", *args], check=True, timeout=30,
                              capture_output=True, text=True).stdout.strip()

    @staticmethod
    def _mount_entries(path):
        result = subprocess.run(["/usr/bin/findmnt", "--kernel", "--list", "--json", "--output", "TARGET,FSTYPE,SOURCE"],
                                check=True, capture_output=True, text=True, timeout=15)
        entries = [entry for entry in json.loads(result.stdout)["filesystems"] if entry["target"] == str(path)]
        if len(entries) > 1:
            raise ValueError("受管工作区存在多个挂载")
        return entries

    @classmethod
    def _mounted(cls, path):
        return bool(cls._mount_entries(path))

    @classmethod
    def _mount_identity(cls, path):
        entries = cls._mount_entries(path)
        if len(entries) != 1 or entries[0]["target"] != str(path) or entries[0]["fstype"] != "fuse.juicefs":
            raise ValueError("受管工作区挂载身份不可核查")
        return entries[0]["source"]

    def _binding(self, run_id, epoch, boot_id, workspace):
        if not isinstance(run_id, str) or str(UUID(run_id)) != run_id or type(epoch) is not int or epoch <= 0:
            raise ValueError("受管工作区运行身份无效")
        if not isinstance(boot_id, str) or str(UUID(boot_id)) != boot_id:
            raise ValueError("受管工作区启动身份无效")
        if Path("/proc/sys/kernel/random/boot_id").read_text(encoding="ascii").strip() != boot_id:
            raise ValueError("受管工作区启动身份已经变化")
        if not isinstance(workspace, dict) or set(workspace) != {"root_run_id", "root_epoch", "max_files", "max_bytes"}:
            raise ValueError("受管工作区根身份无效")
        root_id = workspace["root_run_id"]
        if not isinstance(root_id, str) or str(UUID(root_id)) != root_id or any(type(workspace[name]) is not int or workspace[name] <= 0 for name in ("root_epoch", "max_files", "max_bytes")):
            raise ValueError("受管工作区根额度无效")
        expected = (boot_id, root_id, workspace["root_epoch"], workspace["max_files"], workspace["max_bytes"])
        with self.identities.connect() as db:
            row = db.execute("SELECT boot_id,root_run_id,root_epoch,max_files,max_bytes FROM guest_workspace_bindings WHERE run_id=? AND epoch=?", (run_id, epoch)).fetchone()
            control = db.execute("SELECT state FROM guest_control WHERE run_id=? AND epoch=? AND boot_id=?", (run_id, epoch, boot_id)).fetchone()
        if row != expected or control != ("RESERVED",):
            raise ValueError("受管工作区持久身份不可核查")
        return root_id

    @staticmethod
    def _quota(metadata, max_files, max_bytes):
        with sqlite3.connect(metadata.as_uri() + "?mode=ro", uri=True) as db:
            rows = db.execute("SELECT q.max_inodes,q.max_space FROM jfs_dir_quota q JOIN jfs_edge e ON e.inode=q.inode WHERE e.parent=1 AND e.name=?", (b"shared",)).fetchall()
        if rows != [(max_files, max_bytes)]:
            raise ValueError("受管工作区配额不可核查")

    def prepare(self, run_id, epoch, boot_id, workspace):
        with self.lock:
            return self._prepare(run_id, epoch, boot_id, workspace)

    def _prepare(self, run_id, epoch, boot_id, workspace):
        root_id = self._binding(run_id, epoch, boot_id, workspace)
        if self._systemctl("show", self.supervisor_unit, "--property=MainPID", "--value") != str(os.getpid()):
            raise ValueError("受管工作区监督身份不可核查")
        key = (run_id, epoch)
        if key in self.runs:
            return self.require(run_id, epoch, boot_id, workspace)
        state = self.domains.get(root_id)
        if state is None and run_id != root_id:
            raise ValueError("子运行需要已经准备的根运行工作区")
        if state is None:
            domain = self.root / root_id
            fresh = not domain.exists()
            if fresh:
                domain.mkdir(mode=0o700)
                for name in ("objects", "cache", "mount"):
                    (domain / name).mkdir(mode=0o700)
            if domain.is_symlink() or domain.resolve(strict=True) != domain or domain.stat().st_uid != 0 or stat.S_IMODE(domain.stat().st_mode) != 0o700:
                raise ValueError("受管工作区额度域不可核查")
            lock = os.open(domain / "owner.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
            accepted = False
            attempted = False
            guard_attempted = False
            try:
                info = os.fstat(lock)
                if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o077 or info.st_nlink != 1:
                    raise ValueError("受管工作区排他锁不可核查")
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                mount = domain / "mount"
                metadata = domain / "metadata.db"
                suffix = root_id + "-" + run_id + "-" + str(epoch) + ".service"
                unit = "boss-workspace-" + suffix
                init_unit = "boss-workspace-init-" + suffix
                active_unit = init_unit if fresh else unit
                if not fresh:
                    self._quiesce(root_id, run_id, epoch, mount)
                if self._mounted(mount) or self._systemctl("show", unit, "--property=ActiveState", "--value") not in {"inactive", "failed"} or self._systemctl("show", init_unit, "--property=ActiveState", "--value") not in {"inactive", "failed"}:
                    raise ValueError("受管工作区旧访问尚未停止")
                meta_url = "sqlite3://" + str(metadata)
                if fresh:
                    self._command("format", "--storage", "file", "--bucket", domain / "objects", "--trash-days", "0", meta_url, "boss-" + root_id)
                else:
                    if self._systemctl("show", "nfs-server.service", "--property=ActiveState", "--value") not in {"inactive", "failed"}:
                        raise ValueError("受管工作区旧文件服务尚未停止")
                    self._quota(metadata, workspace["max_files"], workspace["max_bytes"])
                    self._command("quota", "check", "--path", "/shared", "--strict", "--repair", meta_url)
                    self._command("quota", "check", "--path", "/shared", "--strict", meta_url)
                command = ["/usr/bin/systemd-run", "--unit=" + active_unit.removesuffix(".service"), "--property=Type=forking",
                           "--property=BindsTo=" + self.supervisor_unit, "--property=After=" + self.supervisor_unit,
                           str(self.binary), "mount", "--no-usage-report", "--no-syslog", "--background", "--no-bgjob",
                           "--backup-meta", "0", "--cache-dir", str(domain / "cache"), "--cache-size", "32", "--buffer-size", "32", meta_url, str(mount)]
                attempted = True
                subprocess.run(command, check=True, timeout=120)
                source = self._mount_identity(mount)
                if fresh:
                    (mount / "shared").mkdir(mode=0o700)
                    self._command("quota", "set", "--path", "/shared", "--strict", "--capacity", str(workspace["max_bytes"]) + "B", "--inodes", str(workspace["max_files"]), meta_url)
                    self._command("quota", "check", "--path", "/shared", "--strict", meta_url)
                    self._systemctl("stop", active_unit)
                    if self._mounted(mount):
                        subprocess.run(["/usr/bin/umount", "--no-canonicalize", str(mount)], check=True, timeout=30,
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    if self._mounted(mount):
                        raise ValueError("受管工作区初始化挂载仍然存在")
                    self._command("quota", "check", "--path", "/shared", "--strict", meta_url)
                    active_unit = unit
                    command[1] = "--unit=" + unit.removesuffix(".service")
                    subprocess.run(command, check=True, timeout=120)
                    source = self._mount_identity(mount)
                self._quota(metadata, workspace["max_files"], workspace["max_bytes"])
                guard_unit = "boss-workspace-guard-" + suffix
                guard = Path(__file__).with_name("hermes_guest_workspace_guard.py")
                if not guard.is_file() or guard.is_symlink() or guard.resolve(strict=True) != guard:
                    raise ValueError("受管工作区监督程序不可核查")
                guard_command = ["/usr/bin/systemd-run", "--unit=" + guard_unit.removesuffix(".service"),
                                 "--property=Type=exec", "--property=WatchdogSec=1s", "--property=NotifyAccess=all",
                                 "--property=BindsTo=" + unit, "--property=After=" + unit,
                                 sys.executable, str(guard), str(mount), source]
                guard_attempted = True
                subprocess.run(guard_command, check=True, timeout=15)
                state = (lock, unit, mount, source, workspace["root_epoch"], workspace["max_files"], workspace["max_bytes"], guard_unit)
                self.domains[root_id] = state
                accepted = True
            finally:
                if not accepted:
                    try:
                        try:
                            if guard_attempted:
                                self._systemctl("stop", guard_unit)
                        finally:
                            try:
                                if attempted:
                                    self._systemctl("stop", active_unit)
                            finally:
                                if self._mounted(domain / "mount"):
                                    subprocess.run(["/usr/bin/umount", "--no-canonicalize", str(domain / "mount")], check=True, timeout=30,
                                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    finally:
                        os.close(lock)
        if state[4:7] != (workspace["root_epoch"], workspace["max_files"], workspace["max_bytes"]):
            raise ValueError("受管工作区额度域已经变化")
        prepared = False
        try:
            self._require_domain(state)
            _, uid, gid = self.identities.ensure(run_id)
            directory = prepare_private_workspace(state[2] / "shared", run_id, uid, gid)
            info = directory.stat()
            self.runs[key] = (boot_id, root_id, directory, info.st_dev, info.st_ino)
            result = self.require(run_id, epoch, boot_id, workspace)
            prepared = True
            return result
        finally:
            if not prepared:
                if key in self.runs:
                    del self.runs[key]
                if not any(saved[1] == root_id for saved in self.runs.values()):
                    self._close_domain(root_id)

    def _require_domain(self, state):
        os.fstat(state[0])
        fcntl.flock(state[0], fcntl.LOCK_EX | fcntl.LOCK_NB)
        if self._systemctl("show", state[1], "--property=ActiveState", "--value") != "active" or self._systemctl("show", state[7], "--property=ActiveState", "--value") != "active" or self._mount_identity(state[2]) != state[3]:
            raise ValueError("受管工作区服务不可核查")

    def _quiesce(self, root_id, run_id, epoch, mount):
        if self._systemctl("show", "nfs-server.service", "--property=ActiveState", "--value") not in {"inactive", "failed"}:
            raise ValueError("受管工作区旧文件服务尚未停止")
        with self.identities.connect() as db:
            units = db.execute("SELECT c.unit,c.run_id,c.epoch FROM guest_control c JOIN guest_workspace_bindings b ON b.run_id=c.run_id AND b.epoch=c.epoch WHERE b.root_run_id=?", (root_id,)).fetchall()
        for unit, saved_run, saved_epoch in units:
            if (saved_run, saved_epoch) == (run_id, epoch):
                continue
            if self._systemctl("show", unit, "--property=ActiveState", "--value") not in {"inactive", "failed"}:
                self._systemctl("stop", unit)
            if self._systemctl("show", unit, "--property=ActiveState", "--value") not in {"inactive", "failed"}:
                raise ValueError("受管工作区旧运行尚未停止")
        previous_units = []
        for _, saved_run, saved_epoch in units:
            if (saved_run, saved_epoch) != (run_id, epoch):
                suffix = root_id + "-" + saved_run + "-" + str(saved_epoch) + ".service"
                previous_units.extend("boss-workspace-" + prefix + suffix for prefix in ("guard-", "", "init-"))
        for unit in previous_units:
            if self._systemctl("show", unit, "--property=ActiveState", "--value") not in {"inactive", "failed"}:
                self._systemctl("stop", unit)
            if self._systemctl("show", unit, "--property=ActiveState", "--value") not in {"inactive", "failed"}:
                raise ValueError("受管工作区旧服务尚未停止")
        if self._mounted(mount):
            subprocess.run(["/usr/bin/umount", "--no-canonicalize", str(mount)], check=True, timeout=30,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if self._mounted(mount):
            raise ValueError("受管工作区旧挂载仍然存在")

    def require(self, run_id, epoch, boot_id, workspace):
        with self.lock:
            return self._require(run_id, epoch, boot_id, workspace)

    def _require(self, run_id, epoch, boot_id, workspace):
        root_id = self._binding(run_id, epoch, boot_id, workspace)
        state, run = self.domains.get(root_id), self.runs.get((run_id, epoch))
        if state is None or run is None or run[:2] != (boot_id, root_id) or state[4:7] != (workspace["root_epoch"], workspace["max_files"], workspace["max_bytes"]):
            raise ValueError("受管工作区尚未准备")
        self._require_domain(state)
        directory = run[2]
        if directory.is_symlink() or directory.resolve(strict=True) != directory:
            raise ValueError("受管运行目录身份不可核查")
        info = directory.stat()
        if (info.st_dev, info.st_ino) != run[3:]:
            raise ValueError("受管运行目录已经变化")
        _, uid, gid = self.identities.ensure(run_id)
        if (info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode)) != (uid, gid, 0o700):
            raise ValueError("受管运行目录权限已经变化")
        return directory, state[1], state[7]

    def release(self, run_id, epoch, boot_id):
        with self.lock:
            key = (run_id, epoch)
            run = self.runs.get(key)
            if run is None or run[0] != boot_id:
                raise ValueError("受管工作区释放身份不可核查")
            unit = "boss-" + run_id + "-" + str(epoch) + ".service"
            if self._systemctl("show", unit, "--property=ActiveState", "--value") not in {"inactive", "failed"}:
                raise ValueError("受管工作区运行尚未停止")
            root_id = run[1]
            if any(other != key and saved[1] == root_id for other, saved in self.runs.items()):
                del self.runs[key]
                return
            self._close_domain(root_id)
            del self.runs[key]

    def _close_domain(self, root_id):
        state = self.domains[root_id]
        self._systemctl("stop", state[7])
        self._systemctl("stop", state[1])
        if self._mounted(state[2]):
            subprocess.run(["/usr/bin/umount", "--no-canonicalize", str(state[2])], check=True, timeout=30,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if self._mounted(state[2]):
            raise ValueError("受管工作区仍然挂载")
        if self._systemctl("show", "nfs-server.service", "--property=ActiveState", "--value") not in {"inactive", "failed"}:
            raise ValueError("受管工作区旧文件服务尚未停止")
        metadata = state[2].parent / "metadata.db"
        self._command("quota", "check", "--path", "/shared", "--strict", "--repair", "sqlite3://" + str(metadata))
        self._command("quota", "check", "--path", "/shared", "--strict", "sqlite3://" + str(metadata))
        os.close(state[0])
        del self.domains[root_id]

    def has_run(self, run_id, epoch, boot_id):
        with self.lock:
            run = self.runs.get((run_id, epoch))
            if run is not None and run[0] != boot_id:
                raise ValueError("受管工作区释放身份已经变化")
            return run is not None
