import ast
import json
from pathlib import Path
import tomllib


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "validation"


def test_adapter_resources_include_local_imports_and_schema():
    names = (ROOT / "hermes-engine-resources.txt").read_text(encoding="utf-8").splitlines()
    assert len(names) == len(set(names))
    included = {Path(name).name for name in names}
    for name in names:
        source = ROOT / name
        assert source.is_file() and not source.is_symlink()
        if source.suffix != ".py":
            continue
        tree = ast.parse(source.read_text(encoding="utf-8"), filename=name)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                local = SOURCE / (node.module.split(".")[0] + ".py")
                if local.is_file():
                    assert local.name in included, f"{name} 缺少本地导入 {local.name}"
    schema = json.loads((SOURCE / "agent_artifact_schema.json").read_text(encoding="utf-8"))
    assert {"meeting_brief_tool_request", "meeting_brief_format_tool_request"} <= schema["$defs"].keys()
    assert {"hermes_resource_exec.py", "hermes_start_gate.py", "hermes_parent_guard.py"} <= included


def test_adapter_declares_fixed_interpreter_and_transport_dependency():
    project = tomllib.loads((ROOT / "packaging/hermes-adapter/pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert project["requires-python"] == ">=3.14,<3.15"
    assert "httpx==0.28.1" in project["dependencies"]
