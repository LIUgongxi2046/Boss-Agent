import asyncio
import hashlib
import json
import sys

from aiohttp import ClientSession, WSMsgType, web

UPSTREAM = "http://127.0.0.1:" + sys.argv[1]
PORT = int(sys.argv[2])
HOP = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailer", "transfer-encoding", "upgrade", "content-length"}
ACTIONS = {"boss.morning.query", "boss.today.reorder", "boss.simulation.morning_coverage.load"}
STATE = {"events": [], "connections": 0, "armed": None, "dropped_actions": []}


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
                        requests[body["request_id"]] = reference
                        STATE["events"].append({"event": "actual_request_forwarded", **reference})
                    await upstream.send_str(frame.data)
                await upstream.close()
            async def outgoing():
                async for frame in upstream:
                    assert frame.type == WSMsgType.TEXT
                    body = json.loads(frame.data)
                    reference = requests.get(body.get("request_id"))
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
        return web.Response(status=upstream.status, body=await upstream.read(), headers={key: value for key, value in upstream.headers.items() if key.lower() not in HOP})


app = web.Application()
app.on_startup.append(start)
app.on_cleanup.append(close)
app.router.add_get("/_morning/state", state)
app.router.add_post("/_morning/arm", arm)
app.router.add_route("*", "/{path:.*}", proxy)
web.run_app(app, host="127.0.0.1", port=PORT, access_log=None)
