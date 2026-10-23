import argparse
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
parser = argparse.ArgumentParser()
parser.add_argument("--run-dir", type=Path, required=True)
run_dir = parser.parse_args().run_dir.resolve()
assert run_dir.is_relative_to(ROOT / ".work"), "检查目录必须属于本工作目录的.work"
run_dir.mkdir(parents=True, exist_ok=True)
result = pytest.main(["-q", str(ROOT / "app/tests/test_boss_api_spec.py"),
                      "--basetemp=" + str(run_dir / "sqlite"), "-p", "no:cacheprovider",
                      "--junitxml=" + str(run_dir / "results.xml")])
if result != 0:
    raise SystemExit(result)
from boss_command_api import BossCommandAPI
executed = sys.modules["test_boss_api_spec"]
observed = executed.VALIDATED_ACTIONS
baseline = {operation["action"] for operation in executed.SPEC["x-websocket-operations"] if operation["operationId"] == operation["action"]}
assert baseline <= set(BossCommandAPI.ACTION_ROLES)
assert observed == baseline, sorted(baseline - observed)
print(f"PASS: {len(observed)}项基线公共动作全部使用实际SQLite/API运行，合法输入和真实结果通过声明Schema")
print("NOT_RUN: 全部参数边界与业务变体、独立语义审查、公共传输与设备集成")
