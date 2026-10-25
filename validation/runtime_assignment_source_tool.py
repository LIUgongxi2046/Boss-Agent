from aiohttp import web
from nanobot.agent.tools.base import Tool

from business import encode, require
from boss_assignment_sources import AssignmentSourcesAPI


class BossAssignmentSourcesReadTool(Tool):
    def __init__(self, store, role):
        require(role is not None, "需要认证身份", web.HTTPUnauthorized)
        require(role == "BOSS", "交办来源仅允许本人读取", web.HTTPForbidden)
        self._api = AssignmentSourcesAPI(store)
        self._role = role

    @property
    def name(self):
        return "assignmentSourcesRead"

    @property
    def description(self):
        return "读取已有交办的当前来源、采用版本与需要本人核查的范围；无权或失效来源不返回原文片段。该读取不确认来源、不改变任务状态、不发送消息。"

    @property
    def parameters(self):
        return {"type": "object", "properties": {
            "task_id": {"type": "string", "minLength": 1, "maxLength": 128},
        }, "required": ["task_id"], "additionalProperties": False}

    async def execute(self, task_id):
        return encode(self._api.read(self._role, task_id))
