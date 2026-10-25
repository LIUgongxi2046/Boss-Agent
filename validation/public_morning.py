import json
from urllib.parse import parse_qs

from aiohttp import web

from business import require
from boss_morning import MorningAPI
from boss_morning_inputs import MorningInputAPI
from boss_simulation_api import _context


def _parameters(query_string, required, optional=()):
    values = parse_qs(query_string, keep_blank_values=True)
    require(set(required) <= set(values) <= set(required) | set(optional)
            and all(len(value) == 1 and value[0] for value in values.values()), "晨间读取参数缺少、重复或越权", web.HTTPBadRequest)
    return {key: value[0] for key, value in values.items()}


def morning_read(store, role, path, query_string):
    api = MorningAPI(store)
    api._role(role)
    if path == "/api/boss/ui/morning/preview":
        return api.read(role, _parameters(query_string, ("date", "timezone")))
    if path == "/api/boss/ui/morning/list":
        values = _parameters(query_string, ("list_id",), ("historical",))
        require(values.get("historical", "false") in ("true", "false"), "历史读取标识无效", web.HTTPBadRequest)
        return api.read_list(role, values["list_id"], values.get("historical") == "true")
    if path == "/api/boss/ui/morning/detail":
        values = _parameters(query_string, ("list_id", "item_id"))
        return api.detail(role, values["list_id"], values["item_id"])
    if path == "/api/boss/ui/morning/source":
        values = _parameters(query_string, ("list_id", "source_id"))
        return api.source(role, values["list_id"], values["source_id"])
    if path == "/api/boss/ui/morning/receipt":
        values = _parameters(query_string, ("action", "client_request_id"))
        return {**api.receipt(role, values["action"], values["client_request_id"]), "write_performed_by_lookup": False}
    raise web.HTTPNotFound(text="晨间读取入口不存在")


def morning_coverage_read(store, role, path, query_string):
    api = MorningInputAPI(store)
    api._role(role)
    if path == "/api/boss/ui/admin/morning-coverage-receipt":
        values = _parameters(query_string, ("client_request_id",))
        return {**api.receipt(role, values["client_request_id"]), "write_performed_by_lookup": False}
    require(path == "/api/boss/ui/admin/morning-coverage", "覆盖读取入口不存在", web.HTTPNotFound)
    _parameters(query_string, ())
    with store.connect() as db:
        db.execute("BEGIN")
        context = _context(db)
        loaded = []
        for row in db.execute("SELECT body FROM objects WHERE namespace=? AND kind='morning_coverage' ORDER BY id", (context["namespace"],)):
            value = json.loads(row[0])
            if all(value[field] == context[field] for field in ("owner_id", "dataset_id", "dataset_version")) and value["execution_namespace"] == context["namespace"]:
                loaded.append({key: value[key] for key in ("date", "timezone", "version", "source_id", "source_version", "generator_version", "allowed_use")})
        return {"definition": api.catalog(role), "business_clock": context["clock"], "loaded": loaded}
