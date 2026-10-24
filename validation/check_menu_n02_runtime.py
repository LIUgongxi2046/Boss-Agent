import json
from pathlib import Path
import sys

from jsonschema import Draft202012Validator

from boss_runtime_records import runtime_records
from controls import ControlStore


root=Path(__file__).resolve().parents[1]
directory=Path(sys.argv[1]).resolve()
if not directory.is_relative_to(root/"validation/.work") or not directory.name.startswith("menu-n02-") or not (directory/"business.sqlite").is_file():
    raise ValueError("仅允许核查当前N02独立检查资料")
schema=json.loads((root/"specs/runtime-records.schema.json").read_text())
validator=Draft202012Validator({**schema,"$ref":"#/$defs/CurrentRuntimeRun"})
runs=runtime_records(ControlStore(directory/"business.sqlite"),"MAINTAINER")["runs"]
if not runs or any(run["feature_id"]!="N02" for run in runs):
    raise ValueError("当前检查需要实际N02运行")
for run in runs:
    validator.validate(run)
print(json.dumps({"status":"PASS","schema_id":schema["$id"],"runtime_count":len(runs)}))
