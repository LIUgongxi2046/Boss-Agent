import asyncio
import copy
import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from urllib.parse import urldefrag
from uuid import uuid4

import yaml
import pytest
from aiohttp import web
from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[2]
W1 = Path("/Users/liuhaoxian/.codex/worktrees/boss-business/Boss-Agent")
COMMIT = "fc4b2b5e88f9178312f6a7116e160ceeb03e160b"

received = {}
for relative in ("specs/openapi.yaml", "specs/data-dictionary.json", "specs/runtime-events.schema.json", "specs/selection-probe.json",
                 "validation/business.py", "validation/controls.py", "validation/boss_source_access.py", "validation/boss_source_policy.py"):
    committed = subprocess.check_output(["git", "show", COMMIT + ":" + relative], cwd=W1)
    if relative.startswith("validation/") or relative == "specs/selection-probe.json":
        assert (W1 / relative).read_bytes() == committed
    received[relative] = hashlib.sha256(committed).hexdigest()
sys.path.insert(0, str(ROOT / "validation"))
sys.path.insert(0, str(W1 / "validation"))

from controls import ControlStore

# 领域服务固定引用W1，运行适配与其依赖引用W2当前实现。
sys.path.insert(0, str(ROOT / "validation"))
module_spec = importlib.util.spec_from_file_location("w2_received_model_probe", ROOT / "validation/model_probe.py")
module = importlib.util.module_from_spec(module_spec)
sys.modules[module_spec.name] = module
module_spec.loader.exec_module(module)
BusinessTool = module.BusinessTool
assert Path(sys.modules["business"].__file__).resolve() == W1 / "validation/business.py"
assert Path(sys.modules["boss_prompt_config"].__file__).resolve() == ROOT / "validation/boss_prompt_config.py"

backend_path = Path("/Users/liuhaoxian/.codex/worktrees/boss-business/Boss-Agent/specs/openapi.yaml")
backend = yaml.safe_load(subprocess.check_output(["git", "show", COMMIT + ":specs/openapi.yaml"], cwd=W1))
operations = {item["operationId"]: item for item in backend["x-tool-operations"]}
work = ROOT / ".work" / "w2-checks" / "semantic-tools"
work.mkdir(parents=True, exist_ok=True)
store = ControlStore(work / ("approved-" + str(uuid4()) + ".sqlite"))
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
recorded_create = None
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
        if event["name"] == "create_assignment" and recorded_create is None:
            recorded_create = {key: copy.deepcopy(value) for key, value in event["input"].items() if key not in injected}
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
    original_body = document["content"]
    document["version"] = "2"
    store.put(db, namespace, "document", "finance-note", document)
old_read = {
    "envelope": recorded_query["envelope"], "query_id": query_result["query_id"],
    "source_ids": ["finance-note"], "detail_refs": query_result["detail_refs"],
}
with pytest.raises(web.HTTPConflict):
    store.invoke("read_evidence", old_read)
tool_records = []
query_tool = BusinessTool("query_metrics", store, recorded_query["envelope"], {}, tool_records)
evidence_tool = BusinessTool("read_evidence", store, recorded_query["envelope"], {}, tool_records)
with pytest.raises(web.HTTPConflict):
    asyncio.run(evidence_tool.execute(**{key: value for key, value in old_read.items() if key != "envelope"}))
assert tool_records == []
query_parameters = {key: value for key, value in recorded_query.items() if key != "envelope"}
fresh_query = json.loads(asyncio.run(query_tool.execute(**query_parameters)))
fresh_read = {"query_id": fresh_query["query_id"], "source_ids": ["finance-note"], "detail_refs": fresh_query["detail_refs"]}
evidence = json.loads(asyncio.run(evidence_tool.execute(**fresh_read)))
assert fresh_query["query_id"] != query_result["query_id"]
validator(operations["query_metrics"]["output"]).validate(fresh_query)
validator(operations["read_evidence"]["output"]).validate(evidence)
current = next(item["content"] for item in evidence["original_records"] if item["record_id"] == "finance-note")
reported_version = evidence["sources"][0]["version"]
source_version_matches = reported_version == current["version"]
assert source_version_matches and reported_version == fresh_query["sources"][0]["version"] == "2"
assert current["content"] == original_body
assert all(item["version"] == item["content"]["version"] for item in evidence["original_records"])
with store.connect() as db:
    binding = store.get(db, namespace, "query_source_binding", fresh_query["query_id"])
    assert binding["source_version"] == "2"
    db.execute("DELETE FROM objects WHERE namespace=? AND kind='query_source_binding' AND id=?", (namespace, fresh_query["query_id"]))
with pytest.raises(web.HTTPConflict):
    asyncio.run(evidence_tool.execute(**fresh_read))
with store.connect() as db:
    assert db.execute("SELECT COUNT(*) FROM objects WHERE namespace=? AND kind='query_source_binding' AND id=?", (namespace, fresh_query["query_id"])).fetchone()[0] == 0

fresh_query = json.loads(asyncio.run(query_tool.execute(**query_parameters)))
fresh_read = {**fresh_read, "query_id": fresh_query["query_id"]}
with store.connect() as db:
    original_document = store.get(db, namespace, "document", "finance-note")
    changed = {**original_document, "published_at": store.get(db, namespace, "document", "meeting-minutes")["published_at"]}
    store.put(db, namespace, "document", "finance-note", changed)
with pytest.raises(web.HTTPConflict):
    asyncio.run(evidence_tool.execute(**fresh_read))
with store.connect() as db:
    store.put(db, namespace, "document", "finance-note", original_document)
state_checks = []
for state, exception in (("RECEIVED", web.HTTPConflict), ("INCOMPLETE", web.HTTPConflict),
                         ("CONFLICTED", web.HTTPConflict), ("SUPERSEDED", web.HTTPConflict),
                         ("WITHDRAWN", web.HTTPGone), ("EXPIRED", web.HTTPGone)):
    with store.connect() as db:
        store.put(db, namespace, "document", "finance-note", {**original_document, "validity_state": state})
    count = len(tool_records)
    for tool, parameters in ((query_tool, query_parameters), (evidence_tool, fresh_read)):
        with pytest.raises(exception):
            asyncio.run(tool.execute(**parameters))
    assert len(tool_records) == count
    state_checks.append({"state": state, "query_status": exception.status_code, "evidence_status": exception.status_code})
with store.connect() as db:
    store.put(db, namespace, "document", "finance-note", original_document)
    contact_id = store.get(db, namespace, "initial", "snapshot")["contacts"][0]["contact_id"]
    store.put(db, namespace, "document", "finance-note", {**original_document, "access_scope": contact_id})
for tool, parameters in ((query_tool, query_parameters), (evidence_tool, fresh_read)):
    with pytest.raises(web.HTTPForbidden):
        asyncio.run(tool.execute(**parameters))
with store.connect() as db:
    store.put(db, namespace, "document", "finance-note", original_document)
store.control(namespace, "withdraw", {"source_id": "finance-note", "version": "2"})
with pytest.raises(web.HTTPGone):
    asyncio.run(query_tool.execute(**query_parameters))
with store.connect() as db:
    assert store.get(db, namespace, "document", "finance-note")["content"] == original_body
    assert db.execute("SELECT COUNT(*) FROM objects WHERE namespace=? AND kind IN ('task','outbox')", (namespace,)).fetchone()[0] == 0


def assignment_case(change_source):
    current_store = ControlStore(work / (str(uuid4()) + ".sqlite"))
    current_namespace = "assignment-source-" + str(uuid4())
    current_store.initialize(current_namespace)
    envelope = {**recorded_query["envelope"], "execution_namespace": current_namespace, "request_id": str(uuid4())}
    creation_authorization = current_store.authorize(current_namespace, "create_assignment", recorded_create)
    bindings = {"create_assignment": {"authorization_id": creation_authorization, "idempotency_key": str(uuid4())}}
    records = []
    creation_tool = BusinessTool("create_assignment", current_store, envelope, bindings, records)
    created = json.loads(asyncio.run(creation_tool.execute(**recorded_create)))
    validator(operations["create_assignment"]["output"]).validate(created)
    replay = json.loads(asyncio.run(creation_tool.execute(**recorded_create)))
    assert replay == created
    original_key = bindings["create_assignment"]["idempotency_key"]
    bindings["create_assignment"]["idempotency_key"] = str(uuid4())
    with pytest.raises(web.HTTPConflict):
        asyncio.run(creation_tool.execute(**recorded_create))
    bindings["create_assignment"]["idempotency_key"] = original_key
    sending = {"task_id": created["task_id"], "task_version": "1", "recipient_id": recorded_create["coordinator_id"],
               "body": recorded_create["purpose"], "content_version": "1"}
    send_authorization = current_store.authorize(current_namespace, "send_assignment", sending)
    bindings["send_assignment"] = {"authorization_id": send_authorization, "idempotency_key": str(uuid4())}
    sending_tool = BusinessTool("send_assignment", current_store, envelope, bindings, records)
    if change_source:
        with current_store.connect() as db:
            source = current_store.get(db, current_namespace, "document", "finance-note")
            current_store.put(db, current_namespace, "document", "finance-note", {**source, "version": "2"})
        with pytest.raises(web.HTTPConflict):
            asyncio.run(sending_tool.execute(**sending))
    else:
        sent = json.loads(asyncio.run(sending_tool.execute(**sending)))
        validator(operations["send_assignment"]["output"]).validate(sent)
        reread = json.loads(asyncio.run(BusinessTool("read_assignment", ControlStore(current_store.path), envelope, {}, records).execute(task_id=created["task_id"])))
        validator(operations["read_assignment"]["output"]).validate(reread)
        assert reread["status"] == "WAITING_FEEDBACK" and sent["message_id"] in reread["message_ids"]
        current_store.control(current_namespace, "revoke", {"authorization_id": creation_authorization})
        assert json.loads(asyncio.run(creation_tool.execute(**recorded_create))) == created
    with current_store.connect() as db:
        task_count = db.execute("SELECT COUNT(*) FROM objects WHERE namespace=? AND kind='task'", (current_namespace,)).fetchone()[0]
        outbox_count = db.execute("SELECT COUNT(*) FROM objects WHERE namespace=? AND kind='outbox'", (current_namespace,)).fetchone()[0]
        bound = current_store.get(db, current_namespace, "assignment_source_binding", created["task_id"])
    assert task_count == 1 and outbox_count == (0 if change_source else 1)
    assert bound["source_versions"] == {"finance-note": "1"}
    return {"source_changed_after_create": change_source, "task_count": task_count, "outbox_count": outbox_count,
            "new_send_status": 409 if change_source else 200, "duplicate_creation_rejected": True,
            "original_creation_replayed_without_new_write": True, "task_id": created["task_id"]}


assignment_checks = [assignment_case(False), assignment_case(True)]
for relative, expected in received.items():
    if relative.startswith("validation/") or relative == "specs/selection-probe.json":
        assert hashlib.sha256((W1 / relative).read_bytes()).hexdigest() == expected
source_files = [W1 / "validation/business.py", ROOT / "validation/model_probe.py"]
report = {
    "status": "PASS_RECEIVED_SOURCE_BINDING_AND_BASELINE_SCHEMA",
    "full_A07_accepted": False, "backend_version": backend["info"]["version"],
    "received_commit": COMMIT, "received_source_sha256": received,
    "backend_specification_source": "FROZEN_GIT_OBJECTS",
    "recorded_tool_counts": counts, "runs": runs, "input_evidence_sha256": inputs,
    "source_code_sha256": {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in source_files},
    "source_revision_check": {
        "source_id": "finance-note", "current_document_version": current["version"],
        "reported_source_version": reported_version, "source_version_matches": source_version_matches,
        "body_changed": False, "external_request_sent": False,
        "earlier_query_status": 409, "fresh_query_created": True, "missing_binding_status": 409,
        "same_version_metadata_change_status": 409, "state_checks": state_checks,
        "withdrawn_query_status": 410, "failed_tool_results_released": False,
        "source_scope_rejection_status": 403,
        "tool_adapter": "W2 BusinessTool with W1 1.4.1 ControlStore",
    }, "assignment_adapter_checks": assignment_checks,
    "new_external_model_requests": 0, "new_task_count": 2, "new_outbox_count": 1,
}
output = Path(__file__).parent / "w2-20261023-tool-semantics.json"
output.write_text(json.dumps(report, ensure_ascii=False, indent=2))
print(json.dumps({"status": report["status"], "recorded_tool_counts": counts,
                  "source_revision_check": report["source_revision_check"]}, ensure_ascii=False))
