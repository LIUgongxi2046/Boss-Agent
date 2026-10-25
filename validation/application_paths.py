import json
from pathlib import Path


def application_work_directory(root, configured=None):
    parent = (Path(root) / ".work").resolve()
    candidate = Path(configured) if configured is not None else parent / "application"
    if not candidate.is_absolute():
        raise ValueError("应用数据目录必须使用绝对路径")
    resolved = candidate.resolve()
    if resolved.parent != parent:
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
    project = Path(root).resolve().parent
    candidate = Path(configured) if configured is not None else project / ".work/product/nanobot/nanobot/web/dist"
    if not candidate.is_absolute():
        raise ValueError("前端构建目录必须使用绝对路径")
    resolved = candidate.resolve()
    if not resolved.is_relative_to(project):
        raise ValueError("前端构建目录必须位于当前工程")
    if not (resolved / "index.html").is_file():
        raise FileNotFoundError("当前前端构建缺少 index.html")
    return resolved
