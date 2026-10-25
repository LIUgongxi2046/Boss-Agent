from fc04_agent import Fc04ReadTool, VERSION


def interface_contract(store, context_provider):
    return {"feature_id": "FC04", "version": VERSION, "source_type": "SIMULATED",
        "tools": [Fc04ReadTool(store, context_provider).to_schema()], "allowed_projections": ["notifications"],
        "context_fields": ["role", "owner_id", "namespace", "dataset_id", "dataset_version", "request_id",
                           "session_id", "active", "projection_sha256"],
        "runtime_fields": {"reminder_context": ["projection", "projection_sha256"],
                           "tool_results": ["rule_versions", "event_refs", "dispatch_refs", "result_sha256"]},
        "owner_decision_tools_registered": False, "scheduler_executor_created": False}
