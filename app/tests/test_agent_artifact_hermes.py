import json

import pytest
from jsonschema import Draft202012Validator
from tools.registry import ToolRegistry

from agent_artifact_hermes import FORMAT_TOOL_NAME, FORMAT_TOOL_SCHEMA, TOOL_NAME, TOOL_SCHEMA, register_meeting_brief


def test_real_hermes_registry_registers_closed_meeting_brief():
    registry = ToolRegistry()
    register_meeting_brief(registry)
    assert registry.get_schema(TOOL_NAME) == TOOL_SCHEMA
    assert registry.get_schema(FORMAT_TOOL_NAME) == FORMAT_TOOL_SCHEMA
    assert registry.get_definitions({TOOL_NAME}, quiet=True) == []
    validator = Draft202012Validator(TOOL_SCHEMA["parameters"])
    assert validator.is_valid({"source_ids": ["simulation-meeting-material"], "request_key": "brief"})
    assert not validator.is_valid({"source_ids": ["simulation-meeting-material"], "request_key": "brief", "path": "document.docx"})
    format_validator = Draft202012Validator(FORMAT_TOOL_SCHEMA["parameters"])
    for name in ("MARKDOWN", "PDF", "DOCX", "XLSX", "PPTX"):
        assert format_validator.is_valid({"source_ids": ["simulation-meeting-material"], "request_key": "brief", "format_name": name})
    assert not format_validator.is_valid({"source_ids": ["simulation-meeting-material"], "request_key": "brief", "format_name": "DOCX", "previous_artifact_id": "d6cc2b9f-e9a0-44e1-a9a9-772cab6d5df6"})
    assert registry.get_definitions({FORMAT_TOOL_NAME}, quiet=True) == []
    result = registry.dispatch(FORMAT_TOOL_NAME, {"source_ids": ["simulation-meeting-material"], "request_key": "brief", "format_name": "PDF"})
    assert "error" in (json.loads(result) if isinstance(result, str) else result)
    result = registry.dispatch(TOOL_NAME, {"source_ids": ["simulation-meeting-material"], "request_key": "brief"})
    assert "error" in (json.loads(result) if isinstance(result, str) else result)
    with pytest.raises(ValueError, match="已经注册"):
        register_meeting_brief(registry)
