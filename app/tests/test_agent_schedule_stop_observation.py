import asyncio
import multiprocessing
import os
import sqlite3

import httpx
import pytest
from aiohttp import web
from nanobot.bus.queue import MessageBus
from nanobot.channels.websocket.runtime import WebSocketChannel, WebSocketConfig
from nanobot.cron.service import CronService
from nanobot.webui.gateway_services import build_gateway_services

from agent_run_store import RunStore
from agent_schedule_handover_gate import AgentScheduleHandoverGate
from agent_schedule_inspection import AgentScheduleInspectionLease
from agent_schedule_stop_observation import AgentScheduleStopObservation
from boss_memory_sessions import MemorySessionManager
from controls import ControlStore
from hermes_schedule_adapter import HermesScheduleAdapter
from role_channel import RoleChannel


def interrupted_observation(path, cron_path, owner, epoch):
    async def exercise():
        store = ControlStore(path)
        lease = AgentScheduleInspectionLease(store)
        observations = AgentScheduleStopObservation(lease)
        cron = CronService(cron_path)
        await cron.start()
        cron.stop()
        db = store.connect()
        db.execute("BEGIN IMMEDIATE")
        observations.record_in_transaction(db, "interrupted", owner, epoch, cron)
        os._exit(17)

    asyncio.run(exercise())


def test_handover_gate_rejects_unverified_http_identity(tmp_path):
    async def exercise():
        store = ControlStore(tmp_path / "business.sqlite")
        store.initialize("ui-check")
        RunStore(store.path)
        adapter = HermesScheduleAdapter(store)
        adapter.install_schema()
        lease = AgentScheduleInspectionLease(store, allow_migration=True)
        observations = AgentScheduleStopObservation(lease, allow_migration=True)
        gate = AgentScheduleHandoverGate(observations, adapter)
        token = lease.acquire("technical-inspector", 60)
        cron = CronService(tmp_path / "cron" / "jobs.json")
        await cron.start()
        cron.stop()
        with store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            observations.record_in_transaction(db, "stop", token["owner"], token["epoch"], cron)
        sessions = MemorySessionManager(tmp_path / "workspace", business_store=store, sessions_root=tmp_path / "sessions")
        bus, config = MessageBus(), WebSocketConfig()
        gateway = build_gateway_services(config=config, bus=bus, session_manager=sessions, static_dist_path=None,
            workspace_path=tmp_path, default_restrict_to_workspace=True, config_path=tmp_path / "config.json",
            runtime_model_name=None, runtime_surface="webui", runtime_capabilities_overrides=None)
        channel = RoleChannel(WebSocketChannel(config, bus, gateway=gateway), {}, tmp_path / "access.jsonl", store)
        app = web.Application()

        async def activation(request):
            gate.require_activation(request, channel, cron, observation_key="stop", owner=token["owner"], epoch=token["epoch"], plan_id="missing", plan_version="1", occurrence_at="2026-10-30T00:00:00+00:00")
            return web.Response(status=204)

        app.router.add_post("/activation", activation)
        runner = web.AppRunner(app)
        await runner.setup()
        await web.TCPSite(runner, "127.0.0.1", 0).start()
        address = "http://127.0.0.1:" + str(runner.addresses[0][1])
        try:
            async with httpx.AsyncClient(trust_env=False) as client:
                for headers in ({}, {"X-Boss-Role": "BOSS"}, {"Authorization": "Bearer invalid"}):
                    assert (await client.post(address + "/activation", headers=headers)).status_code == 401
            with store.connect() as db:
                assert db.execute("SELECT count(*) FROM agent_runs").fetchone() == (0,)
                assert db.execute("SELECT count(*) FROM hermes_schedule_plan_candidates").fetchone() == (0,)
        finally:
            await runner.cleanup()

    asyncio.run(exercise())


def test_local_stop_observation_is_durable_and_does_not_prove_global_stop(tmp_path):
    async def exercise():
        store = ControlStore(tmp_path / "business.sqlite")
        store.initialize("ui-check")
        RunStore(store.path)
        lease = AgentScheduleInspectionLease(store, allow_migration=True)
        observations = AgentScheduleStopObservation(lease, allow_migration=True)
        token = lease.acquire("technical-inspector", 60)
        cron = CronService(tmp_path / "cron" / "jobs.json")
        await cron.start()
        with store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            with pytest.raises(ValueError, match="尚未停止"):
                observations.record_in_transaction(db, "stop", token["owner"], token["epoch"], cron)
        cron.stop()
        with store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            recorded = observations.record_in_transaction(db, "stop", token["owner"], token["epoch"], cron)
            assert recorded["created"] is True and recorded["scope"] == "LOCAL_OBJECT_ONLY"
            assert recorded["global_state"] == "UNVERIFIED"
            assert observations.record_in_transaction(db, "stop", token["owner"], token["epoch"], cron)["created"] is False
            with pytest.raises(sqlite3.IntegrityError):
                db.execute("DELETE FROM agent_schedule_stop_observations")
        reopened = AgentScheduleStopObservation(AgentScheduleInspectionLease(ControlStore(store.path)))
        with store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            assert reopened.record_in_transaction(db, "stop", token["owner"], token["epoch"], cron)["created"] is False
        process = multiprocessing.get_context("spawn").Process(target=interrupted_observation, args=(store.path, tmp_path / "other-cron" / "jobs.json", token["owner"], token["epoch"]))
        process.start()
        process.join(timeout=15)
        assert process.exitcode == 17
        with store.connect() as db:
            assert db.execute("SELECT count(*) FROM agent_schedule_stop_observations WHERE request_key='interrupted'").fetchone() == (0,)

    asyncio.run(exercise())
