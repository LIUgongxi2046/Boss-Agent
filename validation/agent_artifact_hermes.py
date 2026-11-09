import json
from pathlib import Path

from tools.registry import ToolRegistry


TOOL_NAME = "boss_meeting_brief_docx"
FORMAT_TOOL_NAME = "boss_meeting_brief"
TOOLSET = "boss_artifacts"
PARAMETERS = json.loads((Path(__file__).parent / "agent_artifact_schema.json").read_text(encoding="utf-8"))["$defs"]["meeting_brief_tool_request"]
TOOL_SCHEMA = {
    "name": TOOL_NAME,
    "description": "使用当前会话已选择的来源生成会议简报 DOCX。",
    "parameters": PARAMETERS,
}
FORMAT_TOOL_SCHEMA = {
    "name": FORMAT_TOOL_NAME,
    "description": "使用当前会话已选择的来源生成指定格式的会议简报。",
    "parameters": json.loads((Path(__file__).parent / "agent_artifact_schema.json").read_text(encoding="utf-8"))["$defs"]["meeting_brief_format_tool_request"],
}


def meeting_brief_unavailable(args, **kwargs):
    raise RuntimeError("会议简报工具缺少可信身份、隔离与服务连接")


def meeting_brief_available():
    return False


def register_meeting_brief(registry):
    if not isinstance(registry, ToolRegistry):
        raise ValueError("需要 Hermes ToolRegistry")
    if registry.get_entry(TOOL_NAME) is not None or registry.get_entry(FORMAT_TOOL_NAME) is not None:
        raise ValueError("会议简报工具已经注册")
    registry.register(name=TOOL_NAME, toolset=TOOLSET, schema=TOOL_SCHEMA,
                      handler=meeting_brief_unavailable, check_fn=meeting_brief_available,
                      is_async=False)
    registry.register(name=FORMAT_TOOL_NAME, toolset=TOOLSET, schema=FORMAT_TOOL_SCHEMA,
                      handler=meeting_brief_unavailable, check_fn=meeting_brief_available,
                      is_async=False)
    if registry.get_entry(TOOL_NAME) is None or registry.get_entry(FORMAT_TOOL_NAME) is None:
        raise ValueError("会议简报工具注册失败")
