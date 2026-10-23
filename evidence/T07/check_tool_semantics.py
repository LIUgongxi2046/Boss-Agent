import copy
import hashlib
import json
import sys
from pathlib import Path
from urllib.parse import urldefrag
from uuid import uuid4

import yaml
from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "validation"))

from business import Store
from model_probe import BusinessTool

backend_path = Path("/Users/liuhaoxian/.codex/worktrees/boss-business/Boss-Agent/specs/openapi.yaml")
backend = yaml.safe_load(backend_path.read_text())
operations = {item["operationId"]: item for item in backend["x-tool-operations"]}
work = ROOT / ".work" / "w2-checks" / "semantic-tools"
work.mkdir(parents=True, exist_ok=True)
store = Store(work / ("approved-" + str(uuid4()) + ".sqlite"))
namespace = "semantic-source-version"
store.initialize(namespace)
schema_cache = {}


def validator(reference):
    relative, fragment = urldefrag(reference)
    path = (backend_path.parent / relative).resolve()
    if path not in schema_cache:
        schema_cache[path] = json.loads(path.read_text())
    assert fragment.startswith("/io_schema/")
    schema_root = schema_cache[path]["io_schema"]
    return Draft202012Validator(
        {**schema_root, "$ref": "#" + fragment.removeprefix("/io_schema")},
        format_checker=FormatChecker(),
    )


counts = {name: 0 for name in operations}
inputs = {}
runs = []
recorded_query = None
for path in sorted((ROOT / "evidence" / "T16").glob("deepseek-*/events.json")):
    events = json.loads(path.read_text())
    inputs[str(path.relative_to(ROOT))] = hashlib.sha256(path.read_bytes()).hexdigest()
    tools = [event for event in events if event["type"] == "tool"]
    for event in tools:
        operation = operations[event["name"]]
        validator(operation["input"]).validate(event["input"])
        validator(operation["output"]).validate(event["output"])
        tool = BusinessTool(event["name"], store, event["input"]["envelope"], {}, [])
        parameters = tool.parameters
        injected = {"envelope", "authorization_id", "idempotency_key"}
        assert not set(parameters["properties"]) & injected
        model_input = {name: value for name, value in event["input"].items() if name not in injected}
        Draft202012Validator(parameters, format_checker=FormatChecker()).validate(model_input)
        counts[event["name"]] += 1
        if event["name"] == "query_metrics" and recorded_query is None:
            recorded_query = copy.deepcopy(event["input"])
    creation = next(event["output"] for event in tools if event["name"] == "create_assignment")
    delivery = next(event["output"] for event in tools if event["name"] == "send_assignment")
    reread = [event["output"] for event in tools if event["name"] == "read_assignment"][-1]
    assert creation["task_id"] == delivery["task_id"] == reread["task_id"]
    assert creation["status"] == "OPEN" and reread["status"] == "WAITING_FEEDBACK"
    assert delivery["message_id"] in reread["message_ids"]
    runs.append({"run_id": path.parent.name, "tool_result_count": len(tools),
                 "task_state_reread": reread["status"], "message_reference_matches": True})
assert all(counts.values()) and len(runs) == 4

recorded_query["envelope"].update(
    execution_namespace=namespace, session_id="semantic-session", request_id="semantic-query",
)
query_result = store.invoke("query_metrics", recorded_query)
with store.connect() as db:
    db.execute("BEGIN IMMEDIATE")
    document = store.get(db, namespace, "document", "finance-note")
    document["version"] = "2"
    store.put(db, namespace, "document", "finance-note", document)
evidence = store.invoke("read_evidence", {
    "envelope": recorded_query["envelope"], "query_id": query_result["query_id"],
    "source_ids": ["finance-note"], "detail_refs": query_result["detail_refs"],
})
current = next(item["content"] for item in evidence["original_records"] if item["record_id"] == "finance-note")
reported_version = evidence["sources"][0]["version"]
source_version_matches = reported_version == current["version"]
source_files = [ROOT / "validation" / "business.py", ROOT / "validation" / "model_probe.py", backend_path]
report = {
    "status": "PASS_BASELINE_SCHEMA_WITH_SOURCE_VERSION_REVIEW_REQUIRED",
    "full_A07_accepted": False, "backend_version": backend["info"]["version"],
    "recorded_tool_counts": counts, "runs": runs, "input_evidence_sha256": inputs,
    "source_code_sha256": {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in source_files},
    "source_revision_check": {
        "source_id": "finance-note", "current_document_version": current["version"],
        "reported_source_version": reported_version, "source_version_matches": source_version_matches,
        "body_changed": False, "external_request_sent": False,
        "owner": "W1 business.Store.source and Store.read_evidence",
        "required_behavior": "来源变更后当前引用返回正确版本，或明确拒绝旧查询并要求重读",
    },
}
output = Path(__file__).parent / "w2-20261023-tool-semantics.json"
output.write_text(json.dumps(report, ensure_ascii=False, indent=2))
print(json.dumps({"status": report["status"], "recorded_tool_counts": counts,
                  "source_revision_check": report["source_revision_check"]}, ensure_ascii=False))
