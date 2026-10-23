import json
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator
from jsonpointer import resolve_pointer

ROOT = Path(__file__).resolve().parents[2]
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
print("PASS: JSON/YAML读取、事件Schema、组件Schema、动作引用、operationId唯一性和版本一致性")
print("NOT_RUN: 完整OpenAPI规范验证、全域字段覆盖、独立语义审查、公共入口与Runtime集成")
