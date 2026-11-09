import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
import sqlite3
import socket

import httpx
import pytest
from aiohttp import web

from agent_chat_budget import AgentChatBudget
from agent_chat_budget_routes import install_chat_budget_routes, read_budget_payload
from agent_run_dispatcher import AgentRunDispatcher
from business import checksum
from test_agent_run_dispatcher import services_for


def test_technical_budget_binding_remains_on_original_version(tmp_path):
    services = services_for(tmp_path)
    budgets = AgentChatBudget(services.store, services.recovery.channel, services.scope, allow_migration=True)
    run_id = services.store.create_run("technical-owner", "ui-check", "request", "digest")
    budget = {"model_requests": 2, "rounds": 2, "tools": 2, "seconds": 2, "concurrency": 1, "context_tokens": 128, "files": 1, "file_bytes": 1024, "open_files": 16, "cpu_seconds": 1}
    later = {**budget, "tools": 4}
    with services.store.connect() as db:
        db.execute("UPDATE agent_runs SET conversation_id=?,goal=?,selected_refs=?,scope_proof=? WHERE run_id=?", ("technical-chat", "模拟目标", "[]", "{}", run_id))
        db.execute("INSERT INTO agent_chat_budget_configs VALUES (?,?,?,?,?)", (1, "technical-1", json.dumps(budget), checksum(budget), "2026-10-30T00:00:00+00:00"))
        db.execute("INSERT INTO agent_chat_run_budgets VALUES (?,?,?,?)", (run_id, 1, checksum(budget), "2026-10-30T00:00:00+00:00"))
        db.execute("INSERT INTO agent_chat_budget_configs VALUES (?,?,?,?,?)", (2, "technical-2", json.dumps(later), checksum(later), "2026-10-30T00:00:00+00:00"))
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("UPDATE agent_chat_run_budgets SET config_version=2 WHERE run_id=?", (run_id,))
    with services.store.connect() as db:
        db.execute("BEGIN")
        result = budgets.read_in_transaction(db, run_id)
        assert result == {"config_version": 1, "budget": budget}
        assert AgentRunDispatcher(services).approved_budget_in_transaction(db, run_id)[1] == budget
    reopened = AgentChatBudget(services.store, services.recovery.channel, services.scope)
    with services.store.connect() as db:
        db.execute("BEGIN")
        assert reopened.read_in_transaction(db, run_id) == result
    def reread():
        with services.store.connect() as db:
            db.execute("BEGIN")
            return reopened.read_in_transaction(db, run_id)
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(lambda _: reread(), range(2))) == [result, result]


def test_missing_chat_budget_is_rejected(tmp_path):
    services = services_for(tmp_path)
    budgets = AgentChatBudget(services.store, services.recovery.channel, services.scope, allow_migration=True)
    run_id = services.store.create_run("technical-owner", "ui-check", "request", "digest")
    with services.store.connect() as db:
        db.execute("BEGIN")
        with pytest.raises(ValueError, match="预算尚未绑定"):
            budgets.read_in_transaction(db, run_id)


def test_unauthenticated_configuration_and_binding_rejected(tmp_path):
    services = services_for(tmp_path)
    budgets = AgentChatBudget(services.store, services.recovery.channel, services.scope, allow_migration=True)

    async def exercise():
        async def configure(request):
            budgets.configure(request, "request", 0, {})
            return web.Response()

        async def bind(request):
            with services.store.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                budgets.bind_in_transaction(db, request, "missing")
            return web.Response()

        app = web.Application()
        app.router.add_post("/configure", configure)
        app.router.add_post("/bind", bind)
        runner = web.AppRunner(app)
        await runner.setup()
        await web.TCPSite(runner, "127.0.0.1", 0).start()
        try:
            async with httpx.AsyncClient(trust_env=False) as client:
                base = "http://127.0.0.1:" + str(runner.addresses[0][1])
                assert (await client.post(base + "/configure")).status_code == 401
                assert (await client.post(base + "/bind")).status_code == 401
        finally:
            await runner.cleanup()

    asyncio.run(exercise())
    with services.store.connect() as db:
        assert db.execute("SELECT count(*) FROM agent_chat_budget_configs").fetchone() == (0,)
        assert db.execute("SELECT count(*) FROM agent_chat_run_budgets").fetchone() == (0,)


def test_technical_configuration_versions_and_integrity(tmp_path):
    services = services_for(tmp_path)
    budgets = AgentChatBudget(services.store, services.recovery.channel, services.scope, allow_migration=True)
    budget = {"model_requests": 2, "rounds": 2, "tools": 2, "seconds": 2, "concurrency": 1, "context_tokens": 128, "files": 1, "file_bytes": 1024, "open_files": 16, "cpu_seconds": 1}
    with services.store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        assert budgets._read_configuration_in_transaction(db) == {"version": 0, "budget": None}
        assert budgets._configure_in_transaction(db, "technical-1", 0, budget) == {"version": 1, "budget": budget}
        assert budgets._configure_in_transaction(db, "technical-1", 0, budget) == {"version": 1, "budget": budget}
        with pytest.raises(web.HTTPConflict) as conflict:
            budgets._configure_in_transaction(db, "technical-1", 0, {**budget, "tools": 3})
        assert json.loads(conflict.value.text)["code"] == "REQUEST_KEY_CONFLICT"
        with pytest.raises(web.HTTPConflict) as conflict:
            budgets._configure_in_transaction(db, "technical-2", 0, budget)
        assert json.loads(conflict.value.text)["code"] == "REVISION_CONFLICT"
        with pytest.raises(web.HTTPBadRequest) as invalid:
            budgets._configure_in_transaction(db, "technical-2", 1, {**budget, "open_files": 15})
        assert json.loads(invalid.value.text)["code"] == "INVALID_INPUT"
        for request_key, version, value in (("", 1, budget), ("\ud800", 1, budget), ("technical-2", True, budget), ("technical-2", -1, budget), ("technical-2", 1, {**budget, "tools": True}), ("technical-2", 1, {key: item for key, item in budget.items() if key != "tools"}), ("technical-2", 1, {**budget, "extra": 1})):
            with pytest.raises(web.HTTPBadRequest) as invalid:
                budgets._configure_in_transaction(db, request_key, version, value)
            assert json.loads(invalid.value.text)["code"] == "INVALID_INPUT"
        assert budgets._read_configuration_in_transaction(db) == {"version": 1, "budget": budget}
    with services.store.connect() as db:
        db.execute("BEGIN")
        assert budgets._read_configuration_in_transaction(db) == {"version": 1, "budget": budget}


def test_chat_budget_route_rejects_untrusted_requests(tmp_path):
    services = services_for(tmp_path)
    budgets = AgentChatBudget(services.store, services.recovery.channel, services.scope, allow_migration=True)

    async def exercise():
        async def other(request):
            return web.Response(text="other")

        app = web.Application()
        app.router.add_route("*", "/{tail:.*}", other)
        server_socket = socket.socket()
        server_socket.bind(("127.0.0.1", 0))
        server_socket.listen()
        port = server_socket.getsockname()[1]
        install_chat_budget_routes(app, budgets, public_port=port)
        runner = web.AppRunner(app)
        await runner.setup()
        await web.SockSite(runner, server_socket).start()
        try:
            async with httpx.AsyncClient(trust_env=False) as client:
                base = "http://127.0.0.1:" + str(port)
                url = base + "/api/v2/settings/chat-run-budget"
                assert (await client.get(url)).status_code == 401
                assert (await client.put(url, headers={"Origin": base}, json={})).status_code == 401
                assert (await client.put(url, headers={"Origin": base, "Content-Type": "application/json"}, content=b"{")).status_code == 401
                assert (await client.put(url, json={})).status_code == 403
                assert (await client.get(url, headers={"Origin": "http://example.com"})).status_code == 403
                assert (await client.get(url, headers={"Host": "example.com"})).status_code == 403
                assert (await client.get(url, headers={"Sec-Fetch-Site": "cross-site"})).status_code == 403
                assert (await client.post(url)).status_code == 405
                assert (await client.get(base + "/other")).text == "other"
        finally:
            await runner.cleanup()

    asyncio.run(exercise())
    with services.store.connect() as db:
        assert db.execute("SELECT count(*) FROM agent_chat_budget_configs").fetchone() == (0,)


def test_budget_payload_validation_over_http(tmp_path):
    async def exercise():
        async def validate(request):
            return web.json_response(await read_budget_payload(request))

        app = web.Application(client_max_size=131072)
        app.router.add_put("/validate", validate)
        runner = web.AppRunner(app)
        await runner.setup()
        await web.TCPSite(runner, "127.0.0.1", 0).start()
        try:
            async with httpx.AsyncClient(trust_env=False) as client:
                url = "http://127.0.0.1:" + str(runner.addresses[0][1]) + "/validate"
                headers = {"Content-Type": "application/json"}
                valid = {"request_key": "technical", "expected_version": 0, "budget": {"tools": 1}}
                assert (await client.put(url, json=valid)).json() == valid
                invalid_bodies = [b"{", b'\xff', b'{"request_key":', b'[]', b'{}', b'{"request_key":"a","request_key":"b","expected_version":0,"budget":{}}', b'{"request_key":"a","expected_version":0,"budget":{"tools":{}}}']
                for body in invalid_bodies:
                    response = await client.put(url, headers=headers, content=body)
                    assert response.status_code == 400
                    assert response.json()["code"] == "INVALID_INPUT"
                assert (await client.put(url + "?extra=1", json=valid)).status_code == 400
                assert (await client.put(url, content=b"{}", headers={"Content-Type": "text/plain"})).status_code == 400
        finally:
            await runner.cleanup()

    asyncio.run(exercise())
