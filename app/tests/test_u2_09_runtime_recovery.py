import asyncio
import json
import socket
import sys
from pathlib import Path

import httpx
import pytest
from aiohttp import web
from nanobot.bus.queue import MessageBus
from nanobot.channels.websocket.runtime import WebSocketChannel, WebSocketConfig
from nanobot.config.loader import set_config_path
from nanobot.webui.gateway_services import build_gateway_services

from agent_legacy_inventory import AgentLegacyInventory
from agent_run_api import product_application
from agent_run_broker import RunBroker
from agent_run_concurrency import RunConcurrencyBudget
from agent_run_scope import RunScopeService
from agent_run_store import RunStore
from agent_run_tool_budget import RunToolBudget
from boss_memory_sessions import MemorySessionManager
from controls import ControlStore
from hermes_legacy_routes import install_legacy_routes
from hermes_process_evidence import HermesProcessEvidence
from hermes_source_invalidation import begin_source_cleanup
from role_channel import RoleChannel


def test_technical_family_source_budget_and_process_recovery(tmp_path):
    business = ControlStore(tmp_path / "business.sqlite")
    business.initialize("ui-check")
    runs = RunStore(business.path)
    concurrency = RunConcurrencyBudget(runs, allow_migration=True)
    tools = RunToolBudget(runs, allow_migration=True)
    process_evidence = HermesProcessEvidence(runs, allow_migration=True)
    root = runs.create_run("technical-check", "ui-check", "root-request", "root-digest")
    root_lease = runs.acquire_lease(root, 0, "root-worker", 60)
    runs.transition(root, root_lease["revision"], "RUNNING", "root-worker", root_lease["epoch"])
    concurrency.configure(root, "root-worker", root_lease["epoch"], 1)
    tools.configure(root, "root-worker", root_lease["epoch"], 1)
    child = runs.create_child_run(root, "root-worker", root_lease["epoch"], "child-request", "child-digest")
    child_lease = runs.acquire_lease(child, 0, "child-worker", 60)
    runs.transition(child, child_lease["revision"], "RUNNING", "child-worker", child_lease["epoch"])
    with runs.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        assert tools.reserve_in_transaction(db, root, "root-worker", root_lease["epoch"], "tool-request", "tool-digest", "read")
        with pytest.raises(ValueError, match="工具预算不足"):
            tools.reserve_in_transaction(db, child, "child-worker", child_lease["epoch"], "child-tool", "child-digest", "read")
        assert concurrency.reserve_in_transaction(db, child, "child-worker", child_lease["epoch"], "process-request", "process-digest") == {"state": "ACTIVE", "created": True}
        db.execute("UPDATE agent_runs SET selected_refs=? WHERE run_id=?", (json.dumps(["finance-note"]), root))

    probe = Path(__file__).with_name("hermes_lifecycle_probe.py").resolve()
    process_evidence.start(child, "process-request", "process-digest", "child-worker", child_lease["epoch"],
        "technical-check", "ui-check", [sys.executable, str(probe), "child", "0.5"], cwd=tmp_path)
    process = process_evidence.processes[(child, "process-request")]
    try:
        process.wait(timeout=10)
        assert process_evidence.observe_exit(child, "process-request") == {"state": "EXITED", "exit_code": 0, "exit_scope": "LEADER_ONLY"}
        with runs.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            recovery = concurrency.recover_in_transaction(db, child, "process-request")
            assert recovery == {"state": "UNKNOWN", "process_state": "EXITED", "exit_scope": "LEADER_ONLY"}
            with pytest.raises(ValueError, match="并发额度不足"):
                concurrency.reserve_in_transaction(db, root, "root-worker", root_lease["epoch"], "other-process", "other-digest")
        reopened = RunConcurrencyBudget(RunStore(business.path, allow_migration=False))
        with runs.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            assert reopened.recover_in_transaction(db, child, "process-request") == recovery
        assert begin_source_cleanup(business, "ui-check", "finance-note", "1") is True
        for run_id, worker, epoch in ((root, "root-worker", root_lease["epoch"]), (child, "child-worker", child_lease["epoch"])):
            with pytest.raises(ValueError, match="来源清理尚未完成"):
                runs.renew_lease(run_id, worker, epoch, 60)
        business.control("ui-check", "withdraw", {"source_id": "finance-note", "version": "1"})
        with pytest.raises(ValueError, match="来源已经撤销"):
            runs.renew_lease(child, "child-worker", child_lease["epoch"], 60)
        reopened_business = ControlStore(business.path)
        with reopened_business.connect() as db:
            assert reopened_business.get(db, "ui-check", "document", "finance-note")["withdrawn"] is True
            assert reopened_business.get(db, "ui-check", "hermes_source_cleanup", "finance-note")["state"] == "COMPLETED"
        result = {"root_tool_limit": 1, "child_tool_rejected": True, "process_exit": "LEADER_ONLY",
                  "recovery_state": recovery["state"], "parent_slot_rejected": True,
                  "source_cleanup": "COMPLETED", "root_and_child_renewal_rejected": True}
        (tmp_path / "result.json").write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=10)


def test_legacy_routes_reject_no_identity(tmp_path):
    async def exercise():
        set_config_path(tmp_path / "config.json")
        business = ControlStore(tmp_path / "business.sqlite")
        business.initialize("ui-check")
        runs = RunStore(business.path)
        sessions = MemorySessionManager(tmp_path / "workspace", business_store=business, sessions_root=tmp_path / "sessions")
        scope = RunScopeService(business, sessions, "ui-check")
        broker = RunBroker(runs, scope_service=scope)
        bus, config = MessageBus(), WebSocketConfig()
        gateway = build_gateway_services(config=config, bus=bus, session_manager=sessions, static_dist_path=None,
            workspace_path=tmp_path, default_restrict_to_workspace=True, config_path=tmp_path / "config.json",
            runtime_model_name=None, runtime_surface="webui", runtime_capabilities_overrides=None)
        channel = RoleChannel(WebSocketChannel(config, bus, gateway=gateway), {}, tmp_path / "access.jsonl", business)
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(("127.0.0.1", 0))
        sock.listen()
        sock.setblocking(False)
        port = sock.getsockname()[1]
        origin = f"http://127.0.0.1:{port}"
        app = product_application(channel, broker)
        install_legacy_routes(app, channel, scope, broker, public_port=port)
        runner = web.AppRunner(app)
        await runner.setup()
        await web.SockSite(runner, sock).start()
        try:
            async with httpx.AsyncClient(trust_env=False) as client:
                for method in ("GET", "POST"):
                    response = await client.request(method, origin + "/api/v2/runs/unknown/legacy-link", headers={"Origin": origin})
                    assert response.status_code == 401
                    assert response.json()["code"] == "UNAUTHENTICATED"
            with business.connect() as db:
                assert db.execute("SELECT count(*) FROM agent_runs").fetchone()[0] == 0
                assert db.execute("SELECT count(*) FROM sqlite_master WHERE name='agent_legacy_run_links'").fetchone()[0] == 0
            print(json.dumps({"legacy_get": 401, "legacy_post": 401, "runs_created": 0, "links_table_created": False}))
        finally:
            await runner.cleanup()

    asyncio.run(exercise())


def test_empty_legacy_session_inventory_rechecks_source_cleanup(tmp_path):
    set_config_path(tmp_path / "config.json")
    business = ControlStore(tmp_path / "business.sqlite")
    business.initialize("ui-check")
    RunStore(business.path)
    sessions = MemorySessionManager(tmp_path / "workspace", business_store=business, sessions_root=tmp_path / "sessions")
    session = sessions.get_or_create("websocket:technical-session")
    sessions.save(session, fsync=True)
    scope = RunScopeService(business, sessions, "ui-check")
    inventory = AgentLegacyInventory(business, scope, allow_migration=True)
    with business.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        first = inventory.session_in_transaction(db, "technical-session", [])
        assert first["created"] is True
        assert first["metadata"]["engine"] == "nanobot"
        assert first["metadata"]["message_count"] == 0
    reopened = AgentLegacyInventory(ControlStore(business.path), scope)
    with business.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        again = reopened.session_in_transaction(db, "technical-session", [])
        assert again["created"] is False and again["source_digest"] == first["source_digest"]
    assert begin_source_cleanup(business, "ui-check", "finance-note", "1") is True
    with business.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        with pytest.raises(ValueError, match="当前范围已经变化"):
            reopened.session_in_transaction(db, "technical-session", [])
    assert sessions.read_session_snapshot(session.key).messages == []
    print(json.dumps({"engine": "nanobot", "message_count": 0, "reopen_consistent": True,
                      "source_cleanup_rejected_old_inventory": True}))
