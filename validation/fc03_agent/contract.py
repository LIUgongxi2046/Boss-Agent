from fc03_agent import Fc03TodayTool, VERSION


def interface_contract(store, context_provider):
    return {"feature_id": "FC03", "version": VERSION, "source_type": "SIMULATED",
        "tools": [Fc03TodayTool(store, context_provider).to_schema()],
        "runtime_extension": {"feature_id": "FC03", "morning_context": {
            "date": "正式date", "timezone": "正式timezone", "snapshot_sha256": "当前正式快照摘要",
            "order_version": "当前本人次序版本", "parameters_sha256": "可信读取参数摘要"},
            "tool_result_fields": ["date", "timezone", "snapshot_sha256", "order_version", "business_clock", "item_refs"]},
        "owner_decision_tools_registered": False, "persistent_list_interface": "PENDING_N1_FORMAL_SCHEMA"}
