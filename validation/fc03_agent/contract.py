from fc03_agent import Fc03TodayTool, VERSION


def interface_contract(store, context_provider, *, formal=False):
    tools = [Fc03TodayTool(store, context_provider)]
    if formal:
        from fc03_agent.formal import FORMAL_TOOLS, FormalMorningTool
        tools = [FormalMorningTool(store, context_provider, name) for name in sorted(FORMAL_TOOLS)]
    return {"feature_id": "FC03", "version": VERSION, "source_type": "SIMULATED",
        "tools": [tool.to_schema() for tool in tools],
        "runtime_extension": {"feature_id": "FC03", "morning_context": {
            "date": "正式date", "timezone": "正式timezone", "snapshot_sha256": "当前正式快照摘要",
            "order_version": "当前本人次序版本", "parameters_sha256": "可信读取参数摘要",
            "selected_item_ref": "可选；正式清单与事项的对象、版本和来源引用"},
            "tool_result_fields": ["date", "timezone", "snapshot_sha256", "order_version", "business_clock", "list_id", "list_version", "item_refs", "document_ref"]},
        "owner_decision_tools_registered": False, "persistent_list_interface": "morning.schema.json 1.0.0" if formal else "LEGACY_READ_ONLY"}
