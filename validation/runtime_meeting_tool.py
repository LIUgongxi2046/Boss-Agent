from aiohttp import web
from nanobot.agent.tools.base import Tool

from business import encode, require
from boss_meetings import MeetingAPI


class BossCurrentMeetingTool(Tool):
    def __init__(self, store, role):
        require(role is not None, "需要认证身份", web.HTTPUnauthorized)
        require(role == "BOSS", "当前会议仅允许本人读取", web.HTTPForbidden)
        self.store = store
        self._role = role

    @property
    def name(self):
        return "meetingArrangementRead"

    @property
    def description(self):
        return "读取当前会议版本、状态、时间、参与对象及待确认草稿版本；独立草稿不会代替已确认会议。"

    @property
    def parameters(self):
        return {"type": "object", "properties": {}, "additionalProperties": False}

    async def execute(self):
        return encode(MeetingAPI(self.store).read(self._role))
