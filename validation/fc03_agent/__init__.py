from dataclasses import dataclass
import json

from aiohttp import web
from nanobot.agent.tools.base import Tool
from nanobot.agent.tools.context import current_request_context

from business import checksum, require
from boss_runtime_records import ATTRIBUTE, RuntimeBinding
from runtime_owner_read_tools import BossTodayReadTool

VERSION = "1.1.0"
TOOLS = frozenset({"todayRead"})


@dataclass(frozen=True)
class Fc03Context:
    role: str
    owner_id: str
    namespace: str
    dataset_id: str
    dataset_version: str
    request_id: str
    session_id: str
    active: bool
    read_parameters_json: str
    date: str
    timezone: str
    snapshot_sha256: str
    order_version: str
    client_request_id: str | None = None
    allowed_list_ids: frozenset[str] = frozenset()
    selected_list_id: str | None = None
    selected_item_id: str | None = None


def register_fc03_tools(registry, store, context_provider, *, formal=False):
    require(callable(context_provider), "缺少本人认证请求生产者", web.HTTPBadRequest)
    if formal:
        from fc03_agent.formal import FORMAL_TOOLS, FormalMorningTool
        names = FORMAL_TOOLS
        require(not any(registry.has(name) for name in names), "晨间工具名称已经注册", web.HTTPConflict)
        for name in sorted(names):
            registry.register(FormalMorningTool(store, context_provider, name))
    else:
        names = TOOLS
        require(not any(registry.has(name) for name in names), "晨间工具名称已经注册", web.HTTPConflict)
        registry.register(Fc03TodayTool(store, context_provider))
    return sorted(names)


class Fc03TodayTool(Tool):
    name = "todayRead"
    description = "读取当前可信范围的本人晨间事项、来源、排序及缺少范围；不保存次序或执行本人决定。"

    def __init__(self, store, context_provider):
        self.store, self.context_provider = store, context_provider
        self.adapter = BossTodayReadTool(store, "BOSS")

    @property
    def parameters(self):
        return self.adapter.parameters

    def cast_params(self, params):
        return params

    def context(self, *, require_runtime=True):
        context = self.context_provider()
        require(isinstance(context, Fc03Context) and context.role == "BOSS" and context.active is True,
                "晨间本人认证请求无效", web.HTTPForbidden)
        require(context.namespace == "ui-check" and bool(context.request_id) and bool(context.session_id),
                "晨间执行范围无效", web.HTTPForbidden)
        request = current_request_context()
        if require_runtime and request is not None:
            binding = request.attributes.get(ATTRIBUTE)
            require(isinstance(binding, RuntimeBinding) and binding.recorder.store.path.resolve() == self.store.path.resolve()
                    and binding.recorder.namespace == context.namespace and binding.request_id == context.request_id
                    and binding.session_id == context.session_id and request.sender_id == context.owner_id,
                    "晨间工具与实际Runtime请求不符", web.HTTPForbidden)
        with self.store.connect() as db:
            db.execute("BEGIN")
            self.store.active(db, context.namespace)
            initial = self.store.get(db, context.namespace, "initial", "snapshot")
            require(initial["source_type"] == "SIMULATED" and all(initial[key] == getattr(context, key)
                for key in ("owner_id", "dataset_id", "dataset_version")), "晨间本人或资料范围不符", web.HTTPForbidden)
        return context

    async def execute(self, **params):
        require(not self.adapter.validate_params(params), "晨间读取输入不符合正式Schema", web.HTTPBadRequest)
        context = self.context()
        require(checksum(params) == checksum(json.loads(context.read_parameters_json)),
                "模型读取参数与当前明确范围不符", web.HTTPForbidden)
        result = await self.adapter.execute(**params)
        output = json.loads(result)
        require(output["source_type"] == "SIMULATED" and all(output[key] == getattr(context, key)
                for key in ("date", "timezone", "snapshot_sha256", "order_version")),
                "晨间日期、时区或当前快照已经变化", web.HTTPConflict)
        require(self.context() == context, "晨间读取期间认证范围已经变化", web.HTTPConflict)
        return result
