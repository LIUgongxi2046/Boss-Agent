import json
import os
import stat
from pathlib import Path


def _reject_symlink_components(path, *, allow_missing=False):
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current = current / part
        if os.path.islink(current):
            raise ValueError("应用数据目录不能经过符号链接")
        if not os.path.lexists(current):
            if allow_missing:
                return
            raise FileNotFoundError("应用数据目录组件不存在")
        if not stat.S_ISDIR(os.lstat(current).st_mode):
            raise ValueError("应用数据目录组件必须是目录")


def _is_installed_runtime(root):
    return root.name == "boss_agent_runtime" and root.parent.name == "site-packages"


def _private_data_root(data_root):
    candidate = Path(data_root)
    if not candidate.is_absolute():
        raise ValueError("应用数据根目录必须使用绝对路径")
    if candidate == Path(candidate.anchor) or candidate == Path.home():
        raise ValueError("应用数据根目录不能使用根目录或用户主目录")
    _reject_symlink_components(candidate)
    resolved = candidate.resolve()
    _reject_symlink_components(resolved)
    if not resolved.is_dir():
        raise ValueError("应用数据根目录必须已存在")
    root_stat = resolved.stat()
    if root_stat.st_uid != os.getuid() or root_stat.st_mode & 0o077:
        raise ValueError("应用数据根目录必须由当前用户独占")
    return resolved


def _installed_work_directory(root, configured, data_root):
    configured_root = data_root if data_root is not None else os.environ.get("BOSS_APPLICATION_DATA_ROOT")
    if configured_root is None:
        raise ValueError("独立安装必须配置私有数据根目录")
    private_root = _private_data_root(configured_root)
    if private_root.is_relative_to(root):
        raise ValueError("应用数据根目录不能位于安装目录")
    candidate = Path(configured) if configured is not None else private_root / "application"
    if not candidate.is_absolute():
        raise ValueError("应用数据目录必须使用绝对路径")
    _reject_symlink_components(candidate, allow_missing=True)
    resolved = candidate.resolve()
    if resolved.parent != private_root:
        raise ValueError("应用数据目录必须是私有数据根目录的直接子目录")
    _reject_symlink_components(resolved, allow_missing=True)
    if resolved.exists():
        resolved_stat = resolved.stat()
        if not resolved.is_dir() or resolved_stat.st_uid != os.getuid():
            raise ValueError("应用数据目录必须由当前用户拥有")
    return resolved


def application_work_directory(root, configured=None, data_root=None):
    root = Path(root).resolve()
    if _is_installed_runtime(root):
        return _installed_work_directory(root, configured, data_root)
    parent = (root / ".work").resolve()
    candidate = Path(configured) if configured is not None else parent / "application"
    if not candidate.is_absolute():
        raise ValueError("应用数据目录必须使用绝对路径")
    _reject_symlink_components(candidate, allow_missing=True)
    resolved = candidate.resolve()
    if resolved == parent:
        raise ValueError("应用数据目录必须位于本工程.work的直接子目录")
    if not resolved.is_relative_to(parent) or resolved.parent != parent:
        raise ValueError("应用数据目录必须位于本工程.work的直接子目录")
    return resolved


def application_ports(configured=None):
    ports = {"business": 8871, "webui": 8872, "gateway": 18791} if configured is None else json.loads(configured)
    if not isinstance(ports, dict) or set(ports) != {"business", "webui", "gateway"}:
        raise ValueError("应用端口必须明确包含business、webui和gateway")
    if any(type(value) is not int or not 1024 <= value <= 65535 for value in ports.values()):
        raise ValueError("应用端口必须为1024至65535的整数")
    if len(set(ports.values())) != 3:
        raise ValueError("应用端口不能重复")
    return ports


def application_frontend_directory(root, configured=None):
    runtime = Path(root).resolve()
    project = runtime.parent
    if _is_installed_runtime(runtime):
        default = runtime / "webui"
    else:
        default = project / ".work/product/nanobot/nanobot/web/dist"
    candidate = Path(configured) if configured is not None else default
    if not candidate.is_absolute():
        raise ValueError("前端构建目录必须使用绝对路径")
    _reject_symlink_components(candidate, allow_missing=True)
    resolved = candidate.resolve()
    if not resolved.is_relative_to(project):
        raise ValueError("前端构建目录必须位于当前工程")
    if not (resolved / "index.html").is_file():
        raise FileNotFoundError("当前前端构建缺少 index.html")
    return resolved
