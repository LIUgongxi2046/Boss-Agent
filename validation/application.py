import asyncio
import hashlib
import inspect
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
from nanobot.config.loader import load_config, resolve_config_env_vars, set_config_path
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
from boss_account_auth import AccountStore, account_channel_class
from safe_diagnostics import RedactedEventList
from boss_prompt_config import load_runtime_prompts
from boss_owner_preferences import record_runtime_goal_context_load
from boss_agent_read_tools import BossResearchSourcesTool
from boss_runtime_records import RuntimeRecorder
from boss_memory_runtime import OwnerMemoryContext
from product_runtime import ProductRuntime
from boss_page_api import BossPageAPI
from product_read_tools import product_read_tools
from product_skills import ProductSkills
from product_fc01 import ProductFc01
from product_mvp import ProductMVP
from product_assignment import ProductAssignment, AssignmentReadTool
from product_reminders import ProductReminders
from fc07_agent import TOOLS as ASSIGNMENT_TOOLS
from product_bi import ProductBI, FeatureProvider, FeatureRecorder, FeatureToolRegistry, FeatureBusinessTool, BI_TOOLS
from product_morning import ProductMorning
from product_conversation import ProductConversation
from boss_conversation_attachments import ConversationAttachments
from nanobot.config.paths import get_media_dir
from fc03_agent.formal import FormalMorningTool, FORMAL_TOOLS
from sop_write_tools.fc01 import Fc01Tool, TOOLS as FC01_TOOLS
from sop_write_tools.fc01.runtime import Fc01RuntimeRecorder
from service import application as business_application
from application_paths import application_work_directory, application_ports, application_frontend_directory

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
    runtime_scope = WORK / "runtime-scope.json"
    if config.is_symlink() or runtime_scope.is_symlink():
        raise ValueError("应用配置与实例目录声明不能使用符号链接")
    if not config.exists():
        if runtime_scope.exists():
            raise ValueError("当前实例声明已经存在，应用配置缺少，需要明确恢复配置")
        runtime_scope.write_text(encode({"schema_version": 1, "configuration_path": str(config)}))
        runtime_scope.chmod(0o600)
        config.write_text(encode({
            "agents": {"defaults": {"workspace": str(WORK / "workspace"), "provider": "deepseek",
                "model": "deepseek-flash", "maxToolIterations": 12, "maxTokens": 4096,
                "timezone": "Asia/Shanghai", "timezoneMode": "manual", "dream": {"enabled": False},
                "idleCompactAfterMinutes": 0, "maxToolResultChars": 200000}},
            "providers": {"deepseek": {"apiKey": "${DEEPSEEK_API_KEY}", "apiBase": "https://api.deepseek.com",
                "extraBody": {"thinking": {"type": "disabled"}}}},
            "gateway": {"host": "127.0.0.1", "port": PORTS["gateway"], "heartbeat": {"enabled": False}},
            "channels": {"websocket": {"enabled": True, "host": "127.0.0.1", "port": PORTS["webui"],
                "tokenIssueSecret": "${NANOBOT_WEBUI_SECRET}", "websocketRequiresToken": True,
                "showReasoning": False, "tokenTtlS": 3600}},
            "tools": {"restrictToWorkspace": True}, "transcription": {"enabled": False},
        }))
    if runtime_scope.exists():
        if json.loads(runtime_scope.read_text()) != {"schema_version": 1, "configuration_path": str(config)}:
            raise ValueError("实例目录声明与当前应用配置不符")
        set_config_path(config)
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
    product_mode = os.environ.get("BOSS_PRODUCT_UI") == "1"
    if os.environ.get("BOSS_EXECUTION_SCOPE") not in (None, "BOSS-MVP-1", "BOSS-PRIORITY-ITERATION"):
        raise ValueError("当前执行范围配置无效")
    mvp_mode = product_mode and os.environ.get("BOSS_EXECUTION_SCOPE") in {"BOSS-MVP-1", "BOSS-PRIORITY-ITERATION"}
    account_store = AccountStore(WORK / "accounts/accounts.sqlite") if product_mode else None
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
    output = WORK / "diagnostics" if product_mode else ROOT.parent / "evidence/T02/application"
    output.mkdir(parents=True, exist_ok=True, mode=0o700 if product_mode else 0o755)
    if product_mode:
        output.chmod(0o700)
    fc01 = (ProductMVP(store) if mvp_mode else ProductFc01(store)) if product_mode else None
    bi = ProductBI(store) if product_mode else None
    morning = ProductMorning(store) if product_mode else None
    assignment = ProductAssignment(store) if product_mode else None
    reminders = ProductReminders(store) if product_mode else None
    provider = FeatureProvider(fc01, bi, morning, assignment, reminders) if product_mode else RecordedProvider(connection, output / "http-requests.json", redact_payload=False)
    provider.generation = config.resolve_preset().to_generation_settings()
    registry = FeatureToolRegistry() if product_mode else ToolRegistry()
    runtime_recorder = FeatureRecorder(store, registry, lambda: runtime_control.snapshot(), bi, morning, assignment, reminders) if product_mode else None
    events_path = output / "events.json"
    records, bindings = json.loads(events_path.read_text()) if events_path.exists() else [], {}
    if product_mode:
        records = RedactedEventList(records)
    audit = Audit(output / "events.json", records)
    audit.registry = registry
    bus = MessageBus()
    sessions = SessionManager(config.workspace_path)
    conversation = ProductConversation(store, registry, lambda: runtime_control.snapshot(), ConversationAttachments(sessions, get_media_dir("websocket"))) if product_mode else None
    if conversation is not None:
        registry.conversation = conversation
        provider.conversation = conversation
        conversation.provider.generation = provider.generation
        runtime_recorder.conversation = conversation
    recovery = RecoveryCoordinator(sessions=sessions, bus=bus, unified_session=False)
    delivery = TurnDeliveryFactory(bus, route_policy=WebuiTurnRoutePolicy(sessions))
    loop = AgentLoop.from_config(config, bus, provider=provider, tool_registry=registry, hooks=[audit],
                                 hook_factories=[runtime_recorder.hook_factory, morning.native.hook_factory] if runtime_recorder is not None else [],
                                 session_manager=sessions, turn_delivery_factory=delivery, recovery_admission=recovery)
    audit.runtime_snapshot = lambda: {"provider": "deepseek", "model_id": loop.model, "max_tool_rounds": loop.max_iterations, "max_output_tokens": config.agents.defaults.max_tokens, "config_sha256": effective_config_sha256}
    coordinator = WebuiTurnCoordinator(bus=bus, sessions=sessions, schedule_background=loop.schedule_background, recovery=recovery)
    unsubscribe = coordinator.subscribe()
    for name in list(registry.tool_names):
        registry.unregister(name)
    envelope = {"request_id": "ui-check", "owner_id": "boss-1", "execution_namespace": "ui-check", "dataset_id": "selection", "dataset_version": "1", "session_id": "ui-check"}
    for operation in OPERATIONS:
        registry.register((FeatureBusinessTool(store, fc01, bi, operation) if operation in BI_TOOLS else Fc01Tool(store, fc01.context_provider, operation)) if product_mode else ApplicationTool(operation, store, envelope, bindings, records))
    def research_read_observed(metadata):
        records.append({"type": "tool", "name": "bossWorkspaceRead", "at": now(),
                        "output": {"source_type": "SIMULATED", "status": metadata["current_reference_state"]}})
        audit.output.write_text(encode(records))
    workspace_pages = BossPageAPI(store)
    if product_mode:
        for tool in product_read_tools(store, workspace_pages, research_read_observed):
            if tool.name not in FC01_TOOLS:
                registry.register(tool)
        for name in sorted(FC01_TOOLS - set(OPERATIONS)):
            registry.register(Fc01Tool(store, fc01.context_provider, name))
        for name in sorted(FORMAL_TOOLS):
            if name in registry.tool_names:
                registry.unregister(name)
            registry.register(FormalMorningTool(store, morning.context_provider, name))
        for name in sorted(ASSIGNMENT_TOOLS):
            if name not in registry.tool_names:
                raise ValueError("当前应用缺少正式交办读取工具：" + name)
            ordinary = registry.get(name)
            registry.unregister(name)
            registry.register(AssignmentReadTool(ordinary, assignment))
        registry.register(next(tool for tool in conversation.delegates if tool.name == "conversationRead"))
    else:
        registry.register(BossResearchSourcesTool(store, "BOSS", observation_sink=research_read_observed))
    runtime_control = None
    skills = None
    if product_mode:
        runtime_control = ProductRuntime(store, config_path, loop, registry,
                                         [registry.get(name) for name in registry.tool_names], provider, workspace_api=workspace_pages, workspace_tool_factory=reminders.workspace_tool)
        fc01.runtime = runtime_control
        bi.runtime = runtime_control
        morning.runtime = runtime_control
        assignment.runtime = runtime_control
        reminders.runtime = runtime_control
        audit.runtime_snapshot = runtime_control.snapshot
        skills = ProductSkills(runtime_control)
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
        frontend = application_frontend_directory(ROOT, os.environ.get("BOSS_PRODUCT_FRONTEND_DIR"))
    else:
        frontend = ROOT / ".work/upstream/nanobot-0.3.5/nanobot/web/dist"
    if not (frontend / "index.html").is_file():
        raise FileNotFoundError("固定上游 WebUI 必须完成构建")
    original.gateway.http.static_dist_path = frontend
    if skills is not None:
        def apply_skill_state(disabled):
            loop.context.skills.disabled_skills = set(disabled)
            loop.subagents.disabled_skills = set(disabled)
        original.gateway.http.skill_state_action = apply_skill_state
    if product_mode:
        channels.channels["websocket"] = account_channel_class(RoleChannel)(original, roles, output / "access.jsonl", store,
            runtime_control, skills, account_store=account_store)
    else:
        channels.channels["websocket"] = RoleChannel(original, roles, output / "access.jsonl", store, runtime_control, skills)
    if fc01 is not None:
        channels.channels["websocket"].fc01 = fc01
        channels.channels["websocket"].bi = bi
        channels.channels["websocket"].morning = morning
        channels.channels["websocket"].mvp = fc01 if mvp_mode else None
        channels.channels["websocket"].assignment = assignment
        channels.channels["websocket"].reminders = reminders
        channels.channels["websocket"].native_conversation = conversation
    server = web.AppRunner(business_application(WORK / "business.sqlite"))
    await server.setup()
    await web.TCPSite(server, "127.0.0.1", PORTS["business"]).start()
    stop = asyncio.Event()
    for signum in (signal.SIGTERM, signal.SIGINT):
        asyncio.get_running_loop().add_signal_handler(signum, stop.set)
    async with Nanobot(loop, config=config) as bot:
        if fc01 is not None:
            fc01.bot = bot
            bi.bot = bot
            morning.bot = bot
            assignment.bot = bot
            reminders.bot = bot
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
            def guarded(provider):
                guarded_provider = morning.guard_context(conversation.guard_context(provider))
                name = provider.__qualname__ if inspect.isfunction(provider) or inspect.ismethod(provider) else type(provider).__qualname__
                async def prepare(request):
                    ready = False
                    try:
                        result = await guarded_provider(request)
                        ready = True
                        return result
                    finally:
                        if not ready:
                            records.append({"type": "context_preparation_error", "name": name, "at": now()})
                            audit.output.write_text(encode(records))
                return prepare
            bot.runtime.add_context_provider(morning.native.native_context)
            bot.runtime.add_context_provider(guarded(conversation.native_context))
            bot.runtime.add_context_provider(guarded(runtime_control.context))
            bot.runtime.add_context_provider(guarded(skills.context))
            bot.runtime.add_context_provider(guarded(OwnerMemoryContext(store)))
            bot.runtime.add_context_provider(guarded(owner_goals_context))
            if mvp_mode:
                bot.runtime.add_context_provider(guarded(fc01.scope_context))
            bot.runtime.add_context_provider(guarded(bi.scope_context))
            bot.runtime.add_context_provider(guarded(morning.scope_context))
            bot.runtime.add_context_provider(guarded(assignment.scope_context))
            bot.runtime.add_context_provider(guarded(reminders.scope_context))
            bot.runtime.add_context_provider(guarded(conversation.scope_context))
            bot.runtime.add_context_provider(guarded(runtime_recorder.context))
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
