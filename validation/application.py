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
from safe_diagnostics import RedactedEventList
from boss_prompt_config import load_runtime_prompts
from boss_owner_preferences import record_runtime_goal_context_load
from boss_agent_read_tools import BossResearchSourcesTool
from boss_runtime_records import RuntimeRecorder
from boss_memory_runtime import OwnerMemoryContext
from product_runtime import ProductRuntime
from runtime_owner_read_tools import BossTodayReadTool, BossOwnerPlansReadTool
from runtime_assignment_source_tool import BossAssignmentSourcesReadTool
from service import application as business_application
from application_paths import application_work_directory, application_ports

WORK = application_work_directory(ROOT, os.environ.get("BOSS_APPLICATION_WORK_DIR"))
PORTS = application_ports(os.environ.get("BOSS_APPLICATION_PORTS"))


def product_log_filter(record):
    exception = record["exception"]
    record["extra"]["exception_type"] = exception.type.__name__ if exception else "NONE"
    record["exception"] = None
    return True


class ApplicationTool(BusinessTool):
    async def execute(self, **kwargs):
        if self.operation in {"create_assignment", "send_assignment"}:
            with self.store.connect() as db:
                self.bindings[self.operation] = self.store.get(db, self.envelope["execution_namespace"], "authorization_binding", self.operation)
        return await super().execute(**kwargs)


def prepare():
    WORK.mkdir(parents=True, exist_ok=True)
    if os.environ.get("BOSS_PRODUCT_UI") == "1":
        WORK.chmod(0o700)
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
        config.write_text(encode({
            "agents": {"defaults": {"workspace": str(WORK / "workspace"), "provider": "deepseek",
                "model": "deepseek-flash", "maxToolIterations": 12, "maxTokens": 4096,
                "timezone": "Asia/Shanghai", "timezoneMode": "manual", "dream": {"enabled": False},
                "idleCompactAfterMinutes": 0}},
            "providers": {"deepseek": {"apiKey": "${DEEPSEEK_API_KEY}", "apiBase": "https://api.deepseek.com",
                "extraBody": {"thinking": {"type": "disabled"}}}},
            "gateway": {"host": "127.0.0.1", "port": PORTS["gateway"], "heartbeat": {"enabled": False}},
            "channels": {"websocket": {"enabled": True, "host": "127.0.0.1", "port": PORTS["webui"],
                "tokenIssueSecret": "${NANOBOT_WEBUI_SECRET}", "websocketRequiresToken": True,
                "showReasoning": False, "tokenTtlS": 3600}},
            "tools": {"restrictToWorkspace": True}, "transcription": {"enabled": False},
        }))
    return roles, config


async def serve():
    logger.remove()
    if os.environ.get("BOSS_PRODUCT_UI") == "1":
        logger.add(sys.stderr, level="INFO", diagnose=False, backtrace=False,
                   format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level} | {name}:{function}:{line} | {extra[exception_type]}",
                   filter=product_log_filter)
    else:
        logger.add(sys.stderr, level="INFO", diagnose=False, backtrace=False)
    connection = settings()
    roles, config_path = prepare()
    effective_config_sha256 = hashlib.sha256(config_path.read_bytes()).hexdigest()
    config = resolve_config_env_vars(load_config(config_path), config_path=config_path)
    if config.gateway.port != PORTS["gateway"] or config.channels.websocket["port"] != PORTS["webui"]:
        raise ValueError("已保存配置与当前指定端口不一致")
    if hashlib.sha256(config_path.read_bytes()).hexdigest() != effective_config_sha256:
        raise ValueError("应用启动期间配置发生变化")
    store = ControlStore(WORK / "business.sqlite")
    with store.connect() as db:
        existing = db.execute("SELECT snapshot FROM spaces WHERE namespace='ui-check'").fetchone()
    if existing is None:
        baseline = store.initialize("ui-check")
    else:
        baseline = {"namespace": "ui-check", "snapshot_sha256": existing[0]}
    product_mode = os.environ.get("BOSS_PRODUCT_UI") == "1"
    output = WORK / "diagnostics" if product_mode else ROOT.parent / "evidence/T02/application"
    output.mkdir(parents=True, exist_ok=True, mode=0o700 if product_mode else 0o755)
    if product_mode:
        output.chmod(0o700)
    provider = RecordedProvider(connection, output / "http-requests.json", redact_payload=product_mode)
    provider.generation = config.resolve_preset().to_generation_settings()
    registry = ToolRegistry()
    runtime_recorder = RuntimeRecorder(store, "ui-check", registry, lambda: runtime_control.snapshot()) if product_mode else None
    events_path = output / "events.json"
    records, bindings = json.loads(events_path.read_text()) if events_path.exists() else [], {}
    if product_mode:
        records = RedactedEventList(records)
    audit = Audit(output / "events.json", records)
    audit.registry = registry
    bus = MessageBus()
    sessions = SessionManager(config.workspace_path)
    recovery = RecoveryCoordinator(sessions=sessions, bus=bus, unified_session=False)
    delivery = TurnDeliveryFactory(bus, route_policy=WebuiTurnRoutePolicy(sessions))
    loop = AgentLoop.from_config(config, bus, provider=provider, tool_registry=registry, hooks=[audit],
                                 hook_factories=[runtime_recorder.hook_factory] if runtime_recorder is not None else [],
                                 session_manager=sessions, turn_delivery_factory=delivery, recovery_admission=recovery)
    audit.runtime_snapshot = lambda: {"provider": "deepseek", "model_id": loop.model, "max_tool_rounds": loop.max_iterations, "max_output_tokens": config.agents.defaults.max_tokens, "config_sha256": effective_config_sha256}
    coordinator = WebuiTurnCoordinator(bus=bus, sessions=sessions, schedule_background=loop.schedule_background, recovery=recovery)
    unsubscribe = coordinator.subscribe()
    for name in list(registry.tool_names):
        registry.unregister(name)
    envelope = {"request_id": "ui-check", "owner_id": "boss-1", "execution_namespace": "ui-check", "dataset_id": "selection", "dataset_version": "1", "session_id": "ui-check"}
    for operation in OPERATIONS:
        registry.register(ApplicationTool(operation, store, envelope, bindings, records))
    def research_read_observed(metadata):
        records.append({"type": "tool", "name": "bossWorkspaceRead", "at": now(),
                        "output": {"source_type": "SIMULATED", "status": metadata["current_reference_state"]}})
        audit.output.write_text(encode(records))
    registry.register(BossResearchSourcesTool(store, "BOSS", observation_sink=research_read_observed))
    if product_mode:
        for tool in (BossTodayReadTool(store, "BOSS"), BossOwnerPlansReadTool(store, "BOSS"),
                     BossAssignmentSourcesReadTool(store, "BOSS")):
            registry.register(tool)
    runtime_control = None
    if product_mode:
        runtime_control = ProductRuntime(store, config_path, loop, registry,
                                         [registry.get(name) for name in registry.tool_names], provider)
        provider.transport_observer = runtime_recorder.observe_transport
        audit.runtime_snapshot = runtime_control.snapshot
    cron = CronService(WORK / "cron/jobs.json")
    async def scheduled(job):
        if job.name == "boss-events":
            return encode(store.dispatch_due("ui-check"))
        return await run_bound_cron_job(job, agent=loop, cron=cron)
    cron.on_job = scheduled
    channels = ChannelManager(config, loop.bus, session_manager=loop.sessions, cron_service=cron,
                              webui_runtime_model_name=lambda: loop.model,
                              webui_refresh_runtime_config=runtime_control.native_refresh_requested if runtime_control is not None else loop.refresh_runtime_config,
                              webui_recovery_action=recovery.handle_action, config_path=config_path)
    original = channels.channels["websocket"]
    # Product v6 frontend only when explicitly requested; preserve T02 baseline.
    if os.environ.get("BOSS_PRODUCT_UI") == "1":
        frontend = ROOT.parent / ".work/product/nanobot/nanobot/web/dist"
    else:
        frontend = ROOT / ".work/upstream/nanobot-0.3.5/nanobot/web/dist"
    if not (frontend / "index.html").is_file():
        raise FileNotFoundError("固定上游 WebUI 必须完成构建")
    original.gateway.http.static_dist_path = frontend
    channels.channels["websocket"] = RoleChannel(original, roles, output / "access.jsonl", store, runtime_control)
    server = web.AppRunner(business_application(WORK / "business.sqlite"))
    await server.setup()
    await web.TCPSite(server, "127.0.0.1", PORTS["business"]).start()
    stop = asyncio.Event()
    for signum in (signal.SIGTERM, signal.SIGINT):
        asyncio.get_running_loop().add_signal_handler(signum, stop.set)
    async with Nanobot(loop, config=config) as bot:
        async def context(request):
            current = store.context("ui-check")
            selected_prompts = load_runtime_prompts(store, "ui-check")
            confirmed_owner_goals = record_runtime_goal_context_load(store, "ui-check")
            return RuntimeContextBlock(
                source="boss-confirmed-memory",
                content=encode({
                    "memory": current["memory"],
                    "confirmed_owner_goals": confirmed_owner_goals,
                    "maintained_prompts": selected_prompts,
                    "guidance_authority_boundary":
                        "Technical prompts do not grant BOSS rights, modify "
                        "tool permissions, authorize sends, or override source access.",
                    "runtime": audit.runtime_snapshot(),
                }),
            )
        if runtime_control is not None:
            async def owner_goals_context(request):
                return RuntimeContextBlock(source="boss-confirmed-owner-goals", content=encode({
                    "confirmed_owner_goals": record_runtime_goal_context_load(store, "ui-check"),
                    "guidance_authority_boundary": "Technical prompts do not grant BOSS rights or authorize business writes.",
                }))
            bot.runtime.add_context_provider(runtime_control.context)
            bot.runtime.add_context_provider(OwnerMemoryContext(store))
            bot.runtime.add_context_provider(owner_goals_context)
            bot.runtime.add_context_provider(runtime_recorder.context)
        else:
            bot.runtime.add_context_provider(context)
        await cron.start()
        if not any(job.name == "boss-events" for job in cron.list_jobs(include_disabled=True)):
            cron.add_job("boss-events", CronSchedule(kind="every", every_ms=500), "按当前业务时间检查获准事件", session_key="ui-check", origin_channel="websocket", origin_chat_id="ui-check")
        channel_task = asyncio.create_task(channels.start_all())
        agent_task = asyncio.create_task(loop.run())
        (WORK / "instance.json").write_text(encode({"pid": os.getpid(), "at": now(), "ports": PORTS, "baseline": baseline, "max_tool_rounds": loop.max_iterations, "max_output_tokens": config.agents.defaults.max_tokens, "model": loop.model}))
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
