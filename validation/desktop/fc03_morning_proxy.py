import asyncio
import hashlib
import json
import sys

from aiohttp import ClientSession, WSMsgType, web

UPSTREAM = "http://127.0.0.1:" + sys.argv[1]
PORT = int(sys.argv[2])
HOP = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailer", "transfer-encoding", "upgrade", "content-length"}
ACTIONS = {"boss.morning.query", "boss.today.reorder", "boss.simulation.morning_coverage.load", "boss.mvp.query", "boss.fc01.coordinate", "boss.assignment.send", "boss.assignment.sources.confirm", "boss.commitment.create", "boss.reminder.ack", "boss.reminder.snooze", "boss.reminder.close", "boss.owner.notice.save", "boss.owner.notice.confirm", "boss.owner.plan.pause", "boss.scheduler.draft.save", "boss.alert.ack", "boss.alert.snooze", "boss.alert.close", "boss.alert.meeting.link", "boss.alert.assignment.create", "boss.alert.rule.save", "boss.simulation.alert.load"}
ACTIONS.add("boss.morning.bind")
ACTIONS.add("boss.assignment.create")
ACTIONS.add("boss.morning.cancel")
STATE = {"events": [], "connections": 0, "armed": None, "dropped_actions": [], "delayed_read": None, "held_binding": None}
DELAY = {"selection": None, "release": None}
BINDING_RELEASE = None


async def start(app):
    app["client"] = ClientSession(auto_decompress=False)


async def close(app):
    await app["client"].close()


async def state(request):
    return web.json_response(STATE)


async def arm(request):
    body = await request.json()
    assert set(body) == {"action"} and body["action"] in ACTIONS and STATE["armed"] is None
    STATE["armed"] = body["action"]
    return web.json_response({"armed": STATE["armed"]})


async def delay_read(request):
    body = await request.json()
    assert set(body) == {"path", "field", "value"} and body["path"] in {"/api/boss/ui/morning/detail", "/api/boss/ui/morning/source"}
    assert body["field"] in {"item_id", "source_id"} and isinstance(body["value"], str) and DELAY["selection"] is None
    DELAY.update(selection=body, release=asyncio.Event())
    return web.json_response({"armed": body})


async def release_read(request):
    assert DELAY["release"] is not None
    DELAY["release"].set()
    return web.json_response({"released": True})


async def hold_binding(request):
    global BINDING_RELEASE
    assert BINDING_RELEASE is None
    BINDING_RELEASE = asyncio.Event()
    return web.json_response({"armed": True})


async def release_binding(request):
    assert BINDING_RELEASE is not None and STATE["held_binding"] is not None
    BINDING_RELEASE.set()
    return web.json_response({"released": True})


async def proxy(request):
    client, target = request.app["client"], UPSTREAM + request.raw_path
    headers = {key: value for key, value in request.headers.items() if key.lower() not in HOP}
    if request.headers.get("Upgrade", "").lower() == "websocket":
        STATE["connections"] += 1
        downstream = web.WebSocketResponse()
        await downstream.prepare(request)
        websocket_headers = {key: value for key, value in headers.items() if not key.lower().startswith("sec-websocket-")}
        async with client.ws_connect(target, headers=websocket_headers) as upstream:
            requests = {}
            async def incoming():
                async for frame in downstream:
                    assert frame.type == WSMsgType.TEXT
                    body = json.loads(frame.data)
                    if body.get("action") in ACTIONS:
                        reference = {"request_id": body["request_id"], "action": body["action"], "client_request_id": body["payload"]["client_request_id"]}
                        if body["action"] == "boss.assignment.create" and "morning_reference" in body["payload"]:
                            reference["morning_reference"] = body["payload"]["morning_reference"]
                        requests[body["request_id"]] = reference
                        STATE["events"].append({"event": "actual_request_forwarded", **reference})
                    await upstream.send_str(frame.data)
                await upstream.close()
            async def outgoing():
                global BINDING_RELEASE
                async for frame in upstream:
                    assert frame.type == WSMsgType.TEXT
                    body = json.loads(frame.data)
                    reference = requests.get(body.get("request_id"))
                    if reference and body.get("ok") is True and reference["action"] == "boss.morning.bind" and BINDING_RELEASE is not None:
                        STATE["held_binding"] = {**reference, "response_sha256": hashlib.sha256(frame.data.encode()).hexdigest()}
                        await BINDING_RELEASE.wait()
                        STATE["events"].append({"event": "actual_binding_response_released", **STATE["held_binding"]})
                        STATE["held_binding"] = None
                        BINDING_RELEASE = None
                    if reference and body.get("ok") is True and STATE["armed"] == reference["action"]:
                        STATE["armed"] = None
                        STATE["dropped_actions"].append(reference["action"])
                        STATE["events"].append({"event": "actual_success_delivery_interrupted", **reference, "response_sha256": hashlib.sha256(frame.data.encode()).hexdigest()})
                        await downstream.close(code=1011, message=b"actual success delivery interrupted")
                        await upstream.close()
                        break
                    await downstream.send_str(frame.data)
                await downstream.close()
            await asyncio.gather(incoming(), outgoing())
        return downstream
    async with client.request(request.method, target, headers=headers, data=await request.read(), allow_redirects=False) as upstream:
        body = await upstream.read()
        selection = DELAY["selection"]
        if selection and request.path == selection["path"] and request.query.get(selection["field"]) == selection["value"]:
            STATE["delayed_read"] = {**selection, "actual_status": upstream.status, "response_sha256": hashlib.sha256(body).hexdigest()}
            await DELAY["release"].wait()
            STATE["events"].append({"event": "actual_read_released", **STATE["delayed_read"]})
            DELAY.update(selection=None, release=None)
            STATE["delayed_read"] = None
        return web.Response(status=upstream.status, body=body, headers={key: value for key, value in upstream.headers.items() if key.lower() not in HOP})


app = web.Application()
app.on_startup.append(start)
app.on_cleanup.append(close)
app.router.add_get("/_morning/state", state)
app.router.add_post("/_morning/arm", arm)
app.router.add_post("/_morning/delay", delay_read)
app.router.add_post("/_morning/release", release_read)
app.router.add_post("/_morning/hold-binding", hold_binding)
app.router.add_post("/_morning/release-binding", release_binding)
app.router.add_route("*", "/{path:.*}", proxy)
web.run_app(app, host="127.0.0.1", port=PORT, access_log=None)
