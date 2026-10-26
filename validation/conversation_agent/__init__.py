from copy import deepcopy
from dataclasses import dataclass
import json

from aiohttp import web
from jsonschema import Draft202012Validator, FormatChecker
from nanobot.agent.tools.base import Tool
from nanobot.agent.tools.context import current_request_context
from nanobot.webui.session_identity import webui_session_key

from business import checksum, require
from boss_execution_scope import NAMESPACE
from boss_runtime_records import ATTRIBUTE, RuntimeBinding
from runtime_page_read_tools import _BossPageReadTool


VERSION = "1.4.0"
CONVERSATION_REQUEST = "product_conversation_request"
READ_TOOLS = frozenset({"bossDashboardRead", "bossTasksRead", "bossMeetingsRead", "bossEvidenceRead", "bossWorkspaceRead", "bossSectorRead", "conversationRead"})
CONVERSATION_TOOLS = READ_TOOLS | {"query_metrics"}
AVAILABLE_CONVERSATION_TOOLS = CONVERSATION_TOOLS | {"businessOverviewRead"}


@dataclass(frozen=True)
class ConversationContext:
    role: str
    owner_id: str
    namespace: str
    dataset_id: str
    dataset_version: str
    request_id: str
    session_id: str
    chat_id: str
    turn_id: str
    active: bool
    input_sha256: str
    allowed_tools: frozenset[str]
    allowed_calls: frozenset[tuple[str, str]]
    references: tuple[tuple[str, str, str | None], ...] = ()


class ConversationScope:
    def __init__(self, store, context_provider, context_validator):
        require(callable(context_provider) and callable(context_validator), "会话需要可信上下文及正式资料核查器", web.HTTPBadRequest)
        self.store, self.context_provider, self.context_validator = store, context_provider, context_validator

    def current(self, request=None, *, require_runtime=True):
        request = request or current_request_context()
        require(request is not None, "会话缺少实际请求", web.HTTPForbidden)
        context = self.context_provider(request)
        require(isinstance(context, ConversationContext) and context.role == "BOSS" and context.active is True,
                "会话缺少当前本人认证", web.HTTPForbidden)
        require(context.namespace == NAMESPACE and request.channel == "websocket" and bool(context.request_id)
                and bool(context.turn_id) and context.session_id == webui_session_key(context.chat_id)
                and context.owner_id == request.sender_id
                and context.session_id == request.session_key and context.chat_id == request.chat_id
                and context.turn_id == request.turn_id and context.input_sha256 == checksum(request.original_user_text),
                "会话输入、身份或关联不符", web.HTTPForbidden)
        require(isinstance(context.allowed_tools, frozenset) and bool(context.allowed_tools)
                and context.allowed_tools <= AVAILABLE_CONVERSATION_TOOLS and isinstance(context.allowed_calls, frozenset)
                and all(isinstance(call, tuple) and len(call) == 2 and call[0] in context.allowed_tools
                        and isinstance(call[1], str) and len(call[1]) == 64 for call in context.allowed_calls),
                "会话工具或当前参数范围无效", web.HTTPForbidden)
        require(isinstance(context.references, tuple) and all(isinstance(ref, tuple) and len(ref) == 3
                and all(isinstance(value, str) and bool(value) for value in ref[:2])
                and (ref[2] is None or isinstance(ref[2], str)) for ref in context.references),
                "会话正式引用无效", web.HTTPForbidden)
        with self.store.connect() as db:
            self.store.active(db, context.namespace)
            initial = self.store.get(db, context.namespace, "initial", "snapshot")
            require(initial["source_type"] == "SIMULATED" and all(initial[key] == getattr(context, key)
                for key in ("owner_id", "dataset_id", "dataset_version")), "会话本人资料范围已变化", web.HTTPForbidden)
        if require_runtime:
            binding = request.attributes.get(ATTRIBUTE)
            require(isinstance(binding, RuntimeBinding) and binding.recorder.store.path.resolve() == self.store.path.resolve()
                    and binding.recorder.namespace == context.namespace and binding.request_id == context.request_id
                    and binding.session_id == context.session_id, "会话与实际Runtime关联不符", web.HTTPForbidden)
        require(self.context_validator(context) is True, "会话当前资料或版本无法采用", web.HTTPConflict)
        return context


class ConversationReadTool(Tool):
    def __init__(self, delegate, scope):
        require(isinstance(delegate, _BossPageReadTool) and delegate.name in READ_TOOLS | {"businessOverviewRead"} and delegate.read_only is True
                and delegate._api.store.path.resolve() == scope.store.path.resolve(),
                "会话只能采用同库正式读取工具", web.HTTPForbidden)
        self.delegate, self.scope = delegate, scope

    @property
    def name(self):
        return self.delegate.name

    @property
    def description(self):
        return self.delegate.description

    @property
    def parameters(self):
        return deepcopy(self.delegate.parameters)

    def cast_params(self, params):
        return params

    async def execute(self, **params):
        require(not list(Draft202012Validator(self.parameters, format_checker=FormatChecker()).iter_errors(params)),
                "会话读取参数不符合正式Schema", web.HTTPBadRequest)
        context = self.scope.current()
        require(self.delegate._owner_id == context.owner_id and (self.name, checksum(params)) in context.allowed_calls,
                "模型参数超出本次明确输入范围", web.HTTPForbidden)
        result = await self.delegate.execute(**params)
        output = json.loads(result)
        require(output["source_type"] in {"SIMULATED", "RUNTIME_RECORD"} and self.scope.current() == context,
                "会话读取期间当前范围已变化", web.HTTPConflict)
        return result


def register_conversation_reads(registry, delegates, scope):
    tools = [ConversationReadTool(delegate, scope) for delegate in delegates]
    names = [tool.name for tool in tools]
    require(bool(tools) and len(set(names)) == len(names) and not any(registry.has(name) for name in names),
            "会话读取工具重复或缺少", web.HTTPConflict)
    for tool in tools:
        registry.register(tool)
    return names
