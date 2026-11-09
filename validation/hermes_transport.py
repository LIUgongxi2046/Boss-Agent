import hmac
import hashlib
import json
from contextlib import ExitStack
import sqlite3
from dataclasses import asdict
from datetime import datetime
from urllib.parse import urlsplit
from uuid import uuid4

from aiohttp import web
from jsonschema import Draft202012Validator, FormatChecker

from hermes_bridge import ENGINE_EVENT_FIELDS, EngineEventSink, HermesBridge, ReadScope
from agent_run_scope import RunScopeService
from agent_run_store import EVENT_VALIDATOR, utc_now
from agent_run_tool_budget import RunToolBudget
from agent_run_result import AgentRunResult
from agent_run_requirements import RunRequirements
from agent_artifact_api import ARTIFACT_VALIDATORS
from business import checksum
from boss_source_access import require_current_business_source
from hermes_artifact_transport import HermesArtifactTransport
from hermes_meeting_brief_public import safe_section_audit
from hermes_run_authority import HermesRunAuthority


EVENT_MESSAGE = Draft202012Validator({
    "type": "object", "additionalProperties": False,
    "required": ["protocol_version", "origin_event_id", "type", "payload"],
    "properties": {
        "protocol_version": {"const": 1},
        "origin_event_id": {"type": "string", "minLength": 1, "maxLength": 128},
        "type": {"type": "string", "minLength": 1, "maxLength": 64},
        "payload": {"type": "object"},
    },
})

RESULT_MESSAGE = Draft202012Validator({
    "type": "object", "additionalProperties": False,
    "required": ["protocol_version", "origin_event_id", "goal_revision", "text", "citations"],
    "properties": {
        "protocol_version": {"type": "integer", "const": 1},
        "origin_event_id": {"type": "string", "minLength": 1, "maxLength": 128, "pattern": "\\S"},
        "goal_revision": {"type": "integer", "minimum": 1},
        "text": {"type": "string", "minLength": 1, "maxLength": 65536, "pattern": "\\S"},
        "citations": {"type": "array", "maxItems": 100, "items": {"type": "object", "additionalProperties": False,
            "required": ["source_id", "locator"], "properties": {
                "source_id": {"type": "string", "minLength": 1}, "locator": {"type": "string", "minLength": 1, "maxLength": 2000}}}},
    },
})


def transport_error(exception, code, message):
    return exception(text=json.dumps({"protocol_version": 1, "code": code, "message": message}, ensure_ascii=False), content_type="application/json")


class HermesTransport:
    def __init__(self, sink: EngineEventSink, capability: str, *, actor_id: str, space_id: str, scope_service=None, tool_budget=None, bridge=None, context_tools=None, artifact_tools=None, authority=None):
        if not isinstance(sink, EngineEventSink) or not isinstance(capability, str) or len(capability) < 32 or not capability.isascii():
            raise ValueError("通信入口需要运行事件入口和能力凭据")
        if not all(isinstance(value, str) and value for value in (actor_id, space_id)):
            raise ValueError("缺少服务端身份范围")
        if scope_service is not None and (not isinstance(scope_service, RunScopeService) or scope_service.store.path.resolve() != sink.store.path.resolve()):
            raise ValueError("来源核查必须使用运行数据库")
        if (tool_budget is None) != (bridge is None):
            raise ValueError("业务读取需要工具预算和业务服务")
        if tool_budget is not None and (not isinstance(tool_budget, RunToolBudget) or tool_budget.store.path.resolve() != sink.store.path.resolve() or not isinstance(bridge, HermesBridge) or bridge._store.path.resolve() != sink.store.path.resolve() or scope_service is None):
            raise ValueError("工具预算、来源和业务服务必须属于同一数据库")
        self.sink, self.capability = sink, capability
        self.actor_id, self.space_id = actor_id, space_id
        self.scope_service = scope_service
        self.tool_budget, self.bridge = tool_budget, bridge
        if context_tools is not None:
            from hermes_context_tools import HermesContextTools
            if not isinstance(context_tools, HermesContextTools) or tool_budget is None or context_tools.memory.run_gate.config != sink.config or context_tools.memory.run_gate.lease_owner != sink.lease_owner or context_tools.memory.store.path.resolve() != sink.store.path.resolve():
                raise ValueError("上下文工具与当前运行不匹配")
        self.context_tools = context_tools
        if artifact_tools is not None and (not isinstance(artifact_tools, HermesArtifactTransport) or artifact_tools.preparation.run_gate is not sink or artifact_tools.preparation.scope_service is not scope_service or tool_budget is None):
            raise ValueError("成果服务与当前运行不匹配")
        self.artifact_tools = artifact_tools
        if authority is not None and (not isinstance(authority, HermesRunAuthority) or authority.sink is not sink or authority.services.scope is not scope_service):
            raise ValueError("运行授权与通信服务不匹配")
        self.authority = authority

    def _authorize(self, request):
        bound = request.transport.get_extra_info("sockname") if request.transport is not None else None
        endpoint = urlsplit(self.sink.config.provider_url)
        if not isinstance(bound, tuple) or len(bound) < 2 or bound[:2] != ("127.0.0.1", endpoint.port):
            raise transport_error(web.HTTPForbidden, "INVALID_ENDPOINT", "本机入口地址不匹配")
        if self.capability is None or not hmac.compare_digest(request.headers.get("Authorization", ""), "Bearer " + self.capability):
            raise transport_error(web.HTTPUnauthorized, "INVALID_CAPABILITY", "进程通信凭据无效")

    def _active_run(self, db):
        row = db.execute("SELECT actor_id,space_id,status,cancel_requested_at,goal,goal_revision,applied_goal_revision,conversation_id,selected_refs,scope_proof FROM agent_runs WHERE run_id=?", (self.sink.config.run_id,)).fetchone()
        if row is None or row[:2] != (self.actor_id, self.space_id):
            raise transport_error(web.HTTPForbidden, "RUN_IDENTITY_INVALID", "运行身份不可用")
        if row[2] != "RUNNING" or row[3] is not None:
            raise transport_error(web.HTTPConflict, "RUN_NOT_ACTIVE", "运行当前不可执行")
        refs = json.loads(row[8]) if row[8] is not None else []
        if not isinstance(refs, list) or any(not isinstance(ref, str) or not ref for ref in refs) or len(set(refs)) != len(refs):
            raise transport_error(web.HTTPConflict, "SOURCE_SCOPE_INVALID", "运行来源范围无效")
        if refs or row[9] is not None:
            if self.scope_service is None or row[9] is None or not row[7]:
                raise transport_error(web.HTTPConflict, "SOURCE_PROOF_UNAVAILABLE", "运行来源证明不可用")
            proof = self.scope_service.prove_in_transaction(db, row[7], refs)
            if proof.owner_id != self.actor_id or proof.namespace != self.space_id or json.loads(row[9]) != json.loads(json.dumps(asdict(proof))):
                raise transport_error(web.HTTPConflict, "SOURCE_SCOPE_CHANGED", "运行来源范围已经变化")
        return row

    def _require_gate(self, db, *, readonly=False):
        from hermes_source_invalidation import require_source_cleanup_complete
        require_source_cleanup_complete(db, self.sink.config.run_id,
            invalid=lambda message: transport_error(web.HTTPConflict, "SOURCE_CLEANUP_UNAVAILABLE", message),
            revoked=lambda message: transport_error(web.HTTPGone, "SOURCE_REVOKED", message))
        row = self._active_run(db)
        if self.authority is not None:
            if readonly:
                self.authority.require_readonly_in_transaction(db)
            else:
                self.authority.require_in_transaction(db)
        current = self.sink.config.run_id
        seen = set()
        while current is not None:
            if current in seen:
                raise transport_error(web.HTTPConflict, "RUN_LINEAGE_INVALID", "运行关系无效")
            seen.add(current)
            if self.context_tools is not None:
                invalid = db.execute("SELECT 1 FROM objects WHERE namespace=? AND kind='hermes_memory_invalidation' AND id=?", (self.space_id, current)).fetchone()
                if invalid is not None:
                    raise transport_error(web.HTTPConflict, "RUN_CONTEXT_INVALID", "运行记忆引用已经失效")
            item = db.execute("SELECT parent_run_id,actor_id,space_id,status,cancel_requested_at,lease_owner,lease_epoch,lease_expires_at FROM agent_runs WHERE run_id=?", (current,)).fetchone()
            if item is None or item[1:3] != (self.actor_id, self.space_id) or item[3] not in {"RUNNING", "WAITING_INPUT", "WAITING_CONFIRMATION"} or item[4] is not None or not item[5] or item[7] is None or datetime.fromisoformat(item[7]) <= utc_now():
                raise transport_error(web.HTTPConflict, "RUN_LINEAGE_UNAVAILABLE", "运行或父运行不可执行")
            if current == self.sink.config.run_id and (item[5] != self.sink.lease_owner or item[6] != self.sink.config.lease_epoch):
                raise transport_error(web.HTTPConflict, "RUN_LEASE_UNAVAILABLE", "运行租约不可用")
            current = item[0]
        self.sink.store._require_lease(db, self.sink.config.run_id, self.sink.lease_owner, self.sink.config.lease_epoch)
        self.sink.store.require_active_lineage(db, self.sink.config.run_id)
        return row

    def read_bound_documents_in_transaction(self, db, bridge):
        if not isinstance(bridge, HermesBridge) or not db.in_transaction:
            raise ValueError("来源读取需要业务服务和当前事务")
        row = self._require_gate(db)
        refs = json.loads(row[8]) if row[8] is not None else []
        if not refs or row[9] is None or self.scope_service is None:
            raise transport_error(web.HTTPConflict, "SOURCE_PROOF_UNAVAILABLE", "运行缺少获准来源证明")
        proof = self.scope_service.prove_in_transaction(db, row[7], refs)
        return bridge.read_documents_in_transaction(db, scope=ReadScope(proof.owner_id, proof.namespace, proof.dataset_id, proof.dataset_version), source_ids=refs)

    def _document_request(self, db, call_id):
        run = self._require_gate(db)
        refs = json.loads(run[8]) if run[8] is not None else []
        if not refs or run[9] is None:
            raise transport_error(web.HTTPConflict, "SOURCE_PROOF_UNAVAILABLE", "运行缺少获准来源证明")
        digest = hashlib.sha256(json.dumps({"refs": refs, "proof": json.loads(run[9])}, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        row = db.execute("SELECT root_run_id,request_digest,tool_name,lease_epoch FROM agent_tool_reservations WHERE run_id=? AND request_key=?", (self.sink.config.run_id, call_id)).fetchone()
        if row is not None and (row[1] != digest or row[2] != "read_bound_documents" or row[0] != self.sink.store.require_active_lineage(db, self.sink.config.run_id)):
            raise transport_error(web.HTTPConflict, "TOOL_REQUEST_CONFLICT", "工具请求编号对应的范围已经变化")
        return digest, row

    def _document_result(self, db, call_id, digest):
        key = hashlib.sha256(json.dumps([self.sink.config.run_id, call_id], ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
        row = db.execute("SELECT body FROM objects WHERE namespace=? AND kind='hermes_document_result' AND id=?", (self.space_id, key)).fetchone()
        if row is None:
            return None
        saved = json.loads(row[0])
        if saved.get("state") == "REVOKED":
            raise transport_error(web.HTTPConflict, "TOOL_SOURCE_REVOKED", "工具结果的来源已经撤销")
        if saved.get("run_id") != self.sink.config.run_id or saved.get("call_id") != call_id or saved.get("request_digest") != digest or not isinstance(saved.get("result"), dict):
            raise transport_error(web.HTTPConflict, "TOOL_RESULT_INVALID", "工具结果记录不匹配")
        return saved["result"]

    async def run_request(self, request):
        self._authorize(request)
        if request.query:
            raise transport_error(web.HTTPBadRequest, "INVALID_REQUEST", "请求参数无效")
        gate = self.sink
        with gate.store.connect() as db:
            db.execute("BEGIN")
            row = self._require_gate(db)
            if not isinstance(row[4], str) or not row[4].strip() or row[5] != row[6]:
                raise transport_error(web.HTTPConflict, "GOAL_UNAVAILABLE", "运行目标缺失或版本尚未采用")
            result = {"protocol_version": 1, "run_id": gate.config.run_id, "goal": row[4], "goal_revision": row[5], "selected_refs": json.loads(row[8]) if row[8] is not None else []}
        return web.json_response(result, headers={"Cache-Control": "no-store"})

    async def event(self, request):
        self._authorize(request)
        if request.query or request.content_type != "application/json":
            raise transport_error(web.HTTPBadRequest, "INVALID_EVENT", "事件请求格式无效")
        body = await request.json()
        if not EVENT_MESSAGE.is_valid(body) or type(body.get("protocol_version")) is not int:
            raise transport_error(web.HTTPBadRequest, "INVALID_EVENT", "事件请求字段无效")
        if body["type"] not in ENGINE_EVENT_FIELDS or set(body["payload"]) != ENGINE_EVENT_FIELDS[body["type"]]:
            raise transport_error(web.HTTPBadRequest, "INVALID_EVENT", "事件类型或字段无效")
        gate = self.sink
        if body["type"] == "RUN_STARTED" and body["payload"]["engine_commit"] != gate.config.engine_commit:
            raise transport_error(web.HTTPBadRequest, "ENGINE_VERSION_MISMATCH", "引擎版本不匹配")
        candidate = {"event_id": str(uuid4()), "run_id": gate.config.run_id, "seq": 1, "type": body["type"], "occurred_at": utc_now().isoformat(), "trace_id": str(uuid4()), "payload_version": 1, "payload": body["payload"]}
        if not EVENT_VALIDATOR.is_valid(candidate):
            raise transport_error(web.HTTPBadRequest, "INVALID_EVENT", "事件内容无效")
        encoded = json.dumps(body["payload"], ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
        artifact_preparation = None
        runtime_meeting_brief = None
        if body["type"] == "RUN_FINISHED" and self.authority is not None and self.artifact_tools is not None:
            if self.context_tools is None:
                raise transport_error(web.HTTPServiceUnavailable, "COMPLETION_SERVICE_UNAVAILABLE", "完成检查缺少运行上下文")
            self.artifact_tools.authorize()
            self.artifact_tools.require_ready()
            artifact_preparation = self.artifact_tools.preparation
            if self.context_tools.skill.sop_id == "SOP04":
                from agent_artifact_meeting_brief import RuntimeMeetingBriefPreparation
                runtime_meeting_brief = RuntimeMeetingBriefPreparation(artifact_preparation, self.context_tools.skill)
        with ExitStack() as stack:
            if body["type"] == "RUN_FINISHED" and self.authority is not None:
                if self.context_tools is None or self.scope_service is None:
                    raise transport_error(web.HTTPServiceUnavailable, "COMPLETION_SERVICE_UNAVAILABLE", "完成检查缺少运行上下文")
                db = stack.enter_context(self.context_tools.guarded_result(gate_check=self._require_gate))
            else:
                db = stack.enter_context(gate.store.connect())
                db.execute("BEGIN IMMEDIATE")
                self._require_gate(db)
            old = db.execute("SELECT event_id,seq,type,occurred_at,trace_id,payload_version,payload FROM agent_run_events WHERE run_id=? AND lease_epoch=? AND origin_event_id=?", (gate.config.run_id, gate.config.lease_epoch, body["origin_event_id"])).fetchone()
            if old is not None:
                if old[2] != body["type"] or old[6] != encoded:
                    raise transport_error(web.HTTPConflict, "EVENT_CONFLICT", "事件编号对应的内容已经变化")
                saved = gate.store._event(gate.config.run_id, old)
            else:
                event_id = gate.store._record_event(db, gate.config.run_id, body["type"], body["payload"], gate.config.lease_epoch, body["origin_event_id"])
                db.execute("UPDATE agent_runs SET revision=revision+1 WHERE run_id=?", (gate.config.run_id,))
                row = db.execute("SELECT event_id,seq,type,occurred_at,trace_id,payload_version,payload FROM agent_run_events WHERE event_id=?", (event_id,)).fetchone()
                saved = gate.store._event(gate.config.run_id, row)
            if body["type"] == "RUN_FINISHED" and self.authority is not None:
                from agent_run_business_receipts import RunBusinessReceipts
                run = db.execute("SELECT revision,goal_revision FROM agent_runs WHERE run_id=?", (gate.config.run_id,)).fetchone()
                result = gate.store.result_in_transaction(db, gate.config.run_id, run[1])
                if result is None:
                    raise transport_error(web.HTTPConflict, "COMPLETION_RESULT_UNAVAILABLE", "当前目标缺少运行结果")
                receipts = RunBusinessReceipts(gate.store, self.scope_service) if RunBusinessReceipts.schema_state(db) else None
                inspection = AgentRunResult(gate.store, self.scope_service).inspect_completion_in_transaction(
                    db, self.authority, gate, run[0], result["event_id"], saved["event_id"],
                    "engine-finish:" + saved["event_id"], artifact_preparation=artifact_preparation,
                    runtime_meeting_brief=runtime_meeting_brief, business_receipts=receipts)
                if inspection["completion_state"] != "BLOCKED":
                    raise transport_error(web.HTTPConflict, "COMPLETION_STATE_INVALID", "运行完成状态不可核查")
        return web.json_response({"protocol_version": 1, "event": saved}, headers={"Cache-Control": "no-store"})

    async def pending_input(self, request):
        self._authorize(request)
        if request.query:
            raise transport_error(web.HTTPBadRequest, "INVALID_INPUT", "补充输入请求无效")
        with self.sink.store.connect() as db:
            db.execute("BEGIN")
            run = self._require_gate(db, readonly=True)
            item = db.execute("SELECT input_id,input_seq,goal_revision,content FROM agent_run_inputs WHERE run_id=? AND applied_event_id IS NULL ORDER BY input_seq LIMIT 1", (self.sink.config.run_id,)).fetchone()
            if item is not None and item[2] != run[6] + 1:
                raise transport_error(web.HTTPConflict, "INPUT_ORDER_INVALID", "补充输入顺序无效")
            result = None if item is None else {"input_id": item[0], "input_seq": item[1], "goal_revision": item[2], "content": item[3]}
        return web.json_response({"protocol_version": 1, "input": result}, headers={"Cache-Control": "no-store"})

    async def input_context(self, request):
        self._authorize(request)
        if request.query:
            raise transport_error(web.HTTPBadRequest, "INVALID_INPUT", "补充输入请求无效")
        gate = self.sink
        with gate.store.connect() as db:
            db.execute("BEGIN")
            run = self._require_gate(db, readonly=True)
            if not isinstance(run[4], str) or not run[4].strip():
                raise transport_error(web.HTTPConflict, "GOAL_UNAVAILABLE", "运行目标缺失")
            rows = db.execute("SELECT input_id,input_seq,goal_revision,content,applied_event_id FROM agent_run_inputs WHERE run_id=? ORDER BY input_seq", (gate.config.run_id,)).fetchall()
            if run[5] != len(rows) + 1 or not 1 <= run[6] <= run[5]:
                raise transport_error(web.HTTPConflict, "INPUT_ORDER_INVALID", "补充输入版本不可核查")
            inputs = []
            for index, (input_id, seq, revision, content, event_id) in enumerate(rows, 1):
                applied = revision <= run[6]
                if seq != index or revision != index + 1 or not isinstance(content, str) or not content.strip() or applied != (event_id is not None):
                    raise transport_error(web.HTTPConflict, "INPUT_ORDER_INVALID", "补充输入记录不可核查")
                if applied:
                    event = db.execute("SELECT type,payload FROM agent_run_events WHERE run_id=? AND event_id=?", (gate.config.run_id, event_id)).fetchone()
                    if event is None or event[0] != "INPUT_APPLIED" or json.loads(event[1]) != {"input_id": input_id, "input_seq": seq, "goal_revision": revision}:
                        raise transport_error(web.HTTPConflict, "INPUT_ORDER_INVALID", "补充输入回执不可核查")
                inputs.append({"input_id": input_id, "input_seq": seq, "goal_revision": revision, "content": content, "applied": applied})
            requirements = RunRequirements.read_in_transaction(db, gate.config.run_id, run[5])
            result = {"protocol_version": 1, "run_id": gate.config.run_id, "goal": run[4], "goal_revision": run[5], "inputs": inputs, "requirements": requirements}
        return web.json_response(result, headers={"Cache-Control": "no-store"})

    def _check_result_sources(self, db, citations):
        gate = self.sink
        for citation in citations:
            self.scope_service.read_source_in_transaction(db, gate.store, gate.config.run_id, gate.lease_owner,
                                                          gate.config.lease_epoch, citation["source_id"])

    def _record_citation_checks(self, db, event):
        payload = {"run_id": self.sink.config.run_id, "event_id": event["event_id"], "citations": [
            {**citation, "locator_verification": "NOT_VERIFIED"} for citation in event["payload"]["citations"]]}
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
        row = db.execute("SELECT body FROM objects WHERE namespace=? AND kind='hermes_result_citation_checks' AND id=?", (self.space_id, event["event_id"])).fetchone()
        if row is None:
            db.execute("INSERT INTO objects(namespace,kind,id,body) VALUES (?,'hermes_result_citation_checks',?,?)", (self.space_id, event["event_id"], encoded))
        elif row[0] != encoded:
            raise ValueError("运行结果引用核查记录不一致")
        return payload["citations"]

    async def record_result(self, request):
        self._authorize(request)
        if request.query or request.content_type != "application/json":
            raise transport_error(web.HTTPBadRequest, "INVALID_RESULT", "运行结果请求格式无效")
        body = await request.json()
        if not RESULT_MESSAGE.is_valid(body) or type(body.get("protocol_version")) is not int or type(body.get("goal_revision")) is not int:
            raise transport_error(web.HTTPBadRequest, "INVALID_RESULT", "运行结果请求字段无效")
        if self.scope_service is None:
            raise transport_error(web.HTTPServiceUnavailable, "RESULT_SERVICE_UNAVAILABLE", "运行来源服务尚未装配")
        results = AgentRunResult(self.sink.store, self.scope_service)
        if self.context_tools is None:
            with self.sink.store.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                self._require_gate(db)
                self._check_result_sources(db, body["citations"])
                result = results.record_in_transaction(db, self.sink, body["origin_event_id"], body["goal_revision"], body["text"], body["citations"])
                checks = self._record_citation_checks(db, result)
                self._require_gate(db)
        else:
            with self.context_tools.guarded_result(gate_check=self._require_gate) as db:
                self._check_result_sources(db, body["citations"])
                result = results.record_in_transaction(db, self.sink, body["origin_event_id"], body["goal_revision"], body["text"], body["citations"])
                checks = self._record_citation_checks(db, result)
                self._require_gate(db)
        return web.json_response({"protocol_version": 1, "event": result, "citation_checks": checks}, headers={"Cache-Control": "no-store"})

    def _read_citation_checks(self, db, event_id):
        row = db.execute("SELECT body FROM objects WHERE namespace=? AND kind='hermes_result_citation_checks' AND id=?", (self.space_id, event_id)).fetchone()
        event = db.execute("SELECT payload FROM agent_run_events WHERE run_id=? AND event_id=? AND type='RESULT_RECORDED'", (self.sink.config.run_id, event_id)).fetchone()
        if row is None or event is None:
            raise transport_error(web.HTTPNotFound, "CITATION_CHECKS_NOT_FOUND", "引用核查记录不存在")
        saved = json.loads(row[0])
        citations = json.loads(event[0])["citations"]
        expected = {"run_id": self.sink.config.run_id, "event_id": event_id, "citations": [{**citation, "locator_verification": "NOT_VERIFIED"} for citation in citations]}
        if saved != expected:
            raise transport_error(web.HTTPConflict, "CITATION_CHECKS_INVALID", "引用核查记录不可核查")
        return saved["citations"]

    async def read_citation_checks(self, request):
        self._authorize(request)
        event_id = request.match_info["event_id"]
        if request.query or not event_id or len(event_id) > 128:
            raise transport_error(web.HTTPBadRequest, "INVALID_RESULT", "运行结果请求格式无效")
        if self.context_tools is None:
            with self.sink.store.connect() as db:
                db.execute("BEGIN")
                self._require_gate(db)
                checks = self._read_citation_checks(db, event_id)
        else:
            with self.context_tools.guarded_result(gate_check=self._require_gate) as db:
                checks = self._read_citation_checks(db, event_id)
        return web.json_response({"protocol_version": 1, "event_id": event_id, "citation_checks": checks}, headers={"Cache-Control": "no-store"})

    async def authorize_model_execution(self, request):
        self._authorize(request)
        if request.query or request.content_type != "application/json":
            raise transport_error(web.HTTPBadRequest, "INVALID_REQUEST", "模型执行请求格式无效")
        body = await request.json()
        if not isinstance(body, dict) or set(body) != {"protocol_version"} or type(body["protocol_version"]) is not int or body["protocol_version"] != 1:
            raise transport_error(web.HTTPBadRequest, "INVALID_REQUEST", "模型执行请求字段无效")
        from hermes_deployment_manifest import verify_model_execution_authorization
        deployment = self.authority.execution_factory.deployment if self.authority.execution_factory is not None else None
        if deployment is None or not verify_model_execution_authorization(deployment.deployment_authorization, deployment.artifact_manifest, deployment):
            raise transport_error(web.HTTPServiceUnavailable, "MODEL_EXECUTION_UNAVAILABLE", "模型执行授权不可用")
        if type(self.authority.budget.get("model_requests")) is not int or self.authority.budget["model_requests"] < 1:
            raise transport_error(web.HTTPServiceUnavailable, "MODEL_EXECUTION_UNAVAILABLE", "模型请求额度不可用")
        self.authority.require()
        return web.json_response({"protocol_version": 1, "authorized": True}, headers={"Cache-Control": "no-store"})

    def _require_workspace_file_gate(self, db):
        self.authority.services.recovery.channel.require_run_api_role(self.authority.request)
        from hermes_source_invalidation import require_source_cleanup_complete
        require_source_cleanup_complete(db, self.sink.config.run_id,
            invalid=lambda message: transport_error(web.HTTPConflict, "SOURCE_CLEANUP_UNAVAILABLE", message),
            revoked=lambda message: transport_error(web.HTTPGone, "SOURCE_REVOKED", message))
        return self._require_gate(db)

    async def reserve_workspace_file_tool(self, request):
        self._authorize(request)
        if request.query or request.content_type != "application/json":
            raise transport_error(web.HTTPBadRequest, "INVALID_TOOL_REQUEST", "文件工具请求格式无效")
        body = await request.json()
        if not isinstance(body, dict) or set(body) != {"protocol_version", "call_id", "tool_name", "arguments_sha256"} or type(body["protocol_version"]) is not int or body["protocol_version"] != 1:
            raise transport_error(web.HTTPBadRequest, "INVALID_TOOL_REQUEST", "文件工具请求字段无效")
        call_id, name, digest = body["call_id"], body["tool_name"], body["arguments_sha256"]
        if not isinstance(call_id, str) or not 1 <= len(call_id) <= 80 or any(not character.isascii() or not (character.isalnum() or character in "_.-") for character in call_id) or not isinstance(name, str) or name not in {"workspace_read_file", "workspace_write_file"} or not isinstance(digest, str) or len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
            raise transport_error(web.HTTPBadRequest, "INVALID_TOOL_REQUEST", "文件工具身份无效")
        if self.tool_budget is None or self.authority is None or self.authority.vm_access is None:
            raise transport_error(web.HTTPServiceUnavailable, "TOOL_SERVICE_UNAVAILABLE", "文件工具授权尚未装配")
        gate = self.sink
        with gate.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            run = self._require_workspace_file_gate(db)
            if run[5] != run[6] or not isinstance(run[4], str) or not run[4].strip():
                raise transport_error(web.HTTPConflict, "GOAL_CHANGED", "运行目标版本不可用")
            root = gate.store.require_active_lineage(db, gate.config.run_id)
            budget = db.execute("SELECT max_tools FROM agent_tool_budgets WHERE root_run_id=?", (root,)).fetchone()
            if budget is None:
                raise transport_error(web.HTTPServiceUnavailable, "TOOL_BUDGET_UNAVAILABLE", "根运行工具预算尚未配置")
            if db.execute("SELECT count(*) FROM agent_tool_reservations WHERE root_run_id=?", (root,)).fetchone()[0] >= budget[0]:
                raise transport_error(web.HTTPTooManyRequests, "TOOL_BUDGET_EXHAUSTED", "工具预算已经用尽")
            reserved = self.tool_budget.reserve_in_transaction(db, gate.config.run_id, gate.lease_owner, gate.config.lease_epoch, call_id, digest, name)
            if not reserved:
                raise transport_error(web.HTTPConflict, "TOOL_REQUEST_CONFLICT", "文件工具请求编号已经使用")
            gate.store._record_event(db, gate.config.run_id, "TOOL_STARTED", {"tool_id": name, "call_id": call_id}, gate.config.lease_epoch, "workspace-file-start:" + call_id)
            db.execute("UPDATE agent_runs SET revision=revision+1 WHERE run_id=?", (gate.config.run_id,))
            self._require_workspace_file_gate(db)
        return web.json_response({"protocol_version": 1, "run_id": gate.config.run_id, "call_id": call_id, "reserved": True}, headers={"Cache-Control": "no-store"})

    async def finish_workspace_file_tool(self, request):
        self._authorize(request)
        if request.query or request.content_type != "application/json":
            raise transport_error(web.HTTPBadRequest, "INVALID_TOOL_REQUEST", "文件工具回执格式无效")
        body = await request.json()
        if not isinstance(body, dict) or set(body) != {"protocol_version", "call_id", "tool_name", "outcome"} or type(body["protocol_version"]) is not int or body["protocol_version"] != 1 or not isinstance(body["call_id"], str) or not 1 <= len(body["call_id"]) <= 80 or any(not character.isascii() or not (character.isalnum() or character in "_.-") for character in body["call_id"]) or not isinstance(body["tool_name"], str) or body["tool_name"] not in {"workspace_read_file", "workspace_write_file"} or not isinstance(body["outcome"], str) or body["outcome"] not in {"RETURNED", "FAILED"}:
            raise transport_error(web.HTTPBadRequest, "INVALID_TOOL_REQUEST", "文件工具回执字段无效")
        if self.tool_budget is None or self.authority is None or self.authority.vm_access is None:
            raise transport_error(web.HTTPServiceUnavailable, "TOOL_SERVICE_UNAVAILABLE", "文件工具授权尚未装配")
        gate = self.sink
        with gate.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._require_workspace_file_gate(db)
            reservation = db.execute("SELECT tool_name,lease_epoch FROM agent_tool_reservations WHERE run_id=? AND request_key=?", (gate.config.run_id, body["call_id"])).fetchone()
            if reservation != (body["tool_name"], gate.config.lease_epoch):
                raise transport_error(web.HTTPConflict, "TOOL_REQUEST_CONFLICT", "文件工具预留不可核查")
            if db.execute("SELECT 1 FROM agent_run_events WHERE run_id=? AND lease_epoch=? AND origin_event_id=?", (gate.config.run_id, gate.config.lease_epoch, "workspace-file-finish:" + body["call_id"])).fetchone() is not None:
                raise transport_error(web.HTTPConflict, "TOOL_REQUEST_CONFLICT", "文件工具回执已经登记")
            gate.store._record_event(db, gate.config.run_id, "TOOL_FINISHED", {"tool_id": body["tool_name"], "call_id": body["call_id"], "outcome": body["outcome"]}, gate.config.lease_epoch, "workspace-file-finish:" + body["call_id"])
            db.execute("UPDATE agent_runs SET revision=revision+1 WHERE run_id=?", (gate.config.run_id,))
            self._require_workspace_file_gate(db)
        return web.json_response({"protocol_version": 1, "run_id": gate.config.run_id, "call_id": body["call_id"], "recorded": True}, headers={"Cache-Control": "no-store"})

    async def wait_for_requirements(self, request):
        self._authorize(request)
        if request.query or request.content_type != "application/json":
            raise transport_error(web.HTTPBadRequest, "INVALID_REQUEST", "成果要求请求格式无效")
        body = await request.json()
        if not isinstance(body, dict) or set(body) != {"protocol_version", "goal_revision"} or type(body["protocol_version"]) is not int or body["protocol_version"] != 1 or type(body["goal_revision"]) is not int or body["goal_revision"] < 1:
            raise transport_error(web.HTTPBadRequest, "INVALID_REQUEST", "成果要求请求字段无效")
        gate = self.sink
        with gate.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            run = self._require_gate(db)
            if run[5] != body["goal_revision"]:
                raise transport_error(web.HTTPConflict, "GOAL_CHANGED", "运行目标版本已经变化")
            requirements = RunRequirements.read_in_transaction(db, gate.config.run_id, run[5])
            if requirements["state"] not in {"PENDING_CONFIRMATION", "UNAVAILABLE"}:
                raise transport_error(web.HTTPConflict, "REQUIREMENTS_CHANGED", "成果要求已经确认")
            db.execute("UPDATE agent_runs SET status='WAITING_INPUT',revision=revision+1 WHERE run_id=? AND status='RUNNING'", (gate.config.run_id,))
            gate.store._record_event(db, gate.config.run_id, "STATUS_CHANGED", {"from": "RUNNING", "to": "WAITING_INPUT", "reason": "OUTPUT_REQUIREMENTS_UNCONFIRMED", "goal_revision": run[5]}, gate.config.lease_epoch, "requirements-wait:" + str(run[5]))
        return web.json_response({"protocol_version": 1, "run_id": gate.config.run_id, "status": "WAITING_INPUT", "requirements": requirements}, headers={"Cache-Control": "no-store"})

    async def request_additional_input(self, request):
        self._authorize(request)
        if request.query or request.content_type != "application/json":
            raise transport_error(web.HTTPBadRequest, "INVALID_TOOL_REQUEST", "补充事项请求格式无效")
        body = await request.json()
        if not isinstance(body, dict) or set(body) != {"protocol_version", "call_id", "goal_revision", "question"} or type(body["protocol_version"]) is not int or body["protocol_version"] != 1 or type(body["goal_revision"]) is not int or body["goal_revision"] < 1 or not isinstance(body["call_id"], str) or not body["call_id"] or len(body["call_id"]) > 80 or not isinstance(body["question"], str) or not body["question"].strip() or len(body["question"]) > 2000:
            raise transport_error(web.HTTPBadRequest, "INVALID_TOOL_REQUEST", "补充事项请求字段无效")
        if self.tool_budget is None:
            raise transport_error(web.HTTPServiceUnavailable, "TOOL_SERVICE_UNAVAILABLE", "补充事项工具尚未装配")
        gate = self.sink
        with ExitStack() as stack:
            if self.context_tools is not None:
                db = stack.enter_context(self.context_tools.guarded_result(gate_check=self._require_gate))
            else:
                db = stack.enter_context(gate.store.connect())
                db.execute("BEGIN IMMEDIATE")
            run = self._require_gate(db)
            if run[5] != body["goal_revision"] or run[6] != run[5]:
                raise transport_error(web.HTTPConflict, "GOAL_CHANGED", "运行目标版本已经变化")
            if not isinstance(run[4], str) or not run[4].strip() or run[9] is None:
                raise transport_error(web.HTTPConflict, "RUN_CONTEXT_INVALID", "运行目标或来源范围不可核查")
            root = gate.store.require_active_lineage(db, gate.config.run_id)
            budget = db.execute("SELECT max_tools FROM agent_tool_budgets WHERE root_run_id=?", (root,)).fetchone()
            if budget is None:
                raise transport_error(web.HTTPServiceUnavailable, "TOOL_BUDGET_UNAVAILABLE", "根运行工具预算尚未配置")
            if db.execute("SELECT count(*) FROM agent_tool_reservations WHERE root_run_id=?", (root,)).fetchone()[0] >= budget[0]:
                raise transport_error(web.HTTPTooManyRequests, "TOOL_BUDGET_EXHAUSTED", "工具预算已经用尽")
            digest = checksum({"goal_revision": run[5], "question": body["question"], "scope_proof": json.loads(run[9]) if run[9] else None})
            reserved = self.tool_budget.reserve_in_transaction(db, gate.config.run_id, gate.lease_owner, gate.config.lease_epoch, body["call_id"], digest, "request_additional_input")
            if not reserved:
                raise transport_error(web.HTTPConflict, "TOOL_REQUEST_CONFLICT", "补充事项请求编号已经使用")
            gate.store._record_event(db, gate.config.run_id, "TOOL_STARTED", {"tool_id": "request_additional_input", "call_id": body["call_id"]}, gate.config.lease_epoch, "input-request-start:" + body["call_id"])
            event_id = gate.store._record_event(db, gate.config.run_id, "INPUT_REQUIRED", {"question": body["question"], "goal_revision": run[5]}, gate.config.lease_epoch, "input-required:" + body["call_id"])
            gate.store._record_event(db, gate.config.run_id, "TOOL_FINISHED", {"tool_id": "request_additional_input", "call_id": body["call_id"], "outcome": "RETURNED", "goal_revision": run[5]}, gate.config.lease_epoch, "input-request-finish:" + body["call_id"])
            gate.store._record_event(db, gate.config.run_id, "STATUS_CHANGED", {"from": "RUNNING", "to": "WAITING_INPUT", "reason": "INPUT_REQUIRED", "goal_revision": run[5], "input_required_event_id": event_id}, gate.config.lease_epoch, "input-wait:" + body["call_id"])
            if db.execute("UPDATE agent_runs SET status='WAITING_INPUT',revision=revision+1 WHERE run_id=? AND status='RUNNING'", (gate.config.run_id,)).rowcount != 1:
                raise transport_error(web.HTTPConflict, "RUN_NOT_ACTIVE", "运行状态已经变化")
        return web.json_response({"protocol_version": 1, "run_id": gate.config.run_id, "status": "WAITING_INPUT", "goal_revision": run[5], "event_id": event_id}, headers={"Cache-Control": "no-store"})

    async def acknowledge_input(self, request):
        self._authorize(request)
        if request.query or request.content_type != "application/json":
            raise transport_error(web.HTTPBadRequest, "INVALID_INPUT_ACK", "补充输入回执无效")
        body = await request.json()
        if not isinstance(body, dict) or set(body) != {"protocol_version", "input_seq"} or type(body["protocol_version"]) is not int or body["protocol_version"] != 1 or type(body["input_seq"]) is not int or body["input_seq"] <= 0:
            raise transport_error(web.HTTPBadRequest, "INVALID_INPUT_ACK", "补充输入回执无效")
        gate = self.sink
        with gate.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            run = self._require_gate(db)
            item = db.execute("SELECT input_id,goal_revision,applied_event_id FROM agent_run_inputs WHERE run_id=? AND input_seq=?", (gate.config.run_id, body["input_seq"])).fetchone()
            if item is None:
                raise transport_error(web.HTTPConflict, "INPUT_NOT_FOUND", "补充输入不存在")
            if item[2] is None:
                if item[1] != run[6] + 1:
                    raise transport_error(web.HTTPConflict, "INPUT_ORDER_INVALID", "补充输入顺序无效")
                event_id = gate.store._record_event(db, gate.config.run_id, "INPUT_APPLIED", {"input_id": item[0], "input_seq": body["input_seq"], "goal_revision": item[1]}, gate.config.lease_epoch)
                db.execute("UPDATE agent_run_inputs SET applied_event_id=? WHERE run_id=? AND input_seq=?", (event_id, gate.config.run_id, body["input_seq"]))
                db.execute("UPDATE agent_runs SET applied_goal_revision=?,revision=revision+1 WHERE run_id=?", (item[1], gate.config.run_id))
            else:
                event_id = item[2]
            event = db.execute("SELECT event_id,seq,type,occurred_at,trace_id,payload_version,payload FROM agent_run_events WHERE event_id=? AND run_id=?", (event_id, gate.config.run_id)).fetchone()
            saved = gate.store._event(gate.config.run_id, event)
        return web.json_response({"protocol_version": 1, "event": saved}, headers={"Cache-Control": "no-store"})

    async def bi_definitions(self, request):
        self._authorize(request)
        if request.query or self.authority is None or self.scope_service is None or self.bridge is None:
            raise transport_error(web.HTTPForbidden, "TOOL_SERVICE_UNAVAILABLE", "经营查询授权不可用")
        from hermes_bi_authority import HermesBIQueryAuthority, bi_tool_definitions
        with self.sink.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._require_workspace_file_gate(db)
        definitions = bi_tool_definitions(self.bridge._store, self.space_id)
        prepared = None
        selection = self.authority.services.broker.method_selection
        if selection is not None:
            access = HermesBIQueryAuthority(self.scope_service)
            with selection.drafts._locked(), self.sink.store.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                self._require_workspace_file_gate(db)
                method = selection._require_current_in_transaction(db, self.sink)
                if method["sop_id"] == "SOP03":
                    _, binding = access.require_in_transaction(db, self.authority)
                    prepared = json.loads(binding.parameters_json)
        with self.sink.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._require_workspace_file_gate(db)
        if prepared is not None:
            definitions = [dict(item) for item in definitions]
            for item in definitions:
                if item["name"] == "query_metrics":
                    item["description"] = item["description"] + "\n当前运行的已授权查询参数（调用时必须逐字段原样使用）：" + json.dumps(prepared, ensure_ascii=False, sort_keys=True)
        return web.json_response({"protocol_version": 1, "definitions": definitions}, headers={"Cache-Control": "no-store"})

    async def bi_tool(self, request):
        self._authorize(request)
        if request.query or request.content_type != "application/json" or self.authority is None or self.scope_service is None or self.tool_budget is None or self.bridge is None:
            raise transport_error(web.HTTPForbidden, "TOOL_SERVICE_UNAVAILABLE", "经营查询授权不可用")
        body = await request.json()
        if not isinstance(body, dict) or set(body) != {"protocol_version", "call_id", "tool_name", "arguments"} or type(body["protocol_version"]) is not int or body["protocol_version"] != 1 or not isinstance(body["call_id"], str) or not 1 <= len(body["call_id"]) <= 80 or body["tool_name"] not in ("query_metrics", "read_evidence") or not isinstance(body["arguments"], dict):
            raise transport_error(web.HTTPBadRequest, "INVALID_TOOL_REQUEST", "经营查询请求字段无效")
        from fc02_agent import Fc02Tool
        from hermes_bi_authority import HermesBIQueryAuthority, bi_request_id
        access = HermesBIQueryAuthority(self.scope_service)
        selection = self.authority.services.broker.method_selection
        if selection is None:
            raise transport_error(web.HTTPServiceUnavailable, "TOOL_SERVICE_UNAVAILABLE", "经营查询方法服务不可用")
        tool = Fc02Tool(self.bridge._store, lambda: access.context(self.authority), body["tool_name"])
        if list(Draft202012Validator(tool.parameters, format_checker=FormatChecker()).iter_errors(body["arguments"])):
            raise transport_error(web.HTTPBadRequest, "INVALID_TOOL_REQUEST", "经营查询参数不符合正式 Schema")
        gate, call_id, name = self.sink, body["call_id"], body["tool_name"]
        with selection.drafts._locked(), gate.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            run = self._require_workspace_file_gate(db)
            selected_method = selection._require_current_in_transaction(db, gate)
            if selected_method["sop_id"] != "SOP03":
                raise transport_error(web.HTTPForbidden, "SOURCE_SCOPE_FORBIDDEN", "当前方法不允许经营查询")
            record, binding = access.require_in_transaction(db, self.authority)
            access.bind_epoch_in_transaction(db, self.authority)
            if name == "query_metrics" and checksum(body["arguments"]) != checksum(json.loads(binding.parameters_json)):
                raise transport_error(web.HTTPForbidden, "SOURCE_SCOPE_FORBIDDEN", "经营查询参数超出本人明确范围")
            if name == "read_evidence":
                query = self.bridge._store.get(db, self.space_id, "query", body["arguments"]["query_id"])
                envelope = query.get("envelope")
                if not isinstance(envelope, dict) or (envelope.get("owner_id"), envelope.get("execution_namespace"), envelope.get("dataset_id"), envelope.get("dataset_version"), envelope.get("session_id")) != (
                        record["owner_id"], record["namespace"], record["dataset_id"], record["dataset_version"], record["session_id"]):
                    raise transport_error(web.HTTPForbidden, "SOURCE_SCOPE_FORBIDDEN", "原查询不属于当前本人会话")
                current_request_id = bi_request_id(gate.config.run_id, run[5])
                if envelope.get("request_id") != current_request_id and body["arguments"]["query_id"] != binding.previous_query_id:
                    raise transport_error(web.HTTPForbidden, "SOURCE_SCOPE_FORBIDDEN", "原查询未获当前运行选择")
                if envelope.get("request_id") == current_request_id and body["arguments"]["query_id"] != binding.previous_query_id:
                    prior_query = db.execute("SELECT 1 FROM agent_run_events WHERE run_id=? AND type='TOOL_FINISHED' "
                        "AND json_extract(payload,'$.tool_id')='query_metrics' AND json_extract(payload,'$.outcome')='RETURNED' "
                        "AND json_extract(payload,'$.goal_revision')=? AND json_extract(payload,'$.query_id')=? LIMIT 1",
                        (gate.config.run_id, run[5], body["arguments"]["query_id"])).fetchone()
                    if prior_query is None:
                        raise transport_error(web.HTTPForbidden, "SOURCE_SCOPE_FORBIDDEN", "原查询不属于当前目标版本")
            digest = checksum({"tool": name, "arguments": body["arguments"], "binding_sha256": record["binding_sha256"], "goal_revision": run[5]})
            approved_revision, approved_binding = run[5], record["binding_sha256"]
            prior = db.execute("SELECT 1 FROM agent_tool_reservations WHERE run_id=? AND request_key=?", (gate.config.run_id, call_id)).fetchone()
            if prior is not None:
                raise transport_error(web.HTTPConflict, "TOOL_REQUEST_CONFLICT", "经营查询请求已经登记")
            root = gate.store.require_active_lineage(db, gate.config.run_id)
            budget = db.execute("SELECT max_tools FROM agent_tool_budgets WHERE root_run_id=?", (root,)).fetchone()
            if budget is None:
                raise transport_error(web.HTTPServiceUnavailable, "TOOL_BUDGET_UNAVAILABLE", "根运行工具预算尚未配置")
            if db.execute("SELECT count(*) FROM agent_tool_reservations WHERE root_run_id=?", (root,)).fetchone()[0] >= budget[0]:
                raise transport_error(web.HTTPTooManyRequests, "TOOL_BUDGET_EXHAUSTED", "工具预算已经用尽")
            self.tool_budget.reserve_in_transaction(db, gate.config.run_id, gate.lease_owner, gate.config.lease_epoch, call_id, digest, name)
            gate.store._record_event(db, gate.config.run_id, "TOOL_STARTED", {"tool_id": name, "call_id": call_id}, gate.config.lease_epoch, "bi-start:" + call_id)
            db.execute("UPDATE agent_runs SET revision=revision+1 WHERE run_id=?", (gate.config.run_id,))
        result = json.loads(await tool.execute(**body["arguments"]))
        query_id = result.get("query_id") if isinstance(result, dict) and name == "query_metrics" else body["arguments"].get("query_id")
        if not isinstance(result, dict) or not isinstance(result.get("sources"), list) or not result["sources"] or not isinstance(query_id, str):
            raise ValueError("经营查询结果不可核查")
        with selection.drafts._locked(), gate.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            run = self._require_workspace_file_gate(db)
            if selection._require_current_in_transaction(db, gate) != selected_method:
                raise web.HTTPConflict(text="经营查询执行期间方法已经变化")
            record, _ = access.require_in_transaction(db, self.authority)
            if (run[5], record["binding_sha256"]) != (approved_revision, approved_binding):
                raise web.HTTPConflict(text="经营查询执行期间目标授权已经变化")
            approved = {(item[1], item[2]) for item in record["references"]}
            for source in result["sources"]:
                if not isinstance(source, dict) or (source.get("source_id"), source.get("version")) not in approved:
                    raise web.HTTPForbidden(text="经营查询结果超出授权来源")
                current = self.scope_service.read_source_in_transaction(db, gate.store, gate.config.run_id, gate.lease_owner,
                                                                        gate.config.lease_epoch, source["source_id"])
                if current["version"] != source["version"] or source.get("source_type") != "SIMULATED":
                    raise web.HTTPConflict(text="经营查询结果来源已经变化")
            reservation = db.execute("SELECT request_digest,tool_name,lease_epoch FROM agent_tool_reservations WHERE run_id=? AND request_key=?", (gate.config.run_id, call_id)).fetchone()
            if reservation != (digest, name, gate.config.lease_epoch):
                raise ValueError("经营查询工具预留不可核查")
            gate.store._record_event(db, gate.config.run_id, "TOOL_FINISHED", {"tool_id": name, "call_id": call_id,
                "outcome": "RETURNED", "goal_revision": run[5], "query_id": query_id, "result_sha256": checksum(result)},
                gate.config.lease_epoch, "bi-finish:" + call_id)
            db.execute("UPDATE agent_runs SET revision=revision+1 WHERE run_id=?", (gate.config.run_id,))
        return web.json_response({"protocol_version": 1, "result": result}, headers={"Cache-Control": "no-store"})

    async def read_evidence(self, request):
        self._authorize(request)
        if request.query or request.content_type != "application/json":
            raise transport_error(web.HTTPBadRequest, "INVALID_TOOL_REQUEST", "来源读取请求格式无效")
        body = await request.json()
        if not isinstance(body, dict) or set(body) != {"protocol_version", "call_id", "source"} or type(body["protocol_version"]) is not int or body["protocol_version"] != 1 or not isinstance(body["call_id"], str) or not body["call_id"] or len(body["call_id"]) > 80 or not isinstance(body["source"], str) or not 1 <= len(body["source"]) <= 100:
            raise transport_error(web.HTTPBadRequest, "INVALID_TOOL_REQUEST", "来源读取请求字段无效")
        if self.tool_budget is None or self.bridge is None or self.scope_service is None:
            raise transport_error(web.HTTPServiceUnavailable, "TOOL_SERVICE_UNAVAILABLE", "来源读取服务尚未装配")
        gate, source, call_id = self.sink, body["source"], body["call_id"]
        with gate.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            run = self._require_gate(db)
            if run[5] != run[6]:
                raise transport_error(web.HTTPConflict, "GOAL_CHANGED", "当前目标补充尚未采用")
            if run[8] is None or run[9] is None or not run[7]:
                raise transport_error(web.HTTPConflict, "SOURCE_PROOF_UNAVAILABLE", "运行缺少获准来源证明")
            selected = json.loads(run[8])
            if source not in selected:
                raise transport_error(web.HTTPForbidden, "SOURCE_SCOPE_FORBIDDEN", "来源未获当前运行选择")
            proof = self.scope_service.prove_in_transaction(db, run[7], selected)
            pins = {item[0]: (item[1], item[2]) for item in proof.source_pins}
            document = require_current_business_source(self.bridge._store, db, self.space_id, self.actor_id, source)
            if source not in pins or (document["version"], checksum(document)) != pins[source]:
                raise transport_error(web.HTTPConflict, "SOURCE_SCOPE_CHANGED", "来源版本或内容已经变化")
            digest = checksum({"source": source, "goal_revision": run[5], "scope_proof": json.loads(run[9]), "document_sha256": checksum(document)})
            prior = db.execute("SELECT request_digest,tool_name,lease_epoch FROM agent_tool_reservations WHERE run_id=? AND request_key=?", (gate.config.run_id, call_id)).fetchone()
            if prior is not None and prior != (digest, "bossEvidenceRead", gate.config.lease_epoch):
                raise transport_error(web.HTTPConflict, "TOOL_REQUEST_CONFLICT", "工具请求编号或来源已经变化")
            root = gate.store.require_active_lineage(db, gate.config.run_id)
            budget = db.execute("SELECT max_tools FROM agent_tool_budgets WHERE root_run_id=?", (root,)).fetchone()
            if budget is None:
                raise transport_error(web.HTTPServiceUnavailable, "TOOL_BUDGET_UNAVAILABLE", "根运行工具预算尚未配置")
            if prior is None and db.execute("SELECT count(*) FROM agent_tool_reservations WHERE root_run_id=?", (root,)).fetchone()[0] >= budget[0]:
                raise transport_error(web.HTTPTooManyRequests, "TOOL_BUDGET_EXHAUSTED", "工具预算已经用尽")
            if self.tool_budget.reserve_in_transaction(db, gate.config.run_id, gate.lease_owner, gate.config.lease_epoch, call_id, digest, "bossEvidenceRead"):
                gate.store._record_event(db, gate.config.run_id, "TOOL_STARTED", {"tool_id": "bossEvidenceRead", "call_id": call_id}, gate.config.lease_epoch, "evidence-start:" + call_id)
                gate.store._record_event(db, gate.config.run_id, "TOOL_FINISHED", {"tool_id": "bossEvidenceRead", "call_id": call_id, "outcome": "RETURNED", "goal_revision": run[5], "source_ref": {"source_id": source, "version": document["version"], "source_sha256": checksum(document)}}, gate.config.lease_epoch, "evidence-finish:" + call_id)
                db.execute("UPDATE agent_runs SET revision=revision+1 WHERE run_id=?", (gate.config.run_id,))
            event = db.execute("SELECT occurred_at FROM agent_run_events WHERE run_id=? AND lease_epoch=? AND origin_event_id=? AND type='TOOL_FINISHED'", (gate.config.run_id, gate.config.lease_epoch, "evidence-finish:" + call_id)).fetchone()
            if event is None:
                raise transport_error(web.HTTPConflict, "TOOL_RESULT_UNAVAILABLE", "来源读取事件不可核查")
            result = {"source_type": document["source_type"], "source_id": source, "version": document["version"], "source_sha256": checksum(document), "published_at": document.get("published_at"), "author_contact_id": document.get("author_contact_id"), "original_locator": document.get("original_locator"), "content": document["content"], "read_at": event[0]}
            result.update({key: document[key] for key in ("author_kind", "author_display_name", "generator_version", "business_basis", "allowed_use", "valid_from", "valid_until") if key in document})
            self._require_gate(db)
        return web.json_response({"protocol_version": 1, "result": result}, headers={"Cache-Control": "no-store"})

    async def read_documents(self, request):
        self._authorize(request)
        if request.query or request.content_type != "application/json":
            raise transport_error(web.HTTPBadRequest, "INVALID_TOOL_REQUEST", "工具请求格式无效")
        body = await request.json()
        if not isinstance(body, dict) or set(body) != {"protocol_version", "call_id"} or type(body["protocol_version"]) is not int or body["protocol_version"] != 1 or not isinstance(body["call_id"], str) or not body["call_id"] or len(body["call_id"]) > 80:
            raise transport_error(web.HTTPBadRequest, "INVALID_TOOL_REQUEST", "工具请求字段无效")
        if self.tool_budget is None:
            raise transport_error(web.HTTPServiceUnavailable, "TOOL_SERVICE_UNAVAILABLE", "业务读取与工具预算尚未装配")
        gate = self.sink
        call_id = body["call_id"]
        with gate.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            digest, existing = self._document_request(db, call_id)
            if existing is not None:
                result = self._document_result(db, call_id, digest)
                if result is not None:
                    return web.json_response({"protocol_version": 1, "result": result}, headers={"Cache-Control": "no-store"})
                if existing[3] >= gate.config.lease_epoch:
                    raise transport_error(web.HTTPConflict, "TOOL_RESULT_PENDING", "工具结果尚未保存")
            else:
                root = gate.store.require_active_lineage(db, gate.config.run_id)
                budget = db.execute("SELECT max_tools FROM agent_tool_budgets WHERE root_run_id=?", (root,)).fetchone()
                if budget is None:
                    raise transport_error(web.HTTPServiceUnavailable, "TOOL_BUDGET_UNAVAILABLE", "根运行工具预算尚未配置")
                used = db.execute("SELECT count(*) FROM agent_tool_reservations WHERE root_run_id=?", (root,)).fetchone()[0]
                if used >= budget[0]:
                    raise transport_error(web.HTTPTooManyRequests, "TOOL_BUDGET_EXHAUSTED", "工具预算已经用尽")
                reserved = self.tool_budget.reserve_in_transaction(db, gate.config.run_id, gate.lease_owner, gate.config.lease_epoch, call_id, digest, "read_bound_documents")
                if not reserved:
                    raise transport_error(web.HTTPConflict, "TOOL_REQUEST_CONFLICT", "工具请求编号已经登记")
                gate.store._record_event(db, gate.config.run_id, "TOOL_STARTED", {"tool_id": "read_bound_documents", "call_id": call_id}, gate.config.lease_epoch, "document-start:" + call_id)
                db.execute("UPDATE agent_runs SET revision=revision+1 WHERE run_id=?", (gate.config.run_id,))
        with gate.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            current_digest, reservation = self._document_request(db, call_id)
            if reservation is None or current_digest != digest:
                raise transport_error(web.HTTPConflict, "TOOL_REQUEST_CONFLICT", "工具请求的运行范围已经变化")
            existing_result = self._document_result(db, call_id, digest)
            if existing_result is not None:
                return web.json_response({"protocol_version": 1, "result": existing_result}, headers={"Cache-Control": "no-store"})
            result = self.read_bound_documents_in_transaction(db, self.bridge)
            key = hashlib.sha256(json.dumps([gate.config.run_id, call_id], ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
            saved = {"run_id": gate.config.run_id, "call_id": call_id, "request_digest": digest, "result": result}
            db.execute("INSERT INTO objects(namespace,kind,id,body) VALUES (?,'hermes_document_result',?,?)", (self.space_id, key, json.dumps(saved, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)))
            gate.store._record_event(db, gate.config.run_id, "TOOL_FINISHED", {"tool_id": "read_bound_documents", "call_id": call_id, "outcome": "RETURNED"}, gate.config.lease_epoch, "document-finish:" + call_id)
            db.execute("UPDATE agent_runs SET revision=revision+1 WHERE run_id=?", (gate.config.run_id,))
        return web.json_response({"protocol_version": 1, "result": result}, headers={"Cache-Control": "no-store"})

    async def read_document_result(self, request):
        self._authorize(request)
        if request.query:
            raise transport_error(web.HTTPBadRequest, "INVALID_TOOL_REQUEST", "工具请求格式无效")
        call_id = request.match_info["call_id"]
        if not call_id or len(call_id) > 80:
            raise transport_error(web.HTTPBadRequest, "INVALID_TOOL_REQUEST", "工具请求字段无效")
        if self.tool_budget is None:
            raise transport_error(web.HTTPServiceUnavailable, "TOOL_SERVICE_UNAVAILABLE", "业务读取与工具预算尚未装配")
        with self.sink.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            digest, existing = self._document_request(db, call_id)
            if existing is None:
                raise transport_error(web.HTTPNotFound, "TOOL_REQUEST_NOT_FOUND", "工具请求不存在")
            result = self._document_result(db, call_id, digest)
            if result is None:
                raise transport_error(web.HTTPConflict, "TOOL_RESULT_PENDING", "工具结果尚未保存")
        return web.json_response({"protocol_version": 1, "result": result}, headers={"Cache-Control": "no-store"})

    async def read_context(self, request):
        self._authorize(request)
        if request.query or request.content_type != "application/json":
            raise transport_error(web.HTTPBadRequest, "INVALID_TOOL_REQUEST", "工具请求格式无效")
        body = await request.json()
        if not isinstance(body, dict) or set(body) != {"protocol_version", "call_id"} or type(body["protocol_version"]) is not int or body["protocol_version"] != 1 or not isinstance(body["call_id"], str) or not body["call_id"] or len(body["call_id"]) > 80:
            raise transport_error(web.HTTPBadRequest, "INVALID_TOOL_REQUEST", "工具请求字段无效")
        if self.context_tools is None:
            raise transport_error(web.HTTPServiceUnavailable, "CONTEXT_SERVICE_UNAVAILABLE", "运行上下文尚未装配")
        name = {"memory": "read_product_memory", "method": "read_enabled_method"}[request.match_info["kind"]]
        gate = self.sink
        with self.context_tools.guarded_read(name, gate_check=self._require_gate) as (db, result):
            goal = db.execute("SELECT goal_revision,applied_goal_revision FROM agent_runs WHERE run_id=?", (gate.config.run_id,)).fetchone()
            if goal is None or goal[0] != goal[1]:
                raise transport_error(web.HTTPConflict, "GOAL_CHANGED", "运行目标版本尚未采用")
            root = gate.store.require_active_lineage(db, gate.config.run_id)
            budget = db.execute("SELECT max_tools FROM agent_tool_budgets WHERE root_run_id=?", (root,)).fetchone()
            if budget is None:
                raise transport_error(web.HTTPServiceUnavailable, "TOOL_BUDGET_UNAVAILABLE", "根运行工具预算尚未配置")
            previous = db.execute("SELECT root_run_id,request_digest,tool_name,lease_epoch FROM agent_tool_reservations WHERE run_id=? AND request_key=?", (gate.config.run_id, body["call_id"])).fetchone()
            digest = checksum({"context_digest": self.context_tools.request_digest(name), "goal_revision": goal[0]})
            if previous is not None and previous != (root, digest, name, gate.config.lease_epoch):
                raise transport_error(web.HTTPConflict, "TOOL_REQUEST_CONFLICT", "工具请求编号对应的内容已经变化")
            if previous is None and db.execute("SELECT count(*) FROM agent_tool_reservations WHERE root_run_id=?", (root,)).fetchone()[0] >= budget[0]:
                raise transport_error(web.HTTPTooManyRequests, "TOOL_BUDGET_EXHAUSTED", "工具预算已经用尽")
            reserved = self.tool_budget.reserve_in_transaction(db, gate.config.run_id, gate.lease_owner, gate.config.lease_epoch, body["call_id"], digest, name)
            if not reserved:
                raise transport_error(web.HTTPConflict, "TOOL_RESULT_UNAVAILABLE", "上下文工具请求已经执行，不能重复采用")
            gate.store._record_event(db, gate.config.run_id, "TOOL_STARTED", {"tool_id": name, "call_id": body["call_id"]}, gate.config.lease_epoch, "context-start:" + body["call_id"])
            db.execute("UPDATE agent_runs SET revision=revision+1 WHERE run_id=?", (gate.config.run_id,))
            finished = {"tool_id": name, "call_id": body["call_id"], "outcome": "RETURNED"}
            if name == "read_enabled_method":
                result["goal_revision"] = goal[0]
                finished.update({"goal_revision": goal[0], "method_ref": result["reference"]["method"]})
            gate.store._record_event(db, gate.config.run_id, "TOOL_FINISHED", finished, gate.config.lease_epoch, "context-finish:" + body["call_id"])
            db.execute("UPDATE agent_runs SET revision=revision+1 WHERE run_id=?", (gate.config.run_id,))
            response = web.json_response({"protocol_version": 1, "result": result}, headers={"Cache-Control": "no-store"})
        return response

    def reserve_artifact_call_in_transaction(self, db, payload, *, tool_name="boss_meeting_brief"):
        run = self._require_gate(db)
        if self.tool_budget is None:
            raise ValueError("成果工具缺少运行预算")
        if self.scope_service is None or run[8] is None or not set(payload["source_ids"]).issubset(json.loads(run[8])):
            raise transport_error(web.HTTPForbidden, "SOURCE_SCOPE_INVALID", "成果来源不属于当前运行范围")
        for source_id in payload["source_ids"]:
            self.scope_service.read_source_in_transaction(db, self.sink.store, self.sink.config.run_id,
                                                          self.sink.lease_owner, self.sink.config.lease_epoch, source_id)
        if self.artifact_tools is not None:
            self.artifact_tools.preparation._require_budget(db, self.sink.config.run_id)
        if tool_name not in {"boss_meeting_brief", "boss_runtime_meeting_brief"}:
            raise ValueError("成果工具名称无效")
        key = ("artifact:" if tool_name == "boss_meeting_brief" else "runtime-brief:") + payload["request_key"]
        digest = checksum(payload)
        gate = self.sink
        reserved = self.tool_budget.reserve_in_transaction(db, gate.config.run_id, gate.lease_owner, gate.config.lease_epoch, key, digest, tool_name)
        if not reserved:
            raise transport_error(web.HTTPConflict, "TOOL_RESULT_PENDING", "成果工具原请求需要核查")
        origin = "artifact-tool-start:" + payload["request_key"] if tool_name == "boss_meeting_brief" else "runtime-brief-start:" + payload["request_key"]
        gate.store._record_event(db, gate.config.run_id, "TOOL_STARTED", {"tool_id": tool_name, "call_id": key}, gate.config.lease_epoch, origin)
        db.execute("UPDATE agent_runs SET revision=revision+1 WHERE run_id=?", (gate.config.run_id,))
        return key

    async def meeting_brief(self, request):
        self._authorize(request)
        if request.query or request.content_type != "application/json":
            raise transport_error(web.HTTPBadRequest, "INVALID_TOOL_REQUEST", "成果工具请求格式无效")
        body = await request.json()
        if not isinstance(body, dict) or set(body) != {"protocol_version", "arguments"} or type(body["protocol_version"]) is not int or body["protocol_version"] != 1:
            raise transport_error(web.HTTPBadRequest, "INVALID_TOOL_REQUEST", "成果工具请求字段无效")
        payload = body["arguments"]
        schema = "meeting_brief_format_tool_request" if isinstance(payload, dict) and "format_name" in payload else "meeting_brief_tool_request"
        if not ARTIFACT_VALIDATORS[schema].is_valid(payload):
            raise transport_error(web.HTTPBadRequest, "INVALID_TOOL_REQUEST", "成果工具参数无效")
        if self.artifact_tools is None:
            raise transport_error(web.HTTPServiceUnavailable, "ARTIFACT_SERVICE_UNAVAILABLE", "成果工具尚未装配本人会话")
        self.artifact_tools.authorize()
        self.artifact_tools.require_ready()
        with self.sink.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            key = self.reserve_artifact_call_in_transaction(db, payload)
        result = self.artifact_tools.execute(payload)
        audit = result.get("section_audit") if isinstance(result, dict) else None
        safe_audit = safe_section_audit(audit) if audit is not None else None
        if safe_audit is not None:
            result = {**result, "section_audit": safe_audit}
        with self.sink.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            run = self._require_gate(db)
            self.artifact_tools.channel.require_run_api_role(self.artifact_tools.request)
            self.artifact_tools.channel.require_run_subscription(self.artifact_tools.request, run[7])
            finished = {"tool_id": "boss_meeting_brief", "call_id": key, "outcome": "RETURNED"}
            if safe_audit is not None:
                finished["section_audit"] = safe_audit
            self.sink.store._record_event(db, self.sink.config.run_id, "TOOL_FINISHED", finished, self.sink.config.lease_epoch, "artifact-tool-finish:" + payload["request_key"])
            db.execute("UPDATE agent_runs SET revision=revision+1 WHERE run_id=?", (self.sink.config.run_id,))
        return web.json_response({"protocol_version": 1, "artifact": result}, headers={"Cache-Control": "no-store"})

    async def runtime_meeting_brief(self, request):
        from hermes_domain_schema import RUNTIME_BRIEF_SCHEMA
        self._authorize(request)
        if request.query or request.content_type != "application/json":
            raise transport_error(web.HTTPBadRequest, "INVALID_TOOL_REQUEST", "会议成果请求格式无效")
        body = await request.json()
        if not isinstance(body, dict) or set(body) != {"protocol_version", "arguments"} or type(body["protocol_version"]) is not int or body["protocol_version"] != 1 or not Draft202012Validator(RUNTIME_BRIEF_SCHEMA).is_valid(body["arguments"]):
            raise transport_error(web.HTTPBadRequest, "INVALID_TOOL_REQUEST", "会议成果请求字段无效")
        if self.artifact_tools is None or self.context_tools is None or self.authority is None:
            raise transport_error(web.HTTPServiceUnavailable, "ARTIFACT_SERVICE_UNAVAILABLE", "会议成果服务尚未装配")
        self.artifact_tools.authorize()
        self.artifact_tools.require_ready()
        self.context_tools.require_runtime_dependencies(self.context_tools.skill)
        self.context_tools.require_current()
        payload = body["arguments"]
        with self.sink.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            run = self._require_gate(db)
            if run[5] != payload["expected_goal_revision"] or run[6] != run[5]:
                raise transport_error(web.HTTPConflict, "GOAL_CHANGED", "会议成果目标版本已经变化")
            key = self.reserve_artifact_call_in_transaction(db, payload, tool_name="boss_runtime_meeting_brief")
        result = self.artifact_tools.execute_runtime_brief(payload, self.context_tools.skill)
        audit = result.get("section_audit") if isinstance(result, dict) else None
        safe_audit = safe_section_audit(audit) if audit is not None else None
        if safe_audit is not None:
            result = {**result, "section_audit": safe_audit}
        with self.context_tools.guarded_result(gate_check=self._require_gate) as db:
            self.artifact_tools.channel.require_run_api_role(self.artifact_tools.request)
            self.artifact_tools.channel.require_run_subscription(self.artifact_tools.request, self.context_tools.skill_reference["conversation_id"])
            finished = {"tool_id": "boss_runtime_meeting_brief", "call_id": key, "outcome": "RETURNED", "goal_revision": payload["expected_goal_revision"]}
            if safe_audit is not None:
                finished["section_audit"] = safe_audit
            self.sink.store._record_event(db, self.sink.config.run_id, "TOOL_FINISHED", finished, self.sink.config.lease_epoch, "runtime-brief-finish:" + payload["request_key"])
            db.execute("UPDATE agent_runs SET revision=revision+1 WHERE run_id=?", (self.sink.config.run_id,))
        return web.json_response({"protocol_version": 1, "artifact": result}, headers={"Cache-Control": "no-store"})

    async def prepare_domain_intent(self, request):
        self._authorize(request)
        if request.query or request.content_type != "application/json":
            raise transport_error(web.HTTPBadRequest, "INVALID_TOOL_REQUEST", "业务意图请求格式无效")
        body = await request.json()
        if not isinstance(body, dict) or set(body) != {"protocol_version", "request_key", "action", "params"} or type(body["protocol_version"]) is not int or body["protocol_version"] != 1 or not isinstance(body["request_key"], str) or not 8 <= len(body["request_key"]) <= 128 or not body["request_key"].isascii() or not all(char.isalnum() or char in "-_." for char in body["request_key"]):
            raise transport_error(web.HTTPBadRequest, "INVALID_TOOL_REQUEST", "业务意图请求字段无效")
        tool_name = request.match_info.get("tool_name", "prepare_domain_intent")
        formal_actions = {"meetingConfirm": "boss.meeting.confirm", "meetingCancel": "boss.meeting.cancel", "meetingHeld": "boss.meeting.held"}
        if tool_name != "prepare_domain_intent" and formal_actions.get(tool_name) != body["action"]:
            raise transport_error(web.HTTPBadRequest, "INVALID_TOOL_REQUEST", "会议工具名称与操作不一致")
        if self.authority is None or self.scope_service is None or self.tool_budget is None:
            raise transport_error(web.HTTPServiceUnavailable, "INTENT_SERVICE_UNAVAILABLE", "业务意图服务尚未装配本人会话")
        from hermes_domain_intents import preview_domain_intent
        from hermes_intents import INTENT_VALIDATORS
        gate = self.sink
        content = {"action": body["action"], "params": body["params"]}
        digest = checksum(content if tool_name == "prepare_domain_intent" else {**content, "tool_name": tool_name})
        with gate.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            migration = db.execute("SELECT sha256 FROM agent_schema_migrations WHERE version='upgrade2_intents_001'").fetchone()
            from pathlib import Path
            script = Path(__file__).parent / "migrations/upgrade2_intents_001.sql"
            if migration != (hashlib.sha256(script.read_bytes()).hexdigest(),):
                raise transport_error(web.HTTPServiceUnavailable, "INTENT_SERVICE_UNAVAILABLE", "业务意图迁移不可用")
            old = db.execute("SELECT request_digest,intent_id,status,preview FROM agent_intents WHERE run_id=? AND request_key=?", (gate.config.run_id, body["request_key"])).fetchone()
            if old is not None:
                if old[0] != digest or old[2] != "WAITING_CONFIRMATION":
                    raise transport_error(web.HTTPConflict, "INTENT_REQUEST_CONFLICT", "业务意图请求内容或状态已经变化")
                authority = self.authority
                channel = authority.services.recovery.channel
                channel.require_run_api_role(authority.request)
                plan, budget = authority.dispatcher.approved_budget_in_transaction(db, gate.config.run_id)
                if checksum(plan) != authority.plan_digest or budget != authority.budget:
                    raise transport_error(web.HTTPConflict, "INTENT_AUTHORITY_CHANGED", "运行授权已经变化")
                db.row_factory = sqlite3.Row
                run = db.execute("SELECT * FROM agent_runs WHERE run_id=?", (gate.config.run_id,)).fetchone()
                saved = json.loads(old[3])
                if run is None or run["lease_owner"] != gate.lease_owner or run["lease_epoch"] != gate.config.lease_epoch:
                    raise transport_error(web.HTTPConflict, "RUN_LEASE_UNAVAILABLE", "运行租约不可用")
                from hermes_source_invalidation import require_source_cleanup_complete
                require_source_cleanup_complete(db, gate.config.run_id)
                channel.require_run_subscription(authority.request, run["conversation_id"])
                current = preview_domain_intent(db, self.bridge._store, self.scope_service, run, body["action"], body["params"], allow_waiting=True)
                current.update({"plan_digest": authority.plan_digest, "budget_digest": checksum(authority.budget)})
                if current != saved:
                    raise transport_error(web.HTTPConflict, "INTENT_REQUEST_CONFLICT", "业务意图预览已经变化")
                channel.require_run_subscription(authority.request, run["conversation_id"])
                return web.json_response({"protocol_version": 1, "intent_id": old[1], "status": old[2]}, headers={"Cache-Control": "no-store"})
            self._require_gate(db)
            reservation = db.execute("SELECT request_digest,tool_name,lease_epoch FROM agent_tool_reservations WHERE run_id=? AND request_key=?", (gate.config.run_id, body["request_key"])).fetchone()
            if reservation is not None:
                raise transport_error(web.HTTPConflict, "INTENT_REQUEST_CONFLICT", "业务意图预留缺少可重读的原意图")
            root = gate.store.require_active_lineage(db, gate.config.run_id)
            budget = db.execute("SELECT max_tools FROM agent_tool_budgets WHERE root_run_id=?", (root,)).fetchone()
            if budget is None:
                raise transport_error(web.HTTPServiceUnavailable, "TOOL_BUDGET_UNAVAILABLE", "根运行工具预算尚未配置")
            if db.execute("SELECT count(*) FROM agent_tool_reservations WHERE root_run_id=?", (root,)).fetchone()[0] >= budget[0]:
                raise transport_error(web.HTTPTooManyRequests, "TOOL_BUDGET_EXHAUSTED", "工具预算已经用尽")
            if not self.tool_budget.reserve_in_transaction(db, gate.config.run_id, gate.lease_owner, gate.config.lease_epoch, body["request_key"], digest, tool_name):
                raise transport_error(web.HTTPConflict, "INTENT_REQUEST_CONFLICT", "业务意图预留不可重复使用")
            db.row_factory = sqlite3.Row
            run = db.execute("SELECT * FROM agent_runs WHERE run_id=?", (gate.config.run_id,)).fetchone()
            preview = preview_domain_intent(db, self.bridge._store, self.scope_service, run, body["action"], body["params"])
            preview.update({"plan_digest": self.authority.plan_digest, "budget_digest": checksum(self.authority.budget)})
            INTENT_VALIDATORS["preview_content"].validate(preview)
            self._require_gate(db)
            intent_id = str(uuid4())
            payload_digest = checksum(preview)
            db.execute("INSERT INTO agent_intents VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'WAITING_CONFIRMATION', NULL, NULL, ?, 0)", (intent_id, gate.config.run_id, self.actor_id, self.space_id, body["request_key"], digest, body["action"], preview["object_id"], preview["object_revision"], checksum(preview["source_refs"]), payload_digest, "intent-" + intent_id, json.dumps(preview, ensure_ascii=False, sort_keys=True, allow_nan=False), utc_now().isoformat()))
            gate.store._record_event(db, gate.config.run_id, "TOOL_STARTED", {"tool_id": tool_name, "call_id": body["request_key"]}, gate.config.lease_epoch, "intent-tool-start:" + body["request_key"])
            gate.store._record_event(db, gate.config.run_id, "TOOL_FINISHED", {"tool_id": tool_name, "call_id": body["request_key"], "outcome": "RETURNED"}, gate.config.lease_epoch, "intent-tool-finish:" + body["request_key"])
            gate.store._record_event(db, gate.config.run_id, "INTENT_PREPARED", {"intent_id": intent_id}, gate.config.lease_epoch)
            gate.store._record_event(db, gate.config.run_id, "STATUS_CHANGED", {"from": "RUNNING", "to": "WAITING_CONFIRMATION"}, gate.config.lease_epoch)
            db.execute("UPDATE agent_runs SET status='WAITING_CONFIRMATION',revision=revision+1 WHERE run_id=?", (gate.config.run_id,))
        return web.json_response({"protocol_version": 1, "intent_id": intent_id, "status": "WAITING_CONFIRMATION"}, headers={"Cache-Control": "no-store"})

    async def read_decision_receipt(self, request):
        self._authorize(request)
        if request.query or request.content_type != "application/json":
            raise transport_error(web.HTTPBadRequest, "INVALID_TOOL_REQUEST", "决定回执请求格式无效")
        body = await request.json()
        if not isinstance(body, dict) or set(body) != {"protocol_version", "intent_id", "call_id"} or type(body["protocol_version"]) is not int or body["protocol_version"] != 1 or any(not isinstance(body[k], str) or not body[k] or len(body[k]) > 128 or not body[k].isascii() or not all(c.isalnum() or c in "-_." for c in body[k]) for k in ("intent_id", "call_id")):
            raise transport_error(web.HTTPBadRequest, "INVALID_TOOL_REQUEST", "决定回执请求字段无效")
        if self.tool_budget is None or self.scope_service is None or self.authority is None:
            raise transport_error(web.HTTPServiceUnavailable, "TOOL_SERVICE_UNAVAILABLE", "决定回执服务尚未装配")
        from hermes_intents import read_domain_decision_receipt_in_transaction
        gate = self.sink
        with gate.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            from pathlib import Path
            migration = db.execute("SELECT sha256 FROM agent_schema_migrations WHERE version='upgrade2_intents_001'").fetchone()
            script = Path(__file__).parent / "migrations/upgrade2_intents_001.sql"
            if migration != (hashlib.sha256(script.read_bytes()).hexdigest(),):
                raise transport_error(web.HTTPServiceUnavailable, "INTENT_SERVICE_UNAVAILABLE", "业务意图迁移不可用")
            active = self._require_gate(db)
            if active[5] != active[6]:
                raise transport_error(web.HTTPConflict, "GOAL_CHANGED", "运行目标版本尚未采用")
            db.row_factory = sqlite3.Row
            rows = db.execute("SELECT d.receipt,d.request_digest AS decision_digest,d.request_key AS decision_key,i.* FROM agent_intent_decisions d JOIN agent_intents i ON i.intent_id=d.intent_id WHERE i.intent_id=? AND d.actor_id=? AND d.space_id=? AND i.run_id=? AND i.actor_id=? AND i.space_id=?", (body["intent_id"], self.actor_id, self.space_id, gate.config.run_id, self.actor_id, self.space_id)).fetchall()
            if len(rows) != 1:
                raise transport_error(web.HTTPNotFound, "RECEIPT_NOT_FOUND", "原决定回执不存在")
            row = rows[0]
            preview = json.loads(row["preview"])
            if preview["goal_revision"] != active[5] or active[9] is None:
                raise transport_error(web.HTTPConflict, "GOAL_CHANGED", "决定回执目标或来源范围不可用")
            selected = set(json.loads(active[8]))
            for ref in preview["source_refs"]:
                source_id = ref["source_id"]
                if source_id not in selected:
                    raise transport_error(web.HTTPForbidden, "SOURCE_SCOPE_INVALID", "决定来源不属于当前运行范围")
                self.scope_service.read_source_in_transaction(db, gate.store, gate.config.run_id, gate.lease_owner, gate.config.lease_epoch, source_id)
            receipt = read_domain_decision_receipt_in_transaction(db, row["intent_id"], row["decision_key"], row["decision_digest"], json.loads(row["receipt"]))
            db.row_factory = None
            digest = checksum({"intent_id": body["intent_id"], "goal_revision": active[5], "receipt": receipt})
            root = gate.store.require_active_lineage(db, gate.config.run_id)
            previous = db.execute("SELECT root_run_id,request_digest,tool_name,lease_epoch FROM agent_tool_reservations WHERE run_id=? AND request_key=?", (gate.config.run_id, body["call_id"])).fetchone()
            if previous is not None and previous != (root, digest, "read_decision_receipt", gate.config.lease_epoch):
                raise transport_error(web.HTTPConflict, "TOOL_REQUEST_CONFLICT", "工具请求编号对应内容已经变化")
            budget = db.execute("SELECT max_tools FROM agent_tool_budgets WHERE root_run_id=?", (root,)).fetchone()
            if budget is None:
                raise transport_error(web.HTTPServiceUnavailable, "TOOL_BUDGET_UNAVAILABLE", "工具预算尚未配置")
            if previous is None and db.execute("SELECT count(*) FROM agent_tool_reservations WHERE root_run_id=?", (root,)).fetchone()[0] >= budget[0]:
                raise transport_error(web.HTTPTooManyRequests, "TOOL_BUDGET_EXHAUSTED", "工具预算已经用尽")
            if self.tool_budget.reserve_in_transaction(db, gate.config.run_id, gate.lease_owner, gate.config.lease_epoch, body["call_id"], digest, "read_decision_receipt"):
                gate.store._record_event(db, gate.config.run_id, "TOOL_STARTED", {"tool_id": "read_decision_receipt", "call_id": body["call_id"]}, gate.config.lease_epoch, "decision-read-start:" + body["call_id"])
                gate.store._record_event(db, gate.config.run_id, "TOOL_FINISHED", {"tool_id": "read_decision_receipt", "call_id": body["call_id"], "outcome": "RETURNED", "goal_revision": active[5]}, gate.config.lease_epoch, "decision-read-finish:" + body["call_id"])
                db.execute("UPDATE agent_runs SET revision=revision+1 WHERE run_id=?", (gate.config.run_id,))
            self._require_gate(db)
        return web.json_response({"protocol_version": 1, "intent_id": body["intent_id"], "receipt": receipt}, headers={"Cache-Control": "no-store"})

    async def read_meeting_context(self, request):
        self._authorize(request)
        if request.query or request.content_type != "application/json":
            raise transport_error(web.HTTPBadRequest, "INVALID_TOOL_REQUEST", "会议读取请求格式无效")
        body = await request.json()
        if not isinstance(body, dict) or set(body) != {"protocol_version", "call_id"} or type(body["protocol_version"]) is not int or body["protocol_version"] != 1 or not isinstance(body["call_id"], str) or not body["call_id"] or len(body["call_id"]) > 80:
            raise transport_error(web.HTTPBadRequest, "INVALID_TOOL_REQUEST", "会议读取请求字段无效")
        if self.tool_budget is None or self.bridge is None or self.scope_service is None:
            raise transport_error(web.HTTPServiceUnavailable, "TOOL_SERVICE_UNAVAILABLE", "会议读取服务尚未装配")
        from hermes_domain_intents import read_meeting_context_in_transaction
        gate = self.sink
        with gate.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._require_gate(db)
            db.row_factory = sqlite3.Row
            run = db.execute("SELECT * FROM agent_runs WHERE run_id=?", (gate.config.run_id,)).fetchone()
            result = read_meeting_context_in_transaction(db, self.bridge._store, self.scope_service, run)
            digest = checksum({"goal_revision": run["goal_revision"], "scope_proof": json.loads(run["scope_proof"]), "result": result})
            db.row_factory = None
            previous = db.execute("SELECT request_digest,tool_name,lease_epoch FROM agent_tool_reservations WHERE run_id=? AND request_key=?", (gate.config.run_id, body["call_id"])).fetchone()
            if previous is not None and previous != (digest, "read_meeting_context", gate.config.lease_epoch):
                raise transport_error(web.HTTPConflict, "TOOL_REQUEST_CONFLICT", "会议内容或工具请求编号已经变化")
            root = gate.store.require_active_lineage(db, gate.config.run_id)
            budget = db.execute("SELECT max_tools FROM agent_tool_budgets WHERE root_run_id=?", (root,)).fetchone()
            if budget is None:
                raise transport_error(web.HTTPServiceUnavailable, "TOOL_BUDGET_UNAVAILABLE", "根运行工具预算尚未配置")
            if previous is None and db.execute("SELECT count(*) FROM agent_tool_reservations WHERE root_run_id=?", (root,)).fetchone()[0] >= budget[0]:
                raise transport_error(web.HTTPTooManyRequests, "TOOL_BUDGET_EXHAUSTED", "工具预算已经用尽")
            reserved = self.tool_budget.reserve_in_transaction(db, gate.config.run_id, gate.lease_owner, gate.config.lease_epoch, body["call_id"], digest, "read_meeting_context")
            if reserved:
                gate.store._record_event(db, gate.config.run_id, "TOOL_STARTED", {"tool_id": "read_meeting_context", "call_id": body["call_id"]}, gate.config.lease_epoch, "meeting-read-start:" + body["call_id"])
                gate.store._record_event(db, gate.config.run_id, "TOOL_FINISHED", {"tool_id": "read_meeting_context", "call_id": body["call_id"], "outcome": "RETURNED"}, gate.config.lease_epoch, "meeting-read-finish:" + body["call_id"])
                db.execute("UPDATE agent_runs SET revision=revision+1 WHERE run_id=?", (gate.config.run_id,))
            self._require_gate(db)
        return web.json_response({"protocol_version": 1, "result": result}, headers={"Cache-Control": "no-store"})

    async def read_meeting_projection(self, request):
        from hermes_domain_intents import read_meeting_projection_in_transaction
        self._authorize(request)
        if request.query or request.content_type != "application/json":
            raise transport_error(web.HTTPBadRequest, "INVALID_TOOL_REQUEST", "会议读取请求格式无效")
        body = await request.json()
        if not isinstance(body, dict) or set(body) != {"protocol_version", "call_id"} or type(body["protocol_version"]) is not int or body["protocol_version"] != 1 or not isinstance(body["call_id"], str) or not body["call_id"] or len(body["call_id"]) > 80:
            raise transport_error(web.HTTPBadRequest, "INVALID_TOOL_REQUEST", "会议读取请求字段无效")
        if self.tool_budget is None or self.bridge is None or self.scope_service is None:
            raise transport_error(web.HTTPServiceUnavailable, "TOOL_SERVICE_UNAVAILABLE", "会议读取服务尚未装配")
        kind = request.match_info["kind"]
        tool_name = {"catalog": "bossMeetingsRead", "arrangement": "meetingArrangementRead"}[kind]
        gate = self.sink
        with gate.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._require_gate(db)
            db.row_factory = sqlite3.Row
            run = db.execute("SELECT * FROM agent_runs WHERE run_id=?", (gate.config.run_id,)).fetchone()
            result = read_meeting_projection_in_transaction(db, self.bridge._store, self.scope_service, run, kind)
            db.row_factory = None
            if self.authority is not None:
                object_scope = self.authority.services.broker.object_scope
                if object_scope is None:
                    raise transport_error(web.HTTPServiceUnavailable, "MEETING_SCOPE_UNAVAILABLE", "会议对象范围尚未装配")
                selected = object_scope.read_meeting_in_transaction(db, gate, run["goal_revision"], result["meeting"]["meeting_id"])["meeting_context"]
                if selected["meeting"]["version"] != result["meeting"]["version"] or selected["meeting"]["participant_ids"] != result["meeting"]["participant_ids"] or kind == "arrangement" and selected["participants"] != result["contacts"]:
                    raise transport_error(web.HTTPConflict, "MEETING_SCOPE_CHANGED", "会议或参会人员范围已经变化")
            digest = checksum({"goal_revision": run["goal_revision"], "scope_proof": json.loads(run["scope_proof"]), "result": result})
            prior = db.execute("SELECT request_digest,tool_name,lease_epoch FROM agent_tool_reservations WHERE run_id=? AND request_key=?", (gate.config.run_id, body["call_id"])).fetchone()
            if prior is not None and prior != (digest, tool_name, gate.config.lease_epoch):
                raise transport_error(web.HTTPConflict, "TOOL_REQUEST_CONFLICT", "会议内容或工具请求编号已经变化")
            root = gate.store.require_active_lineage(db, gate.config.run_id)
            budget = db.execute("SELECT max_tools FROM agent_tool_budgets WHERE root_run_id=?", (root,)).fetchone()
            if budget is None:
                raise transport_error(web.HTTPServiceUnavailable, "TOOL_BUDGET_UNAVAILABLE", "根运行工具预算尚未配置")
            if prior is None and db.execute("SELECT count(*) FROM agent_tool_reservations WHERE root_run_id=?", (root,)).fetchone()[0] >= budget[0]:
                raise transport_error(web.HTTPTooManyRequests, "TOOL_BUDGET_EXHAUSTED", "工具预算已经用尽")
            if self.tool_budget.reserve_in_transaction(db, gate.config.run_id, gate.lease_owner, gate.config.lease_epoch, body["call_id"], digest, tool_name):
                gate.store._record_event(db, gate.config.run_id, "TOOL_STARTED", {"tool_id": tool_name, "call_id": body["call_id"]}, gate.config.lease_epoch, "meeting-projection-start:" + body["call_id"])
                gate.store._record_event(db, gate.config.run_id, "TOOL_FINISHED", {"tool_id": tool_name, "call_id": body["call_id"], "outcome": "RETURNED", "goal_revision": run["goal_revision"]}, gate.config.lease_epoch, "meeting-projection-finish:" + body["call_id"])
                db.execute("UPDATE agent_runs SET revision=revision+1 WHERE run_id=?", (gate.config.run_id,))
            self._require_gate(db)
        return web.json_response({"protocol_version": 1, "result": result}, headers={"Cache-Control": "no-store"})

    async def prepare_meeting_brief(self, request):
        self._authorize(request)
        if request.query or request.content_type != "application/json":
            raise transport_error(web.HTTPBadRequest, "INVALID_TOOL_REQUEST", "会议简报请求格式无效")
        body = await request.json()
        if not isinstance(body, dict) or set(body) != {"protocol_version", "request_key", "params"} or type(body["protocol_version"]) is not int or body["protocol_version"] != 1 or not isinstance(body["request_key"], str) or not 8 <= len(body["request_key"]) <= 128 or not body["request_key"].isascii() or not all(char.isalnum() or char in "-_." for char in body["request_key"]) or not isinstance(body["params"], dict) or set(body["params"]) != {"meeting_id", "meeting_version", "expected_version"} or any(not isinstance(value, str) or not value for value in body["params"].values()):
            raise transport_error(web.HTTPBadRequest, "INVALID_TOOL_REQUEST", "会议简报请求字段无效")
        if self.authority is None or self.context_tools is None or self.scope_service is None or self.tool_budget is None or self.bridge is None or self.authority.services.broker.object_scope is None:
            raise transport_error(web.HTTPServiceUnavailable, "BRIEF_SERVICE_UNAVAILABLE", "会议简报运行范围尚未装配")
        from hermes_domain_intents import brief_result_event_in_transaction, prepare_meeting_brief_in_transaction
        gate = self.sink
        with self.context_tools.guarded_result(gate_check=self._require_gate) as db:
            run = self._require_gate(db)
            if run[5] != run[6]:
                raise transport_error(web.HTTPConflict, "GOAL_CHANGED", "运行目标版本尚未采用")
            if self.context_tools.skill.sop_id != "SOP04":
                raise transport_error(web.HTTPConflict, "METHOD_CHANGED", "当前运行方法不适用于会议简报")
            method_event_id = self.context_tools.require_method_read_in_transaction(db, run[5])
            digest = checksum({"goal_revision": run[5], "scope_proof": json.loads(run[9]), "params": body["params"]})
            previous = db.execute("SELECT request_digest,tool_name,lease_epoch FROM agent_tool_reservations WHERE run_id=? AND request_key=?", (gate.config.run_id, body["request_key"])).fetchone()
            if previous is not None and previous != (digest, "boss.meeting.brief.prepare", gate.config.lease_epoch):
                raise transport_error(web.HTTPConflict, "TOOL_REQUEST_CONFLICT", "会议简报请求内容或版本已经变化")
            root = gate.store.require_active_lineage(db, gate.config.run_id)
            budget = db.execute("SELECT max_tools FROM agent_tool_budgets WHERE root_run_id=?", (root,)).fetchone()
            if budget is None:
                raise transport_error(web.HTTPServiceUnavailable, "TOOL_BUDGET_UNAVAILABLE", "根运行工具预算尚未配置")
            if previous is None and db.execute("SELECT count(*) FROM agent_tool_reservations WHERE root_run_id=?", (root,)).fetchone()[0] >= budget[0]:
                raise transport_error(web.HTTPTooManyRequests, "TOOL_BUDGET_EXHAUSTED", "工具预算已经用尽")
            reserved = self.tool_budget.reserve_in_transaction(db, gate.config.run_id, gate.lease_owner, gate.config.lease_epoch, body["request_key"], digest, "boss.meeting.brief.prepare")
            result = prepare_meeting_brief_in_transaction(db, self.bridge._store, self.authority.services.broker.object_scope, gate, body["params"], body["request_key"])
            finished = brief_result_event_in_transaction(db, self.bridge._store, gate.config.run_id, run[5], body["request_key"], result, self.context_tools.skill_reference["method"], method_event_id)
            self._require_gate(db)
            if reserved:
                gate.store._record_event(db, gate.config.run_id, "TOOL_STARTED", {"tool_id": "boss.meeting.brief.prepare", "call_id": body["request_key"]}, gate.config.lease_epoch, "brief-start:" + body["request_key"])
                gate.store._record_event(db, gate.config.run_id, "TOOL_FINISHED", finished, gate.config.lease_epoch, "brief-finish:" + body["request_key"])
                db.execute("UPDATE agent_runs SET revision=revision+1 WHERE run_id=?", (gate.config.run_id,))
        return web.json_response({"protocol_version": 1, "result": result}, headers={"Cache-Control": "no-store"})

    async def save_meeting_draft(self, request):
        self._authorize(request)
        if request.query or request.content_type != "application/json":
            raise transport_error(web.HTTPBadRequest, "INVALID_TOOL_REQUEST", "会议草稿请求格式无效")
        body = await request.json()
        if not isinstance(body, dict) or set(body) != {"protocol_version", "request_key", "params"} or type(body["protocol_version"]) is not int or body["protocol_version"] != 1 or not isinstance(body["request_key"], str) or not 8 <= len(body["request_key"]) <= 128 or not body["request_key"].isascii() or not all(char.isalnum() or char in "-_." for char in body["request_key"]):
            raise transport_error(web.HTTPBadRequest, "INVALID_TOOL_REQUEST", "会议草稿请求字段无效")
        if self.authority is None or self.scope_service is None or self.tool_budget is None or self.bridge is None:
            raise transport_error(web.HTTPServiceUnavailable, "DRAFT_SERVICE_UNAVAILABLE", "会议草稿服务尚未装配本人会话")
        from hermes_domain_intents import MEETING_DRAFT_VALIDATOR, draft_result_event_in_transaction, save_meeting_draft_in_transaction
        if not MEETING_DRAFT_VALIDATOR.is_valid(body["params"]):
            raise transport_error(web.HTTPBadRequest, "INVALID_TOOL_REQUEST", "会议草稿参数无效")
        gate = self.sink
        tool_name = "meetingDraftSave" if request.path.endswith("/meeting-draft-formal") else "save_meeting_draft"
        with gate.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            run_row = self._require_gate(db)
            if run_row[5] != run_row[6]:
                raise transport_error(web.HTTPConflict, "GOAL_CHANGED", "运行目标版本尚未采用")
            digest = checksum({"goal_revision": run_row[5], "scope_proof": json.loads(run_row[9]), "params": body["params"]})
            previous = db.execute("SELECT request_digest,tool_name,lease_epoch FROM agent_tool_reservations WHERE run_id=? AND request_key=?", (gate.config.run_id, body["request_key"])).fetchone()
            if previous is not None and previous != (digest, tool_name, gate.config.lease_epoch):
                raise transport_error(web.HTTPConflict, "TOOL_REQUEST_CONFLICT", "会议草稿请求内容或版本已经变化")
            root = gate.store.require_active_lineage(db, gate.config.run_id)
            budget = db.execute("SELECT max_tools FROM agent_tool_budgets WHERE root_run_id=?", (root,)).fetchone()
            if budget is None:
                raise transport_error(web.HTTPServiceUnavailable, "TOOL_BUDGET_UNAVAILABLE", "根运行工具预算尚未配置")
            if previous is None and db.execute("SELECT count(*) FROM agent_tool_reservations WHERE root_run_id=?", (root,)).fetchone()[0] >= budget[0]:
                raise transport_error(web.HTTPTooManyRequests, "TOOL_BUDGET_EXHAUSTED", "工具预算已经用尽")
            reserved = self.tool_budget.reserve_in_transaction(db, gate.config.run_id, gate.lease_owner, gate.config.lease_epoch, body["request_key"], digest, tool_name)
            db.row_factory = sqlite3.Row
            run = db.execute("SELECT * FROM agent_runs WHERE run_id=?", (gate.config.run_id,)).fetchone()
            result = save_meeting_draft_in_transaction(db, self.bridge._store, self.scope_service, run, body["params"], body["request_key"])
            event_payload = draft_result_event_in_transaction(db, self.bridge._store, gate.config.run_id, run["goal_revision"], body["request_key"], "meeting", result, tool_name=tool_name)
            if tool_name == "meetingDraftSave":
                receipt = db.execute("SELECT result FROM idempotency WHERE namespace=? AND operation=? AND key=?", (self.space_id, "boss.meeting.draft.save", event_payload["draft_ref"]["domain_request_key"])).fetchone()
                if receipt is None:
                    raise transport_error(web.HTTPConflict, "DRAFT_RECEIPT_UNAVAILABLE", "会议草稿领域回执不可核查")
                result = json.loads(receipt[0])
            db.row_factory = None
            self._require_gate(db)
            if reserved:
                gate.store._record_event(db, gate.config.run_id, "TOOL_STARTED", {"tool_id": tool_name, "call_id": body["request_key"]}, gate.config.lease_epoch, "meeting-draft-start:" + body["request_key"])
                gate.store._record_event(db, gate.config.run_id, "TOOL_FINISHED", event_payload, gate.config.lease_epoch, "meeting-draft-finish:" + body["request_key"])
                db.execute("UPDATE agent_runs SET revision=revision+1 WHERE run_id=?", (gate.config.run_id,))
        return web.json_response({"protocol_version": 1, "draft": result}, headers={"Cache-Control": "no-store"})

    async def minutes_tool(self, request):
        self._authorize(request)
        if request.query or request.content_type != "application/json":
            raise transport_error(web.HTTPBadRequest, "INVALID_TOOL_REQUEST", "纪要工具请求格式无效")
        body = await request.json()
        writing = request.path.endswith("/minutes-draft")
        fields = {"protocol_version", "request_key", "params"} if writing else {"protocol_version", "request_key"}
        if not isinstance(body, dict) or set(body) != fields or type(body["protocol_version"]) is not int or body["protocol_version"] != 1 or not isinstance(body["request_key"], str) or not 8 <= len(body["request_key"]) <= 128 or not body["request_key"].isascii() or not all(char.isalnum() or char in "-_." for char in body["request_key"]):
            raise transport_error(web.HTTPBadRequest, "INVALID_TOOL_REQUEST", "纪要工具请求字段无效")
        if self.scope_service is None or self.tool_budget is None or self.bridge is None or (writing and self.authority is None):
            raise transport_error(web.HTTPServiceUnavailable, "MINUTES_SERVICE_UNAVAILABLE", "纪要服务尚未装配")
        from hermes_domain_intents import MINUTES_DRAFT_VALIDATOR, draft_result_event_in_transaction, read_minutes_context_in_transaction, save_minutes_draft_in_transaction
        if writing and not MINUTES_DRAFT_VALIDATOR.is_valid(body["params"]):
            raise transport_error(web.HTTPBadRequest, "INVALID_TOOL_REQUEST", "纪要草稿参数无效")
        gate = self.sink
        name = "save_minutes_draft" if writing else "read_minutes_context"
        with gate.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._require_gate(db)
            db.row_factory = sqlite3.Row
            run = db.execute("SELECT * FROM agent_runs WHERE run_id=?", (gate.config.run_id,)).fetchone()
            if writing:
                digest = checksum({"goal_revision": run["goal_revision"], "scope_proof": json.loads(run["scope_proof"]), "params": body["params"]})
            else:
                result = read_minutes_context_in_transaction(db, self.bridge._store, self.scope_service, run)
                digest = checksum({"goal_revision": run["goal_revision"], "scope_proof": json.loads(run["scope_proof"]), "result": result})
            db.row_factory = None
            previous = db.execute("SELECT request_digest,tool_name,lease_epoch FROM agent_tool_reservations WHERE run_id=? AND request_key=?", (gate.config.run_id, body["request_key"])).fetchone()
            if previous is not None and previous != (digest, name, gate.config.lease_epoch):
                raise transport_error(web.HTTPConflict, "TOOL_REQUEST_CONFLICT", "纪要内容或工具请求编号已经变化")
            root = gate.store.require_active_lineage(db, gate.config.run_id)
            budget = db.execute("SELECT max_tools FROM agent_tool_budgets WHERE root_run_id=?", (root,)).fetchone()
            if budget is None:
                raise transport_error(web.HTTPServiceUnavailable, "TOOL_BUDGET_UNAVAILABLE", "根运行工具预算尚未配置")
            if previous is None and db.execute("SELECT count(*) FROM agent_tool_reservations WHERE root_run_id=?", (root,)).fetchone()[0] >= budget[0]:
                raise transport_error(web.HTTPTooManyRequests, "TOOL_BUDGET_EXHAUSTED", "工具预算已经用尽")
            reserved = self.tool_budget.reserve_in_transaction(db, gate.config.run_id, gate.lease_owner, gate.config.lease_epoch, body["request_key"], digest, name)
            if writing:
                db.row_factory = sqlite3.Row
                run = db.execute("SELECT * FROM agent_runs WHERE run_id=?", (gate.config.run_id,)).fetchone()
                result = save_minutes_draft_in_transaction(db, self.bridge._store, self.scope_service, run, body["params"], body["request_key"])
                event_payload = draft_result_event_in_transaction(db, self.bridge._store, gate.config.run_id, run["goal_revision"], body["request_key"], "minutes", result)
                db.row_factory = None
            self._require_gate(db)
            if reserved:
                gate.store._record_event(db, gate.config.run_id, "TOOL_STARTED", {"tool_id": name, "call_id": body["request_key"]}, gate.config.lease_epoch, name + ":start:" + body["request_key"])
                finished = event_payload if writing else {"tool_id": name, "call_id": body["request_key"], "outcome": "RETURNED"}
                gate.store._record_event(db, gate.config.run_id, "TOOL_FINISHED", finished, gate.config.lease_epoch, name + ":finish:" + body["request_key"])
                db.execute("UPDATE agent_runs SET revision=revision+1 WHERE run_id=?", (gate.config.run_id,))
        return web.json_response({"protocol_version": 1, "result": result}, headers={"Cache-Control": "no-store"})

    async def create_child(self, request):
        self._authorize(request)
        if request.query or request.content_type != "application/json":
            raise transport_error(web.HTTPBadRequest, "INVALID_DELEGATION", "委派请求格式无效")
        body = await request.json()
        if not isinstance(body, dict) or set(body) != {"protocol_version", "request_key", "description"} or type(body["protocol_version"]) is not int or body["protocol_version"] != 1 or not isinstance(body["request_key"], str) or not body["request_key"].strip() or len(body["request_key"]) > 128 or not isinstance(body["description"], str) or not body["description"].strip() or len(body["description"]) > 2000:
            raise transport_error(web.HTTPBadRequest, "INVALID_DELEGATION", "委派请求字段无效")
        if self.authority is None:
            raise transport_error(web.HTTPServiceUnavailable, "DELEGATION_UNAVAILABLE", "委派运行授权尚未准备")
        result = self.authority.create_child(body["request_key"], body["description"])
        return web.json_response({"protocol_version": 1, "child": result}, headers={"Cache-Control": "no-store"})

    async def dispatch_child(self, request):
        self._authorize(request)
        if request.query or request.content_type != "application/json":
            raise transport_error(web.HTTPBadRequest, "INVALID_DELEGATION", "委派派发请求格式无效")
        body = await request.json()
        if not isinstance(body, dict) or set(body) != {"protocol_version", "request_key"} or type(body["protocol_version"]) is not int or body["protocol_version"] != 1 or not isinstance(body["request_key"], str) or not body["request_key"].strip() or len(body["request_key"]) > 128:
            raise transport_error(web.HTTPBadRequest, "INVALID_DELEGATION", "委派派发请求字段无效")
        if self.authority is None:
            raise transport_error(web.HTTPServiceUnavailable, "DELEGATION_UNAVAILABLE", "委派运行授权尚未准备")
        result = await self.authority.dispatch_child(request.match_info["child_id"], body["request_key"])
        return web.json_response({"protocol_version": 1, "dispatch": result}, headers={"Cache-Control": "no-store"})

    async def child_result(self, request):
        self._authorize(request)
        if set(request.query) != {"request_key"} or len(request.query.getall("request_key")) != 1:
            raise transport_error(web.HTTPBadRequest, "INVALID_DELEGATION", "委派结果请求格式无效")
        if self.authority is None:
            raise transport_error(web.HTTPServiceUnavailable, "DELEGATION_UNAVAILABLE", "委派运行授权尚未准备")
        result = self.authority.child_result(request.match_info["child_id"], request.query["request_key"])
        return web.json_response({"protocol_version": 1, "child_result": result}, headers={"Cache-Control": "no-store"})

    def install(self, app):
        app.router.add_get("/internal/v1/request", self.run_request)
        app.router.add_post("/internal/v1/events", self.event)
        app.router.add_post("/internal/v1/result", self.record_result)
        app.router.add_get("/internal/v1/results/{event_id}/citation-checks", self.read_citation_checks)
        app.router.add_post("/internal/v1/model-execution", self.authorize_model_execution)
        app.router.add_post("/internal/v1/tools/workspace-file-reserve", self.reserve_workspace_file_tool)
        app.router.add_post("/internal/v1/tools/workspace-file-finish", self.finish_workspace_file_tool)
        app.router.add_post("/internal/v1/requirements/wait", self.wait_for_requirements)
        app.router.add_post("/internal/v1/tools/input-required", self.request_additional_input)
        app.router.add_get("/internal/v1/inputs", self.pending_input)
        app.router.add_get("/internal/v1/input-context", self.input_context)
        app.router.add_post("/internal/v1/inputs/ack", self.acknowledge_input)
        app.router.add_post("/internal/v1/tools/read-documents", self.read_documents)
        app.router.add_post("/internal/v1/tools/read-evidence", self.read_evidence)
        app.router.add_get("/internal/v1/tools/bi-definitions", self.bi_definitions)
        app.router.add_post("/internal/v1/tools/bi", self.bi_tool)
        app.router.add_post("/internal/v1/children", self.create_child)
        app.router.add_post("/internal/v1/children/{child_id}/dispatch", self.dispatch_child)
        app.router.add_get("/internal/v1/children/{child_id}/result", self.child_result)
        app.router.add_get("/internal/v1/tools/read-documents/{call_id}", self.read_document_result)
        app.router.add_post("/internal/v1/tools/context/{kind:memory|method}", self.read_context)
        app.router.add_post("/internal/v1/tools/meeting-brief", self.meeting_brief)
        app.router.add_post("/internal/v1/tools/runtime-meeting-brief", self.runtime_meeting_brief)
        app.router.add_post("/internal/v1/tools/domain-intent", self.prepare_domain_intent)
        app.router.add_post("/internal/v1/tools/decision-receipt", self.read_decision_receipt)
        app.router.add_post("/internal/v1/tools/domain-intent/{tool_name:meetingConfirm|meetingCancel|meetingHeld}", self.prepare_domain_intent)
        app.router.add_post("/internal/v1/tools/meeting-brief-prepare", self.prepare_meeting_brief)
        app.router.add_post("/internal/v1/tools/meeting-context", self.read_meeting_context)
        app.router.add_post("/internal/v1/tools/meeting-projection/{kind:catalog|arrangement}", self.read_meeting_projection)
        app.router.add_post("/internal/v1/tools/meeting-draft", self.save_meeting_draft)
        app.router.add_post("/internal/v1/tools/meeting-draft-formal", self.save_meeting_draft)
        app.router.add_post("/internal/v1/tools/minutes-context", self.minutes_tool)
        app.router.add_post("/internal/v1/tools/minutes-draft", self.minutes_tool)
