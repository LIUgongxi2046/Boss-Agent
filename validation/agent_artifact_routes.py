from aiohttp import web
from aiohttp.web_urldispatcher import DynamicResource
from jsonschema import Draft202012Validator, FormatChecker
from uuid import UUID

from agent_artifact_api import OwnerArtifactReader
from agent_artifact_workspace import ArtifactWorkspace
from agent_run_broker import fail


ARTIFACT_ROUTE_PARAMS = web.RequestKey("artifact_route_params", dict)
ARTIFACT_ROUTES_INSTALLED = web.AppKey("artifact_read_routes_installed", bool)
UUID_VALIDATOR = Draft202012Validator({"type": "string", "format": "uuid"}, format_checker=FormatChecker())


def require_artifact_read_boundary():
    fail(web.HTTPServiceUnavailable, "SERVICE_NOT_READY", "成果工作区隔离尚未通过核查")


def install_artifact_read_routes(app, channel, scope_service, workspace, *, public_port):
    if type(public_port) is not int or not 1 <= public_port <= 65535:
        raise ValueError("成果服务端口无效")
    reader = (OwnerArtifactReader.for_workspace_mapping(channel, scope_service, workspace)
              if isinstance(workspace, ArtifactWorkspace) else OwnerArtifactReader(channel, scope_service, workspace))
    host = "127.0.0.1:" + str(public_port)
    origin = "http://" + host

    def identifier(request, name):
        value = request[ARTIFACT_ROUTE_PARAMS][name]
        if not UUID_VALIDATOR.is_valid(value) or str(UUID(value)) != value:
            fail(web.HTTPBadRequest, "INVALID_INPUT", "成果编号无效")
        return value

    def no_query(request):
        if request.query:
            fail(web.HTTPBadRequest, "INVALID_INPUT", "成果查询参数无效")

    def version(request):
        values = request.query.getall("version", [])
        if len(request.query) != 1 or len(values) != 1 or not values[0].isascii() or not values[0].isdigit() or len(values[0]) > 16:
            fail(web.HTTPBadRequest, "INVALID_INPUT", "需要有效的成果版本")
        number = int(values[0])
        if number < 1 or number > 9007199254740991 or str(number) != values[0]:
            fail(web.HTTPBadRequest, "INVALID_INPUT", "需要有效的成果版本")
        return number

    def response(value):
        return web.json_response(value, headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})

    async def listing(request):
        no_query(request)
        return response(reader.list_for_run(request, identifier(request, "run_id")))

    async def receipt(request):
        no_query(request)
        params = request[ARTIFACT_ROUTE_PARAMS]
        if not params["request_key"].strip() or len(params["request_key"]) > 128:
            fail(web.HTTPBadRequest, "INVALID_INPUT", "成果请求编号无效")
        return response(reader.request_receipt(request, identifier(request, "run_id"), params["request_key"]))

    async def pending_requests(request):
        no_query(request)
        return response(reader.pending_requests(request, identifier(request, "run_id")))

    async def metadata(request):
        return response(reader.metadata(request, identifier(request, "artifact_id"), version(request)))

    async def versions(request):
        return response(reader.list_versions(request, identifier(request, "artifact_id"), version(request)))

    async def file(request):
        return reader.file_response(request, identifier(request, "artifact_id"), version(request))

    definitions = (("/api/v2/runs/{run_id}/artifacts", listing),
                   ("/api/v2/runs/{run_id}/artifact-pending-requests", pending_requests),
                   ("/api/v2/runs/{run_id}/artifact-requests/{request_key}", receipt),
                   ("/api/v2/artifacts/{artifact_id}", metadata),
                   ("/api/v2/artifacts/{artifact_id}/versions", versions),
                   ("/api/v2/artifacts/{artifact_id}/file", file))
    existing = {resource.canonical for resource in app.router.resources()}
    if ARTIFACT_ROUTES_INSTALLED in app or any(path in existing for path, _ in definitions):
        raise ValueError("成果路由已经注册")
    endpoints = []
    for path, handler in definitions:
        resource = DynamicResource(path)
        resource.add_route("GET", handler)
        endpoints.append(resource)

    @web.middleware
    async def dispatch(request, handler):
        for endpoint in endpoints:
            match, allowed = await endpoint.resolve(request)
            if match is None:
                if allowed:
                    raise web.HTTPMethodNotAllowed(request.method, allowed)
                continue
            request_origin = request.headers.get("Origin")
            if request.headers.get("Host") != host or request_origin not in (None, origin) or request.headers.get("Sec-Fetch-Site") not in (None, "same-origin", "none"):
                fail(web.HTTPForbidden, "FORBIDDEN", "成果请求来源无效")
            channel.require_run_api_role(request)
            require_artifact_read_boundary()
            request[ARTIFACT_ROUTE_PARAMS] = dict(match)
            return await match.handler(request)
        return await handler(request)

    app.middlewares.append(dispatch)
    app[ARTIFACT_ROUTES_INSTALLED] = True
