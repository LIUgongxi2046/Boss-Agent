from aiohttp import web
from nanobot.agent.tools.base import Tool

from business import encode, require
from boss_owner_plans import OwnerPlansAPI
from boss_today import TodayAPI


def _require_owner(role):
    require(role is not None, "需要认证身份", web.HTTPUnauthorized)
    require(role == "BOSS", "本人事项与计划仅允许本人读取", web.HTTPForbidden)


class BossTodayReadTool(Tool):
    def __init__(self, store, role):
        _require_owner(role)
        self._api = TodayAPI(store)
        self._role = role

    @property
    def name(self):
        return "todayRead"

    @property
    def description(self):
        return "读取本人当前今日事项、稳定对象编号、来源版本、排序版本、理由及资料缺口；该读取不修改事项次序。"

    @property
    def parameters(self):
        return {"type": "object", "properties": {}, "additionalProperties": False}

    async def execute(self):
        return encode(self._api.read(self._role))


class BossOwnerPlansReadTool(Tool):
    def __init__(self, store, role):
        _require_owner(role)
        self._api = OwnerPlansAPI(store)
        self._role = role

    @property
    def name(self):
        return "ownerPlansRead"

    @property
    def description(self):
        return "读取本人当前计划、事件、内部通知和执行记录，保留CronService技术执行责任及外部送达未验证状态；该读取不保存计划或触发调度。"

    @property
    def parameters(self):
        return {"type": "object", "properties": {}, "additionalProperties": False}

    async def execute(self):
        return encode(self._api.read(self._role))
