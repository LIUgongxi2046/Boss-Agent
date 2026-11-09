import json
from pathlib import Path

from aiohttp import web

from agent_memory_deletion_log import require_memory_deletion_propagation_in_transaction
from agent_run_scope import RunScopeService
from agent_run_store import RunStore
from boss_execution_transition import pending_transition
from boss_simulation_api import _context
from boss_source_access import require_current_business_source, require_current_simulated_source
from business import checksum


class AgentSourceHistory:
    def __init__(self, runs, scope):
        if not isinstance(runs, RunStore) or not isinstance(scope, RunScopeService) or runs.path.resolve() != scope.store.path.resolve():
            raise ValueError("来源历史需要同一业务数据库")
        self.runs, self.scope = runs, scope

    def retain_citations_in_transaction(self, db, proof, citations, *, run_id=None):
        main = db.execute("PRAGMA database_list").fetchone()
        if not db.in_transaction or main is None or main[1] != "main" or Path(main[2]).resolve() != self.runs.path.resolve():
            raise ValueError("来源版本保存需要同一数据库事务")
        if not citations:
            return
        require_memory_deletion_propagation_in_transaction(self.scope.store, db, proof.namespace)
        if run_id is not None:
            if db.execute("SELECT 1 FROM objects WHERE namespace=? AND kind='hermes_memory_invalidation' AND id=?", (proof.namespace, run_id)).fetchone() is not None:
                raise ValueError("运行记忆引用已经失效")
        elif db.execute("SELECT 1 FROM objects WHERE namespace=? AND kind='hermes_memory_invalidation' LIMIT 1", (proof.namespace,)).fetchone() is not None:
            raise ValueError("个人记忆删除传播尚未核查")
        pins = {pin[0]: (pin[1], pin[2]) for pin in proof.source_pins}
        for source_id in sorted({item["source_id"] for item in citations}):
            if source_id not in pins:
                raise ValueError("来源版本未获当前运行选择")
            document = require_current_business_source(self.scope.store, db, proof.namespace, proof.owner_id, source_id)
            version, digest = pins[source_id]
            if document.get("version") != version or checksum(document) != digest:
                raise ValueError("来源版本或摘要已经变化")
            saved = db.execute("SELECT body FROM objects WHERE namespace=? AND kind='document_revision' AND id=?", (proof.namespace, source_id + ":v" + version)).fetchone()
            if saved is not None:
                if checksum(json.loads(saved[0])) != digest:
                    raise ValueError("已有来源版本与当前内容不一致")
            else:
                self.scope.store.put(db, proof.namespace, "document_revision", source_id + ":v" + version, document)

    def read_artifact_in_transaction(self, db, run_id, artifact_id, artifact_version, source_id, version):
        main = db.execute("PRAGMA database_list").fetchone()
        if not db.in_transaction or main is None or main[1] != "main" or Path(main[2]).resolve() != self.runs.path.resolve():
            raise ValueError("成果来源历史需要同一数据库事务")
        if any(not isinstance(value, str) or not value.strip() or len(value) > 160 for value in (run_id, artifact_id, source_id, version)) or type(artifact_version) is not int or artifact_version < 1:
            raise ValueError("成果来源历史参数无效")
        context = _context(db)
        namespace = context["namespace"]
        if pending_transition(db, namespace) is not None:
            raise web.HTTPConflict(text="当前执行空间正在切换")
        run = db.execute("SELECT actor_id,space_id,conversation_id,selected_refs,scope_proof FROM agent_runs WHERE run_id=?", (run_id,)).fetchone()
        if run is None or run[:2] != (context["owner_id"], namespace) or run[3] is None or run[4] is None:
            raise web.HTTPNotFound(text="运行来源不可读取")
        selected, original = json.loads(run[3]), json.loads(run[4])
        if source_id not in selected or any(original.get(key) != context[key] for key in ("owner_id", "namespace", "dataset_id", "dataset_version")):
            raise web.HTTPForbidden(text="来源不属于原运行范围")
        proof = self.scope.prove_in_transaction(db, run[2], [source_id])
        fields = ("owner_id", "namespace", "dataset_id", "dataset_version", "chat_id", "session_id", "native_session_created_at")
        if any(getattr(proof, key) != original.get(key) for key in fields):
            raise web.HTTPForbidden(text="本人会话或资料范围已经变化")
        require_memory_deletion_propagation_in_transaction(self.scope.store, db, namespace)
        if db.execute("SELECT 1 FROM objects WHERE namespace=? AND kind='hermes_memory_invalidation' AND id=?", (namespace, run_id)).fetchone() is not None:
            raise web.HTTPConflict(text="运行记忆引用已经失效")
        if db.execute("SELECT 1 FROM objects WHERE namespace=? AND kind='hermes_source_cleanup' AND id=?", (namespace, source_id)).fetchone() is not None:
            raise web.HTTPGone(text="来源撤销或清理已经开始")
        current = require_current_business_source(self.scope.store, db, namespace, context["owner_id"], source_id)
        artifact = db.execute("SELECT run_id,version,media_type,sha256,size_bytes,source_refs,context,verification_status,status FROM agent_artifacts WHERE artifact_id=?", (artifact_id,)).fetchone()
        if artifact is None or artifact[:2] != (run_id, artifact_version) or artifact[7] != "VERIFIED" or artifact[8] not in {"VERIFIED", "PUBLISHED"}:
            raise web.HTTPNotFound(text="成果不存在或不可读取")
        scope = {key: context[key] for key in ("owner_id", "namespace", "dataset_id", "dataset_version")}
        if json.loads(artifact[6]) != scope or db.execute("SELECT 1 FROM agent_artifact_revocations WHERE artifact_id=?", (artifact_id,)).fetchone() is not None:
            raise web.HTTPForbidden(text="成果范围或状态不可读取")
        if db.execute("SELECT version FROM agent_artifact_versions WHERE artifact_id=?", (artifact_id,)).fetchone() != (artifact_version,) or db.execute("SELECT run_id,status,size_bytes FROM agent_file_reservations WHERE artifact_id=?", (artifact_id,)).fetchone() != (run_id, "COMPLETED", artifact[4]):
            raise web.HTTPConflict(text="成果版本或预留记录不可核查")
        events = db.execute("SELECT payload FROM agent_run_events WHERE run_id=? AND type='ARTIFACT_CANDIDATE' AND json_extract(payload,'$.artifact_id')=?", (run_id, artifact_id)).fetchall()
        expected = {"artifact_id": artifact_id, "version": artifact_version, "media_type": artifact[2], "sha256": artifact[3]}
        if len(events) != 1 or json.loads(events[0][0]) != expected:
            raise web.HTTPConflict(text="成果运行记录不可核查")
        if artifact[8] == "PUBLISHED" and db.execute("SELECT run_id,version,sha256,actor_id FROM agent_artifact_publications WHERE artifact_id=?", (artifact_id,)).fetchone() != (run_id, artifact_version, artifact[3], context["owner_id"]):
            raise web.HTTPConflict(text="成果发布记录不可核查")
        refs = [ref for ref in json.loads(artifact[5]) if ref.get("source_id") == source_id and ref.get("revision") == version]
        pins = [pin for pin in original.get("source_pins", []) if len(pin) == 3 and pin[0] == source_id and pin[1] == version]
        if len(refs) != 1 or len(pins) != 1 or refs[0].get("sha256") != pins[0][2] or refs[0].get("classification") != "SIMULATED":
            raise web.HTTPNotFound(text="成果没有可核查的来源引用")
        digest = pins[0][2]
        if current["version"] == version:
            document = current
        else:
            saved = db.execute("SELECT body FROM objects WHERE namespace=? AND ((kind='document_revision' AND id=?) OR (kind='document_history' AND id=?))", (namespace, source_id + ":v" + version, source_id + ":" + version)).fetchall()
            if not saved:
                raise web.HTTPNotFound(text="历史来源正文未保存")
            documents = [json.loads(item[0]) for item in saved]
            if any(checksum(item) != digest for item in documents):
                raise web.HTTPConflict(text="历史来源版本或摘要不可核查")
            document = documents[0]
        if document.get("source_id") != source_id or document.get("version") != version or checksum(document) != digest:
            raise web.HTTPConflict(text="历史来源版本或摘要不可核查")
        require_current_simulated_source(document, context["owner_id"], context["clock"])
        if not isinstance(document.get("content"), str):
            raise web.HTTPNotFound(text="历史来源正文未保存")
        return {"run_id": run_id, "artifact_id": artifact_id, "artifact_version": artifact_version, "artifact_sha256": artifact[3], "source_id": source_id, "version": version, "sha256": digest, "current_version": current["version"], "historical": current["version"] != version, "title": document.get("title") or source_id, "content": document["content"], "locator": refs[0].get("locator"), "locator_verification": "NOT_VERIFIED"}

    def read_in_transaction(self, db, run_id, event_id, source_id, version):
        main = db.execute("PRAGMA database_list").fetchone()
        if not db.in_transaction or main is None or main[1] != "main" or Path(main[2]).resolve() != self.runs.path.resolve():
            raise ValueError("来源历史需要同一数据库事务")
        if any(not isinstance(value, str) or not value.strip() or len(value) > 160 for value in (run_id, event_id, source_id, version)):
            raise ValueError("来源历史参数无效")
        context = _context(db)
        namespace = context["namespace"]
        if pending_transition(db, namespace) is not None:
            raise web.HTTPConflict(text="当前执行空间正在切换")
        run = db.execute("SELECT actor_id,space_id,conversation_id,selected_refs,scope_proof FROM agent_runs WHERE run_id=?", (run_id,)).fetchone()
        if run is None or run[:2] != (context["owner_id"], namespace) or run[3] is None or run[4] is None:
            raise web.HTTPNotFound(text="运行来源不可读取")
        selected, original = json.loads(run[3]), json.loads(run[4])
        if source_id not in selected or any(original.get(key) != context[key] for key in ("owner_id", "namespace", "dataset_id", "dataset_version")):
            raise web.HTTPForbidden(text="来源不属于原运行范围")
        proof = self.scope.prove_in_transaction(db, run[2], [source_id])
        if (proof.owner_id, proof.namespace, proof.dataset_id, proof.dataset_version, proof.chat_id, proof.session_id, proof.native_session_created_at) != (original["owner_id"], original["namespace"], original["dataset_id"], original["dataset_version"], original["chat_id"], original["session_id"], original["native_session_created_at"]):
            raise web.HTTPForbidden(text="本人会话或资料范围已经变化")
        require_memory_deletion_propagation_in_transaction(self.scope.store, db, namespace)
        if db.execute("SELECT 1 FROM objects WHERE namespace=? AND kind='hermes_memory_invalidation' AND id=?", (namespace, run_id)).fetchone() is not None:
            raise web.HTTPConflict(text="运行记忆引用已经失效")
        if db.execute("SELECT 1 FROM objects WHERE namespace=? AND kind='hermes_source_cleanup' AND id=?", (namespace, source_id)).fetchone() is not None:
            raise web.HTTPGone(text="来源撤销或清理已经开始")
        current = require_current_business_source(self.scope.store, db, namespace, context["owner_id"], source_id)
        row = db.execute("SELECT event_id,seq,type,occurred_at,trace_id,payload_version,payload FROM agent_run_events WHERE run_id=? AND event_id=? AND type='RESULT_RECORDED'", (run_id, event_id)).fetchone()
        if row is None:
            raise web.HTTPNotFound(text="原结果事件不存在")
        event = self.runs._event(run_id, row)
        payload = event["payload"]
        result = self.runs.result_in_transaction(db, run_id, payload["goal_revision"])
        if result is None or result["event_id"] != event_id:
            raise web.HTTPConflict(text="原结果版本不可核查")
        original_pins = [{"source_id": pin[0], "version": pin[1], "content_sha256": pin[2]} for pin in original["source_pins"]]
        if payload["source_pins"] != original_pins or (payload["dataset_id"], payload["dataset_version"]) != (context["dataset_id"], context["dataset_version"]):
            raise web.HTTPConflict(text="原结果来源版本不可核查")
        pins = [pin for pin in original_pins if pin["source_id"] == source_id and pin["version"] == version]
        citations = [item for item in payload["citations"] if item["source_id"] == source_id]
        if len(pins) != 1 or not citations:
            raise web.HTTPNotFound(text="原结果没有对应来源引用")
        if current["version"] == version:
            document = current
        else:
            saved = db.execute("SELECT body FROM objects WHERE namespace=? AND ((kind='document_revision' AND id=?) OR (kind='document_history' AND id=?))", (namespace, source_id + ":v" + version, source_id + ":" + version)).fetchall()
            if not saved:
                raise web.HTTPNotFound(text="历史来源正文未保存")
            versions = [json.loads(item[0]) for item in saved]
            if any(checksum(item) != pins[0]["content_sha256"] for item in versions):
                raise web.HTTPConflict(text="历史来源版本或摘要不可核查")
            document = versions[0]
        if document.get("source_id") != source_id or document.get("version") != version or checksum(document) != pins[0]["content_sha256"]:
            raise web.HTTPConflict(text="历史来源版本或摘要不可核查")
        require_current_simulated_source(document, context["owner_id"], context["clock"])
        if not isinstance(document.get("content"), str):
            raise web.HTTPNotFound(text="历史来源正文未保存")
        return {"run_id": run_id, "event_id": event_id, "source_id": source_id, "version": version, "sha256": pins[0]["content_sha256"], "current_version": current["version"], "historical": current["version"] != version, "title": document.get("title") or source_id, "content": document["content"], "citations": [{"locator": item["locator"], "locator_verification": "NOT_VERIFIED"} for item in citations]}
