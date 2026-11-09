import asyncio
import sqlite3

import httpx
import pytest
from aiohttp import web
from nanobot.bus.queue import MessageBus
from nanobot.channels.websocket.runtime import WebSocketChannel, WebSocketConfig
from nanobot.webui.gateway_services import build_gateway_services

from agent_legacy_inventory import AgentLegacyInventory
from agent_legacy_run_link import AgentLegacyRunLink
from agent_run_broker import RunBroker
from agent_run_scope import RunScopeService
from agent_run_store import RunStore
from boss_memory_sessions import MemorySessionManager
from controls import ControlStore
from hermes_source_invalidation import begin_source_cleanup
from role_channel import RoleChannel


def setup_inventory(tmp_path):
    store = ControlStore(tmp_path / "business.sqlite")
    store.initialize("ui-check")
    RunStore(store.path)
    sessions = MemorySessionManager(tmp_path / "workspace", business_store=store, sessions_root=tmp_path / "sessions")
    scope = RunScopeService(store, sessions, "ui-check")
    inventory = AgentLegacyInventory(store, scope, allow_migration=True)
    return store, sessions, scope, inventory


def test_nanobot_session_inventory_reopen_and_source_change(tmp_path):
    store, sessions, scope, inventory = setup_inventory(tmp_path)
    session = sessions.get_or_create("websocket:migration-check")
    session.add_message("user", "核查会议资料")
    sessions.save(session, fsync=True)
    original = sessions.read_session_snapshot(session.key)
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        first = inventory.session_in_transaction(db, "migration-check", [])
        assert first["created"] is True
        assert first["metadata"]["engine"] == "nanobot"
        assert first["metadata"]["scope"]["owner_id"] == "boss-1"
        assert first["metadata"]["message_count"] == 1
        assert inventory.session_in_transaction(db, "migration-check", [])["created"] is False
    reopened = AgentLegacyInventory(store, scope)
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        assert reopened.session_in_transaction(db, "migration-check", [])["source_digest"] == first["source_digest"]
        saved = db.execute("SELECT metadata_json FROM agent_legacy_inventory").fetchone()[0]
        assert "核查会议资料" not in saved
    assert sessions.read_session_snapshot(session.key).messages == original.messages
    assert begin_source_cleanup(store, "ui-check", "finance-note", "1") is True
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        with pytest.raises(ValueError, match="当前范围已经变化"):
            reopened.session_in_transaction(db, "migration-check", [])
    assert sessions.read_session_snapshot(session.key).messages == original.messages


def test_interrupted_inventory_and_missing_records(tmp_path):
    store, sessions, _, inventory = setup_inventory(tmp_path)
    session = sessions.get_or_create("websocket:interrupted")
    sessions.save(session, fsync=True)
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        inventory.session_in_transaction(db, "interrupted", [])
        db.rollback()
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        assert db.execute("SELECT count(*) FROM agent_legacy_inventory").fetchone() == (0,)
        assert inventory.session_in_transaction(db, "interrupted", [])["created"] is True
        with pytest.raises(web.HTTPNotFound):
            inventory.plan_in_transaction(db, "missing-plan")
    with sqlite3.connect(store.path) as db:
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("DELETE FROM agent_legacy_inventory")


def test_session_inventory_requires_current_database_and_session(tmp_path):
    store, _, _, inventory = setup_inventory(tmp_path)
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        with pytest.raises(web.HTTPNotFound):
            inventory.session_in_transaction(db, "missing", [])
    with sqlite3.connect(tmp_path / "other.sqlite") as db:
        db.execute("BEGIN")
        with pytest.raises(ValueError, match="同一业务数据库事务"):
            inventory.session_in_transaction(db, "missing", [])


def test_memory_deletion_invalidates_session_inventory(tmp_path):
    store, sessions, _, inventory = setup_inventory(tmp_path)
    sessions.save(sessions.get_or_create("websocket:memory-check"), fsync=True)
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        inventory.session_in_transaction(db, "memory-check", [])
    with store.connect() as db:
        db.execute("DELETE FROM objects WHERE namespace=? AND kind='memory' AND id='current'", ("ui-check",))
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        with pytest.raises(ValueError, match="当前范围已经变化"):
            inventory.session_in_transaction(db, "memory-check", [])


def test_legacy_link_rejects_unauthenticated_http_request(tmp_path):
    async def exercise():
        store, sessions, scope, inventory = setup_inventory(tmp_path)
        sessions.save(sessions.get_or_create("websocket:migration-check"), fsync=True)
        with store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            inventory.session_in_transaction(db, "migration-check", [])
        broker = RunBroker(RunStore(store.path, allow_migration=False), scope_service=scope)
        links = AgentLegacyRunLink(inventory, broker, allow_migration=True)
        bus, config = MessageBus(), WebSocketConfig()
        gateway = build_gateway_services(config=config, bus=bus, session_manager=sessions,
            static_dist_path=None, workspace_path=tmp_path, default_restrict_to_workspace=True,
            config_path=tmp_path / "config.json", runtime_model_name=None,
            runtime_surface="webui", runtime_capabilities_overrides=None)
        channel = RoleChannel(WebSocketChannel(config, bus, gateway=gateway), {}, tmp_path / "access.jsonl", store)
        app = web.Application()

        async def link(request):
            return web.json_response(links.link(request, channel, "missing-run"))

        app.router.add_post("/link", link)
        runner = web.AppRunner(app)
        await runner.setup()
        await web.TCPSite(runner, "127.0.0.1", 0).start()
        address = "http://127.0.0.1:" + str(runner.addresses[0][1])
        try:
            async with httpx.AsyncClient(trust_env=False) as client:
                for headers in ({}, {"X-Boss-Role": "BOSS"}, {"Authorization": "Bearer invalid"}):
                    response = await client.post(address + "/link", headers=headers)
                    assert response.status_code == 401
            with store.connect() as db:
                assert db.execute("SELECT count(*) FROM agent_legacy_run_links").fetchone() == (0,)
                assert db.execute("SELECT count(*) FROM agent_runs").fetchone() == (0,)
        finally:
            await runner.cleanup()

    asyncio.run(exercise())
