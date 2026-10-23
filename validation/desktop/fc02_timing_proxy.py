import asyncio
import hashlib
import json
import sys
import time

from aiohttp import ClientSession, WSMsgType, web


UPSTREAM = "http://127.0.0.1:" + sys.argv[1]
PORT = int(sys.argv[2])
HOP_HEADERS = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailer", "transfer-encoding", "upgrade", "host", "content-length"}


async def start(app):
    app["client"] = ClientSession(auto_decompress=False)
    app["gate"] = None
    app["events"] = []


async def close(app):
    await app["client"].close()


async def state(request):
    gate = request.app["gate"]
    return web.json_response({"gate": {field: gate[field] for field in ("path", "parameter", "value", "held", "released", "delivered")} if gate else None,
        "events": request.app["events"]})


async def arm(request):
    body = await request.json()
    assert set(body) == {"path", "parameter", "value"}
    previous = request.app["gate"]
    assert previous is None or previous["delivered"]
    request.app["gate"] = {**body, "held": False, "released": False, "delivered": False, "event": asyncio.Event()}
    return web.json_response({"armed": True})


async def release(request):
    gate = request.app["gate"]
    assert gate is not None and gate["held"] and not gate["released"]
    gate["released"] = True
    request.app["events"].append({"event": "release_requested", "path": gate["path"], "at_monotonic": time.monotonic()})
    gate["event"].set()
    return web.json_response({"released": True})


async def proxy(request):
    client = request.app["client"]
    target = UPSTREAM + request.raw_path
    headers = {name: value for name, value in request.headers.items() if name.lower() not in HOP_HEADERS}
    if request.headers.get("Upgrade", "").lower() == "websocket":
        downstream = web.WebSocketResponse()
        await downstream.prepare(request)
        async with client.ws_connect(target, headers=headers) as upstream:
            async def forward(source, destination):
                async for frame in source:
                    assert frame.type in (WSMsgType.TEXT, WSMsgType.BINARY)
                    if frame.type == WSMsgType.TEXT:
                        await destination.send_str(frame.data)
                    else:
                        await destination.send_bytes(frame.data)
                await destination.close()
            await asyncio.gather(forward(downstream, upstream), forward(upstream, downstream))
        return downstream
    async with client.request(request.method, target, headers=headers, data=await request.read(), allow_redirects=False) as upstream:
        body = await upstream.read()
        outgoing = {name: value for name, value in upstream.headers.items() if name.lower() not in HOP_HEADERS}
        gate = request.app["gate"]
        if gate is not None and not gate["held"] and request.path == gate["path"] and request.query.get(gate["parameter"]) == gate["value"]:
            assert upstream.status == 200
            decoded = json.loads(body)
            query_id = decoded["query_id"] if "query_id" in decoded else decoded["receipt"]["query"]["result"]["query_id"]
            request.app["events"].append({"event": "real_upstream_response_held", "path": request.path, "at_monotonic": time.monotonic(),
                "query_id": query_id, "status": upstream.status, "sha256": hashlib.sha256(body).hexdigest(), "bytes": len(body)})
            gate["held"] = True
            await gate["event"].wait()
            gate["delivered"] = True
            request.app["events"].append({"event": "identical_body_delivered", "path": request.path, "at_monotonic": time.monotonic(),
                "query_id": query_id, "sha256": hashlib.sha256(body).hexdigest(), "bytes": len(body)})
        return web.Response(status=upstream.status, body=body, headers=outgoing)


app = web.Application()
app.on_startup.append(start)
app.on_cleanup.append(close)
app.router.add_get("/_n4/state", state)
app.router.add_post("/_n4/arm", arm)
app.router.add_post("/_n4/release", release)
app.router.add_route("*", "/{path:.*}", proxy)
web.run_app(app, host="127.0.0.1", port=PORT, access_log=None)
