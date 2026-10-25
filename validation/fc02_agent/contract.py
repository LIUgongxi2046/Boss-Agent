from fc02_agent import TOOLS, VERSION, Fc02Tool


def interface_contract(store, context_provider):
    return {"feature_id": "FC02", "version": VERSION, "source_type": "SIMULATED",
            "tools": [Fc02Tool(store, context_provider, name).to_schema() for name in sorted(TOOLS)],
            "query_context_schema": {
                "$schema": "https://json-schema.org/draft/2020-12/schema", "type": "object", "additionalProperties": False,
                "required": ["parameters", "previous_query_id", "overridden_fields", "inherited_fields", "parameters_sha256"],
                "properties": {"parameters": {"type": "object"}, "previous_query_id": {"type": ["string", "null"]},
                    "overridden_fields": {"type": "array", "uniqueItems": True, "items": {"type": "string"}},
                    "inherited_fields": {"type": "array", "uniqueItems": True, "items": {"type": "string"}},
                    "parameters_sha256": {"type": "string", "pattern": "^[a-f0-9]{64}$"}}},
            "runtime_extension": {"feature_id": "FC02", "source_type": "SIMULATED",
                "bi_query_context": "QueryBinding.visible数组", "bi_readable_query_ids": "当前服务端选择的query_id数组",
                "tool_result_fields": ["bi_query_context", "definition_versions", "detail_refs", "source_refs", "result_sha256"]}}
