import asyncio
import hashlib
import json
import os
import secrets
import signal
import sys
from pathlib import Path

from aiohttp import web
from filelock import FileLock
from loguru import logger
from nanobot import Nanobot, RuntimeContextBlock
from nanobot.agent.loop import AgentLoop
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.agent.turn_delivery import TurnDeliveryFactory
from nanobot.bus.queue import MessageBus
from nanobot.channels.manager import ChannelManager
from nanobot.config.loader import load_config, resolve_config_env_vars
from nanobot.cron.service import CronService
from nanobot.cron.types import CronSchedule
from nanobot.cron.bound_runner import run_bound_cron_job
from nanobot.session.manager import SessionManager
from nanobot.session.recovery import RecoveryCoordinator
from nanobot.session.webui_turns import WebuiTurnCoordinator, WebuiTurnRoutePolicy

from business import OPERATIONS, ROOT, Store, encode, now
from connection import RecordedProvider, settings
from controls import ControlStore
from model_probe import Audit, BusinessTool
from role_channel import RoleChannel
from service import application as business_application

WORK = ROOT / ".work/application"


class ApplicationTool(BusinessTool):
    async def execute(self, **kwargs):
        if self.operation in {"create_assignment", "send_assignment"}:
            with self.store.connect() as db:
                self.bindings[self.operation] = self.store.get(db, self.envelope["execution_namespace"], "authorization_binding", self.operation)
        return await super().execute(**kwargs)


def prepare():
    WORK.mkdir(parents=True, exist_ok=True)
    access = WORK / "access.json"
    if not access.exists():
        access.write_text(encode({"BOSS": secrets.token_urlsafe(32), "MAINTAINER": secrets.token_urlsafe(32)}))
        access.chmod(0o600)
    roles = json.loads(access.read_text())
    os.environ["NANOBOT_WEBUI_SECRET"] = roles["BOSS"]
    os.environ["BOSS_PROBE_TOKEN"] = roles["BOSS"]
    os.environ["MAINTAINER_PROBE_TOKEN"] = roles["MAINTAINER"]
    config = WORK / "config.json"
    if not config.exists():
        config.write_text(encode({"agents": {"defaults": {"workspace": str(WORK / "workspace"), "provider": "deepseek", "model": "deepseek-flash", "maxToolIterations": 12, "maxTokens": 4096, "timezone": "Asia/Shanghai", "timezoneMode": "manual", "dream": {"enabled": False}, "idleCompactAfterMinutes": 0}}, "providers": {"deepseek": {"apiKey": "${DEEPSEEK_API_KEY}", "apiBase": "https://api.deepseek.com", "extraBody": {"thinking": {"type": "disabled"}}}}, "gateway": {"host": "127.0.0.1", "port": 18791, "heartbeat": {"enabled": False}}, "channels": {"websocket": {"enabled": True, "host": "127.0.0.1", "port": 8872, "tokenIssueSecret": "${NANOBOT_WEBUI_SECRET}", "websocketRequiresToken": True, "showReasoning": False, "tokenTtlS": 3600}}, "tools": {"restrictToWorkspace": True}, "transcription": {"enabled": False}}))
    return roles, config


async def serve():
    logger.remove()
    logger.add(sys.stderr, level="INFO", diagnose=False, backtrace=False)
    connection = settings()
    roles, config_path = prepare()
    effective_config_sha256 = hashlib.sha256(config_path.read_bytes()).hexdigest()
    config = resolve_config_env_vars(load_config(config_path), config_path=config_path)
    if hashlib.sha256(config_path.read_bytes()).hexdigest() != effective_config_sha256:
        raise ValueError("应用启动期间配置发生变化")
    store = ControlStore(WORK / "business.sqlite")
    with store.connect() as db:
        existing = db.execute("SELECT snapshot FROM spaces WHERE namespace='ui-check'").fetchone()
    if existing is None:
        baseline = store.initialize("ui-check")
    else:
        baseline = {"namespace": "ui-check", "snapshot_sha256": existing[0]}
    output = ROOT.parent / "evidence/T02/application"
    output.mkdir(parents=True, exist_ok=True)
    provider = RecordedProvider(connection, output / "http-requests.json")
    provider.generation = config.resolve_preset().to_generation_settings()
    registry = ToolRegistry()
    events_path = output / "events.json"
    records, bindings = json.loads(events_path.read_text()) if events_path.exists() else [], {}
    audit = Audit(output / "events.json", records)
    audit.registry = registry
    bus = MessageBus()
    sessions = SessionManager(config.workspace_path)
    recovery = RecoveryCoordinator(sessions=sessions, bus=bus, unified_session=False)
    delivery = TurnDeliveryFactory(bus, route_policy=WebuiTurnRoutePolicy(sessions))
    loop = AgentLoop.from_config(config, bus, provider=provider, tool_registry=registry, hooks=[audit], session_manager=sessions, turn_delivery_factory=delivery, recovery_admission=recovery)
    audit.runtime_snapshot = lambda: {"provider": "deepseek", "model_id": loop.model, "max_tool_rounds": loop.max_iterations, "max_output_tokens": config.agents.defaults.max_tokens, "config_sha256": effective_config_sha256}
    coordinator = WebuiTurnCoordinator(bus=bus, sessions=sessions, schedule_background=loop.schedule_background, recovery=recovery)
    unsubscribe = coordinator.subscribe()
    for name in list(registry.tool_names):
        registry.unregister(name)
    envelope = {"request_id": "ui-check", "owner_id": "boss-1", "execution_namespace": "ui-check", "dataset_id": "selection", "dataset_version": "1", "session_id": "ui-check"}
    for operation in OPERATIONS:
        registry.register(ApplicationTool(operation, store, envelope, bindings, records))
    cron = CronService(WORK / "cron/jobs.json")
    async def scheduled(job):
        if job.name == "boss-events":
            return encode(store.dispatch_due("ui-check"))
        return await run_bound_cron_job(job, agent=loop, cron=cron)
    cron.on_job = scheduled
    channels = ChannelManager(config, loop.bus, session_manager=loop.sessions, cron_service=cron, webui_runtime_model_name=lambda: loop.model, webui_refresh_runtime_config=loop.refresh_runtime_config, webui_recovery_action=recovery.handle_action, config_path=config_path)
    original = channels.channels["websocket"]
    # Product v6 frontend only when explicitly requested; preserve T02 baseline.
    if os.environ.get("BOSS_PRODUCT_UI") == "1":
        frontend = ROOT.parent / ".work/product/nanobot/nanobot/web/dist"
    else:
        frontend = ROOT / ".work/upstream/nanobot-0.3.5/nanobot/web/dist"
    if not (frontend / "index.html").is_file():
        raise FileNotFoundError("固定上游 WebUI 必须完成构建")
    original.gateway.http.static_dist_path = frontend
    channels.channels["websocket"] = RoleChannel(original, roles, output / "access.jsonl", store)
    server = web.AppRunner(business_application(WORK / "business.sqlite"))
    await server.setup()
    await web.TCPSite(server, "127.0.0.1", 8871).start()
    stop = asyncio.Event()
    for signum in (signal.SIGTERM, signal.SIGINT):
        asyncio.get_running_loop().add_signal_handler(signum, stop.set)
    async with Nanobot(loop, config=config) as bot:
        async def context(request):
            current = store.context("ui-check")
            return RuntimeContextBlock(source="boss-confirmed-memory", content=encode({"memory": current["memory"], "runtime": audit.runtime_snapshot()}))
        bot.runtime.add_context_provider(context)
        await cron.start()
        if not any(job.name == "boss-events" for job in cron.list_jobs(include_disabled=True)):
            cron.add_job("boss-events", CronSchedule(kind="every", every_ms=500), "按当前业务时间检查获准事件", session_key="ui-check", origin_channel="websocket", origin_chat_id="ui-check")
        channel_task = asyncio.create_task(channels.start_all())
        agent_task = asyncio.create_task(loop.run())
        (WORK / "instance.json").write_text(encode({"pid": os.getpid(), "at": now(), "baseline": baseline, "max_tool_rounds": loop.max_iterations, "max_output_tokens": config.agents.defaults.max_tokens, "model": loop.model}))
        print("应用验证服务已启动", flush=True)
        await stop.wait()
        loop.stop()
        cron.stop()
        await channels.stop_all()
        await server.cleanup()
        await asyncio.gather(channel_task, agent_task)
        unsubscribe()


if __name__ == "__main__":
    WORK.mkdir(parents=True, exist_ok=True)
    with FileLock(str(WORK / "application.lock"), timeout=0):
        asyncio.run(serve())
