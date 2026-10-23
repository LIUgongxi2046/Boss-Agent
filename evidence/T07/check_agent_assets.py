import ast
import hashlib
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator, FormatChecker

project = Path(__file__).resolve().parents[2]
assets_path = project / "specs" / "agent-assets.json"
current_schema_path = project / "specs" / "selection-probe.json"
backend_path = Path("/Users/liuhaoxian/.codex/worktrees/boss-business/Boss-Agent/specs/openapi.yaml")
events_path = backend_path.with_name("runtime-events.schema.json")
dictionary_path = backend_path.with_name("data-dictionary.json")
received_commit = "fc4b2b5e88f9178312f6a7116e160ceeb03e160b"


def received_source(path):
    repository = backend_path.parents[1]
    return subprocess.check_output(
        ["git", "show", received_commit + ":" + str(path.relative_to(repository))],
        cwd=repository,
    )


backend_bytes = received_source(backend_path)
events_bytes = received_source(events_path)
dictionary_bytes = received_source(dictionary_path)
runtime_schema_bytes = received_source(backend_path.with_name("runtime-records.schema.json"))
workspace_path = project / "validation" / "boss_workspace_api.py"
transcription_path = project / "validation" / "boss_transcription.py"
research_tool_path = project / "validation" / "boss_agent_read_tools.py"
runtime_records_path = project / "validation" / "boss_runtime_records.py"
runtime_query_path = project / "validation" / "runtime_records_query.py"
runtime_ui_path = project / "app" / "webui" / "MaintainerRuntimeRecords.tsx"
meeting_tool_path = project / "validation" / "runtime_meeting_tool.py"
inputs = {
    "agent_assets": hashlib.sha256(assets_path.read_bytes()).hexdigest(),
    "selection_probe": hashlib.sha256(current_schema_path.read_bytes()).hexdigest(),
    "backend_design": hashlib.sha256(backend_bytes).hexdigest(),
    "runtime_events": hashlib.sha256(events_bytes).hexdigest(),
    "data_dictionary": hashlib.sha256(dictionary_bytes).hexdigest(),
    "runtime_records_schema": hashlib.sha256(runtime_schema_bytes).hexdigest(),
    "workspace_projection_source": hashlib.sha256(workspace_path.read_bytes()).hexdigest(),
    "transcription_adapter_source": hashlib.sha256(transcription_path.read_bytes()).hexdigest(),
    "research_tool_source": hashlib.sha256(research_tool_path.read_bytes()).hexdigest(),
    "runtime_records_source": hashlib.sha256(runtime_records_path.read_bytes()).hexdigest(),
    "runtime_query_source": hashlib.sha256(runtime_query_path.read_bytes()).hexdigest(),
    "runtime_ui_source": hashlib.sha256(runtime_ui_path.read_bytes()).hexdigest(),
    "current_meeting_tool_source": hashlib.sha256(meeting_tool_path.read_bytes()).hexdigest(),
}
assets = json.loads(assets_path.read_text())
schema = json.loads(current_schema_path.read_text())
backend = yaml.safe_load(backend_bytes)
events = json.loads(events_bytes)
dictionary = json.loads(dictionary_bytes)
runtime_schema = json.loads(runtime_schema_bytes)
Draft202012Validator.check_schema(runtime_schema)
boss_projections = next(
    ast.literal_eval(node.value) for node in ast.parse(workspace_path.read_text()).body
    if isinstance(node, ast.Assign) and any(
        isinstance(target, ast.Name) and target.id == "BOSS_PAGES" for target in node.targets
    )
)
assert assets["status"] == "PENDING_A06_A07_ACCEPTANCE"
assert assets["formal_backend_version"] == backend["info"]["version"]
assert events["$id"] == "urn:boss-agent:runtime-events:" + assets["formal_event_version"]
transcription_fields = {
    node.target.id
    for definition in ast.parse(transcription_path.read_text()).body
    if isinstance(definition, ast.ClassDef) and definition.name == "TranscriptionResult"
    for node in definition.body
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
}
assert transcription_fields == set(dictionary["entities"]["voice_transcript"]["fields"])
assert {item["tool_id"] for item in assets["tools"]} == {
    item["operation_id"] for item in schema["operations"]
}
for operation in schema["operations"]:
    for field in ("input_schema", "output_schema"):
        assert operation[field].rsplit("/", 1)[1] in schema["io_schema"]["$defs"]
tool_operations = {item["operationId"]: item for item in backend["x-tool-operations"]}
for tool in assets["tools"]:
    operation = tool_operations[tool["operationId"]]
    assert tool["implementation"] == operation["implementation"]
    assert tool["side_effect"] == operation["side_effect"]
    for own, upstream in (("input_schema", "input"), ("output_schema", "output"), ("error_schema", "errors")):
        assert tool[own] == operation[upstream]
        assert tool[own].rsplit("/", 1)[1] in schema["io_schema"]["$defs"]
assert {item["requirement_id"] for item in assets["sops"]} == {
    "FR-" + str(index).zfill(2) for index in range(1, 14)
}
assert len({item["sop_id"] for item in assets["sops"]}) == 13
operations = {
    value["operationId"]
    for path in backend["paths"].values()
    for value in path.values()
    if isinstance(value, dict) and "operationId" in value
}
command_operations = {item["operationId"] for item in backend["x-websocket-operations"]}
assert {item["sop_id"] for item in assets["sop_backend_bindings"]} == {
    item["sop_id"] for item in assets["sops"]
}
for binding in assets["sop_backend_bindings"]:
    assert set(binding["read_operations"]) <= operations | set(tool_operations)
    assert set(binding["command_operations"]) <= command_operations | set(tool_operations)
    if "bossWorkspaceRead" in binding["read_operations"]:
        assert binding["workspace_projections"]
    assert set(binding.get("workspace_projections", [])) <= boss_projections
simulation_operations = backend["x-simulation-operations"]
assert {item["interface_id"] for item in simulation_operations} == {
    "SI" + str(index).zfill(2) for index in range(1, 15)
}
assert dictionary["entities"]["runtime_run"]["design_status"] == "W2_PRODUCER_BOUND_PUBLIC_INTEGRATION_RECHECK_PENDING"
assert events["x-pending"]
for binding in assets["pending_public_read_tools"]:
    assert binding["operationId"] in operations
    assert binding["role"] == "BOSS"
    assert binding["runtime_registration"] == "NOT_REGISTERED"
assert len(assets["agriculture"]["requirements"]) == 10
assert set(assets["agriculture"]["FR-19_uses"]) == {"BROILER", "EGG", "MILK", "BEEF"}
assert not assets["agent"]["evaluation_answers_allowed_in_context"]
assert not assets["prompts"]["grants_owner_authority"]
assert assets["knowledge"]["model_read_allowed_projections"] == ["research"]
assert assets["knowledge"]["model_read_permission"] == "BOSS"
assert assets["knowledge"]["model_read_requires_prepared_research"]
assert assets["knowledge"]["model_read_operation"] in operations
assert set(assets["knowledge"]["source_binding_fields"]) == set(dictionary["entities"]["query_source_binding"]["fields"])
assert {"valid_from", "valid_until", "validity_state"} <= set(dictionary["entities"]["document"]["fields"])
assert hashlib.sha256((project / "validation/boss_source_policy.py").read_bytes()).hexdigest() == backend["x-source-policy"]["policy_sha256"]
assert assets["knowledge"]["source_access_validator"] == backend["x-source-policy"]["current_access_validator"]
assert set(assets["tool_policy"]["assignment_binding_fields"]) == set(dictionary["entities"]["assignment_source_binding"]["fields"])
assert assets["tool_policy"]["authorization_validator"] == backend["x-tool-authorization-policy"]["implementation"]
actual_runtime = json.loads((project / "evidence/T16/runtime-version-ui/runtime-version-adoption.json").read_text())
assert actual_runtime["status"] == "PASS"
runtime_fields = dictionary["entities"]["runtime_run"]["fields"]
required_runtime_fields = {name for name, field in runtime_fields.items() if not field.get("optional", False)}
for stage in actual_runtime["stages"]:
    assert required_runtime_fields <= set(stage["runtime_record"])
sys.path.insert(0, str(project / "validation"))
from runtime_records_query import QUERY

assert QUERY == runtime_schema["$defs"]["RuntimeRecordsQuery"]
observed = {}
for path in sorted((project / "evidence/T16").glob("runtime-version-*/runtime-version-adoption.json")):
    for stage in json.loads(path.read_text())["stages"]:
        observed[stage["runtime_record"]["run_id"]] = stage["runtime_record"]
for stage in json.loads((project / "evidence/T19/w2-20261023-memory-confirmation/memory-confirmation-adoption.json").read_text())["stages"]:
    observed[stage["runtime_record"]["run_id"]] = stage["runtime_record"]
projection_count = 0
for path in sorted((project / "evidence/T16/runtime-record-faults").glob("*/runtime-records.json")):
    projection = json.loads(path.read_text())
    Draft202012Validator(runtime_schema, format_checker=FormatChecker()).validate(projection)
    projection_count += 1
    for row in projection["runs"]:
        observed[row["run_id"]] = row
database = project / ".work/w2-checks/memory-ui/memory.sqlite"
with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True) as db:
    for record in db.execute("SELECT body FROM objects WHERE namespace='ui-check' AND kind='runtime_run'"):
        row = json.loads(record[0])
        if row["run_id"] in observed:
            assert observed[row["run_id"]] == row
        observed[row["run_id"]] = row
current_count = 0
legacy_schema_errors = []
for row in observed.values():
    errors = list(Draft202012Validator({**runtime_schema, "$ref": "#/$defs/RuntimeRun"}, format_checker=FormatChecker()).iter_errors(row))
    if {"dataset_id", "dataset_version", "memory_reference"} <= set(row):
        Draft202012Validator({**runtime_schema, "$ref": "#/$defs/CurrentRuntimeRun"}, format_checker=FormatChecker()).validate(row)
        current_count += 1
    else:
        legacy_schema_errors.extend({"run_id": row["run_id"], "path": list(error.path),
                                     "validator": error.validator, "message": error.message}
                                    for error in errors)
report = {
    "status": "CURRENT_PRODUCER_VALID_LEGACY_SCHEMA_MISMATCH" if legacy_schema_errors else "PASS_DESIGN_STRUCTURE_ONLY",
    "full_A07_accepted": False,
    "input_sha256": inputs, "current_tool_count": len(assets["tools"]),
    "secretary_sop_count": len(assets["sops"]),
    "specified_public_read_bindings": len(assets["pending_public_read_tools"]),
    "sop_backend_binding_count": len(assets["sop_backend_bindings"]),
    "documented_tool_operations": len(tool_operations),
    "documented_command_operations": len(command_operations),
    "documented_simulation_interfaces": len(simulation_operations),
    "simulation_interfaces_mounted": False,
    "research_read_adapter_implemented": True,
    "research_read_public_runtime_registered": False,
    "voice_provider_fields_matched": len(transcription_fields),
    "backend_version": backend["info"]["version"],
    "backend_source_commit": received_commit,
    "source_binding_fields_matched": len(assets["knowledge"]["source_binding_fields"]),
    "assignment_binding_fields_matched": len(assets["tool_policy"]["assignment_binding_fields"]),
    "source_validity_policy_sha256_matched": True,
    "recorded_runtime_required_fields_matched": len(required_runtime_fields),
    "actual_runtime_runs_observed": len(observed),
    "legacy_runtime_schema_errors": legacy_schema_errors,
    "current_producer_runs_schema_validated": current_count,
    "actual_runtime_projections_validated": projection_count,
    "runtime_query_schema_matches_implementation": True,
    "remaining_backend_items": backend["x-pending"],
}
output = Path(__file__).parent / "w2-20261023-design-check.json"
output.write_text(json.dumps(report, ensure_ascii=False, indent=2))
print(json.dumps(report, ensure_ascii=False))
