import asyncio
import json
from pathlib import Path
import time

from aiohttp import ClientSession, DummyCookieJar, WSMsgType, web
from multidict import CIMultiDict
from jsonschema import Draft202012Validator
from yarl import URL

from agent_run_broker import RunIdentity, fail


SCHEMA = json.loads((Path(__file__).resolve().parent.parent / "specs/agent-runs.schema.json").read_text(encoding="utf-8"))
Draft202012Validator.check_schema(SCHEMA)
VALIDATORS = {name: Draft202012Validator({"$ref": "#/$defs/" + name, "$defs": SCHEMA["$defs"]}) for name in ("create", "inputs", "cancel", "key", "snapshot", "usage_snapshot", "completion_inspection", "method_reselection", "method_reselection_receipt", "method_catalog", "object_scope_request", "object_scope_receipt", "object_scope_candidates")}
IDENTITY_KEY = web.RequestKey("agent_run_identity", RunIdentity)


def require_product_engine_ready(*, for_create=False, factory=None):
    blockers = factory.readiness_blockers() if factory is not None and callable(getattr(factory, "readiness_blockers", None)) else ["EXECUTION_FACTORY_NOT_ASSEMBLED"]
    if not blockers:
        return
    message = ("运行安全条件尚未通过，本次没有创建运行：" if for_create else "Hermes 请求额度边界和产品运行安全条件尚未通过，当前无法启动：") + ",".join(blockers)
    fail(web.HTTPServiceUnavailable, "CREATE_NOT_ADMITTED" if for_create else "SERVICE_NOT_READY", message)


def routes(broker, channel=None, *, chat_budget=None):
    def identity(request, payload=None):
        if channel is None:
            result = request.get(IDENTITY_KEY)
            broker.require_identity(result)
            return result
        channel.require_run_api_role(request)
        from boss_execution_scope import NAMESPACE
        if payload is not None and request.path == "/api/v2/runs":
            chat_id, refs = payload["conversation_id"], payload["selected_refs"]
        else:
            with broker.store.connect() as db:
                db.execute("BEGIN")
                if "run_id" in request.match_info:
                    row = db.execute("SELECT conversation_id,selected_refs FROM agent_runs WHERE run_id=? AND actor_id=? AND space_id=?", (request.match_info["run_id"], "boss-1", NAMESPACE)).fetchone()
                else:
                    row = db.execute("SELECT r.conversation_id,r.selected_refs FROM agent_api_requests q JOIN agent_runs r ON r.run_id=q.run_id WHERE q.actor_id=? AND q.space_id=? AND q.request_key=? AND r.actor_id=q.actor_id AND r.space_id=q.space_id", ("boss-1", NAMESPACE, request.match_info["request_key"])).fetchone()
                if row is None:
                    fail(web.HTTPNotFound, "NOT_FOUND", "运行或原请求不存在")
                chat_id, refs = row[0], json.loads(row[1])
        channel.require_run_subscription(request, chat_id)
        proof = broker.scope_service.prove(chat_id, refs)
        channel.require_run_subscription(request, chat_id)
        return RunIdentity(proof.owner_id, proof.namespace, "BOSS", frozenset({chat_id}), frozenset(refs),
                           verify=lambda: channel.require_run_subscription(request, chat_id))

    def precheck(request):
        if channel is not None:
            channel.require_run_api_role(request)
        else:
            broker.require_identity(request.get(IDENTITY_KEY))

    async def body(request, kind):
        if request.query or request.content_type != "application/json":
            fail(web.HTTPBadRequest, "INVALID_INPUT", "请求格式无效")
        if request.content_length is not None and request.content_length > 131072:
            fail(web.HTTPRequestEntityTooLarge, "INPUT_TOO_LARGE", "请求超过大小限制", actual_size=request.content_length)
        payload = await request.json()
        if not VALIDATORS[kind].is_valid(payload):
            fail(web.HTTPBadRequest, "INVALID_INPUT", "请求字段无效")
        return payload

    async def create(request):
        precheck(request)
        payload = await body(request, "create")
        current_identity = identity(request, payload)
        if channel is not None:
            if "method_selection" not in payload:
                fail(web.HTTPBadRequest, "INVALID_INPUT", "创建运行需要本人选择方法")
            require_product_engine_ready(for_create=True, factory=getattr(broker, "execution_factory", None))
            if chat_budget is None:
                fail(web.HTTPServiceUnavailable, "SERVICE_NOT_READY", "聊天运行预算尚未配置")
        return web.json_response(broker.create(current_identity, payload, request=request, chat_budget=chat_budget))

    async def read(request):
        precheck(request)
        if request.query:
            fail(web.HTTPBadRequest, "INVALID_INPUT", "请求字段无效")
        return web.json_response(broker.read(identity(request), request.match_info["run_id"]))

    async def inputs(request):
        precheck(request)
        payload = await body(request, "inputs")
        return web.json_response(broker.mutate(identity(request), request.match_info["run_id"], "inputs", payload, request=request))

    async def cancel(request):
        precheck(request)
        payload = await body(request, "cancel")
        return web.json_response(broker.mutate(identity(request), request.match_info["run_id"], "cancel", payload))

    async def select_method(request):
        precheck(request)
        payload = await body(request, "method_reselection")
        current_identity = identity(request)
        if broker.method_selection is None:
            fail(web.HTTPServiceUnavailable, "SERVICE_NOT_READY", "运行方法选择服务尚未装配")
        result = broker.method_selection.reselect(broker, current_identity, request.match_info["run_id"], payload, request=request)
        VALIDATORS["method_reselection_receipt"].validate(result)
        return web.json_response(result, headers={"Cache-Control": "no-store"})

    async def method_receipt(request):
        precheck(request)
        if request.query or not VALIDATORS["key"].is_valid(request.match_info["request_key"]):
            fail(web.HTTPBadRequest, "INVALID_INPUT", "方法选择请求编号无效")
        current_identity = identity(request)
        if broker.method_selection is None:
            fail(web.HTTPServiceUnavailable, "SERVICE_NOT_READY", "运行方法选择服务尚未装配")
        result = broker.method_selection.request_receipt(broker, current_identity, request.match_info["run_id"], request.match_info["request_key"], request=request)
        VALIDATORS["method_reselection_receipt"].validate(result)
        return web.json_response(result, headers={"Cache-Control": "no-store"})

    async def method_catalog(request):
        precheck(request)
        if request.query:
            fail(web.HTTPBadRequest, "INVALID_INPUT", "方法目录请求参数无效")
        current_identity = identity(request)
        if broker.method_selection is None:
            fail(web.HTTPServiceUnavailable, "SERVICE_NOT_READY", "运行方法选择服务尚未装配")
        result = broker.method_selection.catalog_for_run(broker, current_identity, request.match_info["run_id"], request=request)
        VALIDATORS["method_catalog"].validate(result)
        return web.json_response(result, headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})

    async def bind_object_scope(request):
        precheck(request)
        payload = await body(request, "object_scope_request")
        current_identity = identity(request)
        if broker.object_scope is None:
            fail(web.HTTPServiceUnavailable, "SERVICE_NOT_READY", "运行对象范围服务尚未装配")
        result = broker.object_scope.bind(broker, current_identity, request.match_info["run_id"], payload, request=request)
        VALIDATORS["object_scope_receipt"].validate(result)
        return web.json_response(result, headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})

    async def object_scope_candidates(request):
        precheck(request)
        if request.query:
            fail(web.HTTPBadRequest, "INVALID_INPUT", "对象候选请求参数无效")
        current_identity = identity(request)
        if broker.object_scope is None:
            fail(web.HTTPServiceUnavailable, "SERVICE_NOT_READY", "运行对象范围服务尚未装配")
        result = broker.object_scope.candidates(broker, current_identity, request.match_info["run_id"], request=request)
        VALIDATORS["object_scope_candidates"].validate(result)
        return web.json_response(result, headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})

    async def object_scope_receipt(request):
        precheck(request)
        key = request.match_info["request_key"]
        if request.query or not VALIDATORS["key"].is_valid(key):
            fail(web.HTTPBadRequest, "INVALID_INPUT", "对象选择请求编号无效")
        current_identity = identity(request)
        if broker.object_scope is None:
            fail(web.HTTPServiceUnavailable, "SERVICE_NOT_READY", "运行对象范围服务尚未装配")
        result = broker.object_scope.request_receipt(broker, current_identity, request.match_info["run_id"], key, request=request)
        VALIDATORS["object_scope_receipt"].validate(result)
        return web.json_response(result, headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})

    async def meeting_scope_candidate(request):
        precheck(request)
        meeting_id = request.match_info["meeting_id"]
        if request.query or not VALIDATORS["key"].is_valid(meeting_id):
            fail(web.HTTPBadRequest, "INVALID_INPUT", "会议编号无效")
        current_identity = identity(request)
        if broker.object_scope is None:
            fail(web.HTTPServiceUnavailable, "SERVICE_NOT_READY", "运行对象范围服务尚未装配")
        result = broker.object_scope.meeting_candidate(broker, current_identity, request.match_info["run_id"], meeting_id, request=request)
        VALIDATORS["object_scope_candidates"].validate(result)
        return web.json_response(result, headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})

    async def events(request):
        precheck(request)
        if set(request.query) != {"after_seq"} or len(request.query.getall("after_seq")) != 1:
            fail(web.HTTPBadRequest, "INVALID_INPUT", "事件游标无效")
        cursor = request.query["after_seq"]
        if not cursor.isascii() or not cursor.isdecimal() or len(cursor) > 18:
            fail(web.HTTPBadRequest, "INVALID_INPUT", "事件游标无效")
        return web.json_response(broker.events(identity(request), request.match_info["run_id"], int(cursor)))

    async def result(request):
        precheck(request)
        if request.query:
            fail(web.HTTPBadRequest, "INVALID_INPUT", "请求字段无效")
        return web.json_response(broker.result(identity(request), request.match_info["run_id"]), headers={"Cache-Control": "no-store"})

    async def usage(request):
        precheck(request)
        if request.query:
            fail(web.HTTPBadRequest, "INVALID_INPUT", "用量查询请求字段无效")
        identity(request)
        fail(web.HTTPServiceUnavailable, "SERVICE_NOT_READY", "全运行关系授权和后代范围检查尚未验证")

    async def completion_inspection(request):
        precheck(request)
        values = request.query.getall("finish_event_id", [])
        if set(request.query) - {"finish_event_id"} or len(values) > 1:
            fail(web.HTTPBadRequest, "INVALID_INPUT", "完成核查事件无效")
        finish_event_id = request.query.get("finish_event_id")
        if finish_event_id is not None and not VALIDATORS["key"].is_valid(finish_event_id):
            fail(web.HTTPBadRequest, "INVALID_INPUT", "完成核查事件无效")
        result = broker.completion_inspection(identity(request), request.match_info["run_id"], finish_event_id)
        VALIDATORS["completion_inspection"].validate(result)
        return web.json_response(result, headers={"Cache-Control": "no-store"})

    async def receipt(request):
        precheck(request)
        key = request.match_info["request_key"]
        if request.query or not VALIDATORS["key"].is_valid(key):
            fail(web.HTTPBadRequest, "INVALID_INPUT", "原请求编号无效")
        return web.json_response(broker.request_receipt(identity(request), key))

    return [web.post("/api/v2/runs", create), web.get("/api/v2/runs/{run_id}", read), web.post("/api/v2/runs/{run_id}/inputs", inputs), web.post("/api/v2/runs/{run_id}/cancel", cancel), web.post("/api/v2/runs/{run_id}/object-scope", bind_object_scope), web.get("/api/v2/runs/{run_id}/object-scope/candidates", object_scope_candidates), web.get("/api/v2/runs/{run_id}/object-scope/meeting-candidates/{meeting_id}", meeting_scope_candidate), web.get("/api/v2/runs/{run_id}/object-scope/requests/{request_key}", object_scope_receipt), web.post("/api/v2/runs/{run_id}/method-selection", select_method), web.get("/api/v2/runs/{run_id}/method-selection/requests/{request_key}", method_receipt), web.get("/api/v2/runs/{run_id}/available-methods", method_catalog), web.get("/api/v2/runs/{run_id}/events", events), web.get("/api/v2/runs/{run_id}/result", result), web.get("/api/v2/runs/{run_id}/usage", usage), web.get("/api/v2/runs/{run_id}/completion-inspection", completion_inspection), web.get("/api/v2/requests/{request_key}", receipt)]


def product_application(channel, broker=None, *, public_port=None, upstream_port=None, chat_budget=None):
    async def unavailable(request):
        channel.require_run_api_role(request)
        fail(web.HTTPServiceUnavailable, "SERVICE_NOT_READY", "运行接口需要当前会话与来源范围证明")

    if (public_port is None) != (upstream_port is None):
        raise ValueError("同源服务端口配置不完整")
    middlewares = []
    if public_port is not None:
        expected_host = "127.0.0.1:" + str(public_port)
        expected_origin = "http://" + expected_host

        @web.middleware
        async def origin_guard(request, handler):
            origin = request.headers.get("Origin")
            site = request.headers.get("Sec-Fetch-Site")
            if request.headers.get("Host") != expected_host or origin is not None and origin != expected_origin or site is not None and site not in {"same-origin", "none"}:
                fail(web.HTTPForbidden, "FORBIDDEN", "请求来源无效")
            return await handler(request)
        middlewares.append(origin_guard)

    app = web.Application(client_max_size=131072, middlewares=middlewares)
    if broker is not None:
        if broker.scope_service is None:
            raise ValueError("产品运行接口缺少范围核查服务")
        app.add_routes(routes(broker, channel, chat_budget=chat_budget))
    else:
        app.add_routes([web.post("/api/v2/runs", unavailable), web.get("/api/v2/runs/{run_id}", unavailable), web.post("/api/v2/runs/{run_id}/inputs", unavailable), web.post("/api/v2/runs/{run_id}/cancel", unavailable), web.post("/api/v2/runs/{run_id}/object-scope", unavailable), web.get("/api/v2/runs/{run_id}/object-scope/candidates", unavailable), web.get("/api/v2/runs/{run_id}/object-scope/meeting-candidates/{meeting_id}", unavailable), web.get("/api/v2/runs/{run_id}/object-scope/requests/{request_key}", unavailable), web.post("/api/v2/runs/{run_id}/method-selection", unavailable), web.get("/api/v2/runs/{run_id}/method-selection/requests/{request_key}", unavailable), web.get("/api/v2/runs/{run_id}/available-methods", unavailable), web.get("/api/v2/runs/{run_id}/events", unavailable), web.get("/api/v2/runs/{run_id}/result", unavailable), web.get("/api/v2/runs/{run_id}/usage", unavailable), web.get("/api/v2/runs/{run_id}/completion-inspection", unavailable), web.get("/api/v2/requests/{request_key}", unavailable)])
    if upstream_port is not None:
        session_key = web.AppKey("agent_run_proxy_session", ClientSession)

        async def start(application):
            application[session_key] = ClientSession(auto_decompress=False, cookie_jar=DummyCookieJar())

        async def close(application):
            await application[session_key].close()

        async def relay(source, target):
            try:
                async for message in source:
                    if message.type == WSMsgType.TEXT:
                        await target.send_str(message.data)
                    elif message.type == WSMsgType.BINARY:
                        await target.send_bytes(message.data)
                    elif message.type == WSMsgType.ERROR:
                        raise ConnectionError("会话连接失败")
            finally:
                await target.close()

        async def proxy(request):
            if request.path.startswith("/api/v2/"):
                fail(web.HTTPNotFound, "NOT_FOUND", "接口不存在")
            if request.method != "GET":
                raise web.HTTPMethodNotAllowed(request.method, ["GET"])
            skip = {"connection", "upgrade", "transfer-encoding", "proxy-authorization", "proxy-connection", "forwarded", "x-forwarded-for", "x-forwarded-host", "x-forwarded-proto", "x-real-ip"}
            headers = CIMultiDict((key, value) for key, value in request.headers.items() if key.lower() not in skip and not key.lower().startswith("sec-websocket-"))
            url = URL("http://127.0.0.1:" + str(upstream_port) + request.raw_path, encoded=True)
            session = request.app[session_key]
            if request.headers.get("Upgrade", "").lower() == "websocket":
                tokens = request.query.getall("token", [])
                if len(tokens) != 1 or channel.token_roles.get(tokens[0]) not in {"BOSS", "MAINTAINER"} or time.monotonic() >= channel.token_expirations.get(tokens[0], 0) or time.monotonic() >= channel.gateway.tokens.issued_tokens.get(tokens[0], 0):
                    fail(web.HTTPUnauthorized, "UNAUTHENTICATED", "当前身份无效")
                async with session.ws_connect(url, headers=headers, max_msg_size=channel.config.max_message_bytes) as upstream:
                    client = web.WebSocketResponse(max_msg_size=channel.config.max_message_bytes)
                    await client.prepare(request)
                    async with asyncio.TaskGroup() as tasks:
                        tasks.create_task(relay(client, upstream))
                        tasks.create_task(relay(upstream, client))
                    return client
            async with session.get(url, headers=headers, allow_redirects=False) as upstream:
                response_headers = CIMultiDict((key, value) for key, value in upstream.headers.items() if key.lower() not in skip)
                response = web.StreamResponse(status=upstream.status, headers=response_headers)
                await response.prepare(request)
                async for chunk in upstream.content.iter_chunked(65536):
                    await response.write(chunk)
                await response.write_eof()
                return response

        app.on_startup.append(start)
        app.on_cleanup.append(close)
        app.router.add_route("*", "/{tail:.*}", proxy)
    return app
