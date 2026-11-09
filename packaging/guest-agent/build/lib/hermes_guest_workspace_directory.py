import os
import stat
from pathlib import Path
from uuid import UUID


def prepare_private_workspace(root, run_id, uid, gid):
    root = Path(root)
    if not root.is_absolute() or root.resolve(strict=True) != root or not root.is_dir():
        raise ValueError("受管工作区根目录不可核查")
    if not isinstance(run_id, str) or str(UUID(run_id)) != run_id:
        raise ValueError("受管工作区运行身份无效")
    if type(uid) is not int or type(gid) is not int or uid <= 0 or gid <= 0:
        raise ValueError("受管工作区账号无效")
    root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        root_info = os.fstat(root_fd)
        if root_info.st_uid != os.geteuid() or stat.S_IMODE(root_info.st_mode) != 0o700:
            raise ValueError("受管工作区根目录权限无效")
        workspace = root / run_id
        if not workspace.exists():
            os.mkdir(run_id, mode=0o700, dir_fd=root_fd)
        workspace_fd = os.open(run_id, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root_fd)
        try:
            info = os.fstat(workspace_fd)
            if info.st_uid == os.geteuid() and not os.listdir(workspace_fd) and stat.S_IMODE(info.st_mode) == 0o700:
                os.fchown(workspace_fd, uid, gid)
            info = os.fstat(workspace_fd)
            if (info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode)) != (uid, gid, 0o700):
                raise ValueError("受管运行目录权限无效")
            temporary = workspace / ".temporary"
            if not temporary.exists():
                os.mkdir(".temporary", mode=0o700, dir_fd=workspace_fd)
                temporary_fd = os.open(".temporary", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=workspace_fd)
                try:
                    os.fchown(temporary_fd, uid, gid)
                finally:
                    os.close(temporary_fd)
            temporary_fd = os.open(".temporary", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=workspace_fd)
            try:
                info = os.fstat(temporary_fd)
                if (info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode)) != (uid, gid, 0o700):
                    raise ValueError("受管临时目录权限无效")
            finally:
                os.close(temporary_fd)
        finally:
            os.close(workspace_fd)
    finally:
        os.close(root_fd)
    return workspace
