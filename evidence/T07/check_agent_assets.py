import ast
import hashlib
import json
from pathlib import Path

import yaml

project = Path(__file__).resolve().parents[2]
assets_path = project / "specs" / "agent-assets.json"
current_schema_path = project / "specs" / "selection-probe.json"
backend_path = Path("/Users/liuhaoxian/.codex/worktrees/boss-business/Boss-Agent/specs/openapi.yaml")
events_path = backend_path.with_name("runtime-events.schema.json")
dictionary_path = backend_path.with_name("data-dictionary.json")
workspace_path = project / "validation" / "boss_workspace_api.py"
transcription_path = project / "validation" / "boss_transcription.py"
inputs = {
    "agent_assets": hashlib.sha256(assets_path.read_bytes()).hexdigest(),
    "selection_probe": hashlib.sha256(current_schema_path.read_bytes()).hexdigest(),
    "backend_design": hashlib.sha256(backend_path.read_bytes()).hexdigest(),
    "runtime_events": hashlib.sha256(events_path.read_bytes()).hexdigest(),
    "data_dictionary": hashlib.sha256(dictionary_path.read_bytes()).hexdigest(),
    "workspace_projection_source": hashlib.sha256(workspace_path.read_bytes()).hexdigest(),
    "transcription_adapter_source": hashlib.sha256(transcription_path.read_bytes()).hexdigest(),
}
assets = json.loads(assets_path.read_text())
schema = json.loads(current_schema_path.read_text())
backend = yaml.safe_load(backend_path.read_text())
events = json.loads(events_path.read_text())
dictionary = json.loads(dictionary_path.read_text())
boss_projections = next(
    ast.literal_eval(node.value) for node in ast.parse(workspace_path.read_text()).body
    if isinstance(node, ast.Assign) and any(
        isinstance(target, ast.Name) and target.id == "BOSS_PAGES" for target in node.targets
    )
)
assert assets["status"] == "PENDING_T06"
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
assert dictionary["entities"]["runtime_run"]["design_status"] == "REQUIRES_W2_BINDING"
assert events["x-pending"]
for binding in assets["pending_public_read_tools"]:
    assert binding["operationId"] in operations
    assert binding["role"] == "BOSS"
    assert binding["runtime_registration"] == "NOT_REGISTERED"
assert len(assets["agriculture"]["requirements"]) == 10
assert set(assets["agriculture"]["FR-19_uses"]) == {"BROILER", "EGG", "MILK", "BEEF"}
assert not assets["agent"]["evaluation_answers_allowed_in_context"]
assert not assets["prompts"]["grants_owner_authority"]
assert hashlib.sha256(backend_path.read_bytes()).hexdigest() == inputs["backend_design"]
report = {
    "status": "PASS_DESIGN_STRUCTURE_ONLY", "full_A07_accepted": False,
    "input_sha256": inputs, "current_tool_count": len(assets["tools"]),
    "secretary_sop_count": len(assets["sops"]),
    "specified_public_read_bindings": len(assets["pending_public_read_tools"]),
    "sop_backend_binding_count": len(assets["sop_backend_bindings"]),
    "documented_tool_operations": len(tool_operations),
    "documented_command_operations": len(command_operations),
    "documented_simulation_interfaces": len(simulation_operations),
    "simulation_interfaces_mounted": False,
    "voice_provider_fields_matched": len(transcription_fields),
    "backend_version": backend["info"]["version"],
    "remaining_backend_items": backend["x-pending"],
}
output = Path(__file__).parent / "w2-20261023-design-check.json"
output.write_text(json.dumps(report, ensure_ascii=False, indent=2))
print(json.dumps(report, ensure_ascii=False))
