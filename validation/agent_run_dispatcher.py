import json
import hashlib
from contextlib import contextmanager, nullcontext
from dataclasses import asdict
from pathlib import Path
from uuid import uuid4

from aiohttp import web

from agent_run_api import require_product_engine_ready
from agent_run_broker import fail
from agent_chat_budget import AgentChatBudget, MIGRATION as CHAT_MIGRATION, VERSION as CHAT_VERSION
from agent_run_launch_transaction import RunLaunchTransaction
from agent_run_concurrency import RunConcurrencyBudget
from agent_run_store import utc_now
from boss_execution_transition import pending_transition
from boss_owner_plans import plan_authorization_status, stop_business_until, valid_plan_budget
from boss_simulation_api import _context
from business import checksum
from hermes_bridge import EngineEventSink, EngineProcessConfig
from hermes_product import HermesProductServices
from hermes_schedule_adapter import HermesScheduleAdapter, aware_instant


class AgentRunDispatcher:
    def __init__(self, services, execution_factory=None):
        if not isinstance(services, HermesProductServices):
            raise ValueError("需要产品运行服务")
        self.services = services
        self.execution_factory = execution_factory
        self.store = services.store
        self.channel = services.recovery.channel
        if services.scope.store.path.resolve() != self.store.path.resolve() or services.broker.store.path.resolve() != self.store.path.resolve():
            raise ValueError("运行调度服务不属于同一数据库")

    def require_plan_events_in_transaction(self, db, namespace, plan):
        main = db.execute("PRAGMA database_list").fetchone()
        if not db.in_transaction or main is None or main[1] != "main" or Path(main[2]).resolve() != self.store.path.resolve():
            raise ValueError("计划事件检查需要同一数据库事务")
        events, versions = plan.get("event_ids"), plan.get("event_versions")
        if not isinstance(events, list) or not events or any(not isinstance(event, str) or not event for event in events) or len(events) != len(set(events)) or not isinstance(versions, dict) or set(events) != set(versions):
            raise ValueError("本人计划事件范围不可核查")
        for event_id in events:
            event = self.services.scope.store.get(db, namespace, "event", event_id)
            if event.get("owner_plan_id") != plan.get("plan_id") or event.get("state") == "CANCELED" or event.get("version") != versions[event_id]:
                raise ValueError("本人计划事件已经变化")

    def approved_budget_in_transaction(self, db, run_id):
        main = db.execute("PRAGMA database_list").fetchone()
        if not db.in_transaction or main is None or main[1] != "main" or Path(main[2]).resolve() != self.store.path.resolve():
            raise ValueError("预算检查需要同一数据库事务")
        parent = db.execute("SELECT parent_run_id FROM agent_runs WHERE run_id=?", (run_id,)).fetchone()
        if parent is None:
            raise ValueError("预算运行不存在")
        if parent[0] is not None:
            self._verify_child_authorizations_in_transaction(db, run_id)
            return self.approved_budget_in_transaction(db, parent[0])
        exists = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='agent_chat_run_budgets'").fetchone()
        if exists is not None:
            migration = db.execute("SELECT sha256 FROM agent_schema_migrations WHERE version=?", (CHAT_VERSION,)).fetchone()
            if migration != (hashlib.sha256(CHAT_MIGRATION.read_bytes()).hexdigest(),):
                raise ValueError("聊天预算迁移摘要不符")
            binding = db.execute("SELECT 1 FROM agent_chat_run_budgets WHERE run_id=?", (run_id,)).fetchone()
            if binding is not None:
                schedule_table = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='hermes_schedule_run_links'").fetchone()
                if schedule_table is not None and db.execute("SELECT 1 FROM hermes_schedule_run_links WHERE run_id=?", (run_id,)).fetchone() is not None:
                    raise ValueError("运行预算来源存在冲突")
                saved = AgentChatBudget.read_in_transaction(db, run_id)
                run = db.execute("SELECT actor_id,conversation_id,goal,selected_refs,scope_proof FROM agent_runs WHERE run_id=?", (run_id,)).fetchone()
                if run is None or run[3] is None or run[4] is None:
                    raise ValueError("聊天运行来源不可核查")
                return {"owner_id": run[0], "conversation_id": run[1], "purpose": run[2], "source_refs": json.loads(run[3]), "scope_proof": json.loads(run[4]), "config_version": saved["config_version"]}, saved["budget"]
        HermesScheduleAdapter._require_schema(db)
        rows = db.execute("SELECT b.plan_id,b.plan_version,b.authorization_id,b.budget,b.budget_sha256,c.plan_sha256,c.occurrence_at,c.namespace,c.dataset_id,c.dataset_version FROM hermes_schedule_run_links l JOIN hermes_schedule_run_budgets b ON b.occurrence_id=l.occurrence_id JOIN hermes_schedule_plan_candidates c ON c.occurrence_id=l.occurrence_id WHERE l.run_id=?", (run_id,)).fetchall()
        if len(rows) != 1:
            raise ValueError("运行缺少唯一的本人批准计划预算")
        plan_id, version, authorization_id, budget_json, budget_digest, plan_digest, occurrence, namespace, dataset_id, dataset_version = rows[0]
        context = _context(db)
        if pending_transition(db, context["namespace"]) is not None:
            raise ValueError("执行空间正在切换")
        plan = self.services.scope.store.get(db, namespace, "owner_plan", plan_id)
        budget = json.loads(budget_json)
        if (namespace, dataset_id, dataset_version) != (context["namespace"], context["dataset_id"], context["dataset_version"]) or plan.get("plan_id") != plan_id or plan.get("version") != version or plan.get("authorization_id") != authorization_id or checksum(plan) != plan_digest or not valid_plan_budget(budget) or budget != plan.get("budget") or checksum(budget) != budget_digest:
            raise ValueError("本人计划预算或来源已经变化")
        if plan_authorization_status(self.services.scope.store, db, namespace, plan, utc_now()) is not None:
            raise ValueError("本人计划授权不可用")
        self.require_plan_events_in_transaction(db, namespace, plan)
        if aware_instant(context["clock"]) >= stop_business_until(plan["stop_conditions"]) or aware_instant(occurrence) >= stop_business_until(plan["stop_conditions"]):
            raise ValueError("本人计划已经到达停止时间")
        return plan, budget

    def bind_budget_in_transaction(self, db, run_id, owner, epoch):
        plan, budget = self.approved_budget_in_transaction(db, run_id)
        self.store._require_lease(db, run_id, owner, epoch)
        root = self.store.require_active_lineage(db, run_id)
        migrations = ("upgrade2_tool_budget_001", "upgrade2_concurrency_001", "hermes_budget_001", "hermes_cpu_budget_001", "hermes_cpu_budget_002", "hermes_cpu_budget_003", "hermes_cpu_budget_004", "hermes_cpu_budget_005", "hermes_cpu_budget_006")
        for version in migrations:
            path = Path(__file__).parent / "migrations" / (version + ".sql")
            expected = hashlib.sha256(path.read_bytes()).hexdigest()
            row = db.execute("SELECT sha256 FROM agent_schema_migrations WHERE version=?", (version,)).fetchone()
            if row is None or row[0] != expected:
                raise ValueError("运行预算迁移尚未完成或摘要不符")
        cpu_ns = budget["cpu_seconds"] * 1_000_000_000
        if cpu_ns >= 2**63:
            raise ValueError("CPU 预算超过持久存储范围")
        records = (("agent_tool_budgets", ("root_run_id", "max_tools"), (root, budget["tools"])),
                   ("agent_concurrency_budgets", ("root_run_id", "max_concurrency"), (root, budget["concurrency"])),
                   ("hermes_model_budgets", ("root_run_id", "request_limit"), (root, budget["model_requests"])),
                   ("hermes_cpu_budgets", ("root_run_id", "limit_ns"), (root, cpu_ns)),
                   ("agent_file_budgets", ("root_run_id", "max_files", "max_bytes"), (root, budget["files"], budget["file_bytes"])))
        for table, columns, values in records:
            if root == run_id:
                db.execute("INSERT INTO " + table + " (" + ",".join(columns) + ") VALUES (" + ",".join("?" for _ in values) + ") ON CONFLICT(root_run_id) DO NOTHING", values)
            saved = db.execute("SELECT " + ",".join(columns) + " FROM " + table + " WHERE root_run_id=?", (root,)).fetchone()
            if saved is None:
                raise ValueError("根运行预算尚未配置")
            if tuple(saved) != values:
                raise ValueError("运行预算与原记录不匹配")
        return {"budget": budget}

    def recheck_in_launch_transaction(self, db, request, run_id, owner, epoch, expected_plan_digest, expected_budget):
        self.channel.require_run_api_role(request)
        main = db.execute("PRAGMA database_list").fetchone()
        if not db.in_transaction or main is None or main[1] != "main" or Path(main[2]).resolve() != self.store.path.resolve():
            raise ValueError("启动检查需要同一数据库事务")
        db.execute("UPDATE agent_runs SET revision=revision WHERE 0")
        self.store._require_lease(db, run_id, owner, epoch)
        self.store.require_active_lineage(db, run_id)
        row = db.execute("SELECT actor_id,space_id,conversation_id,goal,selected_refs,scope_proof,status,cancel_requested_at FROM agent_runs WHERE run_id=?", (run_id,)).fetchone()
        if row is None or row[6:] != ("RUNNING", None) or row[4] is None or row[5] is None:
            raise ValueError("运行状态或取消检查未通过")
        self._recheck_authorization_context(db, request, run_id, row, expected_plan_digest, expected_budget)

    def recheck_readonly_in_transaction(self, db, request, run_id, owner, epoch, expected_plan_digest, expected_budget):
        self.channel.require_run_api_role(request)
        main = db.execute("PRAGMA database_list").fetchone()
        if not db.in_transaction or main is None or main[1] != "main" or Path(main[2]).resolve() != self.store.path.resolve():
            raise ValueError("启动检查需要同一数据库事务")
        self.store._require_lease(db, run_id, owner, epoch)
        self.store.require_active_lineage(db, run_id)
        row = db.execute("SELECT actor_id,space_id,conversation_id,goal,selected_refs,scope_proof,status,cancel_requested_at FROM agent_runs WHERE run_id=?", (run_id,)).fetchone()
        if row is None or row[6:] != ("RUNNING", None) or row[4] is None or row[5] is None:
            raise ValueError("运行状态或取消检查未通过")
        self._recheck_authorization_context(db, request, run_id, row, expected_plan_digest, expected_budget)

    def _recheck_authorization_context(self, db, request, run_id, row, expected_plan_digest, expected_budget):
        self.channel.require_run_subscription(request, row[2])
        self._verify_lineage_approval_in_transaction(db, run_id, expected_plan_digest, expected_budget)
        self._verify_child_authorizations_in_transaction(db, run_id)
        self.channel.require_run_subscription(request, row[2])

    def _verify_child_authorizations_in_transaction(self, db, run_id):
        from agent_run_method_selection import AgentRunMethodSelection
        from agent_run_requirements import RunRequirements
        selection = self.services.broker.method_selection
        current, seen = run_id, set()
        while True:
            if current in seen:
                raise ValueError("运行关系存在循环")
            seen.add(current)
            child = db.execute("SELECT parent_run_id,goal,scope_proof,space_id,goal_revision,applied_goal_revision FROM agent_runs WHERE run_id=?", (current,)).fetchone()
            if child is None:
                raise ValueError("子运行不存在")
            if child[0] is None:
                return
            if child[4:] != (1, 1):
                raise web.HTTPConflict(text="子运行目标超出委派授权")
            if not isinstance(selection, AgentRunMethodSelection):
                raise ValueError("子运行缺少方法服务")
            saved = db.execute("SELECT body FROM objects WHERE namespace=? AND kind='hermes_child_authorization' AND id=?", (child[3], current)).fetchone()
            if saved is None:
                raise ValueError("子运行缺少委派授权")
            record = json.loads(saved[0])
            fields = {"child_run_id", "parent_run_id", "parent_epoch", "parent_goal_revision", "parent_goal_sha256",
                      "scope_sha256", "method_sha256", "requirements_sha256", "bi_binding_sha256", "goal_sha256", "request_digest"}
            if not isinstance(record, dict) or set(record) != fields:
                raise ValueError("子运行委派授权字段不可核查")
            parent = db.execute("SELECT goal_revision,applied_goal_revision,lease_epoch,scope_proof FROM agent_runs WHERE run_id=?", (child[0],)).fetchone()
            if parent is None or parent[0] != parent[1] or (record.get("child_run_id"), record.get("parent_run_id"), record.get("parent_epoch"), record.get("parent_goal_revision")) != (current, child[0], parent[2], parent[0]):
                raise web.HTTPConflict(text="父运行授权版本已经变化")
            snapshot, scope_digest = selection._goal_snapshot(db, child[0], parent[0])
            goal = json.loads(child[1])
            if not isinstance(goal, dict) or set(goal) != {"goal", "additional_inputs", "delegated_task"} or goal["goal"] != snapshot["goal"] or goal["additional_inputs"] != [item[4] for item in snapshot["inputs"]] or not isinstance(goal["delegated_task"], str) or not goal["delegated_task"].strip() or len(goal["delegated_task"]) > 2000 or record.get("request_digest") != checksum({"parent_run_id": child[0], "goal_revision": parent[0], "description": goal["delegated_task"]}):
                raise ValueError("委派任务目标不可核查")
            method = selection.read_in_transaction(db, child[0])
            child_method = selection.read_in_transaction(db, current, 1)
            outputs = RunRequirements.read_in_transaction(db, child[0], parent[0])
            child_outputs = RunRequirements.read_in_transaction(db, current, 1)
            if method is None or child_method is None or outputs["state"] != "CONFIRMED" or child_outputs["state"] != "CONFIRMED":
                raise ValueError("委派方法或成果要求不可核查")
            selected = {key: method[key] for key in ("sop_id", "name", "version", "content_sha256")}
            actual = selection._current_method(db, {key: selected[key] for key in ("sop_id", "version", "content_sha256")})
            if actual != selected or {key: child_method[key] for key in selected} != selected or outputs["required_outputs"] != child_outputs["required_outputs"]:
                raise ValueError("委派方法或成果要求已经变化")
            if (record.get("parent_goal_sha256"), record.get("scope_sha256"), record.get("method_sha256"), record.get("requirements_sha256"), record.get("goal_sha256")) != (checksum(snapshot), scope_digest, checksum(selected), checksum(outputs["required_outputs"]), checksum(child[1])) or child[2] != parent[3]:
                raise ValueError("委派目标或来源范围已经变化")
            if selected["sop_id"] == "SOP03":
                parent_key = child[0] if parent[0] == 1 else child[0] + ":" + str(parent[0])
                rows = [db.execute("SELECT body FROM objects WHERE namespace=? AND kind='hermes_bi_query_authorization' AND id=?", (child[3], key)).fetchone() for key in (parent_key, current)]
                if any(row is None for row in rows) or any(json.loads(row[0]).get("binding_sha256") != record.get("bi_binding_sha256") for row in rows):
                    raise ValueError("委派经营授权已经变化")
            elif record.get("bi_binding_sha256") is not None:
                raise ValueError("委派经营授权不可核查")
            current = child[0]

    def _verify_lineage_approval_in_transaction(self, db, run_id, expected_plan_digest, expected_budget):
        root, root_row = self._verify_scope_lineage_in_transaction(db, run_id)
        plan, budget = self.approved_budget_in_transaction(db, root)
        if checksum(plan) != expected_plan_digest or budget != expected_budget or (plan.get("owner_id"), plan.get("conversation_id"), plan.get("purpose"), plan.get("source_refs"), plan.get("scope_proof")) != (root_row[0], root_row[2], root_row[3], json.loads(root_row[4]), json.loads(root_row[5])):
            raise ValueError("本人计划或预算已经变化")
        if "plan_id" in plan:
            self.require_authorized_plan_execution_in_transaction(db, root, plan)

    def require_authorized_plan_execution_in_transaction(self, db, run_id, plan):
        from agent_run_method_selection import AgentRunMethodSelection
        from agent_run_requirements import RunRequirements
        main = db.execute("PRAGMA database_list").fetchone()
        if not db.in_transaction or main is None or Path(main[2]).resolve() != self.store.path.resolve():
            raise ValueError("计划执行授权检查需要当前数据库事务")
        run = db.execute("SELECT goal_revision,applied_goal_revision FROM agent_runs WHERE run_id=?", (run_id,)).fetchone()
        if run != (1, 1):
            raise ValueError("计划运行目标版本超出本人授权")
        selected = AgentRunMethodSelection.read_in_transaction(db, run_id, 1)
        requirements = RunRequirements.read_in_transaction(db, run_id, 1)
        if selected is None or requirements["state"] != "CONFIRMED" or requirements["required_outputs"] != plan.get("required_outputs") or {key: selected[key] for key in ("sop_id", "version", "content_sha256")} != plan.get("method_selection"):
            raise ValueError("计划运行方法或成果要求已经变化")

    def _verify_scope_lineage_in_transaction(self, db, run_id):
        current, seen, identity, conversation, child_refs = run_id, set(), None, None, None
        while current is not None:
            if current in seen:
                raise ValueError("运行关系存在循环")
            seen.add(current)
            entry = db.execute("SELECT parent_run_id,actor_id,space_id,conversation_id,goal,selected_refs,scope_proof,lease_owner,lease_epoch FROM agent_runs WHERE run_id=?", (current,)).fetchone()
            if entry is None or entry[5] is None or entry[6] is None:
                raise ValueError("运行身份或来源范围不可核查")
            row = entry[1:7]
            if identity is None:
                identity, conversation = row[:2], row[2]
            if row[:2] != identity or row[2] != conversation:
                raise ValueError("父子运行主体、空间或会话不一致")
            self.store._require_lease(db, current, entry[7], entry[8])
            refs = json.loads(row[4])
            proof = self.services.scope.prove_in_transaction(db, row[2], refs)
            if (proof.owner_id, proof.namespace) != row[:2] or json.loads(json.dumps(asdict(proof))) != json.loads(row[5]):
                raise ValueError("运行来源范围已经变化")
            if child_refs is not None and not child_refs.issubset(set(refs)):
                raise ValueError("子运行来源范围超过父运行")
            root, root_row = current, row
            child_refs, current = set(refs), entry[0]
        return root, root_row

    def recheck_cancelled_usage_in_transaction(self, db, request, run_id, owner, epoch, expected_plan_digest, expected_budget):
        self.channel.require_run_api_role(request)
        main = db.execute("PRAGMA database_list").fetchone()
        if not db.in_transaction or main is None or main[1] != "main" or Path(main[2]).resolve() != self.store.path.resolve():
            raise ValueError("用量授权检查需要同一数据库事务")
        self.store._require_lease(db, run_id, owner, epoch)
        current, seen, identity, canceled = run_id, set(), None, False
        while current is not None:
            if current in seen:
                raise ValueError("运行关系存在循环")
            seen.add(current)
            item = db.execute("SELECT parent_run_id,actor_id,space_id,status,cancel_requested_at,lease_owner,lease_epoch FROM agent_runs WHERE run_id=?", (current,)).fetchone()
            if item is None:
                raise ValueError("运行或父运行不存在")
            if identity is None:
                identity = item[1:3]
            if item[1:3] != identity:
                raise ValueError("父子运行主体或空间不一致")
            self.store._require_lease(db, current, item[5], item[6])
            if item[3] in {"CANCEL_REQUESTED", "RECONCILING"} and item[4] is not None:
                canceled = True
            elif item[3] not in {"RUNNING", "WAITING_INPUT", "WAITING_CONFIRMATION"} or item[4] is not None:
                raise ValueError("运行状态或取消检查未通过")
            current = item[0]
        if not canceled:
            raise ValueError("用量收尾需要已确认的取消状态")
        row = db.execute("SELECT actor_id,space_id,conversation_id,goal,selected_refs,scope_proof,status,cancel_requested_at FROM agent_runs WHERE run_id=?", (run_id,)).fetchone()
        if row is None or row[4] is None or row[5] is None:
            raise ValueError("运行身份或来源范围不可核查")
        from hermes_source_invalidation import require_source_cleanup_complete
        require_source_cleanup_complete(db, run_id)
        self._recheck_authorization_context(db, request, run_id, row, expected_plan_digest, expected_budget)

    @contextmanager
    def launch_transaction(self, request, run_id, owner, epoch, expected_plan_digest, expected_budget):
        self.channel.require_run_api_role(request)
        with RunLaunchTransaction(self.store).hold(run_id, owner, epoch) as db:
            self.recheck_in_launch_transaction(db, request, run_id, owner, epoch, expected_plan_digest, expected_budget)
            yield db

    def recheck_after_claim(self, request, run_id, owner, epoch, expected_plan_digest, expected_budget):
        self.channel.require_run_api_role(request)
        with self.launch_transaction(request, run_id, owner, epoch, expected_plan_digest, expected_budget):
            pass

    def record_start_failure(self, run_id, owner, epoch):
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            current = db.execute("SELECT status,lease_owner,lease_epoch FROM agent_runs WHERE run_id=?", (run_id,)).fetchone()
            if current is None or current[1:] != (owner, epoch):
                return "LEASE_CHANGED"
            if current[0] in {"RUNNING", "CANCEL_REQUESTED", "WAITING_INPUT", "WAITING_CONFIRMATION", "RECONCILING"}:
                if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='agent_concurrency_reservations'").fetchone() is not None:
                    db.execute("UPDATE agent_concurrency_reservations SET state='UNKNOWN',updated_at=? WHERE run_id=? AND lease_owner=? AND lease_epoch=? AND state='ACTIVE'", (utc_now().isoformat(), run_id, owner, epoch))
                if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='hermes_process_evidence'").fetchone() is not None:
                    db.execute("UPDATE hermes_process_evidence SET state='UNKNOWN',updated_at=? WHERE run_id=? AND lease_owner=? AND lease_epoch=? AND state IN ('STARTING','RUNNING')", (utc_now().isoformat(), run_id, owner, epoch))
                if current[0] == "RUNNING":
                    db.execute("UPDATE agent_runs SET status='INTERRUPTED',revision=revision+1 WHERE run_id=?", (run_id,))
                    self.store._record_event(db, run_id, "STATUS_CHANGED", {"from": "RUNNING", "to": "INTERRUPTED"}, epoch)
                    return "INTERRUPTED"
            return current[0]

    def inspect(self, request, run_id):
        if not isinstance(request, web.Request):
            raise ValueError("需要实际产品请求")
        self.channel.require_run_api_role(request)
        with self.store.connect() as db:
            db.execute("BEGIN")
            row = db.execute("SELECT actor_id,space_id,conversation_id,selected_refs,scope_proof,status,revision,cancel_requested_at,lease_epoch FROM agent_runs WHERE run_id=?", (run_id,)).fetchone()
            if row is None or row[3] is None or row[4] is None:
                raise web.HTTPNotFound(text="运行不存在")
            self.channel.require_run_subscription(request, row[2])
            proof = self.services.scope.prove_in_transaction(db, row[2], json.loads(row[3]))
            if (proof.owner_id, proof.namespace) != row[:2] or json.loads(json.dumps(asdict(proof))) != json.loads(row[4]):
                raise ValueError("运行来源范围已经变化")
            self.channel.require_run_subscription(request, row[2])
            return {"run_id": run_id, "status": row[5], "revision": row[6], "cancel_requested": row[7] is not None, "lease_epoch": row[8]}

    def dispatch_receipt(self, request, run_id, request_key):
        self.inspect(request, run_id)
        with self.store.connect() as db:
            self.require_dispatch_schema(db)
            row = db.execute("SELECT expected_revision,lease_epoch,state,result,request_digest FROM agent_dispatch_receipts WHERE run_id=? AND request_key=?", (run_id, request_key)).fetchone()
        if row is None:
            raise web.HTTPNotFound(text="派发请求不存在")
        if row[4] != checksum({"run_id": run_id, "expected_revision": row[0], "request_key": request_key}):
            raise ValueError("派发请求记录不可核查")
        return {"run_id": run_id, "request_key": request_key, "expected_revision": row[0], "lease_epoch": row[1],
                "state": row[2], "result": json.loads(row[3]) if row[3] is not None else None}

    def inspect_dispatch_recovery_in_transaction(self, db, run_id, request_key):
        main = db.execute("PRAGMA database_list").fetchone()
        if not db.in_transaction or main is None or Path(main[2]).resolve() != self.store.path.resolve():
            raise ValueError("派发核查需要当前数据库事务")
        self.require_dispatch_schema(db)
        for version in ("upgrade2_concurrency_001", "hermes_process_evidence_001"):
            source = Path(__file__).parent / "migrations" / (version + ".sql")
            row = db.execute("SELECT sha256 FROM agent_schema_migrations WHERE version=?", (version,)).fetchone()
            if row != (hashlib.sha256(source.read_bytes()).hexdigest(),):
                fail(web.HTTPServiceUnavailable, "SERVICE_NOT_READY", "派发进程记录尚未准备")
        receipt = db.execute("SELECT expected_revision,lease_owner,lease_epoch,state,request_digest FROM agent_dispatch_receipts WHERE run_id=? AND request_key=?", (run_id, request_key)).fetchone()
        if receipt is None:
            raise web.HTTPNotFound(text="派发请求不存在")
        expected = checksum({"run_id": run_id, "expected_revision": receipt[0], "request_key": request_key})
        if receipt[4] != expected:
            raise ValueError("派发请求记录不可核查")
        run = db.execute("SELECT actor_id,space_id,status,lease_owner,lease_epoch,lease_expires_at FROM agent_runs WHERE run_id=?", (run_id,)).fetchone()
        if run is None:
            raise ValueError("派发运行不可核查")
        process_key = "dispatch:" + run_id + ":" + str(receipt[2])
        reservation = db.execute("SELECT request_digest,lease_owner,lease_epoch,state FROM agent_concurrency_reservations WHERE run_id=? AND request_key=?", (run_id, process_key)).fetchone()
        if reservation is None or reservation[1:3] != receipt[1:3]:
            raise ValueError("派发并发预留不可核查")
        process = db.execute("SELECT request_digest,lease_owner,lease_epoch,actor_id,space_id,state,exit_code,exit_scope FROM hermes_process_evidence WHERE run_id=? AND request_key=?", (run_id, process_key)).fetchone()
        if process is not None and process[:5] != (*reservation[:3], *run[:2]):
            raise ValueError("派发进程记录不可核查")
        return {"run_id": run_id, "request_key": request_key, "receipt_state": receipt[3], "run_status": run[2],
                "lease_epoch": receipt[2], "current_lease_epoch": run[4], "lease_owner_matches": run[3] == receipt[1],
                "lease_expires_at": run[5], "reservation_state": reservation[3],
                "process_state": process[5] if process is not None else "NOT_RECORDED",
                "exit_code": process[6] if process is not None else None,
                "exit_scope": process[7] if process is not None else None,
                "automatic_retry": False}

    def inspect_dispatch_recovery(self, request, run_id, request_key):
        self.inspect(request, run_id)
        with self.store.connect() as db:
            db.execute("BEGIN")
            result = self.inspect_dispatch_recovery_in_transaction(db, run_id, request_key)
        self.inspect(request, run_id)
        return result

    @staticmethod
    def require_dispatch_schema(db):
        source = Path(__file__).parent / "migrations/upgrade2_dispatch_receipts_001.sql"
        row = db.execute("SELECT sha256 FROM agent_schema_migrations WHERE version=?", ("upgrade2_dispatch_receipts_001",)).fetchone()
        if row != (hashlib.sha256(source.read_bytes()).hexdigest(),):
            fail(web.HTTPServiceUnavailable, "SERVICE_NOT_READY", "派发回执尚未准备")

    def record_dispatch_in_transaction(self, db, run_id, request_key, expected_revision, owner, epoch):
        main = db.execute("PRAGMA database_list").fetchone()
        if not db.in_transaction or main is None or Path(main[2]).resolve() != self.store.path.resolve():
            raise ValueError("派发回执需要当前数据库事务")
        self.require_dispatch_schema(db)
        self.store._require_lease(db, run_id, owner, epoch)
        digest = checksum({"run_id": run_id, "expected_revision": expected_revision, "request_key": request_key})
        db.execute("INSERT INTO agent_dispatch_receipts VALUES (?,?,?,?,?,?,'ACCEPTED',NULL)",
                   (run_id, request_key, digest, owner, epoch, expected_revision))

    def finalize_dispatch_receipt(self, run_id, request_key, owner, epoch, result):
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            return self.finalize_dispatch_receipt_in_transaction(db, run_id, request_key, owner, epoch, result)

    def finalize_dispatch_receipt_in_transaction(self, db, run_id, request_key, owner, epoch, result):
        main = db.execute("PRAGMA database_list").fetchone()
        if not db.in_transaction or main is None or Path(main[2]).resolve() != self.store.path.resolve():
            raise ValueError("派发回执消费需要当前数据库事务")
        self.require_dispatch_schema(db)
        if result.descendants not in {"VERIFIED_EXITED", "NOT_VERIFIED"}:
            raise ValueError("派发生命周期结果不可核查")
        state = "COMPLETED" if result.descendants == "VERIFIED_EXITED" else "UNKNOWN"
        updated = db.execute("UPDATE agent_dispatch_receipts SET state=?,result=? WHERE run_id=? AND request_key=? AND lease_owner=? AND lease_epoch=? AND state='ACCEPTED'",
                             (state, json.dumps(asdict(result), sort_keys=True), run_id, request_key, owner, epoch))
        if updated.rowcount != 1:
            raise ValueError("派发回执消费状态不可核查")
        return state

    def fail_dispatch_receipt(self, run_id, request_key, owner, epoch):
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            updated = db.execute("UPDATE agent_dispatch_receipts SET state='UNKNOWN' WHERE run_id=? AND request_key=? AND lease_owner=? AND lease_epoch=? AND state='ACCEPTED'",
                                 (run_id, request_key, owner, epoch))
            if updated.rowcount != 1:
                raise ValueError("派发回执失败状态不可核查")

    def require_no_unresolved_dispatch_in_transaction(self, db, run_id):
        main = db.execute("PRAGMA database_list").fetchone()
        if not db.in_transaction or main is None or Path(main[2]).resolve() != self.store.path.resolve():
            raise ValueError("派发状态检查需要当前数据库事务")
        self.require_dispatch_schema(db)
        if db.execute("SELECT 1 FROM agent_dispatch_receipts WHERE run_id=? AND state IN ('ACCEPTED','UNKNOWN') LIMIT 1", (run_id,)).fetchone() is not None:
            fail(web.HTTPConflict, "REVISION_CONFLICT", "原派发结果尚未确定，请先查询原请求")

    @staticmethod
    def mark_expired_dispatch_unknown_in_transaction(store, db, run_id, lease_owner, lease_epoch):
        main = db.execute("PRAGMA database_list").fetchone()
        if not db.in_transaction or main is None or Path(main[2]).resolve() != store.path.resolve():
            raise ValueError("派发状态恢复需要当前数据库事务")
        AgentRunDispatcher.require_dispatch_schema(db)
        entries = db.execute("SELECT request_key,expected_revision,request_digest,lease_owner,lease_epoch FROM agent_dispatch_receipts WHERE run_id=? AND state='ACCEPTED'", (run_id,)).fetchall()
        for key, revision, digest, owner, epoch in entries:
            if epoch != lease_epoch or lease_owner is not None and owner != lease_owner or digest != checksum({"run_id": run_id, "expected_revision": revision, "request_key": key}):
                raise ValueError("派发回执与恢复租约不一致")
            process_key = "dispatch:" + run_id + ":" + str(epoch)
            reservation = db.execute("SELECT lease_owner,lease_epoch,state FROM agent_concurrency_reservations WHERE run_id=? AND request_key=?", (run_id, process_key)).fetchone()
            settled = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='hermes_cpu_final_exits'").fetchone() is not None and db.execute("SELECT 1 FROM hermes_cpu_final_exits f JOIN hermes_vm_run_bindings b ON b.run_id=f.run_id AND b.request_key=f.request_key WHERE f.run_id=? AND f.request_key=? AND f.lease_epoch=? AND b.lease_owner=? AND b.lease_epoch=f.lease_epoch AND b.vm_id=f.vm_id AND b.boot_id=f.boot_id AND b.unit_name=f.unit AND f.source='SLICE_CPU_NSEC_V1'", (run_id, process_key, epoch, owner)).fetchone() is not None
            if reservation != (owner, epoch, "UNKNOWN") and not (reservation == (owner, epoch, "RELEASED") and settled):
                raise ValueError("派发预留尚未转为未知状态")
            db.execute("UPDATE agent_dispatch_receipts SET state='UNKNOWN' WHERE run_id=? AND request_key=? AND state='ACCEPTED'", (run_id, key))

    def require_dispatch_preconditions_in_transaction(self, db, run_id):
        from agent_run_method_selection import AgentRunMethodSelection
        from agent_run_requirements import RunRequirements
        main = db.execute("PRAGMA database_list").fetchone()
        if not db.in_transaction or main is None or Path(main[2]).resolve() != self.store.path.resolve():
            raise ValueError("派发前置检查需要当前数据库事务")
        row = db.execute("SELECT goal,goal_revision,applied_goal_revision FROM agent_runs WHERE run_id=?", (run_id,)).fetchone()
        if row is None or not isinstance(row[0], str) or not row[0].strip() or type(row[1]) is not int or row[1] < 1 or type(row[2]) is not int or not 1 <= row[2] <= row[1]:
            fail(web.HTTPConflict, "INVALID_INPUT", "当前运行目标尚未准备")
        if row[1] != row[2]:
            inputs = db.execute("SELECT input_seq,goal_revision,applied_event_id FROM agent_run_inputs WHERE run_id=? ORDER BY input_seq", (run_id,)).fetchall()
            if len(inputs) != row[1] - 1 or any(item[0] != index or item[1] != index + 1 or (item[2] is None) != (item[1] > row[2]) for index, item in enumerate(inputs, 1)):
                fail(web.HTTPConflict, "INVALID_INPUT", "当前运行补充目标尚未准备")
        requirements = RunRequirements.read_in_transaction(db, run_id, row[1])
        if requirements["state"] != "CONFIRMED":
            fail(web.HTTPConflict, "INVALID_INPUT", "当前目标成果要求尚未确认")
        selection = self.services.broker.method_selection
        if selection is None:
            fail(web.HTTPServiceUnavailable, "SERVICE_NOT_READY", "运行方法服务尚未准备")
        selected = AgentRunMethodSelection.read_in_transaction(db, run_id, row[1])
        if selected is None:
            fail(web.HTTPConflict, "INVALID_INPUT", "当前目标尚未选择方法")
        method = selection._current_method(db, {key: selected[key] for key in ("sop_id", "version", "content_sha256")})
        if method != {key: selected[key] for key in ("sop_id", "name", "version", "content_sha256")}:
            fail(web.HTTPConflict, "SCOPE_CHANGED", "当前方法版本已经变化")

    async def dispatch(self, request, run_id, expected_revision, request_key):
        if not isinstance(request, web.Request):
            raise ValueError("需要实际产品请求")
        self.channel.require_run_api_role(request)
        self.inspect(request, run_id)
        with self.store.connect() as db:
            self.require_dispatch_schema(db)
            previous = db.execute("SELECT expected_revision FROM agent_dispatch_receipts WHERE run_id=? AND request_key=?", (run_id, request_key)).fetchone()
        if previous is not None:
            if previous[0] != expected_revision:
                fail(web.HTTPConflict, "REQUEST_KEY_CONFLICT", "派发请求编号已经用于其他内容")
            return self.dispatch_receipt(request, run_id, request_key)
        if self.execution_factory is None:
            fail(web.HTTPServiceUnavailable, "SERVICE_NOT_READY", "服务端执行装配尚未准备")
        with self.store.connect() as db:
            row = db.execute("SELECT lease_epoch,conversation_id,status,revision FROM agent_runs WHERE run_id=?", (run_id,)).fetchone()
            if row is None:
                raise web.HTTPNotFound(text="运行不存在")
            self.channel.require_run_subscription(request, row[1])
            if row[2:] != ("QUEUED", expected_revision):
                raise ValueError("排队运行状态或版本已经变化")
            next_epoch = row[0] + 1
        if getattr(self.execution_factory.deployment, "vm_manager", None) is not None:
            from agent_artifact_workspace import ArtifactWorkspace
            ArtifactWorkspace(self.execution_factory.deployment.workspace_root).create(run_id)
        process_config = self.execution_factory.prepare(request, run_id, next_epoch)
        if not isinstance(process_config, EngineProcessConfig) or process_config.run.run_id != run_id or process_config.run.lease_epoch != next_epoch:
            raise ValueError("服务端运行配置与运行不匹配")
        concurrency = RunConcurrencyBudget(self.store)
        owner = str(uuid4())
        selection = self.services.broker.method_selection
        with (selection.drafts._locked() if selection is not None else nullcontext()), self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            previous = db.execute("SELECT expected_revision FROM agent_dispatch_receipts WHERE run_id=? AND request_key=?", (run_id, request_key)).fetchone()
            if previous is not None:
                if previous[0] != expected_revision:
                    fail(web.HTTPConflict, "REQUEST_KEY_CONFLICT", "派发请求编号已经用于其他内容")
                return self.dispatch_receipt(request, run_id, request_key)
            self.require_no_unresolved_dispatch_in_transaction(db, run_id)
            row = db.execute("SELECT actor_id,space_id,conversation_id,goal,selected_refs,scope_proof,status,cancel_requested_at,lease_epoch FROM agent_runs WHERE run_id=?", (run_id,)).fetchone()
            if row is None or row[6:] != ("QUEUED", None, process_config.run.lease_epoch - 1) or row[4] is None or row[5] is None:
                raise ValueError("排队运行身份或状态不可核查")
            self.channel.require_run_subscription(request, row[2])
            proof = self.services.scope.prove_in_transaction(db, row[2], json.loads(row[4]))
            if (proof.owner_id, proof.namespace) != row[:2] or json.loads(json.dumps(asdict(proof))) != json.loads(row[5]):
                raise ValueError("运行来源范围已经变化")
            self.require_dispatch_preconditions_in_transaction(db, run_id)
            plan, budget = self.approved_budget_in_transaction(db, run_id)
            root_id, seen = run_id, set()
            while True:
                if root_id in seen:
                    raise ValueError("运行关系存在循环")
                seen.add(root_id)
                parent = db.execute("SELECT parent_run_id FROM agent_runs WHERE run_id=?", (root_id,)).fetchone()
                if parent is None:
                    raise ValueError("运行关系不可核查")
                if parent[0] is None:
                    break
                root_id = parent[0]
            root_row = db.execute("SELECT actor_id,conversation_id,goal,selected_refs,scope_proof FROM agent_runs WHERE run_id=?", (root_id,)).fetchone()
            if "plan_id" in plan:
                self.require_authorized_plan_execution_in_transaction(db, root_id, plan)
            if (plan.get("owner_id"), plan.get("conversation_id"), plan.get("purpose"), plan.get("source_refs"), plan.get("scope_proof")) != (root_row[0], root_row[1], root_row[2], json.loads(root_row[3]), json.loads(root_row[4])):
                raise ValueError("计划与运行内容不匹配")
            from hermes_cpu_budget import vm_cpu_allocation_seconds
            expected_cpu = vm_cpu_allocation_seconds(budget) if self.execution_factory.deployment.vm_manager is not None else budget["cpu_seconds"]
            expected_budget = {"model_requests": process_config.run.request_limit, "rounds": process_config.max_rounds, "tools": process_config.max_tools, "seconds": process_config.max_seconds, "concurrency": process_config.max_concurrency, "context_tokens": process_config.max_context_tokens, "files": process_config.max_files, "file_bytes": process_config.max_file_bytes, "open_files": process_config.max_open_files, "cpu_seconds": budget["cpu_seconds"]}
            if budget != expected_budget or process_config.max_cpu_seconds != expected_cpu:
                raise ValueError("进程预算与本人批准预算不匹配")
            process_config.validate()
            self.channel.require_run_subscription(request, row[2])
            require_product_engine_ready(factory=self.execution_factory)
            lease = self.store.acquire_queued_in_transaction(db, run_id, expected_revision, owner, budget["seconds"])
            self.bind_budget_in_transaction(db, run_id, owner, lease["epoch"])
            process_key = "dispatch:" + run_id + ":" + str(lease["epoch"])
            process_digest = checksum({"run_id": run_id, "lease_epoch": lease["epoch"], "plan_digest": checksum(plan), "budget": budget})
            concurrency.reserve_in_transaction(db, run_id, owner, lease["epoch"], process_key, process_digest)
            self.record_dispatch_in_transaction(db, run_id, request_key, expected_revision, owner, lease["epoch"])
        sink = EngineEventSink(self.store, process_config.run, owner)
        completed = False
        try:
            self.recheck_after_claim(request, run_id, owner, lease["epoch"], checksum(plan), budget)
            require_product_engine_ready(factory=self.execution_factory)
            assembly = self.execution_factory.assemble(request, sink, budget, checksum(plan))
            with assembly.listener:
                if (assembly.request_key, assembly.request_digest) != (process_key, process_digest):
                    raise ValueError("进程预留与执行装配不匹配")
                result = await self.services.execute(request, sink, budget, process_config, assembly.lifecycle, assembly.listener,
                                                     plan_digest=checksum(plan), request_key=assembly.request_key,
                                                     request_digest=assembly.request_digest, bootstrap=assembly.bootstrap)
            with self.store.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                self.finalize_dispatch_receipt_in_transaction(db, run_id, request_key, owner, lease["epoch"], result)
            completed = True
            return self.dispatch_receipt(request, run_id, request_key)
        finally:
            if not completed:
                self.record_start_failure(run_id, owner, lease["epoch"])
                self.fail_dispatch_receipt(run_id, request_key, owner, lease["epoch"])
