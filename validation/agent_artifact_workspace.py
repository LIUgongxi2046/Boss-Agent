import os
import stat
from pathlib import Path
from uuid import UUID


class ArtifactWorkspace:
    def __init__(self, root):
        root = Path(root)
        if not root.is_absolute() or root.is_symlink() or not root.is_dir():
            raise ValueError("成果目录根路径必须是已存在的绝对目录")
        self.root = root.resolve(strict=True)
        if self.root != root:
            raise ValueError("成果目录根路径必须使用真实路径")
        self._root_identity = self._identity(self.root)

    @staticmethod
    def _identity(path):
        info = path.lstat()
        if not stat.S_ISDIR(info.st_mode):
            raise ValueError("成果目录不可核查")
        return info.st_dev, info.st_ino

    def _path(self, run_id):
        if not isinstance(run_id, str) or str(UUID(run_id)) != run_id:
            raise ValueError("运行编号格式无效")
        if self._identity(self.root) != self._root_identity or self.root.resolve(strict=True) != self.root:
            raise ValueError("成果目录根路径已经变化")
        return self.root / run_id

    def create(self, run_id):
        path = self._path(run_id)
        os.mkdir(path, mode=0o700)
        return self.open(run_id)

    def open(self, run_id):
        path = self._path(run_id)
        self._identity(path)
        if path.resolve(strict=True) != path:
            raise ValueError("成果目录路径不可核查")
        return path

    def restore(self, run_id):
        self._path(run_id)
        raise RuntimeError("成果目录恢复尚未通过核查")
