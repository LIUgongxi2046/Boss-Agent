import argparse
import json
import sqlite3
import sys
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator
from jsonpointer import resolve_pointer

ROOT = Path(__file__).resolve().parents[2]
parser = argparse.ArgumentParser()
parser.add_argument("--receipts", type=Path, required=True)
receipt_root = parser.parse_args().receipts
assert receipt_root.is_dir(), receipt_root
sys.path.insert(0, str(ROOT / "validation"))
from boss_command_api import BossCommandAPI
dictionary = json.loads((ROOT / "specs/data-dictionary.json").read_text())
events = json.loads((ROOT / "specs/runtime-events.schema.json").read_text())
api = yaml.safe_load((ROOT / "specs/openapi.yaml").read_text())
Draft202012Validator.check_schema(events)
for name, schema in api["components"]["schemas"].items():
    Draft202012Validator.check_schema(schema)
for operation in api["x-websocket-operations"]:
    resolve_pointer(api, operation["input"][1:])
    if "output" in operation:
        resolve_pointer(api, operation["output"][1:])
assert len({o["operationId"] for o in api["x-websocket-operations"]}) == len(api["x-websocket-operations"])
assert dictionary["version"] == api["info"]["version"]
assert set(dictionary["requirement_entities"]) == {f"R{number:02d}" for number in range(1, 33)}
assert all(entity in dictionary["entities"] for entities in dictionary["requirement_entities"].values() for entity in entities)
assert {operation["interface_id"] for operation in api["x-simulation-operations"]} == {f"SI{number:02d}" for number in range(1, 15)}
probe = json.loads((ROOT / "specs/selection-probe.json").read_text())
assert {operation["operationId"] for operation in api["x-tool-operations"]} == {operation["operation_id"] for operation in probe["operations"]}
for operation in api["x-tool-operations"]:
    for field in ("input", "output", "errors"):
        resolve_pointer(probe, operation[field].split("#", 1)[1])
operations = {operation["action"]: operation for operation in api["x-websocket-operations"]}
assert set(BossCommandAPI.ACTION_ROLES) <= set(operations), sorted(set(BossCommandAPI.ACTION_ROLES) - set(operations))
assert all(operations[action]["role"] == role for action, role in BossCommandAPI.ACTION_ROLES.items())
for entity in dictionary["entities"].values():
    for field in entity["fields"].values():
        assert "type" in field or field.get("type_ref") in dictionary["types"]
observed = set()
count = 0
for path in receipt_root.rglob("*.sqlite"):
    with sqlite3.connect(path) as db:
        for operation, result in db.execute("SELECT operation,result FROM idempotency"):
            if operation not in operations:
                continue
            specification = operations[operation]
            value = json.loads(result)
            assert set(specification.get("result_required", [])) <= set(value), operation
            schema = {"components": api["components"], "$ref": specification.get("output", "#/components/schemas/BusinessReceipt")}
            Draft202012Validator(schema).validate(value)
            observed.add(operation)
            count += 1
assert count > 0, "没有读取到已执行的业务回执"
print("PASS: JSON/YAML读取、事件Schema、组件Schema、动作引用、operationId唯一性和版本一致性")
print(f"PASS: 当前{len(BossCommandAPI.ACTION_ROLES)}项命令全部有角色和输入映射；实际{count}份SQLite回执覆盖{len(observed)}项动作")
print("PASS: R01—R32实体引用、SI01—SI14全集与五个现有Tool原始Schema引用")
print("NOT_RUN: 独立语义审查、完整合法输入匹配、公共入口与真实Runtime集成；OpenAPI标准检查使用validate_openapi.py独立执行")
