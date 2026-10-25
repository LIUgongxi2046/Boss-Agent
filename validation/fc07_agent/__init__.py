from dataclasses import dataclass
import json

from aiohttp import web
from nanobot.agent.tools.base import Tool
from nanobot.agent.tools.context import current_request_context

from business import encode, require
from boss_assignment_sources import AssignmentSourcesAPI
from boss_runtime_records import ATTRIBUTE, RuntimeBinding
from model_probe import BusinessTool
from runtime_assignment_source_tool import BossAssignmentSourcesReadTool

TOOLS = frozenset({"read_assignment", "assignmentSourcesRead"})
VERSION = "1.0.0"


@dataclass(frozen=True)
class Fc07Context:
    role: str
    owner_id: str
    namespace: str
    dataset_id: str
    dataset_version: str
    request_id: str
    session_id: str
    active: bool
    task_id: str
    task_version: str
    review_sha256: str


def register_fc07_tools(registry, store, context_provider):
    require(callable(context_provider), "缺少可信本人请求生产者", web.HTTPBadRequest)
    require(not any(registry.has(name) for name in TOOLS), "交办工具名称已经注册", web.HTTPConflict)
    for name in sorted(TOOLS):
        registry.register(Fc07ReadTool(store, context_provider, name))
    return sorted(TOOLS)


class Fc07ReadTool(Tool):
    def __init__(self, store, context_provider, name):
        require(name in TOOLS, "当前操作需要本人受信任页面", web.HTTPForbidden)
        self.store, self.context_provider, self._name = store, context_provider, name

    @property
    def name(self):
        return self._name

    @property
    def parameters(self):
        return BossAssignmentSourcesReadTool(self.store, "BOSS").parameters if self.name == "assignmentSourcesRead" else BusinessTool(self.name, self.store, {}, {}, []).parameters

    @property
    def description(self):
        return "读取当前明确选择的交办及其来源资格；准备本人页面核查，不发送、不催办、不批准延期或确认完成。"

    def cast_params(self, params):
        return params

    def context(self, *, runtime=True):
        context = self.context_provider()
        require(isinstance(context, Fc07Context) and context.role == "BOSS" and context.active is True,
                "交办本人请求已经无效", web.HTTPForbidden)
        require(context.namespace == "ui-check" and context.request_id and context.session_id, "交办执行范围无效", web.HTTPForbidden)
        request = current_request_context()
        if runtime and request is not None:
            binding = request.attributes.get(ATTRIBUTE)
            require(isinstance(binding, RuntimeBinding) and binding.recorder.store.path.resolve() == self.store.path.resolve()
                and binding.recorder.namespace == context.namespace and binding.request_id == context.request_id
                and binding.session_id == context.session_id and request.sender_id == context.owner_id,
                "交办工具与实际Runtime请求不符", web.HTTPForbidden)
        with self.store.connect() as db:
            db.execute("BEGIN")
            self.store.active(db, context.namespace)
            initial = self.store.get(db, context.namespace, "initial", "snapshot")
            require(initial["source_type"] == "SIMULATED" and all(initial[key] == getattr(context, key)
                for key in ("owner_id", "dataset_id", "dataset_version")), "交办本人或资料版本不符", web.HTTPForbidden)
            task = self.store.get(db, context.namespace, "task", context.task_id)
            require(task["version"] == context.task_version and task["execution_namespace"] == context.namespace,
                    "当前交办版本或空间已经变化", web.HTTPConflict)
        view = AssignmentSourcesAPI(self.store).read(context.role, context.task_id)
        require(view["review_sha256"] == context.review_sha256, "当前交办来源或证据已经变化", web.HTTPConflict)
        return context

    async def execute(self, **params):
        require(not self.validate_params(params), "交办读取参数不符合正式Schema", web.HTTPBadRequest)
        context = self.context()
        require(params["task_id"] == context.task_id, "模型替换了当前选择的交办", web.HTTPForbidden)
        if self.name == "assignmentSourcesRead":
            result = await BossAssignmentSourcesReadTool(self.store, context.role).execute(**params)
        else:
            envelope = {key: getattr(context, key) for key in ("owner_id", "dataset_id", "dataset_version", "request_id", "session_id")}
            envelope["execution_namespace"] = context.namespace
            result = await BusinessTool(self.name, self.store, envelope, {}, []).execute(**params)
        require(self.context() == context, "读取期间交办范围或认证已经变化", web.HTTPConflict)
        return result
