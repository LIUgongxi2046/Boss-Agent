import json
import sqlite3
from pathlib import Path

from aiohttp import web

from agent_run_method_selection import AgentRunMethodSelection
from agent_run_requirements import RunRequirements
from agent_run_tool_budget import RunToolBudget
from business import checksum
from hermes_bridge import EngineEventSink


class HermesRunAuthority:
    def __init__(self, services, request, sink, plan_digest, budget, *, execution_factory=None):
        from agent_run_dispatcher import AgentRunDispatcher
        from hermes_product import HermesProductServices
        if not isinstance(services, HermesProductServices) or not isinstance(request, web.Request) or not isinstance(sink, EngineEventSink):
            raise ValueError("运行授权需要实际产品请求和运行服务")
        if sink.store.path.resolve() != services.store.path.resolve() or not isinstance(plan_digest, str) or not plan_digest or not isinstance(budget, dict):
            raise ValueError("运行授权与当前环境不匹配")
        self.services, self.request, self.sink = services, request, sink
        self.plan_digest, self.budget = plan_digest, dict(budget)
        self.dispatcher = AgentRunDispatcher(services)
        if execution_factory is not None:
            from hermes_runtime_binding import HermesExecutionFactory
            if not isinstance(execution_factory, HermesExecutionFactory) or execution_factory.services is not services:
                raise ValueError("委派工厂与运行服务不一致")
        self.execution_factory = execution_factory
        self.vm_access = None

    def bind_vm_access(self, access):
        from hermes_vm_identity import HermesVMRunAccess
        if not isinstance(access, HermesVMRunAccess) or access.bindings.store.path.resolve() != self.sink.store.path.resolve():
            raise ValueError("虚拟机绑定与运行授权不匹配")
        if (access.run_id, access.owner, access.epoch) != (self.sink.config.run_id, self.sink.lease_owner, self.sink.config.lease_epoch):
            raise ValueError("虚拟机绑定与运行租约不匹配")
        if self.vm_access is not None and self.vm_access != access:
            raise ValueError("运行授权已经绑定其他虚拟机")
        access.require()
        self.vm_access = access

    def require_in_transaction(self, db):
        self.dispatcher.recheck_in_launch_transaction(db, self.request, self.sink.config.run_id,
            self.sink.lease_owner, self.sink.config.lease_epoch, self.plan_digest, self.budget)
        if self.vm_access is not None:
            self.vm_access.require_in_transaction(db)

    def require_readonly_in_transaction(self, db):
        self.dispatcher.recheck_readonly_in_transaction(db, self.request, self.sink.config.run_id,
            self.sink.lease_owner, self.sink.config.lease_epoch, self.plan_digest, self.budget)
        if self.vm_access is not None:
            self.vm_access.require_in_transaction(db)

    def require(self):
        self.services.recovery.channel.require_run_api_role(self.request)
        with self.sink.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self.require_in_transaction(db)

    def require_cancelled_usage_in_transaction(self, db):
        self.dispatcher.recheck_cancelled_usage_in_transaction(db, self.request, self.sink.config.run_id,
            self.sink.lease_owner, self.sink.config.lease_epoch, self.plan_digest, self.budget)

    def monitor_state_in_transaction(self, db):
        row = db.execute("SELECT status FROM agent_runs WHERE run_id=?", (self.sink.config.run_id,)).fetchone()
        if row is not None and row[0] in {"WAITING_INPUT", "WAITING_CONFIRMATION"}:
            return self.require_waiting_in_transaction(db)
        self.require_in_transaction(db)
        return "RUNNING"

    def require_waiting_in_transaction(self, db):
        from agent_run_broker import RunBroker
        from agent_run_memory_guard import require_current_run_memory_in_transaction
        from hermes_source_invalidation import require_source_cleanup_complete
        channel = self.services.recovery.channel
        channel.require_run_api_role(self.request)
        main = db.execute("PRAGMA database_list").fetchone()
        if not db.in_transaction or main is None or main[1] != "main" or self.sink.store.path.resolve() != Path(main[2]).resolve():
            raise ValueError("等待收尾需要同一运行事务")
        run_id = self.sink.config.run_id
        self.sink.store._require_lease(db, run_id, self.sink.lease_owner, self.sink.config.lease_epoch)
        self.sink.store.require_active_lineage(db, run_id)
        run = db.execute("SELECT actor_id,space_id,conversation_id,goal,selected_refs,scope_proof,status,cancel_requested_at,goal_revision,applied_goal_revision FROM agent_runs WHERE run_id=?", (run_id,)).fetchone()
        if run is None or run[6] not in {"WAITING_INPUT", "WAITING_CONFIRMATION"} or run[7] is not None or run[8] < run[9] or run[4] is None or run[5] is None:
            raise ValueError("运行等待状态不可核查")
        self.dispatcher._recheck_authorization_context(db, self.request, run_id, run[:8], self.plan_digest, self.budget)
        require_source_cleanup_complete(db, run_id)
        require_current_run_memory_in_transaction(db, self.services.scope.store, run_id)
        if self.vm_access is None:
            raise ValueError("等待收尾缺少虚拟机绑定")
        self.vm_access.require_final_in_transaction(db)
        event = db.execute("SELECT lease_epoch,payload FROM agent_run_events WHERE run_id=? AND type='STATUS_CHANGED' ORDER BY seq DESC LIMIT 1", (run_id,)).fetchone()
        if event is None or event[0] != self.sink.config.lease_epoch:
            raise ValueError("等待状态事件不可核查")
        payload = json.loads(event[1])
        if payload.get("from") != "RUNNING" or payload.get("to") != run[6]:
            raise ValueError("等待状态事件不匹配")
        if run[6] == "WAITING_INPUT":
            if payload.get("goal_revision") != run[9]:
                raise ValueError("等待目标版本不可核查")
            if payload.get("reason") == "INPUT_REQUIRED":
                original_factory = db.row_factory
                db.row_factory = sqlite3.Row
                current = db.execute("SELECT * FROM agent_runs WHERE run_id=?", (run_id,)).fetchone()
                db.row_factory = original_factory
                if RunBroker._waiting_input_in_transaction(db, current, include_answered=True) is None:
                    raise ValueError("等待问题不可核查")
            elif payload != {"from": "RUNNING", "to": "WAITING_INPUT", "reason": "OUTPUT_REQUIREMENTS_UNCONFIRMED", "goal_revision": run[9]}:
                raise ValueError("等待成果要求事件不可核查")
        else:
            if payload != {"from": "RUNNING", "to": "WAITING_CONFIRMATION"}:
                raise ValueError("等待本人确认事件不可核查")
            original_factory = db.row_factory
            db.row_factory = sqlite3.Row
            intents = db.execute("SELECT * FROM agent_intents WHERE run_id=? AND status='WAITING_CONFIRMATION'", (run_id,)).fetchall()
            db.row_factory = original_factory
            if len(intents) != 1 or json.loads(intents[0]["preview"]).get("goal_revision") != run[9]:
                raise ValueError("等待本人确认意图不可核查")
            from hermes_intents import validate_domain_intent_provenance
            validate_domain_intent_provenance(db, intents[0])
        channel.require_run_subscription(self.request, run[2])
        return run[6]

    def reserve_delegate_tool_in_transaction(self, db, tool_key, tool_digest, tool_name):
        run_id = self.sink.config.run_id
        previous = db.execute("SELECT request_digest,tool_name,lease_epoch FROM agent_tool_reservations WHERE run_id=? AND request_key=?", (run_id, tool_key)).fetchone()
        if previous is not None and previous != (tool_digest, tool_name, self.sink.config.lease_epoch):
            raise web.HTTPConflict(text="委派工具请求编号对应的内容已经变化")
        root = self.sink.store.require_active_lineage(db, run_id)
        limit = db.execute("SELECT max_tools FROM agent_tool_budgets WHERE root_run_id=?", (root,)).fetchone()
        if limit is None:
            raise web.HTTPServiceUnavailable(text="根运行工具预算尚未配置")
        if previous is None and db.execute("SELECT count(*) FROM agent_tool_reservations WHERE root_run_id=?", (root,)).fetchone()[0] >= limit[0]:
            raise web.HTTPTooManyRequests(text="根运行工具预算已经用尽")
        return RunToolBudget(self.sink.store).reserve_in_transaction(db, run_id, self.sink.lease_owner,
            self.sink.config.lease_epoch, tool_key, tool_digest, tool_name)

    def create_child(self, request_key, description):
        if not isinstance(request_key, str) or not request_key.strip() or len(request_key) > 128:
            raise ValueError("委派请求编号无效")
        if not isinstance(description, str) or not description.strip() or len(description) > 2000:
            raise ValueError("委派任务描述无效")
        selection = self.services.broker.method_selection
        if not isinstance(selection, AgentRunMethodSelection):
            raise ValueError("委派需要当前运行方法服务")
        parent_id = self.sink.config.run_id
        store = self.sink.store
        tool_budget = RunToolBudget(store)
        with selection.drafts._locked(), store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self.require_in_transaction(db)
            method = selection._require_current_in_transaction(db, self.sink)
            parent = db.execute("SELECT goal,goal_revision,applied_goal_revision,scope_proof,space_id FROM agent_runs WHERE run_id=?", (parent_id,)).fetchone()
            if parent is None or parent[1] != parent[2]:
                raise ValueError("委派目标版本不可核查")
            snapshot, scope_digest = selection._goal_snapshot(db, parent_id, parent[1])
            outputs = RunRequirements.read_in_transaction(db, parent_id, parent[1])
            if outputs["state"] != "CONFIRMED":
                raise ValueError("委派需要当前成果要求")
            bi = None
            if method["sop_id"] == "SOP03":
                from hermes_bi_authority import HermesBIQueryAuthority
                bi = HermesBIQueryAuthority(self.services.scope).require_in_transaction(db, self)[0]
            parent_method = {key: method[key] for key in ("sop_id", "name", "version", "content_sha256")}
            goal = json.dumps({"goal": snapshot["goal"], "additional_inputs": [item[4] for item in snapshot["inputs"]],
                               "delegated_task": description}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            request_digest = checksum({"parent_run_id": parent_id, "goal_revision": parent[1], "description": description})
            tool_key = "delegate:" + checksum(request_key)
            previous = db.execute("SELECT request_digest,tool_name,lease_epoch FROM agent_tool_reservations WHERE run_id=? AND request_key=?", (parent_id, tool_key)).fetchone()
            if previous is not None and previous != (request_digest, "create_child", self.sink.config.lease_epoch):
                raise web.HTTPConflict(text="委派请求编号对应的内容已经变化")
            root = store.require_active_lineage(db, parent_id)
            limit = db.execute("SELECT max_tools FROM agent_tool_budgets WHERE root_run_id=?", (root,)).fetchone()
            if limit is None:
                raise web.HTTPServiceUnavailable(text="根运行工具预算尚未配置")
            if previous is None and db.execute("SELECT count(*) FROM agent_tool_reservations WHERE root_run_id=?", (root,)).fetchone()[0] >= limit[0]:
                raise web.HTTPTooManyRequests(text="根运行工具预算已经用尽")
            reserved = tool_budget.reserve_in_transaction(db, parent_id, self.sink.lease_owner, self.sink.config.lease_epoch,
                                                          tool_key, request_digest, "create_child")
            if reserved:
                store._record_event(db, parent_id, "TOOL_STARTED", {"tool_id": "create_child", "call_id": tool_key},
                                    self.sink.config.lease_epoch, "delegate-start:" + checksum(request_key))
            child = store.create_child_run_in_transaction(db, parent_id, self.sink.lease_owner, self.sink.config.lease_epoch,
                "delegate:" + parent_id + ":" + request_key, request_digest)
            expected = {"child_run_id": child, "parent_run_id": parent_id, "parent_epoch": self.sink.config.lease_epoch,
                        "parent_goal_revision": parent[1], "parent_goal_sha256": checksum(snapshot),
                        "scope_sha256": scope_digest, "method_sha256": checksum(parent_method),
                        "requirements_sha256": checksum(outputs["required_outputs"]),
                        "bi_binding_sha256": bi["binding_sha256"] if bi is not None else None,
                        "goal_sha256": checksum(goal), "request_digest": request_digest}
            row = db.execute("SELECT body FROM objects WHERE namespace=? AND kind='hermes_child_authorization' AND id=?", (parent[4], child)).fetchone()
            if row is None:
                db.execute("UPDATE agent_runs SET goal=? WHERE run_id=? AND status='QUEUED' AND lease_epoch=0", (goal, child))
                if db.execute("SELECT changes()").fetchone() != (1,):
                    raise ValueError("子运行目标不可登记")
                encoded = json.dumps(parent_method, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                db.execute("INSERT INTO agent_run_method_selections VALUES (?,?,?,?,?,?)",
                           (child, 1, encoded, checksum(parent_method), checksum(goal), scope_digest))
                RunRequirements.save_in_transaction(db, child, 1, "delegate:" + checksum(request_key), outputs["required_outputs"])
                if bi is not None:
                    prepared = {key: value for key, value in bi.items() if key not in {"run_id", "goal_revision", "goal_snapshot_sha256"}}
                    prepared["goal_sha256"] = checksum(goal)
                    HermesBIQueryAuthority(self.services.scope).save_in_transaction(db, child, prepared)
                self.services.scope.store.put(db, parent[4], "hermes_child_authorization", child, expected)
            elif json.loads(row[0]) != expected:
                raise ValueError("委派授权记录已经变化")
            saved_method = selection.read_in_transaction(db, child, 1)
            saved_outputs = RunRequirements.read_in_transaction(db, child, 1)
            saved_goal = db.execute("SELECT parent_run_id,goal,scope_proof,goal_revision,applied_goal_revision FROM agent_runs WHERE run_id=?", (child,)).fetchone()
            if saved_goal != (parent_id, goal, parent[3], 1, 1) or saved_method != {**parent_method, "goal_revision": 1, "state": "SELECTED"} or saved_outputs["required_outputs"] != outputs["required_outputs"]:
                raise ValueError("子运行授权内容不可核查")
            if bi is not None:
                saved_bi = db.execute("SELECT body FROM objects WHERE namespace=? AND kind='hermes_bi_query_authorization' AND id=?", (parent[4], child)).fetchone()
                if saved_bi is None or json.loads(saved_bi[0]).get("binding_sha256") != bi["binding_sha256"]:
                    raise ValueError("子运行经营授权不可核查")
            if reserved:
                store._record_event(db, parent_id, "TOOL_FINISHED", {"tool_id": "create_child", "call_id": tool_key, "outcome": "RETURNED"},
                                    self.sink.config.lease_epoch, "delegate-finish:" + checksum(request_key))
            self.require_in_transaction(db)
            return {"run_id": child, "parent_run_id": parent_id, "parent_goal_revision": parent[1], "goal_revision": 1}

    async def dispatch_child(self, child_id, request_key):
        from uuid import UUID
        if not isinstance(child_id, str) or str(UUID(child_id)) != child_id or not isinstance(request_key, str) or not request_key.strip() or len(request_key) > 128:
            raise ValueError("委派派发请求无效")
        if self.execution_factory is None:
            raise web.HTTPServiceUnavailable(text="委派执行工厂尚未准备")
        selection = self.services.broker.method_selection
        if not isinstance(selection, AgentRunMethodSelection):
            raise ValueError("委派需要当前运行方法服务")
        with selection.drafts._locked(), self.sink.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self.require_in_transaction(db)
            row = db.execute("SELECT parent_run_id,revision FROM agent_runs WHERE run_id=?", (child_id,)).fetchone()
            if row is None or row[0] != self.sink.config.run_id:
                raise web.HTTPForbidden(text="子运行不属于当前委派")
            self.dispatcher._verify_child_authorizations_in_transaction(db, child_id)
            tool_key = "delegate-dispatch:" + checksum(request_key)
            tool_digest = checksum({"child_run_id": child_id})
            reserved = self.reserve_delegate_tool_in_transaction(db, tool_key, tool_digest, "dispatch_managed_child")
            if reserved:
                self.sink.store._record_event(db, self.sink.config.run_id, "TOOL_STARTED", {"tool_id": "dispatch_managed_child", "call_id": tool_key},
                    self.sink.config.lease_epoch, "delegate-dispatch-start:" + checksum(request_key))
            prior = db.execute("SELECT expected_revision FROM agent_dispatch_receipts WHERE run_id=? AND request_key=?", (child_id, request_key)).fetchone()
            revision = prior[0] if prior is not None else row[1]
        dispatcher = type(self.dispatcher)(self.services, self.execution_factory)
        result = await dispatcher.dispatch(self.request, child_id, revision, request_key)
        with selection.drafts._locked(), self.sink.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self.require_in_transaction(db)
            origin = "delegate-dispatch-finish:" + checksum(request_key)
            if db.execute("SELECT 1 FROM agent_run_events WHERE run_id=? AND lease_epoch=? AND origin_event_id=?", (self.sink.config.run_id, self.sink.config.lease_epoch, origin)).fetchone() is None:
                self.sink.store._record_event(db, self.sink.config.run_id, "TOOL_FINISHED", {"tool_id": "dispatch_managed_child", "call_id": tool_key, "outcome": "RETURNED"},
                    self.sink.config.lease_epoch, origin)
        return result

    def child_result(self, child_id, request_key):
        from uuid import UUID
        if not isinstance(child_id, str) or str(UUID(child_id)) != child_id or not isinstance(request_key, str) or not request_key.strip() or len(request_key) > 128:
            raise ValueError("子运行编号无效")
        selection = self.services.broker.method_selection
        if not isinstance(selection, AgentRunMethodSelection):
            raise ValueError("委派需要当前运行方法服务")
        tool_key = "delegate-result:" + checksum(request_key)
        with selection.drafts._locked():
            with self.sink.store.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                self.require_in_transaction(db)
                row = db.execute("SELECT parent_run_id FROM agent_runs WHERE run_id=?", (child_id,)).fetchone()
                if row is None or row[0] != self.sink.config.run_id:
                    raise web.HTTPForbidden(text="子运行不属于当前委派")
                self.dispatcher._verify_child_authorizations_in_transaction(db, child_id)
                reserved = self.reserve_delegate_tool_in_transaction(db, tool_key, checksum({"child_run_id": child_id}), "read_managed_child_result")
                if reserved:
                    self.sink.store._record_event(db, self.sink.config.run_id, "TOOL_STARTED", {"tool_id": "read_managed_child_result", "call_id": tool_key}, self.sink.config.lease_epoch, "delegate-result-start:" + checksum(request_key))
            with self.sink.store.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                self.require_in_transaction(db)
                row = db.execute("SELECT parent_run_id,status,goal_revision FROM agent_runs WHERE run_id=?", (child_id,)).fetchone()
                if row is None or row[0] != self.sink.config.run_id:
                    raise web.HTTPForbidden(text="子运行不属于当前委派")
                self.dispatcher._verify_child_authorizations_in_transaction(db, child_id)
                result = self.sink.store.result_in_transaction(db, child_id, row[2])
                if result is None:
                    raise web.HTTPConflict(text="子运行结果尚未登记")
                self.require_in_transaction(db)
                origin = "delegate-result-finish:" + checksum(request_key)
                if db.execute("SELECT 1 FROM agent_run_events WHERE run_id=? AND lease_epoch=? AND origin_event_id=?", (self.sink.config.run_id, self.sink.config.lease_epoch, origin)).fetchone() is None:
                    self.sink.store._record_event(db, self.sink.config.run_id, "TOOL_FINISHED", {"tool_id": "read_managed_child_result", "call_id": tool_key, "outcome": "RETURNED"}, self.sink.config.lease_epoch, origin)
                return {"run_id": child_id, "status": row[1], "result": result}
