import asyncio
import hashlib
import json
import sys

from aiohttp import ClientSession, WSMsgType, web

UPSTREAM = "http://127.0.0.1:" + sys.argv[1]
PORT = int(sys.argv[2])
HOP = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailer", "transfer-encoding", "upgrade", "content-length"}
GATE = {"chat_id": None, "release": None, "held": None}
MESSAGES = []
REQUESTS = []
DROP = {"action": None, "request_id": None, "client_request_id": None, "dropped": None}


async def start(app):
    app["client"] = ClientSession(auto_decompress=False)


async def close(app):
    await app["client"].close()


async def state(request):
    return web.json_response({"held": GATE["held"], "messages": MESSAGES, "requests": REQUESTS, "dropped": DROP["dropped"]})


async def drop_response(request):
    body = await request.json()
    assert set(body) == {"action"} and body["action"] in {"boss.message.draft.save", "boss.message.send"}
    assert DROP["action"] is None and DROP["request_id"] is None
    DROP.update(action=body["action"], client_request_id=None, dropped=None)
    return web.json_response({"armed": True})


async def hold(request):
    body = await request.json()
    assert set(body) == {"chat_id"} and isinstance(body["chat_id"], str) and body["chat_id"] and GATE["release"] is None
    GATE.update(chat_id=body["chat_id"], release=asyncio.Event(), held=None)
    return web.json_response({"armed": True})


async def release(request):
    assert GATE["release"] is not None and GATE["held"] is not None
    GATE["release"].set()
    return web.json_response({"released": True})


async def proxy(request):
    client, target = request.app["client"], UPSTREAM + request.raw_path
    headers = {key: value for key, value in request.headers.items() if key.lower() not in HOP}
    if request.headers.get("Upgrade", "").lower() == "websocket":
        downstream = web.WebSocketResponse()
        await downstream.prepare(request)
        websocket_headers = {key: value for key, value in headers.items() if not key.lower().startswith("sec-websocket-")}
        async with client.ws_connect(target, headers=websocket_headers) as upstream:
            async def incoming():
                async for frame in downstream:
                    assert frame.type == WSMsgType.TEXT
                    body = json.loads(frame.data)
                    if body.get("type") == "message":
                        MESSAGES.append({"chat_id": body.get("chat_id"), "turn_id": body.get("turn_id"), "content_sha256": hashlib.sha256(body["content"].encode()).hexdigest()})
                    if body.get("type") == "webui_request":
                        action, identifier = body["action"], body["request_id"]
                        REQUESTS.append({"action": action, "request_id": identifier})
                        if action == DROP["action"]:
                            assert DROP["request_id"] is None
                            DROP.update(request_id=identifier, client_request_id=body["payload"]["client_request_id"])
                    await upstream.send_str(frame.data)
                await upstream.close()
            async def outgoing():
                async for frame in upstream:
                    assert frame.type == WSMsgType.TEXT
                    body = json.loads(frame.data)
                    if DROP["request_id"] is not None and body.get("event") == "webui_response" and body.get("request_id") == DROP["request_id"]:
                        assert body["ok"] is True
                        DROP["dropped"] = {"action": DROP["action"], "request_id": DROP["request_id"], "client_request_id": DROP["client_request_id"],
                            "transaction_response_ok": True, "response_sha256": hashlib.sha256(frame.data.encode()).hexdigest()}
                        DROP.update(action=None, request_id=None, client_request_id=None)
                        await downstream.close(code=1012)
                        await upstream.close()
                        return
                    if GATE["release"] is not None and body.get("chat_id") == GATE["chat_id"]:
                        GATE["held"] = {"chat_id": body["chat_id"], "event": body.get("event"), "response_sha256": hashlib.sha256(frame.data.encode()).hexdigest()}
                        await GATE["release"].wait()
                        GATE.update(chat_id=None, release=None, held=None)
                    await downstream.send_str(frame.data)
                await downstream.close()
            await asyncio.gather(incoming(), outgoing())
        return downstream
    async with client.request(request.method, target, headers=headers, data=await request.read(), allow_redirects=False) as upstream:
        return web.Response(status=upstream.status, body=await upstream.read(), headers={key: value for key, value in upstream.headers.items() if key.lower() not in HOP})


app = web.Application()
app.on_startup.append(start)
app.on_cleanup.append(close)
app.router.add_get("/_n02/state", state)
app.router.add_post("/_n02/hold", hold)
app.router.add_post("/_n02/release", release)
app.router.add_post("/_n02/drop-response", drop_response)
app.router.add_route("*", "/{path:.*}", proxy)
web.run_app(app, host="127.0.0.1", port=PORT, access_log=None)
