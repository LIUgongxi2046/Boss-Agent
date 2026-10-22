"""Metadata-only diagnostic projection for local Boss-Agent desktop use.

Never persist model prompts, source body, raw tool arguments/results, personal
memory text, authorization payloads or private messages in runtime audit JSON.
The full authorised business state remains available only through the scoped
domain service, not model transport logs. T02 historical probe files stay
unchanged; this projection is opt-in for BOSS_PRODUCT_UI=1.
"""
from __future__ import annotations


class RedactedEventList(list):
    """Accept existing AgentHook/BusinessTool .append calls without raw bodies."""

    def __init__(self, records=()):
        super().__init__()
        # list.__init__(iterable) bypasses the overridden append method.
        # Resanitize any on-disk records loaded from older app versions.
        self.extend(records)

    @staticmethod
    def redact(raw: object) -> dict:
        if not isinstance(raw, dict):
            return {"type": "unrecognized_event"}
        kind = raw.get("type")
        entry = {
            "type": kind if isinstance(kind, str) else "unrecognized_event",
        }
        for field in ("at", "name", "iteration", "stop_reason"):
            value = raw.get(field)
            if isinstance(value, (int, float, str)) and field != "stop_reason":
                entry[field] = value
            if field == "stop_reason" and isinstance(value, str):
                entry[field] = value[:80]
        if kind == "runtime_admission":
            config = raw.get("configuration")
            if isinstance(config, dict):
                entry["configuration"] = {
                    key: config[key] for key in (
                        "provider", "model_id", "max_tool_rounds",
                        "max_output_tokens", "config_sha256"
                    ) if key in config and isinstance(config[key], (int, str))
                }
        elif kind == "iteration":
            usage = raw.get("usage")
            if isinstance(usage, dict):
                entry["usage"] = {
                    key: usage[key] for key in (
                        "prompt_tokens", "completion_tokens",
                        "total_tokens", "cached_tokens"
                    ) if key in usage and isinstance(usage[key], (int, float))
                }
            if raw.get("error"):
                entry["error_present"] = True
        elif kind == "tool":
            output = raw.get("output")
            if isinstance(output, dict):
                for key in ("task_id", "message_id", "status", "source_type", "query_id"):
                    if key in output and isinstance(output[key], str):
                        entry[key] = output[key][:128]
            entry["arguments_redacted"] = True
            entry["result_redacted"] = True
        elif kind in ("tool_error", "tool_validation_error"):
            entry["error_present"] = True
            entry["error_detail_redacted"] = True
        return entry

    def append(self, item: object) -> None:
        super().append(self.redact(item))

    def extend(self, sequence) -> None:
        for item in sequence:
            self.append(item)
