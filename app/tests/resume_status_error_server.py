import asyncio
import json

from aiohttp import web


async def main():
    async def resume_status(request):
        run_id = request.match_info["run_id"]
        if run_id == "00000000-0000-4000-8000-000000000001":
            return web.json_response({"run_id": run_id})
        if run_id == "00000000-0000-4000-8000-000000000002":
            return web.json_response({"error": "service unavailable"}, status=503)
        if run_id == "00000000-0000-4000-8000-000000000003":
            return web.json_response({"run_id": run_id, "status": "WAITING_INPUT", "revision": 1, "goal_revision": 1,
                                      "allowed_actions": [], "waiting_reasons": ["ENGINE_BOUNDARY_UNVERIFIED"],
                                      "original_receipt": None})
        return web.json_response({"error": "not found"}, status=404)

    app = web.Application()
    app.add_routes([web.get("/api/v2/runs/{run_id}/resume-status", resume_status)])
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    print(site._server.sockets[0].getsockname()[1], flush=True)
    await asyncio.Event().wait()


asyncio.run(main())
