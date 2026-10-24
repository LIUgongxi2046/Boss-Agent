from fc07_agent import Fc07ReadTool, TOOLS, VERSION


def interface_contract(store, context_provider):
    return {"feature_id": "FC07", "version": VERSION, "source_type": "SIMULATED",
        "tools": [Fc07ReadTool(store, context_provider, name).to_schema() for name in sorted(TOOLS)],
        "context_fields": ["role", "owner_id", "namespace", "dataset_id", "dataset_version", "request_id", "session_id",
                           "active", "task_id", "task_version", "review_sha256"],
        "runtime_fields": {"assignment_context": ["task_id", "task_version", "review_sha256"],
                           "tool_results": ["task_id", "version", "status", "source_refs", "review_sha256", "result_sha256"]},
        "owner_decision_tools_registered": False,
        "authorized_write_adapter": "sop_write_tools.fc01.Fc01Tool；仅消费真实生产者绑定的已有授权"}
