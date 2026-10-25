import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[2]
parser = argparse.ArgumentParser()
parser.add_argument("--records-root", type=Path, required=True)
parser.add_argument("--provider-root", type=Path, required=True)
parser.add_argument("--memory-records", type=Path, required=True)
arguments = parser.parse_args()
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / "validation"))
sys.path.append(str(arguments.provider_root / "validation"))
from runtime_records_query import QUERY
schema_path = ROOT / "specs/runtime-records.schema.json"
schema = json.loads(schema_path.read_text())
Draft202012Validator.check_schema(schema)
assert schema["$defs"]["RuntimeRecordsQuery"] == QUERY, "查询字段与当前W2实现不符"
validators = {name: Draft202012Validator({**schema, "$ref": "#/$defs/" + name}, format_checker=FormatChecker())
              for name in ("RuntimeRun", "CurrentRuntimeRun", "RuntimeRecordsProjection")}
paths = sorted(arguments.records_root.rglob("runtime-records.json"))
adoption = arguments.records_root / "runtime-version-final/runtime-version-adoption.json"
assert paths and adoption.is_file(), "真实Runtime原始结果缺少"
records = []
files = {}


def checked(name, value):
    errors = list(validators[name].iter_errors(value))
    assert not errors, {"schema": name, "paths": [list(error.absolute_path) for error in errors]}


for path in paths:
    projection = json.loads(path.read_text())
    checked("RuntimeRecordsProjection", projection)
    assert all(record["namespace"] == projection["namespace"] for record in projection["runs"])
    records.extend(projection["runs"])
    files[str(path.relative_to(arguments.records_root))] = hashlib.sha256(path.read_bytes()).hexdigest()
stages = json.loads(adoption.read_text())["stages"]
for stage in stages:
    record = stage["runtime_record"]
    checked("RuntimeRun", record)
    assert stage["prompt_version_adoption_verified"] and stage["tool_schema_transport_matches"]
    records.append(record)
files[str(adoption.relative_to(arguments.records_root))] = hashlib.sha256(adoption.read_bytes()).hexdigest()
memory_evidence = json.loads(arguments.memory_records.read_text())
for stage in memory_evidence["stages"]:
    record = stage["runtime_record"]
    checked("RuntimeRun", record)
    assert record["memory_reference"] is not None
    records.append(record)
files[str(arguments.memory_records)] = hashlib.sha256(arguments.memory_records.read_bytes()).hexdigest()
current_records = [record for record in records if "dataset_id" in record]
assert current_records, "当前数据集字段没有真实记录证据"
for record in current_records:
    checked("CurrentRuntimeRun", record)
statuses = Counter(record["status"] for record in records)
assert {"SUCCEEDED", "FAILED", "CANCELED", "TIMED_OUT"} <= set(statuses)
for record in records:
    assert record["cost_total"] is None and record["price_version"] is None
    assert record["private_body_recorded"] is False and record["model_behavior_evaluation_passed"] is False
    assert all(request["tool_config_sha256"] == record["tool_config_sha256"] for request in record["model_requests"])
    observed = [request["usage"] for request in record["model_requests"] if request["usage"] is not None]
    if observed:
        assert record["usage"] is not None
        assert all(record["usage"][key] == sum(usage[key] for usage in observed)
                   for key in ("prompt_tokens", "completion_tokens", "total_tokens"))
    else:
        assert record["usage"] is None
provider_files = {name: hashlib.sha256((arguments.provider_root / name).read_bytes()).hexdigest()
                  for name in ("validation/boss_runtime_records.py", "validation/runtime_records_query.py")}
print(json.dumps({"status": "PASS", "runtime_runs": len(records), "status_counts": dict(statuses),
    "current_runtime_runs": len(current_records), "query_schema_matches_implementation": True,
    "legacy_runs_missing_dataset_binding": sum("dataset_id" not in record for record in records),
    "legacy_runs_missing_memory_reference": sum("memory_reference" not in record for record in records),
    "schema_sha256": hashlib.sha256(schema_path.read_bytes()).hexdigest(), "actual_record_files_sha256": files,
    "provider_files_sha256": provider_files, "new_model_calls": False, "business_mutation_performed": False,
    "scope": "实际已有Runtime字段、配置和工具引用及已观察用量；公共界面和完整模型质量另行验收"}, ensure_ascii=False))
