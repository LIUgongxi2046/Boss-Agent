from dataclasses import dataclass
import json

from aiohttp import web
from nanobot.agent.tools.base import Tool
from nanobot.agent.tools.context import current_request_context

from business import checksum, require
from boss_runtime_records import ATTRIBUTE, RuntimeBinding
from boss_workspace_api import BossWorkspaceAPI
from runtime_sop_read_tools import BossWorkspaceReadTool

TOOLS = frozenset({"bossWorkspaceRead"})
VERSION = "1.0.0"


def notifications_digest(value):
    return checksum({key: item for key, item in value.items() if key != "read_at"})


@dataclass(frozen=True)
class Fc04Context:
    role: str
    owner_id: str
    namespace: str
    dataset_id: str
    dataset_version: str
    request_id: str
    session_id: str
    active: bool
    projection_sha256: str


def register_fc04_tools(registry, store, context_provider):
    require(callable(context_provider), "缺少当前本人认证请求生产者", web.HTTPBadRequest)
    require(not registry.has("bossWorkspaceRead"), "工作投影工具已经注册", web.HTTPConflict)
    registry.register(Fc04ReadTool(store, context_provider))
    return sorted(TOOLS)


class Fc04ReadTool(Tool):
    name = "bossWorkspaceRead"
    description = "读取当前批准的经营提醒投影、实际规则与处理状态；不知晓、暂缓、关闭、安排会议或创建交办。"
    allowed_projections = frozenset({"notifications"})

    def __init__(self, store, context_provider):
        self.store, self.context_provider = store, context_provider
        self.adapter = BossWorkspaceReadTool(BossWorkspaceAPI(store), "BOSS", allowed_projections=self.allowed_projections)

    @property
    def parameters(self):
        return self.adapter.parameters

    def cast_params(self, params):
        return params

    def context(self, *, runtime=True):
        context = self.context_provider()
        require(isinstance(context, Fc04Context) and context.role == "BOSS" and context.active is True,
                "提醒本人认证请求无效", web.HTTPForbidden)
        require(context.namespace == "ui-check" and context.request_id and context.session_id,
                "提醒当前执行空间无效", web.HTTPForbidden)
        request = current_request_context()
        if runtime and request is not None:
            binding = request.attributes.get(ATTRIBUTE)
            require(isinstance(binding, RuntimeBinding) and binding.recorder.store.path.resolve() == self.store.path.resolve()
                    and binding.recorder.namespace == context.namespace and binding.request_id == context.request_id
                    and binding.session_id == context.session_id and request.sender_id == context.owner_id,
                    "提醒读取与实际Runtime请求不符", web.HTTPForbidden)
        with self.store.connect() as db:
            db.execute("BEGIN")
            self.store.active(db, context.namespace)
            data = self.store.get(db, context.namespace, "initial", "snapshot")
            require(data["source_type"] == "SIMULATED" and all(data[key] == getattr(context, key)
                for key in ("owner_id", "dataset_id", "dataset_version")), "提醒本人或资料范围不符", web.HTTPForbidden)
        return context

    async def execute(self, **params):
        require(not self.adapter.validate_params(params), "提醒读取参数不符合当前Schema", web.HTTPBadRequest)
        context = self.context()
        result = await self.adapter.execute(**params)
        require(notifications_digest(json.loads(result)) == context.projection_sha256,
                "提醒对象、规则或当前处理状态已经变化", web.HTTPConflict)
        require(self.context() == context, "提醒读取期间认证范围已经变化", web.HTTPConflict)
        return result
