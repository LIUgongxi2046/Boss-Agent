import asyncio
import hashlib
import json
import sys

from aiohttp import ClientSession, WSMsgType, web

UPSTREAM = "http://127.0.0.1:" + sys.argv[1]
PORT = int(sys.argv[2])
HOP = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailer", "transfer-encoding", "upgrade", "content-length"}
STATE = {"events": [], "connections": 0, "dropped": False}


async def start(app):
    app["client"] = ClientSession(auto_decompress=False)


async def close(app):
    await app["client"].close()


async def state(request):
    return web.json_response(STATE)


async def proxy(request):
    client, target = request.app["client"], UPSTREAM + request.raw_path
    headers = {key: value for key, value in request.headers.items() if key.lower() not in HOP}
    if request.headers.get("Upgrade", "").lower() == "websocket":
        STATE["connections"] += 1
        downstream = web.WebSocketResponse()
        await downstream.prepare(request)
        websocket_headers = {key: value for key, value in headers.items() if not key.lower().startswith("sec-websocket-")}
        async with client.ws_connect(target, headers=websocket_headers) as upstream:
            order_ids = set()
            async def incoming():
                async for frame in downstream:
                    assert frame.type in (WSMsgType.TEXT, WSMsgType.BINARY)
                    if frame.type == WSMsgType.TEXT:
                        body = json.loads(frame.data)
                        if body.get("action") == "boss.today.reorder":
                            order_ids.add(body["request_id"])
                            STATE["events"].append({"event": "actual_order_forwarded", "request_id": body["request_id"],
                                "client_request_id": body["payload"]["client_request_id"]})
                        await upstream.send_str(frame.data)
                    else:
                        await upstream.send_bytes(frame.data)
                await upstream.close()
            async def outgoing():
                async for frame in upstream:
                    assert frame.type in (WSMsgType.TEXT, WSMsgType.BINARY)
                    if frame.type == WSMsgType.TEXT:
                        body = json.loads(frame.data)
                        if body.get("request_id") in order_ids and body.get("ok") is True and not STATE["dropped"]:
                            STATE["dropped"] = True
                            STATE["events"].append({"event": "actual_order_result_connection_closed", "request_id": body["request_id"],
                                "version": body["result"]["version"], "sha256": hashlib.sha256(frame.data.encode()).hexdigest()})
                            await downstream.close(code=1011, message=b"actual response delivery interrupted")
                            await upstream.close()
                            break
                        await downstream.send_str(frame.data)
                    else:
                        await downstream.send_bytes(frame.data)
                await downstream.close()
            await asyncio.gather(incoming(), outgoing())
        return downstream
    async with client.request(request.method, target, headers=headers, data=await request.read(), allow_redirects=False) as upstream:
        return web.Response(status=upstream.status, body=await upstream.read(),
            headers={key: value for key, value in upstream.headers.items() if key.lower() not in HOP})


app = web.Application()
app.on_startup.append(start)
app.on_cleanup.append(close)
app.router.add_get("/_order/state", state)
app.router.add_route("*", "/{path:.*}", proxy)
web.run_app(app, host="127.0.0.1", port=PORT, access_log=None)
