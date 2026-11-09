import os
import plistlib
import re
import stat
import subprocess
import tempfile
from pathlib import Path
from uuid import UUID


class ExperimentalWorkspaceImage:
    def __init__(self, capacity_mib, *, run_id=None):
        if type(capacity_mib) is not int or not 16 <= capacity_mib <= 256:
            raise ValueError("实验工作区容量无效")
        if run_id is not None and (not isinstance(run_id, str) or str(UUID(run_id)) != run_id):
            raise ValueError("实验工作区运行编号无效")
        root = Path(__file__).resolve().parent.parent / ".work/upgrade2/u2-03/isolated-workspaces"
        if not root.is_dir() or root != root.resolve(strict=True):
            raise ValueError("实验工作区根目录无效")
        self.capacity_mib = capacity_mib
        self.directory = Path(tempfile.mkdtemp(prefix="bounded-", dir=root))
        self.image = self.directory / "workspace.dmg"
        self.mount = self.directory / (run_id if run_id is not None else "mount")
        self.mount.mkdir(mode=0o700)
        self.environment = {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "HOME": str(self.directory), "TMPDIR": str(self.directory)}
        self._entered = False

    def _attached_device(self):
        result = subprocess.run(["/usr/bin/hdiutil", "info", "-plist"], env=self.environment,
                                capture_output=True, check=True, timeout=30)
        images = [item for item in plistlib.loads(result.stdout)["images"] if item.get("image-path") == str(self.image)]
        if not images:
            return None
        if len(images) != 1:
            raise ValueError("实验映像附加身份不唯一")
        entities = images[0]["system-entities"]
        mounts = [item for item in entities if "mount-point" in item]
        if mounts:
            if len(mounts) != 1 or mounts[0]["mount-point"] != str(self.mount):
                raise ValueError("实验映像挂载位置不匹配")
            device = mounts[0].get("dev-entry")
        else:
            devices = [item.get("dev-entry") for item in entities if re.fullmatch(r"/dev/disk[0-9]+", item.get("dev-entry", ""))]
            if len(devices) != 1:
                raise ValueError("实验映像设备身份不可核查")
            device = devices[0]
        if not isinstance(device, str) or re.fullmatch(r"/dev/disk[0-9]+(?:s[0-9]+)*", device) is None:
            raise ValueError("实验映像设备身份不可核查")
        return device

    def _detach(self):
        device = self._attached_device()
        if device is None:
            if os.path.ismount(self.mount):
                raise ValueError("实验工作区挂载身份不可核查")
            return
        subprocess.run(["/usr/bin/hdiutil", "detach", device], env=self.environment,
                       capture_output=True, check=True, timeout=60)
        if self._attached_device() is not None or os.path.ismount(self.mount):
            raise ValueError("实验工作区卸载不可核查")

    def require_capacity(self, run_id, workspace, disk_limit_bytes):
        if type(disk_limit_bytes) is not int or disk_limit_bytes <= 0:
            raise ValueError("实验磁盘容量上限无效")
        if not isinstance(run_id, str) or str(UUID(run_id)) != run_id:
            raise ValueError("实验工作区运行编号无效")
        if (not self._entered or self.mount != self.directory / run_id or self.image != self.directory / "workspace.dmg"
                or Path(workspace) != self.mount or not os.path.ismount(self.mount)):
            raise ValueError("实验映像与运行工作区不匹配")
        device = self._attached_device()
        if device is None:
            raise ValueError("实验映像与运行工作区不匹配")
        descriptor = os.open(self.mount, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            opened = os.fstat(descriptor)
            device_stat = os.stat(device)
            current = os.stat(self.mount, follow_symlinks=False)
            if not stat.S_ISBLK(device_stat.st_mode) or opened.st_dev != device_stat.st_rdev or (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino):
                raise ValueError("实验映像设备与工作区不匹配")
            capacity = os.fstatvfs(descriptor)
            if capacity.f_blocks * capacity.f_frsize > disk_limit_bytes or self.capacity_mib * 1024 * 1024 > disk_limit_bytes:
                raise ValueError("实验映像超过磁盘容量上限")
            if self._attached_device() != device:
                raise ValueError("实验映像设备已经变化")
            current = os.stat(self.mount, follow_symlinks=False)
            if (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino):
                raise ValueError("实验工作区已经变化")
        finally:
            os.close(descriptor)

    def __enter__(self):
        if self._entered:
            raise ValueError("实验工作区不能重复启动")
        self._entered = True
        ready = False
        try:
            subprocess.run(["/usr/bin/hdiutil", "create", "-size", str(self.capacity_mib) + "m", "-fs", "HFS+",
                            "-type", "UDIF", "-volname", "BossAgentWorkspace", "-nospotlight", str(self.image)],
                           env=self.environment, capture_output=True, check=True, timeout=60)
            result = subprocess.run(["/usr/bin/hdiutil", "attach", str(self.image), "-mountpoint", str(self.mount),
                                     "-noautoopen", "-plist"], env=self.environment,
                                    capture_output=True, check=True, timeout=60)
            entries = plistlib.loads(result.stdout)["system-entities"]
            mounted = [item for item in entries if item.get("mount-point") == str(self.mount)]
            if len(mounted) != 1 or mounted[0].get("dev-entry") != self._attached_device() or not os.path.ismount(self.mount):
                raise ValueError("实验工作区挂载身份不可核查")
            ready = True
            return self.mount
        finally:
            if not ready:
                self._detach()

    def __exit__(self, exc_type, exc_value, traceback):
        self._detach()
