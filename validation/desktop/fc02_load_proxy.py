import asyncio
import hashlib
import json
import sys

from aiohttp import ClientSession, WSMsgType, web

UPSTREAM = "http://127.0.0.1:" + sys.argv[1]
PORT = int(sys.argv[2])
HEADERS = {"connection","keep-alive","proxy-authenticate","proxy-authorization","te","trailer","transfer-encoding","upgrade","content-length"}


async def start(app):
    app["client"] = ClientSession(auto_decompress=False)
    app["events"] = []
    app["dropped"] = False
    app["connections"] = 0


async def close(app):
    await app["client"].close()


async def state(request):
    return web.json_response({"events":request.app["events"],"dropped":request.app["dropped"],"connections":request.app["connections"]})


async def proxy(request):
    client, target = request.app["client"], UPSTREAM + request.raw_path
    headers = {key:value for key,value in request.headers.items() if key.lower() not in HEADERS}
    if request.headers.get("Upgrade","").lower() == "websocket":
        request.app["connections"] += 1
        downstream = web.WebSocketResponse()
        await downstream.prepare(request)
        websocket_headers = {key:value for key,value in headers.items() if not key.lower().startswith("sec-websocket-")}
        async with client.ws_connect(target,headers=websocket_headers) as upstream:
            load_ids = set()
            async def incoming():
                async for frame in downstream:
                    assert frame.type in (WSMsgType.TEXT,WSMsgType.BINARY)
                    if frame.type == WSMsgType.TEXT:
                        body = json.loads(frame.data)
                        if body.get("action") == "boss.simulation.bi_scenario.load":
                            load_ids.add(body["request_id"])
                            request.app["events"].append({"event":"actual_load_forwarded","request_id":body["request_id"],"client_request_id":body["payload"]["client_request_id"],"scenario_id":body["payload"]["scenario_id"]})
                        await upstream.send_str(frame.data)
                    else:
                        await upstream.send_bytes(frame.data)
                await upstream.close()
            async def outgoing():
                async for frame in upstream:
                    assert frame.type in (WSMsgType.TEXT,WSMsgType.BINARY)
                    if frame.type == WSMsgType.TEXT:
                        body = json.loads(frame.data)
                        if body.get("request_id") in load_ids and body.get("ok") is True and not request.app["dropped"]:
                            request.app["dropped"] = True
                            request.app["events"].append({"event":"actual_load_result_connection_closed","request_id":body["request_id"],"client_request_id":body["result"]["client_request_id"],"scenario_id":body["result"]["scenario_id"],"version":body["result"]["version"],"sha256":hashlib.sha256(frame.data.encode()).hexdigest()})
                            await downstream.close(code=1011,message=b"actual response delivery interrupted")
                            await upstream.close()
                            break
                        await downstream.send_str(frame.data)
                    else:
                        await downstream.send_bytes(frame.data)
                await downstream.close()
            await asyncio.gather(incoming(),outgoing())
        return downstream
    async with client.request(request.method,target,headers=headers,data=await request.read(),allow_redirects=False) as upstream:
        return web.Response(status=upstream.status,body=await upstream.read(),headers={key:value for key,value in upstream.headers.items() if key.lower() not in HEADERS})


app = web.Application()
app.on_startup.append(start)
app.on_cleanup.append(close)
app.router.add_get("/_bi_load/state",state)
app.router.add_route("*","/{path:.*}",proxy)
web.run_app(app,host="127.0.0.1",port=PORT,access_log=None)
