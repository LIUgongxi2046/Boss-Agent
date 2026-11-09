import subprocess
from pathlib import Path


def process_launch_options(workspace):
    path = Path(workspace)
    if path.is_symlink() or not path.is_dir():
        raise ValueError("进程工作目录无效")
    path = path.resolve(strict=True)
    return {
        "cwd": path,
        "env": {"PATH": "/usr/bin:/bin", "HOME": str(path), "TMPDIR": str(path),
                "HERMES_HOME": str(path), "PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1"},
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
        "start_new_session": True,
    }
