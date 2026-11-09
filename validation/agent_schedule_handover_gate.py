import hashlib
import os
from pathlib import Path

from aiohttp import web
from nanobot.cron.service import CronService

from agent_schedule_inspection import inspect_legacy_cron
from agent_schedule_stop_observation import AgentScheduleStopObservation, MIGRATION, VERSION
from boss_simulation_api import _context
from hermes_schedule_adapter import HermesScheduleAdapter
from role_channel import RoleChannel


class AgentScheduleHandoverGate:
    def __init__(self, observations, adapter):
        if not isinstance(observations, AgentScheduleStopObservation) or not isinstance(adapter, HermesScheduleAdapter) or observations.store.path.resolve() != adapter.store.path.resolve():
            raise ValueError("调度交接与计划数据库不匹配")
        self.observations = observations
        self.adapter = adapter
        self.store = adapter.store

    def require_activation(self, request, channel, cron, *, observation_key, owner, epoch, plan_id, plan_version, occurrence_at):
        if not isinstance(request, web.Request) or not isinstance(channel, RoleChannel) or not isinstance(cron, CronService) or channel.boss_commands is None or channel.boss_commands.store.path.resolve() != self.store.path.resolve():
            raise ValueError("需要同一环境的本人身份和调度服务")
        channel.require_run_api_role(request)
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self.observations.lease.require_current_in_transaction(db, owner, epoch)
            if db.execute("SELECT sha256 FROM agent_schema_migrations WHERE version=?", (VERSION,)).fetchone() != (hashlib.sha256(MIGRATION.read_bytes()).hexdigest(),):
                raise ValueError("调度停止观察迁移摘要不符")
            namespace = _context(db)["namespace"]
            evidence = db.execute("SELECT lease_owner,lease_epoch,observer_pid,cron_path,scope FROM agent_schedule_stop_observations WHERE namespace=? AND request_key=?", (namespace, observation_key)).fetchone()
            if evidence != (owner, epoch, os.getpid(), str(Path(cron.store_path).resolve()), "LOCAL_OBJECT_ONLY") or inspect_legacy_cron(cron)["local_state"] != "STOPPED":
                raise ValueError("本地调度停止状态不可核查")
            self.adapter.require_plan(plan_id, plan_version, occurrence_at, db=db)
            plan = self.store.get(db, namespace, "owner_plan", plan_id)
            channel.require_run_subscription(request, plan["conversation_id"])
            raise web.HTTPServiceUnavailable(text="旧调度全局停止及唯一执行条件尚未核查")
