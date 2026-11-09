import hashlib
import json
from contextlib import nullcontext
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5
from zoneinfo import ZoneInfo

from aiohttp import web
from croniter import croniter

from agent_run_api import VALIDATORS as RUN_VALIDATORS
from agent_run_broker import RunBroker, RunIdentity
from agent_run_scope import RunScopeService
from boss_execution_transition import pending_transition
from boss_scheduler_config import plan_fields
from boss_simulation_api import _context
from business import checksum
from controls import ControlStore
from boss_owner_plans import plan_authorization_status, stop_business_until, valid_plan_budget, valid_plan_execution_choices
from role_channel import RoleChannel
from filelock import FileLock


MIGRATION_PATH = Path(__file__).parent / "migrations" / "hermes_schedule_001.sql"
MIGRATION_VERSION = "hermes_schedule_001"
PREVIEW_MIGRATION_PATH = Path(__file__).parent / "migrations" / "hermes_schedule_002.sql"
PREVIEW_MIGRATION_VERSION = "hermes_schedule_002"
RUN_BUDGET_MIGRATION_PATH = Path(__file__).parent / "migrations" / "hermes_schedule_003.sql"
RUN_BUDGET_MIGRATION_VERSION = "hermes_schedule_003"


class ScheduleTriggerUnavailable(RuntimeError):
    pass


def aware_instant(value):
    if not isinstance(value, str):
        raise ValueError("发生时间无效")
    instant = datetime.fromisoformat(value)
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError("发生时间必须包含时区")
    return instant.astimezone(timezone.utc)


def stable_occurrence_id(namespace, dataset_id, dataset_version, plan_id, plan_version, occurrence_at):
    values = (namespace, dataset_id, dataset_version, plan_id, plan_version)
    if any(not isinstance(value, str) or not value.strip() for value in values):
        raise ValueError("计划发生编号参数无效")
    instant = aware_instant(occurrence_at).isoformat()
    encoded = json.dumps(["boss-agent-plan-occurrence-v1", *values, instant], ensure_ascii=False, separators=(",", ":"))
    return str(uuid5(NAMESPACE_URL, encoded))


class HermesScheduleAdapter:
    def __init__(self, store):
        if not isinstance(store, ControlStore):
            raise ValueError("需要产品计划存储")
        self.store = store

    def claim_run_occurrence_in_transaction(self, gate, db, plan_id, plan_version, occurrence_at, occurrence_id):
        from agent_schedule_occurrence_gate import AgentScheduleOccurrenceGate
        if not isinstance(gate, AgentScheduleOccurrenceGate) or gate.store.path.resolve() != self.store.path.resolve():
            raise ValueError("计划发生门禁与运行数据库不一致")
        claim = gate.claim_in_transaction(db, plan_id, plan_version, occurrence_at)
        if claim["occurrence_id"] != occurrence_id:
            raise ValueError("计划发生编号不一致")
        old = db.execute("SELECT run_id FROM hermes_schedule_run_links WHERE occurrence_id=?", (occurrence_id,)).fetchone()
        if claim["claimed"] != (old is None):
            raise ValueError("计划发生领取与运行关联不一致")
        return old

    def install_schema(self):
        source = MIGRATION_PATH.read_bytes()
        digest = hashlib.sha256(source).hexdigest()
        extra = PREVIEW_MIGRATION_PATH.read_bytes()
        extra_digest = hashlib.sha256(extra).hexdigest()
        with FileLock(str(self.store.path) + ".schedule-migration.lock", timeout=10), self.store.connect() as db:
            exists = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='hermes_schedule_migrations'").fetchone()
            if exists:
                row = db.execute("SELECT sha256 FROM hermes_schedule_migrations WHERE version=?", (MIGRATION_VERSION,)).fetchone()
                if row is None or row[0] != digest:
                    raise ValueError("计划迁移摘要不可核查")
            else:
                if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name IN ('hermes_schedule_observations','hermes_schedule_plan_candidates')").fetchone() is not None:
                    raise ValueError("计划迁移状态不可核查")
                db.executescript("BEGIN IMMEDIATE;\n" + source.decode("utf-8"))
                db.execute("INSERT INTO hermes_schedule_migrations VALUES (?,?)", (MIGRATION_VERSION, digest))
                db.commit()
            row = db.execute("SELECT sha256 FROM hermes_schedule_migrations WHERE version=?", (PREVIEW_MIGRATION_VERSION,)).fetchone()
            if row is not None:
                if row[0] != extra_digest:
                    raise ValueError("计划预览迁移摘要不可核查")
            else:
                if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='hermes_schedule_previews'").fetchone() is not None:
                    raise ValueError("计划预览迁移状态不可核查")
                db.executescript("BEGIN IMMEDIATE;\n" + extra.decode("utf-8"))
                db.execute("INSERT INTO hermes_schedule_migrations VALUES (?,?)", (PREVIEW_MIGRATION_VERSION, extra_digest))
                db.commit()
            budget_source = RUN_BUDGET_MIGRATION_PATH.read_bytes()
            budget_digest = hashlib.sha256(budget_source).hexdigest()
            row = db.execute("SELECT sha256 FROM hermes_schedule_migrations WHERE version=?", (RUN_BUDGET_MIGRATION_VERSION,)).fetchone()
            if row is not None:
                if row[0] != budget_digest:
                    raise ValueError("计划运行预算迁移摘要不可核查")
                return
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='hermes_schedule_run_budgets'").fetchone() is not None:
                raise ValueError("计划运行预算迁移状态不可核查")
            db.executescript("BEGIN IMMEDIATE;\n" + budget_source.decode("utf-8"))
            db.execute("INSERT INTO hermes_schedule_migrations VALUES (?,?)", (RUN_BUDGET_MIGRATION_VERSION, budget_digest))

    @staticmethod
    def _require_schema(db):
        for version, path in ((MIGRATION_VERSION, MIGRATION_PATH), (PREVIEW_MIGRATION_VERSION, PREVIEW_MIGRATION_PATH), (RUN_BUDGET_MIGRATION_VERSION, RUN_BUDGET_MIGRATION_PATH)):
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            row = db.execute("SELECT sha256 FROM hermes_schedule_migrations WHERE version=?", (version,)).fetchone()
            if row is None or row[0] != digest:
                raise ValueError("计划迁移摘要不可核查")

    def _schedule(self, db, expected_version):
        context = _context(db)
        if pending_transition(db, context["namespace"]) is not None:
            raise ValueError("执行空间正在切换")
        schedule = self.store.get(db, context["namespace"], "schedule", "current")
        if schedule["version"] != expected_version or not schedule["enabled"] or schedule["canceled"] or schedule["trigger"] not in {"CRON", "EVENT_OR_TIME"}:
            raise ValueError("调度配置版本或状态不可用")
        settings = plan_fields(schedule)
        if schedule["timezone"] != context["timezone"] or not croniter.is_valid(settings["expression"]):
            raise ValueError("调度时区或表达式不可核查")
        ZoneInfo(schedule["timezone"])
        if not isinstance(schedule["schedule_version"], str) or not schedule["schedule_version"].isdecimal():
            raise ValueError("调度版本无效")
        return context, schedule, settings

    def observe(self, expected_version, occurrence_at):
        instant = aware_instant(occurrence_at)
        if instant.second or instant.microsecond:
            raise ValueError("发生时间必须为完整分钟")
        canonical = instant.isoformat()
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._require_schema(db)
            context, schedule, settings = self._schedule(db, expected_version)
            business_time = aware_instant(context["clock"])
            local = instant.astimezone(ZoneInfo(schedule["timezone"]))
            if instant > business_time or not croniter.match(settings["expression"], local.replace(tzinfo=None)):
                raise ValueError("发生时间未到或不符合调度表达式")
            key = (context["namespace"], context["dataset_id"], context["dataset_version"], schedule["schedule_id"], schedule["schedule_version"], canonical)
            old = db.execute("SELECT configuration_version,timezone,expression,business_time,observed_at,status FROM hermes_schedule_observations WHERE namespace=? AND dataset_id=? AND dataset_version=? AND schedule_id=? AND schedule_version=? AND occurrence_at=?", key).fetchone()
            if old is not None:
                if old[:3] != (schedule["version"], schedule["timezone"], settings["expression"]):
                    raise ValueError("相同发生时间的调度内容已经变化")
                return {"schedule_id": schedule["schedule_id"], "schedule_version": schedule["schedule_version"], "occurrence_at": canonical, "business_time": old[3], "observed_at": old[4], "status": old[5]}
            observed_at = datetime.now(timezone.utc).isoformat()
            db.execute("INSERT INTO hermes_schedule_observations VALUES (?,?,?,?,?,?,?,?,?,?,?, 'CANDIDATE')", (*key[:5], schedule["version"], canonical, schedule["timezone"], settings["expression"], business_time.isoformat(), observed_at))
            return {"schedule_id": schedule["schedule_id"], "schedule_version": schedule["schedule_version"], "occurrence_at": canonical, "business_time": business_time.isoformat(), "observed_at": observed_at, "status": "CANDIDATE"}

    def plan_candidate(self, plan_id, expected_version, occurrence_at):
        if not isinstance(plan_id, str) or not plan_id.strip() or not isinstance(expected_version, str) or not expected_version.isdecimal():
            raise ValueError("本人计划参数无效")
        instant = aware_instant(occurrence_at)
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._require_schema(db)
            context = _context(db)
            current_schedule = self.store.get(db, context["namespace"], "schedule", "current")
            context, schedule, settings = self._schedule(db, current_schedule["version"])
            if "OWNER_PLANS" not in settings["authorized_scope"]:
                raise ValueError("当前调度范围不包含本人计划")
            key = (context["namespace"], context["dataset_id"], context["dataset_version"], schedule["schedule_id"], schedule["schedule_version"], instant.isoformat())
            observed = db.execute("SELECT configuration_version,timezone,expression,status FROM hermes_schedule_observations WHERE namespace=? AND dataset_id=? AND dataset_version=? AND schedule_id=? AND schedule_version=? AND occurrence_at=?", key).fetchone()
            if observed != (schedule["version"], schedule["timezone"], settings["expression"], "CANDIDATE"):
                raise ValueError("当前发生时间不可核查")
            plan = self.store.get(db, context["namespace"], "owner_plan", plan_id)
            if plan.get("plan_id") != plan_id or plan.get("version") != expected_version or plan.get("owner_id") != context["owner_id"] or plan.get("state") != "ACTIVE" or plan.get("source_type") != "SIMULATED" or plan.get("timezone") != context["timezone"]:
                raise ValueError("本人计划状态或版本不可用")
            if instant < aware_instant(plan["not_before"]) or instant > aware_instant(context["clock"]):
                raise ValueError("本人计划尚未到期")
            events, versions = plan.get("event_ids"), plan.get("event_versions")
            if not isinstance(events, list) or not events or len(set(events)) != len(events) or not isinstance(versions, dict) or set(events) != set(versions):
                raise ValueError("本人计划事件范围不可核查")
            for event_id in events:
                event = self.store.get(db, context["namespace"], "event", event_id)
                if event.get("owner_plan_id") != plan_id or event.get("state") == "CANCELED" or event.get("version") != versions[event_id]:
                    raise ValueError("本人计划事件已经变化")
            plan_digest = checksum(plan)
            candidate_key = (context["namespace"], context["dataset_id"], context["dataset_version"], plan_id, expected_version, instant.isoformat())
            occurrence_id = stable_occurrence_id(*candidate_key)
            old = db.execute("SELECT schedule_id,schedule_version,timezone,plan_sha256,occurrence_id,created_at,status FROM hermes_schedule_plan_candidates WHERE namespace=? AND dataset_id=? AND dataset_version=? AND plan_id=? AND plan_version=? AND occurrence_at=?", candidate_key).fetchone()
            if old is not None:
                if old[:5] != (schedule["schedule_id"], schedule["schedule_version"], plan["timezone"], plan_digest, occurrence_id):
                    raise ValueError("本人计划候选内容已经变化")
                return {"occurrence_id": occurrence_id, "plan_id": plan_id, "plan_version": expected_version, "occurrence_at": instant.isoformat(), "created_at": old[5], "status": old[6]}
            created_at = datetime.now(timezone.utc).isoformat()
            db.execute("INSERT INTO hermes_schedule_plan_candidates VALUES (?,?,?,?,?,?,?,?,?,?,?,?, 'CANDIDATE')", (*candidate_key, schedule["schedule_id"], schedule["schedule_version"], plan["timezone"], plan_digest, occurrence_id, created_at))
            return {"occurrence_id": occurrence_id, "plan_id": plan_id, "plan_version": expected_version, "occurrence_at": instant.isoformat(), "created_at": created_at, "status": "CANDIDATE"}

    def require_plan(self, plan_id, expected_version, occurrence_at, *, db=None):
        if not isinstance(plan_id, str) or not plan_id.strip() or not isinstance(expected_version, str):
            raise ValueError("本人计划参数无效")
        instant = aware_instant(occurrence_at)
        external = db is not None
        with (nullcontext(db) if external else self.store.connect()) as db:
            if external:
                main = db.execute("PRAGMA database_list").fetchone()
                if not db.in_transaction or main is None or main[1] != "main" or Path(main[2]).resolve() != self.store.path.resolve():
                    raise ValueError("计划检查需要同一数据库的事务")
            else:
                db.execute("BEGIN")
            self._require_schema(db)
            context = _context(db)
            if pending_transition(db, context["namespace"]) is not None:
                raise ValueError("执行空间正在切换")
            current_schedule = self.store.get(db, context["namespace"], "schedule", "current")
            context, schedule, settings = self._schedule(db, current_schedule["version"])
            if "OWNER_PLANS" not in settings["authorized_scope"]:
                raise ValueError("当前调度范围不包含本人计划")
            observed = db.execute("SELECT configuration_version,timezone,expression,status FROM hermes_schedule_observations WHERE namespace=? AND dataset_id=? AND dataset_version=? AND schedule_id=? AND schedule_version=? AND occurrence_at=?", (context["namespace"], context["dataset_id"], context["dataset_version"], schedule["schedule_id"], schedule["schedule_version"], instant.isoformat())).fetchone()
            if observed != (schedule["version"], schedule["timezone"], settings["expression"], "CANDIDATE"):
                raise ValueError("当前发生时间不可核查")
            plan = self.store.get(db, context["namespace"], "owner_plan", plan_id)
            if plan["plan_id"] != plan_id or plan["version"] != expected_version or plan["owner_id"] != context["owner_id"] or plan["state"] != "ACTIVE" or plan["source_type"] != "SIMULATED" or plan["timezone"] != context["timezone"]:
                raise ValueError("本人计划状态或版本不可用")
            if instant < aware_instant(plan["not_before"]) or instant > aware_instant(context["clock"]):
                raise ValueError("本人计划尚未到期")
            candidate_key = (context["namespace"], context["dataset_id"], context["dataset_version"], plan_id, expected_version, instant.isoformat())
            candidate = db.execute("SELECT schedule_id,schedule_version,timezone,plan_sha256,occurrence_id,status FROM hermes_schedule_plan_candidates WHERE namespace=? AND dataset_id=? AND dataset_version=? AND plan_id=? AND plan_version=? AND occurrence_at=?", candidate_key).fetchone()
            if candidate != (schedule["schedule_id"], schedule["schedule_version"], plan["timezone"], checksum(plan), stable_occurrence_id(*candidate_key), "CANDIDATE"):
                raise ValueError("本人计划候选不可核查")
            budget = plan.get("budget")
            if not valid_plan_budget(budget):
                raise ScheduleTriggerUnavailable("本人计划缺少有效运行预算")
            if not valid_plan_execution_choices(plan.get("required_outputs"), plan.get("method_selection")):
                raise ScheduleTriggerUnavailable("本人计划缺少已授权的成果要求或方法")
            until = stop_business_until(plan.get("stop_conditions"))
            if instant >= until or aware_instant(context["clock"]) >= until:
                raise ScheduleTriggerUnavailable("本人计划已到业务停止时间")
            status = plan_authorization_status(self.store, db, context["namespace"], plan, datetime.now(timezone.utc))
            if status is not None:
                raise ScheduleTriggerUnavailable(status)
            for event_id in plan["event_ids"]:
                event = self.store.get(db, context["namespace"], "event", event_id)
                if event.get("owner_plan_id") != plan_id or event.get("state") == "CANCELED" or event.get("version") != plan["event_versions"].get(event_id):
                    raise ValueError("本人计划事件已经变化")
                receipt_row = db.execute("SELECT body FROM objects WHERE namespace=? AND kind='notification' AND id=?", (context["namespace"], event_id + ":" + event["version"])).fetchone()
                if receipt_row is not None:
                    receipt = json.loads(receipt_row[0])
                    if receipt.get("event_id") != event_id or receipt.get("event_version") != event["version"] or receipt.get("state") != "DELIVERED" or receipt.get("source_type") != "SIMULATED":
                        raise ValueError("已有业务结果不可核查")
                    raise ScheduleTriggerUnavailable("该事件版本已有业务结果")
        raise ScheduleTriggerUnavailable("正式调度身份、隔离与唯一执行责任尚未完成验证")

    def require_available_concurrency(self, db, namespace, plan_id, occurrence_id, limit):
        if not db.in_transaction or type(limit) is not int or limit <= 0 or any(
                not isinstance(value, str) or not value for value in (namespace, plan_id, occurrence_id)):
            raise ValueError("计划并发检查参数无效")
        main = db.execute("PRAGMA database_list").fetchone()
        if main is None or main[1] != "main" or Path(main[2]).resolve() != self.store.path.resolve():
            raise ValueError("计划并发检查需要同一数据库的事务")
        db.execute("UPDATE agent_runs SET revision=revision WHERE 0")
        count = db.execute("SELECT count(*) FROM hermes_schedule_plan_candidates c JOIN hermes_schedule_run_links l ON l.occurrence_id=c.occurrence_id JOIN agent_runs r ON r.run_id=l.run_id WHERE c.namespace=? AND c.plan_id=? AND c.occurrence_id<>? AND r.status NOT IN ('SUCCEEDED','FAILED','CANCELED')", (namespace, plan_id, occurrence_id)).fetchone()[0]
        if count >= limit:
            raise ScheduleTriggerUnavailable("本人计划并发额度不足")

    def create_scheduled_run(self, request, channel, broker, plan_id, expected_version, occurrence_at):
        if not isinstance(request, web.Request) or not isinstance(channel, RoleChannel) or not isinstance(broker, RunBroker):
            raise ValueError("需要实际产品请求、身份和运行服务")
        channel.require_run_api_role(request)
        if channel.boss_commands is None or channel.boss_commands.store.path.resolve() != self.store.path.resolve() or broker.store.path.resolve() != self.store.path.resolve():
            raise ValueError("身份、计划和运行服务不属于同一数据库")
        if not isinstance(broker.scope_service, RunScopeService) or channel.gateway.session_manager is not broker.scope_service.sources.sessions:
            raise ValueError("运行缺少同一环境的会话范围服务")
        from agent_schedule_occurrence_gate import AgentScheduleOccurrenceGate
        gate = AgentScheduleOccurrenceGate(self.store)
        instant = aware_instant(occurrence_at)
        selection = broker.method_selection
        if selection is None:
            raise ScheduleTriggerUnavailable("计划方法服务尚未准备")
        with selection.drafts._locked(), self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._require_schema(db)
            self.require_plan(plan_id, expected_version, instant.isoformat(), db=db)
            context = _context(db)
            plan = self.store.get(db, context["namespace"], "owner_plan", plan_id)
            candidate_key = (context["namespace"], context["dataset_id"], context["dataset_version"], plan_id, expected_version, instant.isoformat())
            occurrence_id = stable_occurrence_id(*candidate_key)
            self.require_available_concurrency(db, context["namespace"], plan_id, occurrence_id, plan["budget"]["concurrency"])
            candidate = db.execute("SELECT plan_sha256,occurrence_id,status FROM hermes_schedule_plan_candidates WHERE namespace=? AND dataset_id=? AND dataset_version=? AND plan_id=? AND plan_version=? AND occurrence_at=?", candidate_key).fetchone()
            if candidate != (checksum(plan), occurrence_id, "CANDIDATE"):
                raise ValueError("本人计划候选不可核查")
            chat_id, refs = plan["conversation_id"], plan["source_refs"]
            channel.require_run_subscription(request, chat_id)
            proof = broker.scope_service.prove_in_transaction(db, chat_id, refs)
            if (proof.owner_id, proof.namespace, proof.dataset_id, proof.dataset_version) != (context["owner_id"], context["namespace"], context["dataset_id"], context["dataset_version"]):
                raise ValueError("本人计划运行范围不可核查")
            if json.loads(json.dumps(asdict(proof), ensure_ascii=False)) != plan["scope_proof"]:
                raise ValueError("本人计划会话或来源已经变化")
            payload = {"conversation_id": chat_id, "goal": plan["purpose"], "selected_refs": refs, "request_key": occurrence_id,
                       "required_outputs": plan["required_outputs"], "method_selection": plan["method_selection"]}
            RUN_VALIDATORS["create"].validate(payload)
            method = selection._current_method(db, plan["method_selection"])
            identity = RunIdentity(proof.owner_id, proof.namespace, "BOSS", frozenset({chat_id}), frozenset(refs), verify=lambda: channel.require_run_subscription(request, chat_id))
            old = self.claim_run_occurrence_in_transaction(gate, db, plan_id, expected_version, instant.isoformat(), occurrence_id)
            receipt = broker._create_in_transaction(db, identity, payload, request=request)
            run = db.execute("SELECT goal,scope_proof FROM agent_runs WHERE run_id=?", (receipt["run_id"],)).fetchone()
            if run is None or run[1] is None:
                raise ValueError("计划运行目标或来源不可核查")
            method_json = json.dumps(method, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            record = (receipt["run_id"], 1, method_json, checksum(method), checksum(run[0]), checksum(json.loads(run[1])))
            saved = db.execute("SELECT run_id,goal_revision,method,method_sha256,goal_sha256,scope_sha256 FROM agent_run_method_selections WHERE run_id=?", (receipt["run_id"],)).fetchone()
            if saved is None:
                if old is not None:
                    raise ValueError("原计划运行缺少方法选择")
                db.execute("INSERT INTO agent_run_method_selections VALUES (?,?,?,?,?,?)", record)
            elif saved != record:
                raise ValueError("原计划运行方法选择已经变化")
            from agent_run_requirements import RunRequirements
            requirements = RunRequirements.read_in_transaction(db, receipt["run_id"], 1)
            if requirements["state"] != "CONFIRMED" or requirements["required_outputs"] != plan["required_outputs"]:
                raise ValueError("原计划运行成果要求已经变化")
            if old is not None and old[0] != receipt["run_id"]:
                raise ValueError("计划发生对应的运行已经变化")
            if old is None:
                db.execute("INSERT INTO hermes_schedule_run_links VALUES (?,?,?)", (occurrence_id, receipt["run_id"], datetime.now(timezone.utc).isoformat()))
            budget_json = json.dumps(plan["budget"], ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
            budget_record = (plan_id, expected_version, plan["authorization_id"], budget_json, checksum(plan["budget"]))
            saved_budget = db.execute("SELECT plan_id,plan_version,authorization_id,budget,budget_sha256 FROM hermes_schedule_run_budgets WHERE occurrence_id=?", (occurrence_id,)).fetchone()
            if saved_budget is None:
                if old is not None:
                    raise ValueError("原计划运行缺少授权预算")
                db.execute("INSERT INTO hermes_schedule_run_budgets VALUES (?,?,?,?,?,?)", (occurrence_id, *budget_record))
            elif saved_budget != budget_record:
                raise ValueError("计划运行授权预算已经变化")
            channel.require_run_subscription(request, chat_id)
            return {"occurrence_id": occurrence_id, "run": receipt}

    def dispatch_scheduled_event(self, request, channel, scope_service, plan_id, expected_version, occurrence_at, event_id):
        if not isinstance(request, web.Request) or not isinstance(channel, RoleChannel) or not isinstance(scope_service, RunScopeService):
            raise ValueError("需要实际产品请求、身份和会话范围服务")
        channel.require_run_api_role(request)
        if channel.boss_commands is None or channel.boss_commands.store.path.resolve() != self.store.path.resolve() or scope_service.store.path.resolve() != self.store.path.resolve() or channel.gateway.session_manager is not scope_service.sources.sessions:
            raise ValueError("身份、计划和会话服务不属于同一环境")
        if not isinstance(event_id, str) or not event_id.strip():
            raise ValueError("事件编号无效")
        instant = aware_instant(occurrence_at)
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._require_schema(db)
            self.require_plan(plan_id, expected_version, instant.isoformat(), db=db)
            context = _context(db)
            plan = self.store.get(db, context["namespace"], "owner_plan", plan_id)
            if event_id not in plan["event_ids"]:
                raise ValueError("事件不属于本人计划")
            event = self.store.get(db, context["namespace"], "event", event_id)
            if event.get("generated_by") == "BUSINESS_ALERT_INPUT":
                raise ScheduleTriggerUnavailable("经营提醒需要专属的权威回执")
            candidate_key = (context["namespace"], context["dataset_id"], context["dataset_version"], plan_id, expected_version, instant.isoformat())
            occurrence_id = stable_occurrence_id(*candidate_key)
            chat_id, refs = plan["conversation_id"], plan["source_refs"]
            channel.require_run_subscription(request, chat_id)
            proof = scope_service.prove_in_transaction(db, chat_id, refs)
            if json.loads(json.dumps(asdict(proof), ensure_ascii=False)) != plan["scope_proof"]:
                raise ValueError("本人计划会话或来源已经变化")
            link = db.execute("SELECT run_id FROM hermes_schedule_run_links WHERE occurrence_id=?", (occurrence_id,)).fetchone()
            if link is None:
                raise ValueError("计划发生缺少运行关联")
            run = db.execute("SELECT actor_id,space_id,conversation_id,goal,selected_refs,scope_proof,status,cancel_requested_at FROM agent_runs WHERE run_id=?", (link[0],)).fetchone()
            if run is None or run[:4] != (context["owner_id"], context["namespace"], chat_id, plan["purpose"]) or json.loads(run[4]) != refs or json.loads(run[5]) != plan["scope_proof"] or run[6:] != ("SUCCEEDED", None):
                raise ValueError("计划运行结果不可核查")
            existing = db.execute("SELECT dispatch_id,status FROM hermes_schedule_notification_links WHERE occurrence_id=? AND event_id=? AND event_version=?", (occurrence_id, event_id, event["version"])).fetchone()
            if existing is not None:
                raise ScheduleTriggerUnavailable("该计划发生已有原业务回执")
            outcomes = self.store.dispatch_due_in_transaction(db, context["namespace"], only_event_id=event_id)
            if len(outcomes) != 1 or outcomes[0].get("event_id") != event_id or outcomes[0].get("event_version") != event["version"] or outcomes[0].get("owner_plan_id") != plan_id or outcomes[0].get("state") not in {"DELIVERED", "SUPPRESSED"}:
                raise ValueError("计划业务回执不可核查")
            result = outcomes[0]
            dispatch_id = checksum(result)
            history = self.store.get(db, context["namespace"], "dispatch_history", dispatch_id)
            original = {key: value for key, value in history.items() if key not in {"dispatch_id", "recorded_at"}}
            if original != result or history.get("dispatch_id") != dispatch_id:
                raise ValueError("计划业务回执内容不符")
            db.execute("INSERT INTO hermes_schedule_notification_links VALUES (?,?,?,?,?)", (occurrence_id, event_id, event["version"], dispatch_id, result["state"]))
            channel.require_run_subscription(request, chat_id)
            if json.loads(json.dumps(asdict(scope_service.prove_in_transaction(db, chat_id, refs)), ensure_ascii=False)) != plan["scope_proof"]:
                raise ValueError("本人计划会话或来源已经变化")
            return {"occurrence_id": occurrence_id, "run_id": link[0], "event_id": event_id, "event_version": event["version"], "dispatch_id": dispatch_id, "status": result["state"]}

    def list_suppressed_history(self, request, channel, scope_service, plan_id, expected_version, event_id):
        from agent_schedule_receipts import list_suppressed_receipts_in_transaction
        from jsonschema import Draft202012Validator
        if not isinstance(request, web.Request) or not isinstance(channel, RoleChannel):
            raise ValueError("需要实际产品请求和身份服务")
        if channel.boss_commands is None or channel.boss_commands.store.path.resolve() != self.store.path.resolve() or not isinstance(scope_service, RunScopeService) or scope_service.store.path.resolve() != self.store.path.resolve() or channel.gateway.session_manager is not scope_service.sources.sessions:
            raise ValueError("身份与计划存储不属于同一环境")
        channel.require_run_api_role(request)
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._require_schema(db)
            context = _context(db)
            if pending_transition(db, context["namespace"]) is not None:
                raise ValueError("执行空间正在切换")
            plan = self.store.get(db, context["namespace"], "owner_plan", plan_id)
            chat_id, refs = plan.get("conversation_id"), plan.get("source_refs")
            if not isinstance(chat_id, str) or not isinstance(refs, list) or not refs or not isinstance(plan.get("scope_proof"), dict):
                raise ValueError("计划会话或来源范围不可核查")
            channel.require_run_subscription(request, chat_id)
            proof = scope_service.prove_in_transaction(db, chat_id, refs)
            if json.loads(json.dumps(asdict(proof), ensure_ascii=False)) != plan["scope_proof"]:
                raise ValueError("计划会话或来源已经变化")
            result = list_suppressed_receipts_in_transaction(self.store, db, plan_id, event_id)
            if result["plan_version"] != expected_version:
                raise ValueError("本人计划版本已经变化")
            schema = json.loads((Path(__file__).parent / "agent_schedule_history_schema.json").read_text())
            Draft202012Validator(schema).validate(result)
            channel.require_run_subscription(request, chat_id)
            return result

    def read_existing_notification(self, request, channel, plan_id, expected_version, event_id):
        if not isinstance(request, web.Request) or not isinstance(channel, RoleChannel):
            raise ValueError("需要实际产品请求和身份服务")
        if channel.boss_commands is None or channel.boss_commands.store.path.resolve() != self.store.path.resolve():
            raise ValueError("身份与计划存储不属于同一环境")
        channel.require_run_api_role(request)
        if any(not isinstance(value, str) or not value.strip() for value in (plan_id, expected_version, event_id)):
            raise ValueError("计划或事件参数无效")
        with self.store.connect() as db:
            db.execute("BEGIN")
            self._require_schema(db)
            context = _context(db)
            if pending_transition(db, context["namespace"]) is not None:
                raise ValueError("执行空间正在切换")
            plan = self.store.get(db, context["namespace"], "owner_plan", plan_id)
            if plan.get("plan_id") != plan_id or plan.get("version") != expected_version or plan.get("owner_id") != context["owner_id"] or plan.get("source_type") != "SIMULATED" or event_id not in plan.get("event_ids", []):
                raise ValueError("本人计划或事件范围不可核查")
            event = self.store.get(db, context["namespace"], "event", event_id)
            if event.get("owner_plan_id") != plan_id or event.get("version") != plan["event_versions"].get(event_id):
                raise ValueError("本人计划事件已经变化")
            receipt = self.store.get(db, context["namespace"], "notification", event_id + ":" + event["version"])
            if receipt.get("event_id") != event_id or receipt.get("event_version") != event["version"] or receipt.get("owner_plan_id") != plan_id or receipt.get("state") != "DELIVERED" or receipt.get("source_type") != "SIMULATED":
                raise ValueError("原通知记录不可核查")
            rows = db.execute("SELECT body FROM objects WHERE namespace=? AND kind='dispatch_history' AND json_extract(body,'$.event_id')=? AND json_extract(body,'$.event_version')=? AND json_extract(body,'$.owner_plan_id')=? AND json_extract(body,'$.business_at')=? AND json_extract(body,'$.state')='DELIVERED'", (context["namespace"], event_id, event["version"], plan_id, receipt["business_at"])).fetchall()
            if len(rows) != 1:
                raise ValueError("原调度回执不可唯一核查")
            history = json.loads(rows[0][0])
            dispatch_id = history["dispatch_id"]
            original = {key: value for key, value in history.items() if key not in {"dispatch_id", "recorded_at"}}
            if checksum(original) != dispatch_id or any(receipt.get(key) != value for key, value in original.items()):
                raise ValueError("原调度回执内容不符")
            link = db.execute("SELECT l.occurrence_id,r.run_id,c.plan_id,c.plan_version,c.plan_sha256,l.status FROM hermes_schedule_notification_links l JOIN hermes_schedule_run_links r ON r.occurrence_id=l.occurrence_id JOIN hermes_schedule_plan_candidates c ON c.occurrence_id=l.occurrence_id WHERE l.dispatch_id=? AND l.event_id=? AND l.event_version=?", (dispatch_id, event_id, event["version"])).fetchone()
            if link is not None and link[2:] != (plan_id, expected_version, checksum(plan), "DELIVERED"):
                raise ValueError("原通知发生关联不可核查")
            channel.require_run_api_role(request)
            return {"plan_id": plan_id, "plan_version": expected_version, "event_id": event_id, "event_version": event["version"], "dispatch_id": dispatch_id, "business_at": receipt["business_at"], "status": "DELIVERED", "source_type": "SIMULATED", "occurrence_binding": "VERIFIED" if link is not None else "UNVERIFIED", "occurrence_id": link[0] if link is not None else None, "run_id": link[1] if link is not None else None}
