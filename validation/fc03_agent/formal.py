from copy import deepcopy
import json

from aiohttp import web
from jsonschema import Draft202012Validator, FormatChecker

from business import checksum, encode, require
from boss_morning import MorningAPI, SCHEMA, QUERY_ACTION
from fc03_agent import Fc03TodayTool

FORMAL_TOOLS = frozenset({"todayRead", "morningListRead", "morningDetailRead", "morningSourceRead"})


class FormalMorningTool(Fc03TodayTool):
    def __init__(self, store, context_provider, name):
        require(name in FORMAL_TOOLS, "工具超出晨间批准范围", web.HTTPForbidden)
        super().__init__(store, context_provider)
        self.name = name
        self.api = MorningAPI(store)

    @property
    def parameters(self):
        if self.name == "todayRead":
            return {**deepcopy(SCHEMA["$defs"]["Day"]), "$defs": deepcopy(SCHEMA["$defs"])}
        properties = {"list_id": {"$ref": "#/$defs/Id"}}
        if self.name == "morningDetailRead":
            properties["item_id"] = {"$ref": "#/$defs/Id"}
        if self.name == "morningSourceRead":
            properties["source_id"] = {"$ref": "#/$defs/Id"}
        return {"type": "object", "properties": properties, "required": list(properties),
                "additionalProperties": False, "$defs": deepcopy(SCHEMA["$defs"])}

    def receipt(self):
        context = self.context()
        require(bool(context.client_request_id), "原晨间请求编号缺少", web.HTTPBadRequest)
        result = self.api.receipt(context.role, QUERY_ACTION, context.client_request_id)
        require(self.context() == context, "读取原回执期间认证范围已经变化", web.HTTPConflict)
        return result

    async def execute(self, **params):
        require(not list(Draft202012Validator(self.parameters, format_checker=FormatChecker()).iter_errors(params)),
                "晨间参数不符合正式Schema", web.HTTPBadRequest)
        context = self.context()
        require(bool(context.client_request_id) and isinstance(context.allowed_list_ids, frozenset),
                "晨间可信原请求及清单范围缺少", web.HTTPForbidden)
        if self.name == "todayRead":
            require(checksum(params) == checksum(json.loads(context.read_parameters_json))
                    and all(params[key] == getattr(context, key) for key in ("date", "timezone")),
                    "模型日期与明确晨间范围不符", web.HTTPForbidden)
            preview = self.api.read(context.role, params)
            require(all(preview[key] == getattr(context, key) for key in ("snapshot_sha256", "order_version")),
                    "当前晨间快照或次序已经变化", web.HTTPConflict)
            output = self.api.query(context.role, {**params, "client_request_id": context.client_request_id,
                                                  "session_id": context.session_id})
            require(all(output[key] == getattr(context, key) for key in ("date", "timezone", "snapshot_sha256", "order_version")),
                    "晨间查询提交期间范围已经变化", web.HTTPConflict)
        else:
            with self.store.connect() as db:
                db.execute("BEGIN")
                stored = self.store.get(db, context.namespace, "morning_list", params["list_id"])
                current = stored["session_id"] == context.session_id and stored["client_request_id"] == context.client_request_id
                require(current or params["list_id"] in context.allowed_list_ids, "清单不属于当前明确请求", web.HTTPForbidden)
                require(all(stored["result"][key] == getattr(context, key) for key in ("date", "timezone", "snapshot_sha256")),
                        "清单与当前日期或快照不符", web.HTTPConflict)
            current_view = self.api.read_list(context.role, params["list_id"])
            require(current_view["current_order"]["version"] == context.order_version,
                    "当前本人次序已变化，需要新的读取绑定", web.HTTPConflict)
            if self.name == "morningListRead":
                output = current_view
            elif self.name == "morningDetailRead":
                output = self.api.detail(context.role, params["list_id"], params["item_id"])
            else:
                output = self.api.source(context.role, params["list_id"], params["source_id"])
        require(self.context() == context, "晨间读取期间认证范围已经变化", web.HTTPConflict)
        return encode(output)
