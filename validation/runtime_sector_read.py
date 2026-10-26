# 专题只读工具：使用与 F15-F23 页面相同的模拟资料包与筛选条件。
# 不创建任务、计划、会议或决定，也不发送消息。
from __future__ import annotations

import json
from urllib.parse import urlencode

from aiohttp import web
from nanobot.agent.tools.base import Tool

from business import encode, require
from boss_execution_scope import NAMESPACE
from boss_sector_api import BossSectorAPI, SECTORS


class BossSectorReadTool(Tool):
    def __init__(self, store, role, *, owner_id="boss-1"):
        require(role == "BOSS", "当前专题读取仅允许本人", web.HTTPForbidden)
        self.store, self.owner_id = store, owner_id

    @property
    def name(self):
        return "bossSectorRead"

    @property
    def description(self):
        return ("按专题页面读取本人当前模拟指标、明细、章节、关系、流程、来源与缺失范围；"
                "只读，不创建或修改交办、计划、会议与决定，不发送消息。")

    @property
    def parameters(self):
        return {"type": "object",
                "properties": {"page": {"type": "string", "enum": sorted(SECTORS)},
                               "filters": {"type": "object", "additionalProperties": {"type": "string"}}},
                "required": ["page"], "additionalProperties": False}

    @property
    def read_only(self):
        return True

    async def execute(self, page, filters=None):
        require(page in SECTORS, "专题页面不存在", web.HTTPBadRequest)
        require(filters is None or (isinstance(filters, dict)
                and all(isinstance(key, str) and isinstance(value, str) for key, value in filters.items())),
                "专题筛选条件无效", web.HTTPBadRequest)
        with self.store.connect() as db:
            self.store.active(db, NAMESPACE)
            snapshot = self.store.get(db, NAMESPACE, "initial", "snapshot")
            require(snapshot["owner_id"] == self.owner_id and snapshot["source_type"] == "SIMULATED",
                    "当前资料与服务端本人范围不符", web.HTTPForbidden)
        query = urlencode({"page": page, "filters": json.dumps(filters or {})})
        status, body = BossSectorAPI(self.store).serve("BOSS", query)
        require(status == 200, "专题读取失败", web.HTTPConflict)
        return encode(body)
