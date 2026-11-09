import json
from dataclasses import asdict, dataclass
from pathlib import Path

from aiohttp import web

from business import checksum, require
from boss_conversation_sources import ConversationSources
from boss_execution_transition import pending_transition
from boss_memory_sessions import MemorySessionManager
from boss_simulation_api import _context
from boss_source_access import require_current_business_source


@dataclass(frozen=True)
class RunScopeProof:
    namespace: str
    owner_id: str
    dataset_id: str
    dataset_version: str
    chat_id: str
    session_id: str
    native_session_created_at: str
    binding_id: str | None
    context_version: str | None
    source_pins: tuple[tuple[str, str, str], ...]


class RunScopeService:
    def __init__(self, store, sessions, namespace):
        require(isinstance(sessions, MemorySessionManager) and sessions.namespace == namespace
                and sessions.business_store.path.resolve() == store.path.resolve(),
                "会话管理器与当前执行空间不符", web.HTTPForbidden)
        self.store = store
        self.namespace = namespace
        self.sources = ConversationSources(store, sessions)

    def prove(self, chat_id, selected_refs):
        with self.store.connect() as db:
            db.execute("BEGIN")
            return self.prove_in_transaction(db, chat_id, selected_refs)

    def prove_in_transaction(self, db, chat_id, selected_refs):
        require(isinstance(selected_refs, list) and all(isinstance(item, str) and item for item in selected_refs)
                and len(set(selected_refs)) == len(selected_refs), "来源选择字段无效", web.HTTPBadRequest)
        require(db.in_transaction, "范围核查需要当前事务", web.HTTPConflict)
        main = db.execute("PRAGMA database_list").fetchone()
        require(main is not None and main[1] == "main" and Path(main[2]).resolve() == self.store.path.resolve(),
                "范围核查与业务数据库不符", web.HTTPForbidden)
        context = _context(db)
        require(context["namespace"] == self.namespace and pending_transition(db, self.namespace) is None,
                "执行空间不再可用", web.HTTPConflict)
        session = self.sources._session(db, context, chat_id)
        binding = self.sources._binding(db, context, session)
        pins = []
        if binding is not None:
            for ref in binding["source_pins"]:
                document = require_current_business_source(self.store, db, self.namespace, context["owner_id"], ref["source_id"])
                require(document["version"] == ref["version"] and checksum(document) == ref["content_sha256"],
                        "会话来源版本已经变化", web.HTTPConflict)
                pins.append((ref["source_id"], ref["version"], ref["content_sha256"]))
        require(set(selected_refs).issubset({pin[0] for pin in pins}), "来源未获会话选择", web.HTTPForbidden)
        return RunScopeProof(context["namespace"], context["owner_id"], context["dataset_id"], context["dataset_version"],
                             session["chat_id"], session["session_id"], session["native_session_created_at"],
                             binding["binding_id"] if binding is not None else None,
                             binding["context_version"] if binding is not None else None,
                             tuple(pin for pin in pins if pin[0] in selected_refs))

    def read_source_in_transaction(self, db, run_store, run_id, lease_owner, lease_epoch, source_id):
        from agent_run_store import RunStore

        require(isinstance(run_store, RunStore) and run_store.path.resolve() == self.store.path.resolve(),
                "运行与来源数据库不符", web.HTTPForbidden)
        require(db.in_transaction and isinstance(source_id, str) and bool(source_id), "来源读取参数无效", web.HTTPBadRequest)
        main = db.execute("PRAGMA database_list").fetchone()
        require(main is not None and main[1] == "main" and Path(main[2]).resolve() == self.store.path.resolve(),
                "来源读取与业务数据库不符", web.HTTPForbidden)
        run_store._require_lease(db, run_id, lease_owner, lease_epoch)
        run_store.require_active_lineage(db, run_id)
        row = db.execute("SELECT actor_id,space_id,conversation_id,selected_refs,scope_proof,status FROM agent_runs WHERE run_id=?", (run_id,)).fetchone()
        require(row is not None and row[5] == "RUNNING" and row[3] is not None and row[4] is not None, "运行状态不可读取来源", web.HTTPForbidden)
        refs = json.loads(row[3])
        require(source_id in refs, "来源未获当前运行选择", web.HTTPForbidden)
        proof = self.prove_in_transaction(db, row[2], refs)
        require((proof.owner_id, proof.namespace) == row[:2]
                and json.loads(json.dumps(asdict(proof), ensure_ascii=False)) == json.loads(row[4]), "运行来源范围已经变化", web.HTTPForbidden)
        return require_current_business_source(self.store, db, proof.namespace, proof.owner_id, source_id)
