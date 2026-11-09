PRODUCT_TOOL_NAMES = frozenset({
    "query_metrics", "read_evidence",
    "workspace_read_file", "workspace_write_file",
    "create_managed_child", "dispatch_managed_child", "read_managed_child_result",
    "read_bound_documents", "read_product_memory", "read_enabled_method",
    "prepare_domain_intent", "read_meeting_context", "read_decision_receipt", "save_meeting_draft",
    "read_minutes_context", "save_minutes_draft", "bossEvidenceRead",
    "bossMeetingsRead", "meetingArrangementRead", "request_additional_input", "meetingDraftSave", "meetingConfirm", "meetingCancel", "meetingHeld", "boss.meeting.brief.prepare",
})

METHOD_DEPENDENCY_TOOL_NAMES = PRODUCT_TOOL_NAMES - {"bossMeetingsRead", "meetingArrangementRead", "meetingConfirm", "meetingCancel", "meetingHeld", "boss.meeting.brief.prepare", "create_managed_child", "dispatch_managed_child", "read_managed_child_result"}
