import hashlib
import importlib.metadata
import json
import subprocess
from pathlib import Path
from typing import NotRequired, get_args, get_origin, get_type_hints

from nanobot.webui import outbound_wire

schema_path = Path("/Users/liuhaoxian/.codex/worktrees/boss-business/Boss-Agent/specs/runtime-events.schema.json")
received_commit = "fc4b2b5e88f9178312f6a7116e160ceeb03e160b"
schema_bytes = subprocess.check_output(["git", "show", received_commit + ":specs/runtime-events.schema.json"], cwd=schema_path.parents[1])
schema = json.loads(schema_bytes)
source_path = Path(outbound_wire.__file__)
results = []
for name, native in (
    ("RecoveryState", outbound_wire.RecoveryStateWirePayload),
    ("RetryStatus", outbound_wire.RetryStatusWirePayload),
    ("TurnEnd", outbound_wire.TurnEndWirePayload),
    ("ContextCompaction", outbound_wire.ContextCompactionWirePayload),
):
    definition = schema["$defs"][name]
    chat = schema["$defs"]["ChatEvent"]
    specific = definition["allOf"][1]
    properties = {**chat["properties"], **specific["properties"]}
    required = set(chat["required"]) | set(specific.get("required", []))
    native_fields = get_type_hints(native, include_extras=True)
    native_required = {field for field, annotation in native_fields.items() if get_origin(annotation) is not NotRequired}
    assert set(properties) == set(native_fields)
    assert required == native_required
    assert properties["event"]["const"] in get_args(native_fields["event"])
    results.append({"schema_definition": name, "wire_event": properties["event"]["const"],
                    "field_count": len(properties), "required_fields": sorted(required),
                    "field_names_and_requiredness_match": True})
report = {
    "status": "PASS_TYPED_EVENT_FIELDS_ONLY", "full_A07_accepted": False,
    "nanobot_distribution_version": importlib.metadata.version("nanobot-ai"),
    "schema_id": schema["$id"], "schema_sha256": hashlib.sha256(schema_bytes).hexdigest(),
    "received_commit": received_commit,
    "installed_outbound_wire_sha256": hashlib.sha256(source_path.read_bytes()).hexdigest(),
    "results": results,
    "unverified": ["实际公共WebSocket流", "内部推理过滤", "持久运行关联", "断线续接次序", "动态Tool事件字段"],
}
output = Path(__file__).parent / "w2-20261023-runtime-event-fields.json"
output.write_text(json.dumps(report, ensure_ascii=False, indent=2))
print(json.dumps({"status": report["status"], "event_count": len(results),
                  "nanobot_distribution_version": report["nanobot_distribution_version"]}, ensure_ascii=False))
