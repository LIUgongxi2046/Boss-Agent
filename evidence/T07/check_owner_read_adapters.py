import asyncio
import hashlib
import json
import sqlite3
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import yaml
from jsonschema import Draft202012Validator, FormatChecker
from lxml import etree
from nanobot.agent.tools.registry import ToolRegistry

ROOT = Path(__file__).resolve().parents[2]
W1 = Path("/Users/liuhaoxian/.codex/worktrees/boss-business/Boss-Agent")
COMMIT = "f854b07a66a153fc4a92c95c86cce788d009cffe"
inputs = {}
for name in ("boss_today", "boss_owner_plans", "boss_meetings", "boss_source_access"):
    relative = "validation/" + name + ".py"
    data = subprocess.check_output(["git", "show", COMMIT + ":" + relative], cwd=W1)
    assert (W1 / relative).read_bytes() == data
    inputs[relative] = hashlib.sha256(data).hexdigest()
sys.path.insert(0, str(W1 / "validation"))
sys.path.insert(0, str(ROOT / "validation"))

from controls import ControlStore
from runtime_owner_read_tools import BossOwnerPlansReadTool, BossTodayReadTool

assert Path(sys.modules["business"].__file__).resolve() == ROOT / "validation/business.py"
backend_bytes = subprocess.check_output(["git", "show", COMMIT + ":specs/openapi.yaml"], cwd=W1)
backend = yaml.safe_load(backend_bytes)
source = ROOT / ".work/w2-checks/memory-ui/memory.sqlite"
work = ROOT / ".work/w2-checks/owner-read-adapters"
work.mkdir(parents=True, exist_ok=True)
target = work / (str(uuid4()) + ".sqlite")
with sqlite3.connect(source.as_uri() + "?mode=ro", uri=True) as original:
    before = tuple(original.iterdump())
    with sqlite3.connect(target) as copied:
        original.backup(copied)
store = ControlStore(target)
registry = ToolRegistry()
observed = []
for tool, path in ((BossTodayReadTool(store, "BOSS"), "/api/boss/ui/today"),
                   (BossOwnerPlansReadTool(store, "BOSS"), "/api/boss/ui/owner-plans")):
    registry.register(tool)
    view = json.loads(asyncio.run(registry.execute(tool.name, {})))
    operation = backend["paths"][path]["get"]
    schema = operation["responses"]["200"]["content"]["application/json"]["schema"]
    Draft202012Validator({**backend, **schema}, format_checker=FormatChecker()).validate(view)
    assert operation["operationId"] == tool.name and operation["x-role"] == "BOSS"
    assert view["source_type"] == "SIMULATED"
    observed.append({"operationId": tool.name, "field_names": sorted(view),
                     "item_count": len(view["items"] if tool.name == "todayRead" else view["plans"]),
                     "result_sha256": hashlib.sha256(json.dumps(view, ensure_ascii=False, sort_keys=True).encode()).hexdigest(),
                     "coverage_state": view.get("coverage_state"), "execution_owner": view.get("execution_owner"),
                     "external_delivery_verified": view.get("external_delivery_verified")})
with sqlite3.connect(source.as_uri() + "?mode=ro", uri=True) as original:
    with sqlite3.connect(target.as_uri() + "?mode=ro", uri=True) as copied:
        assert tuple(original.iterdump()) == before == tuple(copied.iterdump())

actual_sources = {}
for module in tuple(sys.modules.values()):
    filename = getattr(module, "__file__", None)
    if filename is None:
        continue
    path = Path(filename).resolve()
    if not (path.is_relative_to(ROOT / "validation") or path.is_relative_to(W1 / "validation")):
        continue
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    actual_sources[str(path)] = digest
    if path.is_relative_to(W1):
        relative = str(path.relative_to(W1))
        assert path.read_bytes() == subprocess.check_output(["git", "show", COMMIT + ":" + relative], cwd=W1)
for relative, digest in inputs.items():
    assert hashlib.sha256((W1 / relative).read_bytes()).hexdigest() == digest
suite = etree.parse(str(ROOT / "evidence/T07/w2-20261023-owner-read-adapters.xml")).getroot().find("testsuite")
assert suite is not None and suite.get("failures") == "0" and suite.get("errors") == "0"
report = {
    "status": "PASS_OWNER_READ_ADAPTER_COMPOSITION", "backend_schema_version": backend["info"]["version"],
    "backend_read_module_commit": COMMIT, "backend_schema_sha256": hashlib.sha256(backend_bytes).hexdigest(),
    "full_W1_backend_version_verified": False, "base_store_source": "W2_CURRENT_WORKTREE",
    "read_modules_source": "W1_COMMITTED_BYTES", "input_source_sha256": inputs,
    "actual_loaded_source_sha256": actual_sources, "observed": observed,
    "registry_tool_names": registry.tool_names, "source_and_copy_database_unchanged": True,
    "test_report": {key: suite.get(key) for key in ("tests", "failures", "errors", "skipped", "time")},
    "new_external_requests": 0, "new_business_samples": 0, "runtime_public_registration": "NOT_RUN",
    "model_adoption": "NOT_RUN", "full_A07_accepted": False,
}
(ROOT / "evidence/T07/w2-20261023-owner-read-adapters.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
print(json.dumps({"status": report["status"], "tool_count": len(observed),
                  "source_and_copy_database_unchanged": True, "new_external_requests": 0}, ensure_ascii=False))
