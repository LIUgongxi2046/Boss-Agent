from aiohttp import web
from aiohttp.web_urldispatcher import DynamicResource
from jsonschema import Draft202012Validator

from hermes_skill_adapter import HermesSkillMaintenance


VALIDATION = Draft202012Validator({"type": "object", "additionalProperties": False,
    "required": ["expected_content_sha256"], "properties": {
        "expected_content_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"}}})
CANDIDATE_ID = web.RequestKey("hermes_skill_candidate_id", str)
PUBLICATION_ID = web.RequestKey("hermes_skill_publication_id", str)


def install_skill_maintenance(app, channel, store, *, public_port):
    service = HermesSkillMaintenance(channel, store)
    expected_host = "127.0.0.1:" + str(public_port)
    expected_origin = "http://" + expected_host

    async def input_body(request):
        if request.query or request.content_type != "application/json":
            raise web.HTTPBadRequest(text="方法请求格式无效")
        return await request.json()

    async def list_candidates(request):
        service._authorize(request, None)
        if any(key not in {"after", "limit"} or len(request.query.getall(key)) != 1 for key in request.query):
            raise web.HTTPBadRequest(text="候选分页参数无效")
        raw_limit = request.query.get("limit", "50")
        if not raw_limit.isascii() or not raw_limit.isdecimal() or len(raw_limit) > 3:
            raise web.HTTPBadRequest(text="候选分页参数无效")
        return web.json_response(service.list_candidates(request, after=request.query.get("after", ""), limit=int(raw_limit)), headers={"Cache-Control": "no-store"})

    async def maintenance_detail(request):
        service._authorize(request)
        if request.query:
            raise web.HTTPBadRequest(text="方法请求格式无效")
        return web.json_response(service.maintenance_detail(request, request[CANDIDATE_ID]), headers={"Cache-Control": "no-store"})

    async def preview(request):
        if request.query:
            raise web.HTTPBadRequest(text="方法请求格式无效")
        return web.json_response(service.preview(request, request[CANDIDATE_ID]), headers={"Cache-Control": "no-store"})

    async def decide(request):
        service._authorize(request, "BOSS")
        return web.json_response(service.decide(request, request[CANDIDATE_ID], await input_body(request)), headers={"Cache-Control": "no-store"})

    async def validate(request):
        service._authorize(request)
        payload = await input_body(request)
        if not VALIDATION.is_valid(payload):
            raise web.HTTPBadRequest(text="方法校验请求字段无效")
        return web.json_response(service.validate(request, request[CANDIDATE_ID], payload["expected_content_sha256"]), headers={"Cache-Control": "no-store"})

    async def publish(request):
        service._authorize(request)
        return web.json_response(service.publish(request, request[CANDIDATE_ID], await input_body(request)), headers={"Cache-Control": "no-store"})

    async def publication_status(request):
        service._authorize(request)
        if request.query:
            raise web.HTTPBadRequest(text="方法请求格式无效")
        return web.json_response(service.publication_status(request, request[CANDIDATE_ID], request[PUBLICATION_ID]), headers={"Cache-Control": "no-store"})

    async def decision_status(request):
        service._authorize(request, "BOSS")
        if request.query:
            raise web.HTTPBadRequest(text="方法请求格式无效")
        return web.json_response(service.decision_status(request, request[CANDIDATE_ID], request[PUBLICATION_ID]), headers={"Cache-Control": "no-store"})

    async def disable(request):
        service._authorize(request)
        return web.json_response(service.disable(request, await input_body(request)), headers={"Cache-Control": "no-store"})

    async def recover(request):
        service._authorize(request)
        return web.json_response(service._skills().execute("MAINTAINER", "recover", await input_body(request)), headers={"Cache-Control": "no-store"})

    async def cancel(request):
        service._authorize(request)
        return web.json_response(service._skills().execute("MAINTAINER", "cancel", await input_body(request)), headers={"Cache-Control": "no-store"})

    definitions = [
        ("GET", "/api/v2/skill-candidates", list_candidates),
        ("GET", "/api/v2/skill-candidates/{candidate_id}", preview),
        ("GET", "/api/v2/skill-candidates/{candidate_id}/maintenance", maintenance_detail),
        ("POST", "/api/v2/skill-candidates/{candidate_id}/decision", decide),
        ("GET", "/api/v2/skill-candidates/{candidate_id}/decisions/{publication_id}", decision_status),
        ("POST", "/api/v2/skill-candidates/{candidate_id}/validation", validate),
        ("POST", "/api/v2/skill-candidates/{candidate_id}/publish", publish),
        ("GET", "/api/v2/skill-candidates/{candidate_id}/publications/{publication_id}", publication_status),
        ("POST", "/api/v2/skills/disable", disable),
        ("POST", "/api/v2/skills/recover", recover),
        ("POST", "/api/v2/skills/cancel", cancel),
    ]
    endpoints = []
    for method, path, handler in definitions:
        resource = DynamicResource(path)
        resource.add_route(method, handler)
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
                raise web.HTTPForbidden(text="方法请求来源无效")
            if "candidate_id" in match:
                request[CANDIDATE_ID] = match["candidate_id"]
            if "publication_id" in match:
                request[PUBLICATION_ID] = match["publication_id"]
            return await match.handler(request)
        return await handler(request)

    app.middlewares.append(dispatch)
