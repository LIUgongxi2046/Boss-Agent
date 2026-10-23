from copy import deepcopy

from sop_write_tools.fc01 import SCHEMA, TOOLS, VERSION, Fc01Tool


def interface_contract(store, context_provider):
    coordinate = deepcopy(SCHEMA["$defs"]["CoordinateInput"])
    coordinate["required"].remove("client_request_id")
    del coordinate["properties"]["client_request_id"]
    return {
        "version": VERSION, "feature_id": "FC01", "source_type": "SIMULATED",
        "tools": [Fc01Tool(store, context_provider, name).to_schema() for name in sorted(TOOLS)],
        "preparation_output": {
            "$schema": "https://json-schema.org/draft/2020-12/schema", "$defs": deepcopy(SCHEMA["$defs"]),
            "type": "object", "additionalProperties": False,
            "required": ["source_type", "preparation_sha256", "coordinate_input", "source_refs", "owner_decision_required",
                         "business_authority_granted", "external_service_invoked", "next_operation", "owner_page"],
            "properties": {
                "source_type": {"const": "SIMULATED"}, "preparation_sha256": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
                "coordinate_input": coordinate,
                "source_refs": {"type": "array", "minItems": 1, "items": {"type": "object", "additionalProperties": False,
                    "required": ["source_id", "version", "source_sha256"], "properties": {
                        "source_id": {"type": "string"}, "version": {"type": "string"},
                        "source_sha256": {"type": "string", "pattern": "^[a-f0-9]{64}$"}}}},
                "owner_decision_required": {"const": True}, "business_authority_granted": {"const": False},
                "external_service_invoked": {"const": False}, "next_operation": {"const": "boss.supply_quality.coordinate"},
                "owner_page": {"enum": ["F14", "F21"]},
            },
        },
        "runtime_record_additions": {
            "source_type": "SIMULATED", "external_model_invoked": False, "external_delivery_verified": False,
            "feature_id": "FC01", "simulated_model_events": "event_id/state/source_type/request_sha256/usage/cost_total/finish_reason/tool_call_ids",
            "tool_results_additions": "source_type/source_id/review_sha256/preparation_sha256/source_refs/origin/result_sha256/owner_decision_required",
            "tool_errors": "tool_id/tool_call_id/error_type/source_type",
        },
    }
