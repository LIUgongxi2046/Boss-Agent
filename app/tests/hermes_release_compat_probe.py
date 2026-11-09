import inspect
import json

from run_agent import AIAgent
from tools.registry import ToolRegistry

from agent_artifact_hermes import FORMAT_TOOL_NAME, FORMAT_TOOL_SCHEMA, TOOL_NAME, TOOL_SCHEMA, register_meeting_brief


registry = ToolRegistry()
register_meeting_brief(registry)
assert registry.get_schema(TOOL_NAME) == TOOL_SCHEMA
assert registry.get_schema(FORMAT_TOOL_NAME) == FORMAT_TOOL_SCHEMA
assert registry.get_definitions({TOOL_NAME, FORMAT_TOOL_NAME}, quiet=True) == []
parameters = inspect.signature(AIAgent.run_conversation).parameters
assert "user_message" in parameters
print(json.dumps({"registry": "PASS", "closed_tools": [TOOL_NAME, FORMAT_TOOL_NAME],
                  "run_conversation_parameters": list(parameters)}, ensure_ascii=False))
