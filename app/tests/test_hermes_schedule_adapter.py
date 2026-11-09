from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import asyncio
import hashlib
import os
from pathlib import Path
import sqlite3
import subprocess

import pytest
import httpx
from aiohttp import web
from nanobot.bus.queue import MessageBus
from nanobot.channels.websocket.runtime import WebSocketChannel, WebSocketConfig
from nanobot.webui.gateway_services import build_gateway_services
from boss_simulation_api import _context
from boss_memory_sessions import MemorySessionManager
from boss_owner_plans import OwnerPlansAPI, stop_business_until, valid_plan_budget, valid_plan_execution_choices
from controls import ControlStore
from agent_run_broker import RunBroker
from agent_run_scope import RunScopeService
from agent_run_store import RunStore
from hermes_schedule_adapter import HermesScheduleAdapter, MIGRATION_PATH, MIGRATION_VERSION, stable_occurrence_id
from role_channel import RoleChannel
from test_agent_schedule_occurrence_gate import INSTANT, create_store


def test_plan_choices_require_explicit_outputs_and_current_method_reference(schedule_store):
    from boss_native_skills import BossSkillCatalog
    from model_probe import BusinessTool
    from nanobot.agent.skills import SkillsLoader
    from nanobot.agent.tools.registry import ToolRegistry

    store, _, _, _ = schedule_store
    registry = ToolRegistry()
    envelope = {"request_id": "plan-method", "owner_id": "boss-1", "execution_namespace": "ui-check", "dataset_id": "selection", "dataset_version": "1", "session_id": "result-check"}
    for operation in ("query_metrics", "read_evidence"):
        registry.register(BusinessTool(operation, store, envelope, {}, []))
    catalog = BossSkillCatalog(SkillsLoader(Path(__file__).resolve().parents[2] / "agent"), registry)
    _, references = catalog.context("BOSS", ["SOP03"])
    method = {key: references[0][key] for key in ("sop_id", "version", "content_sha256")}
    assert valid_plan_execution_choices(["TEXT"], method)
    assert not valid_plan_execution_choices(None, method)
    assert not valid_plan_execution_choices(["TEXT"], None)
    assert not valid_plan_execution_choices([], method)


@pytest.fixture
def schedule_store(tmp_path):
    store = ControlStore(tmp_path / "business.sqlite")
    store.initialize("ui-check")
    adapter = HermesScheduleAdapter(store)
    adapter.install_schema()
    adapter.install_schema()
    with store.connect() as db:
        context = _context(db)
        schedule = store.get(db, context["namespace"], "schedule", "current")
    instant = datetime.fromisoformat(context["clock"]).replace(second=0, microsecond=0).astimezone(timezone.utc)
    return store, adapter, schedule, instant


def test_occurrence_claim_requires_matching_run_link(tmp_path):
    store, gate = create_store(tmp_path / "business.sqlite")
    adapter = HermesScheduleAdapter(store)
    adapter.install_schema()
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        context = _context(db)
        identifier = stable_occurrence_id(context["namespace"], context["dataset_id"], context["dataset_version"], "technical-plan", "1", INSTANT)
        assert adapter.claim_run_occurrence_in_transaction(gate, db, "technical-plan", "1", INSTANT, identifier) is None
        db.rollback()
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        assert db.execute("SELECT count(*) FROM agent_schedule_occurrence_gate").fetchone() == (0,)
        assert gate.claim_in_transaction(db, "technical-plan", "1", INSTANT)["claimed"] is True
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        with pytest.raises(ValueError, match="领取与运行关联"):
            adapter.claim_run_occurrence_in_transaction(gate, db, "technical-plan", "1", INSTANT, identifier)


def test_hermes_occurrence_matches_product_time(schedule_store, tmp_path):
    _, adapter, schedule, instant = schedule_store
    earlier = instant - timedelta(minutes=1)
    root = Path(__file__).resolve().parents[2]
    engine = root / ".work/upgrade2/u2-03/clean-hermes"
    code = "import sys; from cron.jobs import compute_next_run; print(compute_next_run({'kind':'cron','expr':'* * * * *'}, sys.argv[1], timezone=sys.argv[2]))"
    process = subprocess.run([str(engine / ".venv/bin/python"), "-c", code, earlier.isoformat(), schedule["timezone"]],
                             cwd=engine, env={"PATH": os.defpath, "HERMES_HOME": str(tmp_path), "TMPDIR": str(tmp_path), "PYTHONPATH": str(engine)},
                             capture_output=True, text=True, check=True)
    actual = process.stdout.strip()
    assert datetime.fromisoformat(actual).astimezone(timezone.utc) == instant
    first = adapter.observe(schedule["version"], actual)
    again = adapter.observe(schedule["version"], instant.isoformat())
    assert first == again and first["status"] == "CANDIDATE"


def test_occurrence_reopen_concurrent_dedup_and_version(schedule_store):
    store, adapter, schedule, instant = schedule_store
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(adapter.observe, schedule["version"], instant.isoformat()) for _ in range(2)]
    assert futures[0].result() == futures[1].result()
    reopened = HermesScheduleAdapter(ControlStore(store.path))
    assert reopened.observe(schedule["version"], instant.isoformat()) == futures[0].result()
    with store.connect() as db:
        assert db.execute("SELECT count(*) FROM hermes_schedule_observations").fetchone()[0] == 1
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            db.execute("DELETE FROM hermes_schedule_observations")
    with pytest.raises(ValueError, match="配置版本"):
        reopened.observe("999", instant.isoformat())


def test_canceled_or_future_occurrence_is_rejected(schedule_store):
    store, adapter, schedule, instant = schedule_store
    with pytest.raises(ValueError, match="未到"):
        adapter.observe(schedule["version"], (instant + timedelta(days=1)).isoformat())
    with pytest.raises(ValueError, match="时区"):
        adapter.observe(schedule["version"], instant.replace(tzinfo=None).isoformat())
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        current = store.get(db, "ui-check", "schedule", "current")
        current["canceled"] = True
        store.put(db, "ui-check", "schedule", "current", current)
    with pytest.raises(ValueError, match="状态不可用"):
        adapter.observe(schedule["version"], instant.isoformat())
    with store.connect() as db:
        assert db.execute("SELECT count(*) FROM hermes_schedule_observations").fetchone()[0] == 0


def test_same_revision_with_changed_expression_is_rejected(schedule_store):
    store, adapter, schedule, instant = schedule_store
    adapter.observe(schedule["version"], instant.isoformat())
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        current = store.get(db, "ui-check", "schedule", "current")
        current["expression"] = "*/1 * * * *"
        store.put(db, "ui-check", "schedule", "current", current)
    with pytest.raises(ValueError, match="内容已经变化"):
        adapter.observe(schedule["version"], instant.isoformat())


def test_observation_never_authorizes_missing_owner_plan(schedule_store):
    store, adapter, schedule, instant = schedule_store
    adapter.observe(schedule["version"], instant.isoformat())
    with pytest.raises(web.HTTPNotFound):
        adapter.plan_candidate("missing-plan", "1", instant.isoformat())
    with pytest.raises(web.HTTPNotFound):
        adapter.require_plan("missing-plan", "1", instant.isoformat())
    with store.connect() as db:
        assert db.execute("SELECT count(*) FROM objects WHERE kind='authorization'").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM hermes_schedule_plan_candidates").fetchone()[0] == 0


def test_plan_candidate_key_is_unique_and_linked_to_technical_occurrence(schedule_store):
    store, _, _, _ = schedule_store
    with store.connect() as db:
        columns = db.execute("PRAGMA table_info(hermes_schedule_plan_candidates)").fetchall()
        primary = [row[1] for row in sorted((row for row in columns if row[5]), key=lambda row: row[5])]
        assert primary == ["namespace", "dataset_id", "dataset_version", "plan_id", "plan_version", "occurrence_at"]
        foreign = db.execute("PRAGMA foreign_key_list(hermes_schedule_plan_candidates)").fetchall()
        assert len(foreign) == 6 and all(row[2] == "hermes_schedule_observations" for row in foreign)
        link_columns = db.execute("PRAGMA table_info(hermes_schedule_run_links)").fetchall()
        assert [row[1] for row in link_columns if row[5]] == ["occurrence_id"]
        link_foreign = db.execute("PRAGMA foreign_key_list(hermes_schedule_run_links)").fetchall()
        assert {row[2] for row in link_foreign} == {"agent_runs", "hermes_schedule_plan_candidates"}
        notification_columns = db.execute("PRAGMA table_info(hermes_schedule_notification_links)").fetchall()
        notification_key = [row[1] for row in sorted((row for row in notification_columns if row[5]), key=lambda row: row[5])]
        assert notification_key == ["occurrence_id", "event_id", "event_version"]
        notification_foreign = db.execute("PRAGMA foreign_key_list(hermes_schedule_notification_links)").fetchall()
        assert len(notification_foreign) == 1 and notification_foreign[0][2] == "hermes_schedule_run_links"
        assert db.execute("SELECT version FROM hermes_schedule_migrations ORDER BY version").fetchall() == [("hermes_schedule_001",), ("hermes_schedule_002",), ("hermes_schedule_003",)]


def test_schedule_migration_rejects_changed_digest(schedule_store):
    store, adapter, _, _ = schedule_store
    with store.connect() as db:
        db.execute("UPDATE hermes_schedule_migrations SET sha256=? WHERE version=?", ("invalid", "hermes_schedule_002"))
    with pytest.raises(ValueError, match="迁移摘要"):
        adapter.install_schema()
    with store.connect() as db:
        assert db.execute("SELECT count(*) FROM hermes_schedule_previews").fetchone()[0] == 0


def test_schedule_migration_adds_preview_to_existing_database(tmp_path):
    store = ControlStore(tmp_path / "business.sqlite")
    store.initialize("ui-check")
    source = MIGRATION_PATH.read_bytes()
    with store.connect() as db:
        before = db.execute("SELECT count(*) FROM objects").fetchone()[0]
        db.executescript("BEGIN IMMEDIATE;\n" + source.decode("utf-8"))
        db.execute("INSERT INTO hermes_schedule_migrations VALUES (?,?)", (MIGRATION_VERSION, hashlib.sha256(source).hexdigest()))
    adapter = HermesScheduleAdapter(store)
    adapter.install_schema()
    adapter.install_schema()
    with store.connect() as db:
        assert db.execute("SELECT count(*) FROM objects").fetchone()[0] == before
        assert db.execute("SELECT count(*) FROM hermes_schedule_migrations").fetchone()[0] == 3
        assert db.execute("SELECT count(*) FROM hermes_schedule_previews").fetchone()[0] == 0


def test_plan_budget_covers_engine_process_fields():
    budget = {"model_requests": 1, "rounds": 1, "tools": 1, "seconds": 1, "concurrency": 1,
              "context_tokens": 1, "files": 1, "file_bytes": 1, "open_files": 16, "cpu_seconds": 1}
    assert valid_plan_budget(budget)
    assert not valid_plan_budget({key: value for key, value in budget.items() if key != "cpu_seconds"})
    assert not valid_plan_budget({**budget, "open_files": 15})
    assert not valid_plan_budget({**budget, "cpu_seconds": True})


def test_stop_time_requires_timezone_and_known_rule():
    assert stop_business_until({"business_until": "2026-10-30T08:00:00+08:00"}) == datetime(2026, 10, 30, tzinfo=timezone.utc)
    with pytest.raises(web.HTTPBadRequest):
        stop_business_until({"business_until": "2026-10-30T08:00:00"})
    with pytest.raises(web.HTTPBadRequest):
        stop_business_until({"unknown": True})


def test_run_creation_in_transaction_rejects_absent_identity(schedule_store):
    store, _, _, _ = schedule_store
    runs = RunStore(store.path)
    broker = RunBroker(runs)
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        with pytest.raises(web.HTTPUnauthorized):
            broker.create_in_transaction(db, None, {})
        assert db.execute("SELECT count(*) FROM agent_runs").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM agent_api_requests").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM hermes_schedule_run_links").fetchone()[0] == 0


def test_concurrency_check_requires_transaction_and_matching_database(schedule_store, tmp_path):
    store, adapter, _, _ = schedule_store
    RunStore(store.path)
    with store.connect() as db:
        with pytest.raises(ValueError, match="参数"):
            adapter.require_available_concurrency(db, "ui-check", "missing-plan", "missing-occurrence", 1)
        db.execute("BEGIN IMMEDIATE")
        adapter.require_available_concurrency(db, "ui-check", "missing-plan", "missing-occurrence", 1)
        with pytest.raises(ValueError, match="参数"):
            adapter.require_available_concurrency(db, "ui-check", "missing-plan", "missing-occurrence", 0)
    with sqlite3.connect(tmp_path / "other.sqlite") as db:
        db.execute("BEGIN IMMEDIATE")
        with pytest.raises(ValueError, match="同一数据库"):
            adapter.require_available_concurrency(db, "ui-check", "missing-plan", "missing-occurrence", 1)


def test_occurrence_identifier_is_stable_for_equivalent_instants(schedule_store):
    store, _, _, instant = schedule_store
    with store.connect() as db:
        context = _context(db)
    args = (context["namespace"], context["dataset_id"], context["dataset_version"], "missing-plan", "1")
    identifier = stable_occurrence_id(*args, instant.isoformat())
    local = instant.astimezone(timezone(timedelta(hours=8))).isoformat()
    assert identifier == stable_occurrence_id(*args, local)
    assert identifier != stable_occurrence_id(*args[:-1], "2", local)
    assert identifier != stable_occurrence_id(*args, (instant + timedelta(minutes=1)).isoformat())


def test_original_receipt_rejects_unauthenticated_http(schedule_store, tmp_path):
    store, adapter, _, _ = schedule_store

    async def exercise():
        bus, config = MessageBus(), WebSocketConfig()
        sessions = MemorySessionManager(tmp_path / "workspace", business_store=store, sessions_root=tmp_path / "sessions")
        gateway = build_gateway_services(config=config, bus=bus, session_manager=sessions,
            static_dist_path=None, workspace_path=tmp_path, default_restrict_to_workspace=True,
            config_path=tmp_path / "config.json", runtime_model_name=None,
            runtime_surface="webui", runtime_capabilities_overrides=None)
        channel = RoleChannel(WebSocketChannel(config, bus, gateway=gateway), {}, tmp_path / "access.jsonl", store)
        runs = RunStore(store.path)
        scope_service = RunScopeService(store, sessions, "ui-check")
        broker = RunBroker(runs, scope_service=scope_service)
        plans = OwnerPlansAPI(store)

        async def receipt(request):
            result = adapter.read_existing_notification(request, channel, "missing-plan", "1", "missing-event")
            return web.json_response(result)

        async def create_run(request):
            result = adapter.create_scheduled_run(request, channel, broker, "missing-plan", "1", "2026-10-22T01:00:00+00:00")
            return web.json_response(result)

        async def bind_execution(request):
            return web.json_response(plans.bind_execution(request, channel, scope_service, {}))

        async def preview_execution(request):
            return web.json_response(plans.preview_execution(request, channel, scope_service, {}))

        async def decide_execution(request):
            return web.json_response(plans.decide_execution(request, channel, scope_service, {}))

        async def execution_receipt(request):
            return web.json_response(plans.execution_receipt(request, channel, scope_service, plan_id="missing-plan", client_request_id="missing-request", operation="decision"))

        async def dispatch(request):
            result = adapter.dispatch_scheduled_event(request, channel, scope_service, "missing-plan", "1", "2026-10-22T01:00:00+00:00", "missing-event")
            return web.json_response(result)

        app = web.Application()
        app.router.add_get("/receipt", receipt)
        app.router.add_post("/create-run", create_run)
        app.router.add_post("/bind-execution", bind_execution)
        app.router.add_post("/preview-execution", preview_execution)
        app.router.add_post("/decide-execution", decide_execution)
        app.router.add_post("/execution-receipt", execution_receipt)
        app.router.add_post("/dispatch", dispatch)
        runner = web.AppRunner(app)
        await runner.setup()
        await web.TCPSite(runner, "127.0.0.1", 0).start()
        try:
            async with httpx.AsyncClient(trust_env=False) as client:
                url = "http://127.0.0.1:" + str(runner.addresses[0][1]) + "/receipt"
                for headers in ({}, {"X-Boss-Role": "BOSS"}):
                    response = await client.get(url, headers=headers)
                    assert response.status_code == 401 and response.json()["code"] == "UNAUTHENTICATED"
                    response = await client.post(url.replace("/receipt", "/create-run"), headers=headers)
                    assert response.status_code == 401 and response.json()["code"] == "UNAUTHENTICATED"
                    for path in ("/bind-execution", "/preview-execution", "/decide-execution", "/execution-receipt", "/dispatch"):
                        response = await client.post(url.replace("/receipt", path), headers=headers)
                        assert response.status_code == 401 and response.json()["code"] == "UNAUTHENTICATED"
        finally:
            await runner.cleanup()

    asyncio.run(exercise())
    with store.connect() as db:
        assert db.execute("SELECT count(*) FROM agent_runs").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM agent_api_requests").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM hermes_schedule_run_links").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM hermes_schedule_notification_links").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM hermes_schedule_previews").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM objects WHERE kind IN ('authorization','owner_plan','notification')").fetchone()[0] == 0
