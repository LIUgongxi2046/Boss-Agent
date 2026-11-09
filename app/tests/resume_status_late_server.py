import asyncio
import json

from aiohttp import web


RUN_TIMEOUT = "00000000-0000-4000-8000-000000000010"
RUN_UNMOUNT = "00000000-0000-4000-8000-000000000011"
RUN_A = "00000000-0000-4000-8000-000000000012"
RUN_B = "00000000-0000-4000-8000-000000000013"
RUN_401 = "00000000-0000-4000-8000-000000000014"


def status(run_id, reason):
    return {"run_id": run_id, "status": "WAITING_INPUT", "revision": 1, "goal_revision": 1,
            "allowed_actions": [], "waiting_reasons": [reason], "original_receipt": None}


async def main():
    counts = {}

    async def resume_status(request):
        run_id = request.match_info["run_id"]
        token = request.headers.get("Authorization", "")
        counts[run_id] = counts.get(run_id, 0) + 1
        if run_id == RUN_401:
            return web.json_response({"error": "unauthorized"}, status=401)
        if run_id == RUN_TIMEOUT:
            await asyncio.sleep(3)
            return web.json_response(status(run_id, "ENGINE_BOUNDARY_UNVERIFIED"))
        if run_id == RUN_UNMOUNT:
            await asyncio.sleep(0.8)
            return web.json_response(status(run_id, "ENGINE_BOUNDARY_UNVERIFIED"))
        if run_id == RUN_A:
            if token == "Bearer token-a":
                await asyncio.sleep(0.8)
                return web.json_response(status(run_id, "ENGINE_BOUNDARY_UNVERIFIED"))
            return web.json_response(status(run_id, "PROCESS_RECOVERY_UNVERIFIED"))
        if run_id == RUN_B:
            return web.json_response(status(run_id, "PROCESS_RECOVERY_UNVERIFIED"))
        return web.json_response({"error": "not found"}, status=404)

    async def state(request):
        return web.json_response({"counts": counts})

    app = web.Application()
    app.add_routes([web.get("/api/v2/runs/{run_id}/resume-status", resume_status), web.get("/test-state", state)])
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    print(site._server.sockets[0].getsockname()[1], flush=True)
    await asyncio.Event().wait()


asyncio.run(main())
