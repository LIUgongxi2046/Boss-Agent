import asyncio
import json
import sqlite3
from pathlib import Path

from aiohttp import web

from agent_run_store import RunStore
from agent_run_broker import RunBroker


ROOT = Path(__file__).resolve().parents[2]
FIXTURES = [
    ROOT / ".work/upgrade2-u2-04/pytest-run-result-verified/test_result_persists_idempoten0/business.sqlite",
    ROOT / ".work/upgrade2-u2-04/pytest-result-citation-checks/test_result_citation_checks_us0/business.sqlite",
]


def load(path):
    store = RunStore(path, allow_migration=False)
    with store.connect() as db:
        db.execute("BEGIN")
        run_id = db.execute("SELECT run_id FROM agent_runs").fetchone()[0]
        row = store.read_run(run_id)
        selected = json.loads(row["selected_refs"]) if isinstance(row["selected_refs"], str) else list(row["selected_refs"] or [])
        snapshot = {
            "run_id": run_id,
            "conversation_id": row["conversation_id"],
            "goal": row["goal"],
            "selected_refs": selected,
            "status": row["status"],
            "revision": row["revision"],
            "goal_revision": row["goal_revision"],
            "applied_goal_revision": row["applied_goal_revision"],
            "last_event_seq": row["last_event_seq"],
            "cancel_requested_at": row["cancel_requested_at"],
            "allowed_actions": ["READ_EVENTS"],
            "requirements": {"goal_revision": row["goal_revision"], "state": "UNAVAILABLE", "required_outputs": None},
        }
        page = store.event_page_in_transaction(db, run_id, 0)
        result = store.result_in_transaction(db, run_id, row["goal_revision"])
        checks = RunBroker.result_citation_checks_in_transaction(db, row["space_id"], run_id, result)
        return run_id, {"snapshot": snapshot, "page": page, "result": {"run_id": run_id, "goal_revision": row["goal_revision"], "result": result, "citation_checks": checks}}


async def main():
    data = {}
    for path in FIXTURES:
        run_id, value = load(path)
        data[run_id] = value
    delayed = {"run": None}
    finished = {"run": None}

    async def snapshot(request):
        run_id = request.match_info["run_id"]
        if run_id not in data:
            raise web.HTTPNotFound(text="run not found")
        if delayed["run"] is None:
            delayed["run"] = run_id
            await asyncio.sleep(0.8)
            finished["run"] = run_id
        return web.json_response(data[run_id]["snapshot"])

    async def events(request):
        run_id = request.match_info["run_id"]
        if run_id not in data:
            raise web.HTTPNotFound(text="run not found")
        return web.json_response(data[run_id]["page"])

    async def result(request):
        run_id = request.match_info["run_id"]
        if run_id not in data:
            raise web.HTTPNotFound(text="run not found")
        return web.json_response(data[run_id]["result"])

    async def state(request):
        return web.json_response({"delayed_run": delayed["run"], "finished_run": finished["run"], "runs": list(data)})

    app = web.Application()
    app.add_routes([web.get("/api/v2/runs/{run_id}", snapshot), web.get("/api/v2/runs/{run_id}/events", events),
                    web.get("/api/v2/runs/{run_id}/result", result), web.get("/test-state", state)])
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    print(site._server.sockets[0].getsockname()[1], flush=True)
    await asyncio.Event().wait()


asyncio.run(main())
