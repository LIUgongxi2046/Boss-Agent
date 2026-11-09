import hashlib
import json
from contextlib import nullcontext
from dataclasses import asdict
from pathlib import Path
from uuid import uuid4

from agent_run_scope import RunScopeService
from agent_run_requirements import RunRequirements
from agent_run_store import EVENT_VALIDATOR, RunStore, utc_now
from boss_source_access import require_current_business_source
from business import checksum
from hermes_bridge import EngineEventSink
from hermes_source_invalidation import require_source_cleanup_complete
from agent_artifact_formats import FORMATS


def vm_tree_exit_evidence(db, run_id, epoch):
    if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='hermes_vm_tree_exits'").fetchone() is None:
        return [], False
    migration = Path(__file__).parent / "migrations" / "hermes_cpu_budget_007.sql"
    saved = db.execute("SELECT sha256 FROM agent_schema_migrations WHERE version='hermes_cpu_budget_007'").fetchone()
    if saved is None or tuple(saved) != (hashlib.sha256(migration.read_bytes()).hexdigest(),):
        raise ValueError("虚拟机进程范围退出迁移不可核查")
    rows = db.execute("SELECT p.request_key,p.lease_owner,p.lease_epoch,b.lease_owner,b.lease_epoch,b.vm_id,b.boot_id,b.unit_name,c.lease_owner,c.lease_epoch,c.state,f.lease_epoch,f.vm_id,f.boot_id,f.unit,f.invocation,f.slice,f.cpu_ns,f.source,t.lease_epoch,t.vm_id,t.boot_id,t.unit,t.invocation,t.slice,t.cpu_ns,t.source,o.lease_epoch,o.vm_id,o.boot_id,o.unit,o.invocation,o.unit_state,o.kill_mode FROM hermes_process_evidence p LEFT JOIN hermes_vm_run_bindings b ON b.run_id=p.run_id AND b.request_key=p.request_key LEFT JOIN agent_concurrency_reservations c ON c.run_id=p.run_id AND c.request_key=p.request_key LEFT JOIN hermes_cpu_final_exits f ON f.run_id=p.run_id AND f.request_key=p.request_key LEFT JOIN hermes_vm_tree_exits t ON t.run_id=p.run_id AND t.request_key=p.request_key LEFT JOIN hermes_cpu_exit_observations o ON o.run_id=p.run_id AND o.request_key=p.request_key WHERE p.run_id=? AND p.lease_epoch=? ORDER BY p.request_key", (run_id, epoch)).fetchall()
    verified = bool(rows)
    for row in rows:
        owner, lease_epoch, bound_owner, bound_epoch, vm_id, boot_id, unit, slot_owner, slot_epoch, slot_state = row[1:11]
        final, tree, observation = row[11:19], row[19:27], row[27:34]
        if (owner, lease_epoch, bound_owner, bound_epoch, slot_owner, slot_epoch, slot_state) != (owner, epoch, owner, epoch, owner, epoch, "RELEASED") or not all((vm_id, boot_id, unit)):
            verified = False
        elif final != (epoch, vm_id, boot_id, unit, tree[4], tree[5], tree[6], "SLICE_CPU_NSEC_V1") or tree != (epoch, vm_id, boot_id, unit, final[4], final[5], final[6], "SYSTEMD_CGROUP_EXIT_V1"):
            verified = False
        elif observation[:5] != (epoch, vm_id, boot_id, unit, final[4]) or observation[5] not in {"inactive", "failed"} or observation[6] != "control-group":
            verified = False
    return [tuple(row) for row in rows], verified


def root_vm_tree_exits_verified(db, root_run_id):
    if not db.in_transaction or not isinstance(root_run_id, str) or not root_run_id:
        raise ValueError("根运行范围核查需要当前事务")
    processes = db.execute("SELECT p.run_id,p.lease_epoch,count(*) FROM hermes_process_evidence p JOIN agent_concurrency_reservations c ON c.run_id=p.run_id AND c.request_key=p.request_key WHERE c.root_run_id=? GROUP BY p.run_id,p.lease_epoch", (root_run_id,)).fetchall()
    for run_id, epoch, count in processes:
        records, verified = vm_tree_exit_evidence(db, run_id, epoch)
        if not verified or len(records) != count:
            return False
    return True


class AgentRunResult:
    def __init__(self, store, scope):
        if not isinstance(store, RunStore) or not isinstance(scope, RunScopeService) or store.path.resolve() != scope.store.path.resolve():
            raise ValueError("运行结果服务环境不一致")
        self.store, self.scope = store, scope

    def record(self, sink, origin_event_id, expected_goal_revision, text, citations):
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            return self.record_in_transaction(db, sink, origin_event_id, expected_goal_revision, text, citations)

    def record_in_transaction(self, db, sink, origin_event_id, expected_goal_revision, text, citations):
        main = db.execute("PRAGMA database_list").fetchone()
        if not db.in_transaction or main is None or main[1] != "main" or Path(main[2]).resolve() != self.store.path.resolve():
            raise ValueError("运行结果需要同一数据库事务")
        db.execute("UPDATE agent_runs SET revision=revision WHERE 0")
        if not isinstance(sink, EngineEventSink) or sink.store.path.resolve() != self.store.path.resolve():
            raise ValueError("运行结果需要同一数据库的引擎入口")
        if not isinstance(origin_event_id, str) or not origin_event_id.strip() or len(origin_event_id) > 128 or type(expected_goal_revision) is not int or expected_goal_revision < 1:
            raise ValueError("运行结果请求无效")
        run_id = sink.config.run_id
        self.store._require_lease(db, run_id, sink.lease_owner, sink.config.lease_epoch)
        self.store.require_active_lineage(db, run_id)
        require_source_cleanup_complete(db, run_id)
        from agent_run_memory_guard import require_current_run_memory_in_transaction
        require_current_run_memory_in_transaction(db, self.scope.store, run_id)
        row = db.execute("SELECT actor_id,space_id,conversation_id,selected_refs,scope_proof,status,cancel_requested_at,goal_revision,applied_goal_revision FROM agent_runs WHERE run_id=?", (run_id,)).fetchone()
        if row is None or row[3] is None or row[4] is None or row[5] != "RUNNING" or row[6] is not None:
            raise ValueError("运行状态或目标版本不可保存结果")
        proof = self.scope.prove_in_transaction(db, row[2], json.loads(row[3]))
        if (proof.owner_id, proof.namespace) != tuple(row[:2]) or json.loads(json.dumps(asdict(proof))) != json.loads(row[4]):
            raise ValueError("运行来源范围已经变化")
        pins = [{"source_id": pin[0], "version": pin[1], "content_sha256": pin[2]} for pin in proof.source_pins]
        payload = {"text": text, "goal_revision": expected_goal_revision, "engine_commit": sink.config.engine_commit, "dataset_id": proof.dataset_id, "dataset_version": proof.dataset_version, "source_pins": pins, "citations": citations}
        candidate = {"event_id": str(uuid4()), "run_id": run_id, "seq": 1, "type": "RESULT_RECORDED", "occurred_at": utc_now().isoformat(), "trace_id": str(uuid4()), "payload_version": 1, "payload": payload}
        if not EVENT_VALIDATOR.is_valid(candidate) or any(item["source_id"] not in {pin["source_id"] for pin in pins} for item in citations):
            raise ValueError("运行结果内容或引用无效")
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
        existing = db.execute("SELECT event_id,seq,type,occurred_at,trace_id,payload_version,payload,origin_event_id FROM agent_run_events WHERE run_id=? AND (origin_event_id=? OR (type='RESULT_RECORDED' AND json_extract(payload,'$.goal_revision')=?)) ORDER BY seq", (run_id, origin_event_id, expected_goal_revision)).fetchall()
        if existing:
            if len(existing) != 1 or existing[0][2] != "RESULT_RECORDED" or existing[0][6] != encoded or existing[0][7] != origin_event_id:
                raise ValueError("运行结果请求或目标版本冲突")
            return self.store._event(run_id, existing[0][:7])
        if row[7] != expected_goal_revision or row[8] != expected_goal_revision:
            raise ValueError("运行目标版本不可保存结果")
        from agent_source_history import AgentSourceHistory
        AgentSourceHistory(self.store, self.scope).retain_citations_in_transaction(db, proof, citations, run_id=run_id)
        event_id = self.store._record_event(db, run_id, "RESULT_RECORDED", payload, sink.config.lease_epoch, origin_event_id)
        db.execute("UPDATE agent_runs SET revision=revision+1 WHERE run_id=?", (run_id,))
        event = db.execute("SELECT event_id,seq,type,occurred_at,trace_id,payload_version,payload FROM agent_run_events WHERE event_id=?", (event_id,)).fetchone()
        return self.store._event(run_id, event)

    @staticmethod
    def _semantic_query_evidence(db, store, proof, run_id, conversation_id, goal, goal_revision, query_id, values, source_ids, pins):
        from agent_run_method_selection import AgentRunMethodSelection
        row = db.execute("SELECT body FROM objects WHERE namespace=? AND kind='query' AND id=?", (proof.namespace, query_id)).fetchone()
        if row is None:
            return None
        query = json.loads(row[0])
        if query.get("query_type") is not None or query.get("values") != values or query.get("source_type") != "SIMULATED":
            return None
        query_sources = query.get("sources")
        if not isinstance(query_sources, list) or [item.get("source_id") for item in query_sources] != source_ids:
            return None
        expected_request_id = run_id if goal_revision == 1 else run_id + ":goal:" + str(goal_revision)
        expected_envelope = {"dataset_id": proof.dataset_id, "dataset_version": proof.dataset_version,
                             "execution_namespace": proof.namespace, "owner_id": proof.owner_id,
                             "request_id": expected_request_id, "session_id": "websocket:" + conversation_id}
        if query.get("envelope") != expected_envelope:
            return None
        context = query.get("context_snapshot")
        if not isinstance(context, dict) or context.get("envelope") != expected_envelope:
            return None
        authorization_id = run_id if goal_revision == 1 else run_id + ":" + str(goal_revision)
        auth_row = db.execute("SELECT body FROM objects WHERE namespace=? AND kind='hermes_bi_query_authorization' AND id=?", (proof.namespace, authorization_id)).fetchone()
        if auth_row is None:
            return None
        authorization = json.loads(auth_row[0])
        try:
            snapshot, _ = AgentRunMethodSelection._goal_snapshot(db, run_id, goal_revision)
        except ValueError:
            return None
        expected_scope = json.loads(json.dumps(asdict(proof)))
        expected_pins = [[pin["source_id"], pin["version"], pin["content_sha256"]] for pin in pins]
        if (authorization.get("run_id"), authorization.get("goal_revision"), authorization.get("owner_id"), authorization.get("namespace"),
                authorization.get("chat_id"), authorization.get("session_id"), authorization.get("dataset_id"), authorization.get("dataset_version")) != (
                run_id, goal_revision, proof.owner_id, proof.namespace, conversation_id, "websocket:" + conversation_id, proof.dataset_id, proof.dataset_version):
            return None
        snapshot_sha256 = authorization.get("goal_snapshot_sha256")
        if authorization.get("goal_sha256") != checksum(goal) or (snapshot_sha256 is None) != (goal_revision == 1) or (snapshot_sha256 is not None and snapshot_sha256 != checksum(snapshot)):
            return None
        if authorization.get("scope_proof") != expected_scope:
            return None
        binding = authorization.get("binding")
        if not isinstance(binding, dict) or authorization.get("binding_sha256") != checksum(binding) or not isinstance(binding.get("parameters"), dict):
            return None
        if {key: value for key, value in context.items() if key != "envelope"} != binding["parameters"]:
            return None
        if authorization["scope_proof"].get("source_pins") != expected_pins:
            return None
        if [item.get("version") for item in query_sources] != [pin["version"] for pin in pins]:
            return None
        for pin in pins:
            document_body = require_current_business_source(store, db, proof.namespace, proof.owner_id, pin["source_id"])
            if document_body.get("source_type") != "SIMULATED" or document_body.get("version") != pin["version"] or checksum(document_body) != pin["content_sha256"]:
                return None
        return {"goal_revision": goal_revision, "query_id": query_id, "values_sha256": checksum(values), "source_ids": source_ids,
                "goal_snapshot_sha256": checksum(snapshot), "authorization_id": authorization_id, "source_pins": expected_pins}

    @staticmethod
    def result_semantic_evidence(db, store, proof, run_id, conversation_id, goal, goal_revision, payload, pins):
        text = payload.get("text")
        if not isinstance(text, str) or not text.strip():
            return None
        try:
            document = json.loads(text)
        except (TypeError, ValueError):
            document = None
        if isinstance(document, dict) and isinstance(document.get("semantic_evidence"), dict):
            evidence = document["semantic_evidence"]
            if evidence.get("goal_revision") != goal_revision:
                return None
            query_id, values, source_ids = evidence.get("query_id"), evidence.get("values"), evidence.get("source_ids")
            if not isinstance(query_id, str) or not isinstance(values, list) or not isinstance(source_ids, list) or not source_ids:
                return None
            if document.get("query_id") != query_id or document.get("values") != values or document.get("sources") != source_ids:
                return None
            return AgentRunResult._semantic_query_evidence(db, store, proof, run_id, conversation_id, goal, goal_revision, query_id, values, source_ids, pins)
        event_row = db.execute("SELECT payload FROM agent_run_events WHERE run_id=? AND type='TOOL_FINISHED' AND json_extract(payload,'$.tool_id')='query_metrics' AND json_extract(payload,'$.outcome')='RETURNED' AND json_extract(payload,'$.goal_revision')=? ORDER BY seq DESC LIMIT 1", (run_id, goal_revision)).fetchone()
        if event_row is None:
            return None
        query_id = json.loads(event_row[0]).get("query_id")
        if not isinstance(query_id, str):
            return None
        row = db.execute("SELECT body FROM objects WHERE namespace=? AND kind='query' AND id=?", (proof.namespace, query_id)).fetchone()
        if row is None:
            return None
        query = json.loads(row[0])
        values = query.get("values")
        source_ids = [item.get("source_id") for item in query.get("sources", []) if isinstance(item, dict)]
        if not isinstance(values, list) or not source_ids:
            return None
        return AgentRunResult._semantic_query_evidence(db, store, proof, run_id, conversation_id, goal, goal_revision, query_id, values, source_ids, pins)

    def finalize_success_in_transaction(self, db, sink, expected_revision, result_event_id, finish_event_id, inspection_key):
        main = db.execute("PRAGMA database_list").fetchone()
        if not db.in_transaction or main is None or main[1] != "main" or Path(main[2]).resolve() != self.store.path.resolve():
            raise ValueError("运行终态需要同一数据库事务")
        if not isinstance(sink, EngineEventSink) or sink.store.path.resolve() != self.store.path.resolve():
            raise ValueError("运行终态需要同一数据库的引擎入口")
        if type(expected_revision) is not int or expected_revision < 0 or any(not isinstance(value, str) or not value.strip() or len(value) > 128 for value in (result_event_id, finish_event_id, inspection_key)):
            raise ValueError("运行终态参数无效")
        run_id = sink.config.run_id
        saved = db.execute("SELECT receipt FROM agent_run_operations WHERE run_id=? AND operation='completion_inspection' AND request_key=?",
                           (run_id, "completion-inspection:" + inspection_key)).fetchone()
        if saved is None:
            raise ValueError("运行终态缺少完成核查")
        inspection = json.loads(saved[0])
        if inspection.get("completion_state") != "PASS" or inspection.get("blockers") or inspection.get("result_event_id") != result_event_id or inspection.get("finish_event_id") != finish_event_id:
            raise ValueError("运行终态完成核查未通过")
        row = db.execute("SELECT status,goal_revision,lease_owner,lease_epoch,cancel_requested_at,revision FROM agent_runs WHERE run_id=?", (run_id,)).fetchone()
        if row is None:
            raise ValueError("运行终态身份不可核查")
        if row[0] == "SUCCEEDED":
            current = self.store.result_in_transaction(db, run_id, row[1])
            if current is None or current["event_id"] != result_event_id or row[2] is not None:
                raise ValueError("运行终态幂等记录不可核查")
            return "SUCCEEDED"
        if row[0] != "RUNNING" or row[4] is not None:
            raise ValueError("运行已经取消或处于不可完成状态")
        if (row[2], row[3]) != (sink.lease_owner, sink.config.lease_epoch) or row[5] != expected_revision:
            raise ValueError("运行终态租约或修订不可核查")
        updated = db.execute("UPDATE agent_runs SET status='SUCCEEDED',lease_owner=NULL,lease_expires_at=NULL,revision=revision+1 WHERE run_id=? AND status='RUNNING' AND cancel_requested_at IS NULL AND lease_owner=? AND lease_epoch=? AND revision=?", (run_id, sink.lease_owner, sink.config.lease_epoch, expected_revision))
        if updated.rowcount != 1:
            raise ValueError("运行终态状态已经变化")
        sink.store._record_event(db, run_id, "STATUS_CHANGED", {"from": "RUNNING", "to": "SUCCEEDED"}, sink.config.lease_epoch)
        return "SUCCEEDED"

    def inspect_completion_in_transaction(self, db, authority, sink, expected_revision, result_event_id, finish_event_id, inspection_key, *, artifact_preparation=None, runtime_meeting_brief=None, business_receipts=None):
        from hermes_run_authority import HermesRunAuthority
        main = db.execute("PRAGMA database_list").fetchone()
        if not db.in_transaction or main is None or main[1] != "main" or Path(main[2]).resolve() != self.store.path.resolve():
            raise ValueError("运行完成核查需要同一数据库事务")
        if not isinstance(authority, HermesRunAuthority) or authority.sink is not sink or authority.services.scope is not self.scope:
            raise ValueError("运行完成核查需要当前本人运行授权")
        authority.require_in_transaction(db)
        result = self.inspect_completion(sink, expected_revision, result_event_id, finish_event_id, inspection_key, artifact_preparation=artifact_preparation, runtime_meeting_brief=runtime_meeting_brief, business_receipts=business_receipts, _db=db)
        authority.require_in_transaction(db)
        return result

    def inspect_completion(self, sink, expected_revision, result_event_id, finish_event_id, inspection_key, *, artifact_preparation=None, runtime_meeting_brief=None, business_receipts=None, _db=None):
        if not isinstance(sink, EngineEventSink) or sink.store.path.resolve() != self.store.path.resolve():
            raise ValueError("运行完成核查需要同一数据库的引擎入口")
        if type(expected_revision) is not int or expected_revision < 0 or any(not isinstance(value, str) or not value.strip() or len(value) > 128 for value in (result_event_id, finish_event_id, inspection_key)):
            raise ValueError("运行完成核查参数无效")
        if artifact_preparation is not None:
            from agent_artifacts import ArtifactPreparation
            if not isinstance(artifact_preparation, ArtifactPreparation) or artifact_preparation.store.path.resolve() != self.store.path.resolve() or artifact_preparation.scope_service is not self.scope or artifact_preparation.run_gate.config != sink.config or artifact_preparation.run_gate.lease_owner != sink.lease_owner:
                raise ValueError("成果核查服务与运行环境不一致")
        if runtime_meeting_brief is not None:
            from agent_artifact_meeting_brief import RuntimeMeetingBriefPreparation
            if not isinstance(runtime_meeting_brief, RuntimeMeetingBriefPreparation) or runtime_meeting_brief.preparation is not artifact_preparation or _db is None:
                raise ValueError("运行会议简报核查需要同一事务和方法锁")
        if business_receipts is not None:
            from agent_run_business_receipts import RunBusinessReceipts
            if not isinstance(business_receipts, RunBusinessReceipts) or business_receipts.runs.path.resolve() != self.store.path.resolve() or business_receipts.scope is not self.scope:
                raise ValueError("业务回执核查服务与运行环境不一致")
        run_id = sink.config.run_id
        with self.store.connect() if _db is None else nullcontext(_db) as db:
            if _db is None:
                db.execute("BEGIN IMMEDIATE")
            else:
                main = db.execute("PRAGMA database_list").fetchone()
                if not db.in_transaction or main is None or main[1] != "main" or Path(main[2]).resolve() != self.store.path.resolve():
                    raise ValueError("运行完成核查需要同一数据库事务")
            self.store._require_lease(db, run_id, sink.lease_owner, sink.config.lease_epoch)
            self.store.require_active_lineage(db, run_id)
            require_source_cleanup_complete(db, run_id)
            from agent_run_memory_guard import require_current_run_memory_in_transaction
            require_current_run_memory_in_transaction(db, self.scope.store, run_id)
            row = db.execute("SELECT actor_id,space_id,conversation_id,selected_refs,scope_proof,status,cancel_requested_at,goal_revision,applied_goal_revision,revision,goal,last_input_seq FROM agent_runs WHERE run_id=?", (run_id,)).fetchone()
            if row is None or row[3] is None or row[4] is None or row[5] != "RUNNING" or row[6] is not None or row[7] != row[8] or row[9] != expected_revision:
                raise ValueError("运行状态或目标版本不可核查完成")
            proof = self.scope.prove_in_transaction(db, row[2], json.loads(row[3]))
            if (proof.owner_id, proof.namespace) != row[:2] or json.loads(json.dumps(asdict(proof))) != json.loads(row[4]):
                raise ValueError("运行来源范围已经变化")
            result = self.store.result_in_transaction(db, run_id, row[7])
            if result is None or result["event_id"] != result_event_id:
                raise ValueError("当前目标缺少指定结果")
            records = db.execute("SELECT event_id,lease_epoch,type,payload,seq FROM agent_run_events WHERE run_id=? AND event_id IN (?,?)", (run_id, result_event_id, finish_event_id)).fetchall()
            records = {record[0]: record[1:] for record in records}
            if len(records) != 2 or records[result_event_id][:2] != (sink.config.lease_epoch, "RESULT_RECORDED") or records[finish_event_id][:2] != (sink.config.lease_epoch, "RUN_FINISHED"):
                raise ValueError("结果或引擎结束事件与当前租约不符")
            finish_payload = json.loads(records[finish_event_id][2])
            if set(finish_payload) != {"outcome"} or not isinstance(finish_payload["outcome"], str) or not finish_payload["outcome"].strip():
                raise ValueError("引擎结束事件内容不可核查")
            pins = [{"source_id": pin[0], "version": pin[1], "content_sha256": pin[2]} for pin in proof.source_pins]
            payload = result["payload"]
            if payload["engine_commit"] != sink.config.engine_commit or payload["dataset_id"] != proof.dataset_id or payload["dataset_version"] != proof.dataset_version or payload["source_pins"] != pins:
                raise ValueError("结果引擎或来源版本已经变化")
            inputs = db.execute("SELECT input_id,input_seq,goal_revision,content,applied_event_id FROM agent_run_inputs WHERE run_id=? ORDER BY input_seq", (run_id,)).fetchall()
            if not isinstance(row[10], str) or not row[10].strip() or len(inputs) != row[11] or row[7] != len(inputs) + 1:
                raise ValueError("运行目标与补充记录不可核查")
            for index, item in enumerate(inputs, 1):
                applied = db.execute("SELECT type,payload FROM agent_run_events WHERE run_id=? AND event_id=?", (run_id, item[4])).fetchone()
                if item[1] != index or item[2] != index + 1 or applied is None or applied[0] != "INPUT_APPLIED" or json.loads(applied[1]) != {"input_id": item[0], "input_seq": index, "goal_revision": item[2]}:
                    raise ValueError("补充输入采用记录不可核查")
            last_applied_seq = db.execute("SELECT seq FROM agent_run_events WHERE event_id=?", (inputs[-1][4],)).fetchone()[0] if inputs else 0
            if not last_applied_seq < records[result_event_id][3] < records[finish_event_id][3]:
                raise ValueError("目标输入、运行结果和引擎结束事件顺序不可核查")
            records = db.execute("SELECT a.artifact_id,a.version,a.sha256,a.verification_status,a.status,v.version,f.run_id,f.status,a.source_refs,a.context,a.media_type FROM agent_artifacts a LEFT JOIN agent_artifact_versions v ON v.artifact_id=a.artifact_id LEFT JOIN agent_file_reservations f ON f.artifact_id=a.artifact_id WHERE a.run_id=? ORDER BY a.artifact_id", (run_id,)).fetchall()
            pins_by_id = {pin["source_id"]: pin for pin in pins}
            artifacts = []
            for item in records:
                refs, context = json.loads(item[8]), json.loads(item[9])
                matching_refs = isinstance(refs, list) and bool(refs) and all(isinstance(ref, dict) and ref.get("source_id") in pins_by_id and ref.get("revision") == pins_by_id[ref["source_id"]]["version"] and ref.get("sha256") == pins_by_id[ref["source_id"]]["content_sha256"] for ref in refs)
                if matching_refs:
                    source_ids = [ref["source_id"] for ref in refs]
                    documents = [require_current_business_source(self.scope.store, db, proof.namespace, proof.owner_id, source_id) for source_id in source_ids]
                    expected_refs = [{"source_id": doc["source_id"], "revision": doc["version"], "locator": doc["original_locator"], "classification": doc["source_type"], "sha256": checksum(doc)} for doc in documents]
                    matching_refs = len(set(source_ids)) == len(source_ids) and refs == expected_refs
                matching_context = context == {"owner_id": proof.owner_id, "namespace": proof.namespace, "dataset_id": proof.dataset_id, "dataset_version": proof.dataset_version}
                publication = db.execute("SELECT run_id,version,sha256,actor_id FROM agent_artifact_publications WHERE artifact_id=?", (item[0],)).fetchone()
                revoked = db.execute("SELECT 1 FROM agent_artifact_revocations WHERE artifact_id=?", (item[0],)).fetchone()
                matching_publication = item[4] != "PUBLISHED" or publication == (run_id, item[1], item[2], proof.owner_id)
                matches = item[5] == item[1] and item[6] == run_id and item[7] == "COMPLETED" and matching_refs and matching_context and matching_publication and revoked is None
                candidate = db.execute("SELECT seq,payload FROM agent_run_events WHERE run_id=? AND type='ARTIFACT_CANDIDATE' AND json_extract(payload,'$.artifact_id')=?", (run_id, item[0])).fetchall()
                goal_match = len(candidate) == 1 and last_applied_seq < candidate[0][0] < result["seq"] and json.loads(candidate[0][1]) == {"artifact_id": item[0], "version": item[1], "media_type": item[10], "sha256": item[2]}
                artifacts.append({"artifact_id": item[0], "version": item[1], "sha256": item[2], "media_type": item[10], "verification_status": item[3], "status": item[4], "records_match": matches, "goal_match": goal_match})
            reservations = db.execute("SELECT count(*) FROM agent_file_reservations WHERE run_id=? AND status='RESERVED'", (run_id,)).fetchone()[0]
            intent_migration = Path(__file__).parent / "migrations" / "upgrade2_intents_001.sql"
            intent_digest = hashlib.sha256(intent_migration.read_bytes()).hexdigest()
            intents_available = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='agent_intents'").fetchone() is not None and db.execute("SELECT sha256 FROM agent_schema_migrations WHERE version='upgrade2_intents_001'").fetchone() == (intent_digest,)
            pending_intents = db.execute("SELECT count(*) FROM agent_intents WHERE run_id=? AND status NOT IN ('SUCCEEDED','FAILED','REJECTED','EXPIRED')", (run_id,)).fetchone()[0] if intents_available else None
            requirements = RunRequirements.read_in_transaction(db, run_id, row[7])
            selected_formats = set(requirements["required_outputs"] or []).intersection(FORMATS)
            runtime_brief_verified = False
            brief_audits = []
            if artifact_preparation is not None:
                for item in artifacts:
                    if item["records_match"] and item["goal_match"] and item["verification_status"] == "VERIFIED" and item["status"] in {"VERIFIED", "PUBLISHED"} and any(item["media_type"] == FORMATS[name][1] for name in selected_formats):
                        has_briefs = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='agent_artifact_briefs'").fetchone() is not None
                        runtime_record = has_briefs and db.execute("SELECT 1 FROM agent_artifact_briefs WHERE artifact_id=?", (item["artifact_id"],)).fetchone() is not None
                        if runtime_record and runtime_meeting_brief is None:
                            continue
                        evidence = runtime_meeting_brief.verify_in_transaction(db, item["artifact_id"], item["version"]) if runtime_record else artifact_preparation.verify_meeting_brief_in_transaction(db, item["artifact_id"], item["version"])
                        item["file_state"] = evidence["file_state"]
                        if runtime_record:
                            audit = evidence.get("section_audit")
                            brief_audits.append({"artifact_id": item["artifact_id"], "version": item["version"], "section_audit": audit})
                            if evidence["file_state"] == "VERIFIED" and audit is not None and audit.get("completion_state") == "PASS":
                                runtime_brief_verified = True
            checks = []
            tree_rows, tree_verified = vm_tree_exit_evidence(db, run_id, sink.config.lease_epoch)
            semantic_evidence = self.result_semantic_evidence(db, self.scope.store, proof, run_id, row[2], row[10], row[7], payload, pins)
            blockers = [] if semantic_evidence is not None else ["RESULT_SEMANTICS_UNVERIFIED"]
            if not tree_verified:
                blockers.append("PROCESS_GROUP_EXIT_UNVERIFIED")
            if any(item["section_audit"] is None or item["section_audit"].get("completion_state") != "PASS" for item in brief_audits):
                blockers.append("BRIEF_SECTION_AUDIT_UNVERIFIED")
            action_evidence = None
            if requirements["state"] == "CONFIRMED" and "ACTION_DRAFT" in requirements["required_outputs"]:
                from agent_run_action_drafts import RunActionDrafts
                action_evidence = RunActionDrafts(self.store, self.scope).inspect_in_transaction(db, sink, row[7], result["seq"], last_applied_seq)
            business_evidence = None
            if business_receipts is not None and requirements["state"] == "CONFIRMED" and "BUSINESS_RECEIPT" in requirements["required_outputs"]:
                business_evidence = business_receipts.inspect_in_transaction(db, run_id, row[7])
            if requirements["state"] != "CONFIRMED":
                blockers.append("ACCEPTANCE_REQUIREMENTS_UNAVAILABLE")
            else:
                for output in requirements["required_outputs"]:
                    if output == "TEXT":
                        state = "RECORD_PRESENT"
                    elif output == "ACTION_DRAFT":
                        state = action_evidence["state"] if action_evidence is not None else "NOT_VERIFIED"
                    elif output == "BRIEF":
                        state = "RECORD_PRESENT" if runtime_brief_verified else "NOT_VERIFIED"
                    elif output == "BUSINESS_RECEIPT":
                        state = business_evidence["state"] if business_evidence is not None else "NOT_VERIFIED"
                    elif output == "SOURCE_LIST":
                        state = "NOT_VERIFIED"
                    else:
                        media_type = FORMATS[output][1]
                        matches = [item for item in artifacts if item["media_type"] == media_type and item["records_match"] and item["goal_match"] and item["verification_status"] == "VERIFIED" and item["status"] in {"VERIFIED", "PUBLISHED"}]
                        state = "FILE_VERIFIED" if any(item.get("file_state") == "VERIFIED" for item in matches) else "RECORD_PRESENT" if matches else "MISSING"
                    checks.append({"type": output, "state": state})
                if any(item["state"] == "MISSING" for item in checks):
                    blockers.append("REQUIRED_OUTPUT_MISSING")
                if any(item["state"] == "NOT_VERIFIED" for item in checks):
                    blockers.append("REQUIRED_OUTPUT_UNVERIFIED")
            if any(item.get("file_state") != "VERIFIED" for item in artifacts):
                blockers.append("ARTIFACT_FILES_UNVERIFIED")
            if any(item["verification_status"] != "VERIFIED" or item["status"] not in {"VERIFIED", "PUBLISHED"} or not item["records_match"] for item in artifacts):
                blockers.append("ARTIFACT_STATE_UNAVAILABLE")
            if reservations:
                blockers.append("FILE_RESERVATIONS_PENDING")
            if pending_intents is None:
                blockers.append("INTENT_STATE_UNAVAILABLE")
            elif pending_intents:
                blockers.append("INTENTS_PENDING")
            intent_rows = db.execute("SELECT intent_id,action,status,revision,request_key,authorization_id,result_ref,payload_digest FROM agent_intents WHERE run_id=? ORDER BY intent_id", (run_id,)).fetchall() if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='agent_intents'").fetchone() is not None else []
            process_rows = db.execute("SELECT request_key,state,exit_code,exit_scope FROM hermes_process_evidence WHERE run_id=? ORDER BY request_key", (run_id,)).fetchall() if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='hermes_process_evidence'").fetchone() is not None else []
            completion_state = "PASS" if not blockers else "BLOCKED"
            receipt = {"run_id": run_id, "revision": row[9], "intent_state_sha256": checksum([tuple(item) for item in intent_rows]), "process_evidence_sha256": checksum([tuple(item) for item in process_rows]), "goal_revision": row[7], "result_event_id": result_event_id, "finish_event_id": finish_event_id, "finish_outcome": finish_payload["outcome"], "lease_epoch": sink.config.lease_epoch, "goal_sha256": checksum({"goal": row[10], "inputs": inputs}), "result_sha256": checksum(payload), "requirements": requirements, "output_checks": checks, "artifacts_sha256": checksum(artifacts), "artifacts": artifacts, "brief_section_audits": brief_audits, "pending_file_reservations": reservations, "pending_intents": pending_intents, "completion_state": completion_state, "result_semantic_evidence": semantic_evidence, "blockers": blockers}
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='hermes_vm_tree_exits'").fetchone() is not None:
                receipt["vm_tree_evidence_sha256"] = checksum(tree_rows)
            if action_evidence is not None:
                receipt["action_draft_inspection"] = action_evidence
            if business_evidence is not None:
                receipt["business_receipt_inspection"] = business_evidence
            key = "completion-inspection:" + inspection_key
            old = db.execute("SELECT operation,expected_revision,receipt FROM agent_run_operations WHERE run_id=? AND request_key=?", (run_id, key)).fetchone()
            encoded = json.dumps(receipt, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            if old is not None:
                if old != ("completion_inspection", expected_revision, encoded):
                    raise ValueError("运行完成核查请求内容已经变化")
                return json.loads(old[2])
            db.execute("INSERT INTO agent_run_operations VALUES (?,?,'completion_inspection',?,?)", (run_id, key, expected_revision, encoded))
            return receipt
