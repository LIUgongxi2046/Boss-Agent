# 专题只读工具：使用与 F15-F23 页面相同的模拟资料包与筛选条件。
# 不创建任务、计划、会议或决定，也不发送消息。
from __future__ import annotations

import json
from urllib.parse import urlencode

from aiohttp import web

from business import encode, require
from boss_sector_api import CATALOGUE, BossSectorAPI, SECTORS
from runtime_page_read_tools import _BossPageReadTool

PAGE_TITLES = "；".join(page + "=" + str(CATALOGUE[page]["title"]) for page in sorted(SECTORS))


class BossSectorReadTool(_BossPageReadTool):
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
                "properties": {"page": {"type": "string", "enum": sorted(SECTORS),
                                        "description": "专题页面编号与标题对照：" + PAGE_TITLES},
                               "filters": {"type": "object", "additionalProperties": {"type": "string"},
                                           "description": "可选筛选项，键为页面筛选项名称，值为对应取值"}},
                "required": ["page"], "additionalProperties": False}

    async def execute(self, page, filters=None):
        self._scope()
        require(page in SECTORS, "专题页面不存在", web.HTTPBadRequest)
        require(filters is None or (isinstance(filters, dict)
                and all(isinstance(key, str) and isinstance(value, str) for key, value in filters.items())),
                "专题筛选条件无效", web.HTTPBadRequest)
        query = urlencode({"page": page, "filters": json.dumps(filters or {})})
        status, body = BossSectorAPI(self._api.store).serve("BOSS", query)
        require(status == 200, "专题读取失败", web.HTTPConflict)
        return encode(body)
