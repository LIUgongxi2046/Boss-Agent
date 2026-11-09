import asyncio
import multiprocessing
import os
import sqlite3
import time
from uuid import uuid4

import httpx
import pytest
from aiohttp import web
from nanobot.bus.queue import MessageBus
from nanobot.channels.websocket.runtime import WebSocketChannel, WebSocketConfig
from nanobot.webui.gateway_services import build_gateway_services

from agent_recovery_checkpoint import AgentRecoveryCheckpoint
from agent_recovery_preflight import AgentRecoveryPreflight
from agent_run_store import RunStore
from agent_simulation_recovery import AgentSimulationRecovery
from agent_simulation_recovery_journal import AgentSimulationRecoveryJournal
from agent_simulation_snapshot import AgentSimulationSnapshot
from boss_memory_sessions import MemorySessionManager
from controls import ControlStore
from hermes_source_invalidation import begin_source_cleanup
from role_channel import RoleChannel


def interrupted_preflight(path, directory):
    store = ControlStore(path)
    checkpoint = AgentRecoveryCheckpoint(AgentRecoveryPreflight(store))
    snapshots = AgentSimulationSnapshot(checkpoint, directory)
    recovery = AgentSimulationRecovery(snapshots, AgentSimulationRecoveryJournal(snapshots))
    recovery.preflight("snapshot", max_age_seconds=300)
    db = store.connect()
    db.execute("BEGIN IMMEDIATE")
    os._exit(17)


def interrupted_blocked_request(path, directory, target_id):
    store = ControlStore(path)
    checkpoint = AgentRecoveryCheckpoint(AgentRecoveryPreflight(store))
    snapshots = AgentSimulationSnapshot(checkpoint, directory)
    journal = AgentSimulationRecoveryJournal(snapshots)
    recovery = AgentSimulationRecovery(snapshots, journal)
    checked = recovery.preflight("snapshot", max_age_seconds=300)
    journal.record_blocked("snapshot", target_id, checked)
    os._exit(17)


def setup_recovery(tmp_path):
    store = ControlStore(tmp_path / "business.sqlite")
    store.initialize("ui-check")
    RunStore(store.path)
    checkpoint = AgentRecoveryCheckpoint(AgentRecoveryPreflight(store), allow_migration=True)
    snapshots = AgentSimulationSnapshot(checkpoint, tmp_path, allow_migration=True)
    journal = AgentSimulationRecoveryJournal(snapshots, allow_migration=True)
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        checkpoint_id = checkpoint.capture_in_transaction(db, "state")["checkpoint_id"]
    result = snapshots.create("snapshot", "state", checkpoint_id)
    return store, AgentSimulationRecovery(snapshots, journal), result


def test_simulation_preflight_is_repeatable_and_rejects_missing_permission(tmp_path):
    store, recovery, result = setup_recovery(tmp_path)
    before = {item.name for item in tmp_path.iterdir()}
    first = recovery.preflight("snapshot", max_age_seconds=300)
    assert first == recovery.preflight("snapshot", max_age_seconds=300)
    assert first["sha256"] == result["sha256"] and first["restore_state"] == "BLOCKED"
    assert first["reason"] == "DELETION_LEDGER_COMPLETENESS_UNVERIFIED"
    with pytest.raises(ValueError, match="本人身份服务"):
        recovery.restore(None, None, "snapshot", str(uuid4()), max_age_seconds=300)
    assert {item.name for item in tmp_path.iterdir()} == before
    with store.connect() as db:
        assert db.execute("SELECT count(*) FROM agent_simulation_snapshots").fetchone() == (1,)


def test_simulation_preflight_rejects_expired_changed_and_missing(tmp_path):
    store, recovery, result = setup_recovery(tmp_path)
    with pytest.raises(ValueError, match="记录不存在"):
        recovery.preflight("missing", max_age_seconds=300)
    time.sleep(0.03)
    with pytest.raises(ValueError, match="已经过期"):
        recovery.preflight("snapshot", max_age_seconds=0.001)
    path = tmp_path / result["snapshot_name"]
    with sqlite3.connect(path) as db:
        db.execute("DELETE FROM objects WHERE namespace=? AND kind='memory' AND id='current'", ("ui-check",))
    with pytest.raises(ValueError, match="摘要不符"):
        recovery.preflight("snapshot", max_age_seconds=300)
    assert begin_source_cleanup(store, "ui-check", "finance-note", "1")
    with pytest.raises(ValueError, match="当前状态已经变化"):
        recovery.preflight("snapshot", max_age_seconds=300)


def test_simulation_preflight_after_independent_process_exit(tmp_path):
    store, recovery, _ = setup_recovery(tmp_path)
    process = multiprocessing.get_context("spawn").Process(target=interrupted_preflight, args=(store.path, tmp_path))
    process.start()
    process.join(timeout=60)
    assert process.exitcode == 17
    assert recovery.preflight("snapshot", max_age_seconds=300)["restore_state"] == "BLOCKED"


def test_simulation_recovery_path_is_confined_and_not_created(tmp_path):
    _, recovery, _ = setup_recovery(tmp_path)
    identifier = str(uuid4())
    target = recovery.target_path(identifier)
    assert target == tmp_path / "recovery" / identifier and not target.exists()
    with pytest.raises(ValueError):
        recovery.target_path("../../business.sqlite")
    (tmp_path / "recovery").symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError, match="目录不可用"):
        recovery.target_path(identifier)


def test_blocked_request_survives_process_exit_and_preserves_unverified_files(tmp_path):
    store, recovery, _ = setup_recovery(tmp_path)
    identifier = str(uuid4())
    process = multiprocessing.get_context("spawn").Process(target=interrupted_blocked_request, args=(store.path, tmp_path, identifier))
    process.start()
    process.join(timeout=60)
    assert process.exitcode == 17
    checked = recovery.preflight("snapshot", max_age_seconds=300)
    assert recovery.journal.record_blocked("snapshot", identifier, checked) == {"state": "BLOCKED", "created": False}
    with pytest.raises(ValueError, match="请求内容已经变化"):
        recovery.journal.record_blocked("snapshot", str(uuid4()), checked)
    assert recovery.journal.inspect_target(identifier) == {"state": "ABSENT", "cleanup": "NONE"}
    target = tmp_path / "recovery" / identifier
    target.mkdir(parents=True)
    preserved = target / "document.txt"
    preserved.write_text("保留资料", encoding="utf-8")
    assert recovery.journal.inspect_target(identifier) == {"state": "UNVERIFIED", "cleanup": "BLOCKED"}
    assert preserved.read_text(encoding="utf-8") == "保留资料"


@pytest.mark.parametrize("recorded", [False, True])
def test_recovery_journal_rechecks_snapshot_before_record_and_retry(tmp_path, recorded):
    store, recovery, snapshot = setup_recovery(tmp_path)
    identifier = str(uuid4())
    checked = recovery.preflight("snapshot", max_age_seconds=300)
    if recorded:
        assert recovery.journal.record_blocked("snapshot", identifier, checked) == {"state": "BLOCKED", "created": True}
    with sqlite3.connect(tmp_path / snapshot["snapshot_name"]) as db:
        db.execute("DELETE FROM objects WHERE namespace=? AND kind='memory' AND id='current'", ("ui-check",))
    with pytest.raises(ValueError, match="摘要已经变化"):
        recovery.journal.record_blocked("snapshot", identifier, checked)
    with store.connect() as db:
        assert db.execute("SELECT count(*) FROM agent_simulation_recovery_requests").fetchone() == (int(recorded),)
    assert not (tmp_path / "recovery").exists()


def test_simulation_restore_http_refuses_unverified_identity(tmp_path):
    async def exercise():
        store, recovery, _ = setup_recovery(tmp_path)
        bus, config = MessageBus(), WebSocketConfig()
        sessions = MemorySessionManager(tmp_path / "workspace", business_store=store, sessions_root=tmp_path / "sessions")
        gateway = build_gateway_services(config=config, bus=bus, session_manager=sessions,
            static_dist_path=None, workspace_path=tmp_path, default_restrict_to_workspace=True,
            config_path=tmp_path / "config.json", runtime_model_name=None,
            runtime_surface="webui", runtime_capabilities_overrides=None)
        channel = RoleChannel(WebSocketChannel(config, bus, gateway=gateway), {}, tmp_path / "access.jsonl", store)
        app = web.Application()
        target_id = str(uuid4())

        async def restore(request):
            return web.json_response(recovery.restore(request, channel, "snapshot", target_id, max_age_seconds=300))

        app.router.add_post("/restore", restore)
        runner = web.AppRunner(app)
        await runner.setup()
        await web.TCPSite(runner, "127.0.0.1", 0).start()
        address = "http://127.0.0.1:" + str(runner.addresses[0][1])
        try:
            async with httpx.AsyncClient(trust_env=False) as client:
                for headers in ({}, {"X-Boss-Role": "BOSS"}, {"Authorization": "Bearer invalid"}):
                    assert (await client.post(address + "/restore", headers=headers)).status_code == 401
            assert not (tmp_path / "recovery").exists()
            with store.connect() as db:
                assert db.execute("SELECT count(*) FROM agent_simulation_recovery_requests").fetchone() == (0,)
        finally:
            await runner.cleanup()

    asyncio.run(exercise())
