from aiohttp import web
from aiohttp.web_urldispatcher import DynamicResource

from boss_owner_plans import OwnerPlansAPI
from hermes_schedule_adapter import HermesScheduleAdapter

PLAN_PARAMS = web.RequestKey("hermes_plan_receipt_parameters", dict)


def install_plan_execution(app, channel, store, scope_service, *, public_port):
    service = OwnerPlansAPI(store)
    schedule = HermesScheduleAdapter(store)
    expected_host = "127.0.0.1:" + str(public_port)
    expected_origin = "http://" + expected_host

    async def body(request):
        channel.require_run_api_role(request)
        if request.query or request.content_type != "application/json":
            raise web.HTTPBadRequest(text="计划请求格式无效")
        return await request.json()

    async def preview(request):
        return web.json_response(service.preview_execution(request, channel, scope_service, await body(request)), headers={"Cache-Control": "no-store"})

    async def methods(request):
        return web.json_response(service.execution_methods(request, channel, scope_service, await body(request)), headers={"Cache-Control": "no-store"})

    async def decide(request):
        return web.json_response(service.decide_execution(request, channel, scope_service, await body(request)), headers={"Cache-Control": "no-store"})

    async def bind(request):
        return web.json_response(service.bind_execution(request, channel, scope_service, await body(request)), headers={"Cache-Control": "no-store"})

    async def receipt(request):
        channel.require_run_api_role(request)
        if request.query:
            raise web.HTTPBadRequest(text="计划请求格式无效")
        params = request[PLAN_PARAMS]
        return web.json_response(service.execution_receipt(request, channel, scope_service, plan_id=params["plan_id"], client_request_id=params["client_request_id"], operation=params["operation"]), headers={"Cache-Control": "no-store"})

    async def suppressed_history(request):
        channel.require_run_api_role(request)
        if set(request.query) != {"version", "event_id"} or any(len(request.query.getall(key)) != 1 for key in ("version", "event_id")):
            raise web.HTTPBadRequest(text="计划历史查询参数无效")
        return web.json_response(schedule.list_suppressed_history(request, channel, scope_service, request[PLAN_PARAMS]["plan_id"], request.query["version"], request.query["event_id"]), headers={"Cache-Control": "no-store"})

    endpoints = []
    for path, handler in (("/api/v2/owner-plans/execution-methods", methods),
                          ("/api/v2/owner-plans/execution-preview", preview),
                          ("/api/v2/owner-plans/execution-decision", decide),
                          ("/api/v2/owner-plans/execution-binding", bind)):
        resource = DynamicResource(path)
        resource.add_route("POST", handler)
        endpoints.append(resource)
    resource = DynamicResource("/api/v2/owner-plans/{plan_id}/execution-receipts/{operation}/{client_request_id}")
    resource.add_route("GET", receipt)
    endpoints.append(resource)
    resource = DynamicResource("/api/v2/owner-plans/{plan_id}/suppressed-history")
    resource.add_route("GET", suppressed_history)
    endpoints.append(resource)

    @web.middleware
    async def dispatch(request, handler):
        for endpoint in endpoints:
            match, allowed = await endpoint.resolve(request)
            if match is None:
                if allowed:
                    raise web.HTTPMethodNotAllowed(request.method, allowed)
                continue
            origin = request.headers.get("Origin")
            if request.headers.get("Host") != expected_host or origin not in (None, expected_origin) or request.method != "GET" and origin != expected_origin or request.headers.get("Sec-Fetch-Site") not in (None, "same-origin"):
                raise web.HTTPForbidden(text="计划请求来源无效")
            if "plan_id" in match:
                request[PLAN_PARAMS] = dict(match)
            return await match.handler(request)
        return await handler(request)

    app.middlewares.append(dispatch)
