from copy import deepcopy
from dataclasses import dataclass
from urllib.parse import urlencode
import json

from aiohttp import web
from boss_recovery_api import BossRecoveryAPI
from hermes_bridge import EngineEventSink
from sop_write_tools.fc01 import Fc01Context, Fc01Tool


@dataclass(frozen=True)
class ReceiptBinding:
    action: str
    client_request_id: str


class HermesBusinessTools:
    def __init__(self, store, context_provider, preparation_provider, receipt_provider, *, run_gate):
        if not all(callable(item) for item in (context_provider, preparation_provider, receipt_provider)):
            raise ValueError("需要服务端提供可信范围与请求绑定")
        if not isinstance(run_gate, EngineEventSink):
            raise ValueError("需要运行租约检查")
        self._run_gate = run_gate
        self._store = store
        self._context_provider = context_provider
        self._preparation_provider = preparation_provider
        self._receipt_provider = receipt_provider
        self._prepare = Fc01Tool(store, context_provider, "bossSupplyQualityPrepare")
        self._recovery = BossRecoveryAPI(store)

    async def prepare(self):
        context = self._prepare._context()
        self._run_gate.require_tool_access(context.owner_id, context.namespace)
        params = self._preparation_provider()
        if not isinstance(params, dict):
            raise ValueError("缺少服务端准备内容")
        self._run_gate.require_tool_access(context.owner_id, context.namespace)
        result = json.loads(await self._prepare.execute(**deepcopy(params)))
        if self._prepare._context() != context:
            raise web.HTTPForbidden(text="准备期间可信范围已变化")
        self._run_gate.require_tool_access(context.owner_id, context.namespace)
        return result

    def receipt(self):
        context = self._prepare._context()
        self._run_gate.require_tool_access(context.owner_id, context.namespace)
        binding = self._receipt_provider()
        if not isinstance(context, Fc01Context) or not isinstance(binding, ReceiptBinding):
            raise web.HTTPForbidden(text="缺少可信原请求绑定")
        if binding.action != "boss.assignment.send":
            raise web.HTTPForbidden(text="当前回执操作不在允许范围")
        self._run_gate.require_tool_access(context.owner_id, context.namespace)
        status, result = self._recovery.serve("BOSS", "/api/boss/ui/operation-status", urlencode({
            "action": binding.action, "client_request_id": binding.client_request_id,
        }))
        if status != 200:
            raise web.HTTPConflict(text="原请求回执不可读取")
        if self._prepare._context() != context or self._receipt_provider() != binding:
            raise web.HTTPForbidden(text="读取期间可信范围已变化")
        self._run_gate.require_tool_access(context.owner_id, context.namespace)
        result.pop("safe_same_key_retry", None)
        return result
