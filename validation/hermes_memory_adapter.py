import json
from dataclasses import asdict

from agent_run_scope import RunScopeService
from boss_execution_transition import pending_transition
from boss_memory_runtime import memory_adoption
from boss_simulation_api import _context
from business import checksum
from hermes_bridge import EngineEventSink


def hermes_memory_settings(enabled_toolsets):
    if not isinstance(enabled_toolsets, list) or any(value != "boss_domain" for value in enabled_toolsets) or len(set(enabled_toolsets)) != len(enabled_toolsets):
        raise ValueError("Hermes 工具集不在获准范围")
    return {"enabled_toolsets": list(enabled_toolsets), "disabled_toolsets": ["memory"],
            "skip_memory": True, "skip_context_files": True, "load_soul_identity": False,
            "checkpoints_enabled": False, "save_trajectories": False}


class HermesMemoryAdapter:
    def __init__(self, store, scope_service, *, run_gate):
        if not isinstance(scope_service, RunScopeService) or not isinstance(run_gate, EngineEventSink):
            raise ValueError("需要实际运行与会话范围服务")
        if store.path.resolve() != scope_service.store.path.resolve() or store.path.resolve() != run_gate.store.path.resolve():
            raise ValueError("记忆、运行和会话必须属于同一数据库")
        self.store = store
        self.scope_service = scope_service
        self.run_gate = run_gate

    def _read(self, db):
        gate = self.run_gate
        gate.store._require_lease(db, gate.config.run_id, gate.lease_owner, gate.config.lease_epoch)
        gate.store.require_active_lineage(db, gate.config.run_id)
        run = db.execute("SELECT actor_id,space_id,conversation_id,selected_refs,scope_proof,status,cancel_requested_at,parent_run_id FROM agent_runs WHERE run_id=?", (gate.config.run_id,)).fetchone()
        if run is None or run[5] != "RUNNING" or run[6] is not None or run[3] is None or run[4] is None:
            raise ValueError("运行状态或会话范围无效")
        context = _context(db)
        if run[:2] != (context["owner_id"], context["namespace"]) or context["namespace"] != self.scope_service.namespace or pending_transition(db, context["namespace"]) is not None:
            raise ValueError("运行身份或执行空间无效")
        proof = self.scope_service.prove_in_transaction(db, run[2], json.loads(run[3]))
        if json.loads(json.dumps(asdict(proof))) != json.loads(run[4]):
            raise ValueError("运行会话或来源范围已经变化")
        reference, eligible = memory_adoption(self.store, db, context["namespace"])
        marker = {"owner_id": context["owner_id"], "namespace": context["namespace"],
                  "dataset_id": context["dataset_id"], "dataset_version": context["dataset_version"],
                  "conversation_id": run[2], "scope_sha256": checksum(asdict(proof)),
                  "memory_reference": reference, "content_sha256": checksum(eligible) if eligible is not None else None}
        return marker, eligible, run[7]

    def _saved(self, db, namespace, run_id):
        row = db.execute("SELECT body FROM objects WHERE namespace=? AND kind='hermes_memory_adoption' AND id=?", (namespace, run_id)).fetchone()
        return json.loads(row[0]) if row is not None else None

    def _require_saved(self, db, marker, run_id):
        invalid = db.execute("SELECT 1 FROM objects WHERE namespace=? AND kind='hermes_memory_invalidation' AND id=?", (marker["namespace"], run_id)).fetchone()
        if invalid is not None:
            raise ValueError("运行记忆引用已经失效，旧上下文不能继续采用")
        saved = self._saved(db, marker["namespace"], run_id)
        if saved is None or saved != marker:
            raise ValueError("运行记忆引用缺少或已经变化，旧上下文不能继续采用")

    def read(self):
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            marker, eligible, parent = self._read(db)
            if parent is not None:
                self._require_saved(db, marker, parent)
            saved = self._saved(db, marker["namespace"], self.run_gate.config.run_id)
            if saved is None:
                invalid = db.execute("SELECT 1 FROM objects WHERE namespace=? AND kind='hermes_memory_invalidation' AND id=?", (marker["namespace"], self.run_gate.config.run_id)).fetchone()
                if invalid is not None:
                    raise ValueError("运行记忆引用已经失效，旧上下文不能继续采用")
                self.store.put(db, marker["namespace"], "hermes_memory_adoption", self.run_gate.config.run_id, marker)
            else:
                self._require_saved(db, marker, self.run_gate.config.run_id)
            return {"reference": marker, "memory": {key: eligible[key] for key in ("memory_id", "version", "confirmation_state", "text")} if eligible is not None else None}

    def require_current(self, reference):
        if not isinstance(reference, dict):
            raise ValueError("记忆引用无效")
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            current, _, parent = self._read(db)
            self._require_saved(db, current, self.run_gate.config.run_id)
            if parent is not None:
                self._require_saved(db, current, parent)
            if reference != current:
                raise ValueError("记忆或执行空间已经变化，旧上下文不能继续采用")
