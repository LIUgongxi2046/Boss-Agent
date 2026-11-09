import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from aiohttp import web

from agent_run_concurrency import RunConcurrencyBudget
from agent_run_store import RunStore, utc_now
from hermes_bridge import EngineEventSink
from hermes_process_evidence import HermesProcessEvidence


class HermesRunRecovery:
    def __init__(self, channel, scope, store):
        from role_channel import RoleChannel
        from agent_run_scope import RunScopeService
        if not isinstance(channel, RoleChannel) or not isinstance(scope, RunScopeService) or not isinstance(store, RunStore):
            raise ValueError("运行恢复缺少产品身份或范围服务")
        if channel.boss_commands is None or channel.boss_commands.store.path.resolve() != store.path.resolve() or scope.store.path.resolve() != store.path.resolve() or channel.gateway.session_manager is not scope.sources.sessions:
            raise ValueError("运行恢复服务不属于同一环境")
        self.channel, self.scope, self.store = channel, scope, store

    def authorize_start(self, request, sink):
        if not isinstance(request, web.Request) or not isinstance(sink, EngineEventSink) or sink.store.path.resolve() != self.store.path.resolve():
            raise ValueError("运行启动缺少实际产品请求或运行入口")
        self.channel.require_run_api_role(request)
        from hermes_legacy_routes import guard_legacy_adoption_in_transaction, load_legacy_inventory
        inventory = load_legacy_inventory(self.scope)
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self.store._require_lease(db, sink.config.run_id, sink.lease_owner, sink.config.lease_epoch)
            self.store.require_active_lineage(db, sink.config.run_id)
            row = db.execute("SELECT actor_id,space_id,conversation_id,selected_refs,scope_proof,status,cancel_requested_at FROM agent_runs WHERE run_id=?", (sink.config.run_id,)).fetchone()
            if row is None or row[3] is None or row[4] is None or row[5:] != ("RUNNING", None):
                raise ValueError("运行身份或来源范围不可核查")
            self.channel.require_run_subscription(request, row[2])
            proof = self.scope.prove_in_transaction(db, row[2], json.loads(row[3]))
            if (proof.owner_id, proof.namespace) != row[:2] or json.loads(json.dumps(asdict(proof))) != json.loads(row[4]):
                raise ValueError("运行来源范围已经变化")
            with guard_legacy_adoption_in_transaction(db, inventory, self.scope, self.store, sink.config.run_id, sink.lease_owner, sink.config.lease_epoch):
                self.channel.require_run_subscription(request, row[2])
                return {"run_id": sink.config.run_id, "actor_id": row[0], "space_id": row[1], "lease_owner": sink.lease_owner, "lease_epoch": sink.config.lease_epoch}

    def recover_expired(self, run_id, actor_id, space_id):
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            return self._recover_expired_in_transaction(db, run_id, actor_id, space_id)

    def recover_expired_authenticated_in_transaction(self, db, request, run_id):
        main = db.execute("PRAGMA database_list").fetchone()
        if not db.in_transaction or main is None or main[1] != "main" or Path(main[2]).resolve() != self.store.path.resolve():
            raise ValueError("本人恢复需要同一数据库写事务")
        if not isinstance(request, web.Request):
            raise ValueError("本人恢复需要实际产品请求")
        self.channel.require_run_api_role(request)
        from boss_simulation_api import _context
        context = _context(db)
        row = db.execute("SELECT actor_id,space_id,conversation_id,selected_refs,scope_proof FROM agent_runs WHERE run_id=?", (run_id,)).fetchone()
        if row is None or row[:2] != (context["owner_id"], context["namespace"]) or row[3] is None or row[4] is None:
            raise ValueError("运行身份或来源范围不可核查")
        self.channel.require_run_subscription(request, row[2])
        proof = self.scope.prove_in_transaction(db, row[2], json.loads(row[3]))
        if (proof.owner_id, proof.namespace) != row[:2] or json.loads(json.dumps(asdict(proof))) != json.loads(row[4]):
            raise ValueError("运行来源范围已经变化")
        from hermes_source_invalidation import require_source_cleanup_complete
        require_source_cleanup_complete(db, run_id)
        from agent_run_memory_guard import require_current_run_memory_in_transaction
        require_current_run_memory_in_transaction(db, self.scope.store, run_id)
        self.channel.require_run_subscription(request, row[2])
        return self._recover_expired_in_transaction(db, run_id, context["owner_id"], context["namespace"])

    def recover_vm_expired(self, request, run_id, manager, workspace_root):
        from hermes_cpu_budget import HermesCPUBudget
        from hermes_vm_host import HermesVMHostClient
        from hermes_vm_identity import HermesVMRecoveryAccess, HermesVMRunBindings
        from hermes_vm_manager import HermesVMManager
        if not isinstance(request, web.Request) or not isinstance(manager, HermesVMManager):
            raise ValueError("虚拟机恢复需要本人请求和受管实例")
        workspace_root = Path(workspace_root)
        if not workspace_root.is_absolute() or workspace_root.resolve(strict=True) != workspace_root or not workspace_root.is_dir():
            raise ValueError("虚拟机恢复工作区根目录不可核查")
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self.recover_expired_authenticated_in_transaction(db, request, run_id)
            rows = db.execute("SELECT b.request_key,b.lease_owner,b.lease_epoch,b.vm_id,b.boot_id FROM hermes_vm_run_bindings b JOIN hermes_cpu_sources s ON s.run_id=b.run_id AND s.request_key=b.request_key JOIN agent_runs r ON r.run_id=b.run_id WHERE b.run_id=? AND b.lease_epoch=r.lease_epoch AND s.source='SLICE_CPU_NSEC_V1' ORDER BY b.request_key", (run_id,)).fetchall()
        bindings = HermesVMRunBindings(self.store)
        cpu_budget = HermesCPUBudget(self.store)
        for key, owner, epoch, vm_id, boot_id in rows:
            access = HermesVMRecoveryAccess(bindings, run_id, key, owner, epoch, vm_id, boot_id, workspace_root / run_id, self, request)
            manager.require_live(access)
            host = HermesVMHostClient(access, manager.control.context, manager.control.guest_name,
                                      manager.control.guest_certificate_sha256, manager.control.control_port)
            host.stop_for_recovery()
            if host.final_exit_status() == "UNKNOWN":
                continue
            cpu_budget.record_unknown_exit(host)
            cpu_budget.record_unknown_exit_observation(host)
            cpu_budget.settle_final_exit(host)
            cpu_budget.cleanup_settled_exit(host)
            manager.require_live(access)
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            return self.recover_expired_authenticated_in_transaction(db, request, run_id)

    def _recover_expired_in_transaction(self, db, run_id, actor_id, space_id):
        budget = RunConcurrencyBudget(self.store)
        HermesProcessEvidence(self.store)
        row = db.execute("SELECT actor_id,space_id,status,lease_owner,lease_epoch,lease_expires_at FROM agent_runs WHERE run_id=?", (run_id,)).fetchone()
        if row is None or row[:2] != (actor_id, space_id):
            raise ValueError("运行身份不可核查")
        if row[2] not in {"RUNNING", "WAITING_INPUT", "WAITING_CONFIRMATION", "CANCEL_REQUESTED", "RECONCILING", "INTERRUPTED"}:
            raise ValueError("运行状态不可恢复")
        if row[5] is not None and datetime.fromisoformat(row[5]) > utc_now():
            raise ValueError("原租约仍然有效")
        if row[2] != "INTERRUPTED" and row[5] is None:
            raise ValueError("原租约不可核查")
        if (row[3] is None) != (row[5] is None):
            raise ValueError("原租约不可核查")
        reservations = db.execute("SELECT request_key,request_digest,lease_owner,lease_epoch,state FROM agent_concurrency_reservations WHERE run_id=?", (run_id,)).fetchall()
        for key, digest, owner, epoch, state in reservations:
            evidence = db.execute("SELECT request_digest,lease_owner,lease_epoch,actor_id,space_id,state FROM hermes_process_evidence WHERE run_id=? AND request_key=?", (run_id, key)).fetchone()
            if evidence is not None and evidence[:5] != (digest, owner, epoch, actor_id, space_id):
                raise ValueError("进程记录与并发预留不一致")
            if evidence is not None and state == "RELEASED":
                final_table = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='hermes_cpu_final_exits'").fetchone()
                if final_table is None or db.execute("SELECT 1 FROM hermes_cpu_final_exits f JOIN hermes_vm_run_bindings b ON b.run_id=f.run_id AND b.request_key=f.request_key WHERE f.run_id=? AND f.request_key=? AND f.lease_epoch=? AND b.lease_owner=? AND b.lease_epoch=f.lease_epoch AND b.vm_id=f.vm_id AND b.boot_id=f.boot_id AND b.unit_name=f.unit AND f.source='SLICE_CPU_NSEC_V1'", (run_id, key, epoch, owner)).fetchone() is None:
                    raise ValueError("进程记录对应的并发预留已经释放，无法确认完整回收")
            if state == "ACTIVE":
                budget.mark_unknown_in_transaction(db, run_id, key)
            if evidence is not None and evidence[5] in {"STARTING", "RUNNING"}:
                db.execute("UPDATE hermes_process_evidence SET state='UNKNOWN',updated_at=? WHERE run_id=? AND request_key=?", (utc_now().isoformat(), run_id, key))
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='agent_dispatch_receipts'").fetchone() is not None:
            from agent_run_dispatcher import AgentRunDispatcher
            AgentRunDispatcher.mark_expired_dispatch_unknown_in_transaction(self.store, db, run_id, row[3], row[4])
        if row[2] != "INTERRUPTED":
            db.execute("UPDATE agent_runs SET status='INTERRUPTED',lease_owner=NULL,lease_expires_at=NULL,revision=revision+1 WHERE run_id=?", (run_id,))
            self.store._record_event(db, run_id, "STATUS_CHANGED", {"from": row[2], "to": "INTERRUPTED"}, row[4])
        elif row[3] is not None:
            db.execute("UPDATE agent_runs SET lease_owner=NULL,lease_expires_at=NULL,revision=revision+1 WHERE run_id=?", (run_id,))
        unknown = db.execute("SELECT count(*) FROM agent_concurrency_reservations WHERE run_id=? AND state='UNKNOWN'", (run_id,)).fetchone()[0]
        return {"run_id": run_id, "status": "INTERRUPTED", "unknown_reservations": unknown}

def inspect_recovery(store, run_id, actor_id, space_id):
    if not isinstance(store, RunStore) or any(not isinstance(value, str) or not value.strip() for value in (run_id, actor_id, space_id)):
        raise ValueError("恢复查询参数无效")
    with store.connect() as db:
        db.execute("BEGIN")
        row = db.execute("SELECT status,revision,goal_revision,applied_goal_revision,cancel_requested_at,lease_owner,lease_expires_at FROM agent_runs WHERE run_id=? AND actor_id=? AND space_id=?", (run_id, actor_id, space_id)).fetchone()
        if row is None:
            raise ValueError("运行身份不可核查")
        if row[0] not in {"INTERRUPTED", "CANCEL_REQUESTED", "RECONCILING", "FAILED"}:
            raise ValueError("运行状态不可恢复查询")
        if row[5] is not None and row[6] is not None and datetime.fromisoformat(row[6]) > utc_now():
            raise ValueError("原租约仍然有效")
        intents = []
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='agent_intents'").fetchone() is not None:
            for identifier, action, status, revision, request_key, authorization_id, result_ref, digest, raw_preview in db.execute(
                    "SELECT intent_id,action,status,revision,request_key,authorization_id,result_ref,payload_digest,preview FROM agent_intents WHERE run_id=? AND actor_id=? AND space_id=? ORDER BY created_at,intent_id",
                    (run_id, actor_id, space_id)).fetchall():
                preview = json.loads(raw_preview)
                intents.append({"intent_id": identifier, "action": action, "status": status, "revision": revision,
                                "request_key": request_key, "authorization_id": authorization_id,
                                "result_ref": result_ref, "payload_digest": digest, "preview": preview,
                                "source_refs": preview.get("source_refs") if isinstance(preview, dict) else None})
        receipts = []
        if intents and db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='agent_intent_decisions'").fetchone() is not None:
            for request_key, identifier, raw_receipt in db.execute(
                    "SELECT d.request_key,d.intent_id,d.receipt FROM agent_intent_decisions d JOIN agent_intents i ON i.intent_id=d.intent_id WHERE i.run_id=? AND d.actor_id=? AND d.space_id=? ORDER BY d.created_at,d.request_key",
                    (run_id, actor_id, space_id)).fetchall():
                receipts.append({"request_key": request_key, "intent_id": identifier, "receipt": json.loads(raw_receipt)})
        process = []
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='hermes_process_evidence'").fetchone() is not None:
            process = [{"request_key": key, "state": state, "exit_code": exit_code, "exit_scope": scope}
                       for key, state, exit_code, scope in db.execute(
                           "SELECT request_key,state,exit_code,exit_scope FROM hermes_process_evidence WHERE run_id=? ORDER BY request_key",
                           (run_id,)).fetchall()]
        unknown = 0
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='agent_concurrency_reservations'").fetchone() is not None:
            unknown = db.execute("SELECT count(*) FROM agent_concurrency_reservations WHERE run_id=? AND state='UNKNOWN'", (run_id,)).fetchone()[0]
        return {"run_id": run_id, "status": row[0], "revision": row[1], "goal_revision": row[2],
                "applied_goal_revision": row[3], "cancel_requested": row[4] is not None,
                "intents": intents, "receipts": receipts,
                "original_receipt": receipts[0] if len(receipts) == 1 else None,
                "process_evidence": process, "unknown_reservations": unknown,
                "duplicate_execution_allowed": False, "automatic_requeue": False,
                "recovery_action": "QUERY_ORIGINAL_RECEIPT" if receipts else "NO_RECORDED_DECISION"}
