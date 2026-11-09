import hashlib
import json
import sqlite3
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from filelock import FileLock
from aiohttp import web
from aiohttp.web_urldispatcher import DynamicResource
from jsonschema import Draft202012Validator, FormatChecker

from agent_run_broker import RunBroker, RunIdentity
from agent_run_scope import RunScopeService
from agent_run_store import RunStore, utc_now
from boss_supply_quality import SupplyQualityAPI
from business import checksum
from hermes_business_tools import HermesBusinessTools

DECISION_INTENT_KEY = web.RequestKey("hermes_decision_intent", str)
OWNER_ROUTE_PARAMS = web.RequestKey("hermes_owner_route_params", dict)
INTENT_SCHEMA = json.loads((Path(__file__).resolve().parent.parent / "specs/agent-intents.schema.json").read_text(encoding="utf-8"))
Draft202012Validator.check_schema(INTENT_SCHEMA)
INTENT_VALIDATORS = {name: Draft202012Validator({"$ref": "#/$defs/" + name, "$defs": INTENT_SCHEMA["$defs"]}, format_checker=FormatChecker()) for name in ("preview", "preview_content", "decision", "decision_receipt")}


class HermesIntentService:
    def __init__(self, run_store: RunStore, tools: HermesBusinessTools, *, allow_migration=False):
        if not isinstance(run_store, RunStore) or not isinstance(tools, HermesBusinessTools):
            raise ValueError("需要运行存储与业务工具")
        if run_store.path.resolve() != tools._run_gate.store.path.resolve():
            raise ValueError("意图与运行必须使用同一数据库")
        self.store, self.tools = run_store, tools
        migration = Path(__file__).parent / "migrations/upgrade2_intents_001.sql"
        script = migration.read_text(encoding="utf-8")
        digest = hashlib.sha256(script.encode("utf-8")).hexdigest()
        with FileLock(str(run_store.path) + ".migration.lock", timeout=10):
            with run_store.connect() as db:
                row = db.execute("SELECT sha256 FROM agent_schema_migrations WHERE version=?", ("upgrade2_intents_001",)).fetchone()
                if row is not None:
                    if row[0] != digest:
                        raise ValueError("意图迁移摘要不符")
                else:
                    existing = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='agent_intents'").fetchone()
                    if existing is not None or not allow_migration:
                        raise ValueError("意图迁移尚未完成或已有未登记的表")
                    db.executescript("BEGIN IMMEDIATE;\n" + script + "\nINSERT INTO agent_schema_migrations VALUES ('upgrade2_intents_001', '" + digest + "');\nCOMMIT;")

    def _context(self):
        return self.tools._prepare._context()

    def _require_run(self, db, context, statuses, *, allow_cancel=False):
        gate = self.tools._run_gate
        gate.store._require_lease(db, gate.config.run_id, gate.lease_owner, gate.config.lease_epoch)
        row = db.execute("SELECT actor_id,space_id,status,cancel_requested_at FROM agent_runs WHERE run_id=?", (gate.config.run_id,)).fetchone()
        if row is None or (row[0], row[1]) != (context.owner_id, context.namespace) or row[2] not in statuses or row[3] is not None and not allow_cancel:
            raise ValueError("当前运行无法处理意图")

    @staticmethod
    def _view(row):
        return {"intent_id": row[0], "run_id": row[1], "action": row[2], "object_id": row[3], "expected_revision": row[4], "scope_revision": row[5], "payload_digest": row[6], "client_request_id": row[7], "preview": json.loads(row[8]), "status": row[9], "authorization_id": row[10], "result_ref": row[11], "revision": row[13]}

    async def prepare(self, request_key):
        if not isinstance(request_key, str) or not request_key or len(request_key) > 128:
            raise ValueError("意图请求编号无效")
        context = self._context()
        params = deepcopy(self.tools._preparation_provider())
        if not isinstance(params, dict):
            raise ValueError("缺少服务端准备内容")
        digest = checksum({"params": params, "owner_id": context.owner_id, "namespace": context.namespace, "dataset_id": context.dataset_id, "dataset_version": context.dataset_version, "request_id": context.request_id, "session_id": context.session_id})
        gate = self.tools._run_gate
        query = "SELECT intent_id,run_id,action,object_id,expected_revision,scope_revision,payload_digest,client_request_id,preview,status,authorization_id,result_ref,request_digest,revision FROM agent_intents WHERE run_id=? AND request_key=?"
        with self.store.connect() as db:
            db.execute("BEGIN")
            self._require_run(db, context, {"RUNNING", "WAITING_CONFIRMATION"})
            old = db.execute(query, (gate.config.run_id, request_key)).fetchone()
            if old is not None:
                if old[12] != digest:
                    raise ValueError("意图请求编号内容冲突")
                return self._view(old)
        preview = await self.tools.prepare()
        if preview["next_operation"] != "boss.supply_quality.coordinate" or preview["business_authority_granted"] is not False or preview["owner_decision_required"] is not True or preview["coordinate_input"] != params:
            raise ValueError("领域准备结果无效")
        if self._context() != context:
            raise ValueError("意图准备期间身份范围已变化")
        intent_id = str(uuid4())
        client_request_id = "intent-" + intent_id
        scope_revision = checksum({"dataset_id": context.dataset_id, "dataset_version": context.dataset_version, "source_refs": preview["source_refs"]})
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._require_run(db, context, {"RUNNING", "WAITING_CONFIRMATION"})
            old = db.execute(query, (gate.config.run_id, request_key)).fetchone()
            if old is not None:
                if old[12] != digest:
                    raise ValueError("意图请求编号内容冲突")
                return self._view(old)
            self._require_run(db, context, {"RUNNING"})
            db.execute("INSERT INTO agent_intents VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'WAITING_CONFIRMATION', NULL, NULL, ?, 0)", (intent_id, gate.config.run_id, context.owner_id, context.namespace, request_key, digest, preview["next_operation"], params["origin_record_id"], params["origin_version"], scope_revision, preview["preparation_sha256"], client_request_id, json.dumps(preview, ensure_ascii=False, sort_keys=True, allow_nan=False), utc_now().isoformat()))
            self.store._record_event(db, gate.config.run_id, "INTENT_PREPARED", {"intent_id": intent_id}, gate.config.lease_epoch)
            self.store._record_event(db, gate.config.run_id, "STATUS_CHANGED", {"from": "RUNNING", "to": "WAITING_CONFIRMATION"}, gate.config.lease_epoch)
            db.execute("UPDATE agent_runs SET status='WAITING_CONFIRMATION',revision=revision+1 WHERE run_id=?", (gate.config.run_id,))
            return self._view(db.execute(query, (gate.config.run_id, request_key)).fetchone())

    def receipt(self, intent_id):
        context = self._context()
        gate = self.tools._run_gate
        with self.store.connect() as db:
            db.execute("BEGIN")
            self._require_run(db, context, {"RUNNING", "WAITING_CONFIRMATION", "CANCEL_REQUESTED", "RECONCILING"}, allow_cancel=True)
            row = db.execute("SELECT action,client_request_id,status,preview,authorization_id,result_ref FROM agent_intents WHERE intent_id=? AND run_id=? AND actor_id=? AND space_id=?", (intent_id, gate.config.run_id, context.owner_id, context.namespace)).fetchone()
            if row is None or row[0] != "boss.supply_quality.coordinate":
                raise ValueError("意图不存在或操作无效")
        receipt = SupplyQualityAPI(self.tools._store).receipt("BOSS", row[0], row[1])
        if self._context() != context:
            raise ValueError("回执查询期间身份范围已变化")
        verified = False
        with self.store.connect() as db:
            db.execute("BEGIN")
            self._require_run(db, context, {"RUNNING", "WAITING_CONFIRMATION", "CANCEL_REQUESTED", "RECONCILING"}, allow_cancel=True)
            if row[2] == "SUCCEEDED" and self.store.path.resolve() == self.tools._store.path.resolve():
                from boss_command_api import BossCommandAPI
                preview = json.loads(row[3])
                if row[5] != row[1] or receipt["outcome"] != "RECORDED":
                    raise ValueError("意图与原回执关联不符")
                result = BossCommandAPI(self.tools._store).verify_coordinate_receipt_in_transaction(db, actor_id=context.owner_id, space_id=context.namespace, payload={**preview["coordinate_input"], "client_request_id": row[1]}, source_refs=preview["source_refs"], authorization_id=row[4])
                if result != receipt["result"]:
                    raise ValueError("原回执内容已经变化")
                verified = True
        return {"intent_id": intent_id, "receipt": receipt, "receipt_binding_verified": verified}

    def inspect_recovery(self, run_id, actor_id, space_id):
        from hermes_run_recovery import inspect_recovery
        return inspect_recovery(self.store, run_id, actor_id, space_id)

    def execute(self, intent_id):
        raise PermissionError("本人确认与授权消费尚未接入")


def validate_owner_decision(payload):
    if not INTENT_VALIDATORS["decision"].is_valid(payload):
        raise web.HTTPBadRequest(text="本人决定字段无效")


def preview_response(item, saved):
    response = {"schema_version": 1, "intent_id": item["intent_id"], "run_id": item["run_id"], "status": item["status"], "revision": item["revision"], "payload_digest": item["payload_digest"], "preview": saved, "allowed_actions": ["CONFIRM", "REJECT"]}
    INTENT_VALIDATORS["preview"].validate(response)
    return response


def decision_response(request_key, receipt):
    response = {"schema_version": 1, "request_key": request_key, "receipt": receipt}
    INTENT_VALIDATORS["decision_receipt"].validate(response)
    return response


def validate_decision_state(item, run, payload):
    if run["status"] != "WAITING_CONFIRMATION" or run["cancel_requested_at"] is not None or run["goal_revision"] != run["applied_goal_revision"] or item["status"] != "WAITING_CONFIRMATION" or item["revision"] != payload["expected_revision"] or item["payload_digest"] != payload["payload_digest"]:
        raise web.HTTPConflict(text="意图版本、摘要或运行状态已经变化")


def validate_current_preview(db, business_store, item, selected_refs):
    from boss_simulation_api import _context
    from boss_supply_quality import bound_source_references
    from boss_supply_quality_views import read_projection

    saved = json.loads(item["preview"]) if isinstance(item["preview"], str) else item["preview"]
    if item["action"] != "boss.supply_quality.coordinate":
        from hermes_domain_intents import FIELDS, preview_domain_intent
        if item["action"] not in FIELDS or checksum(saved) != item["payload_digest"] or saved["object_id"] != item["object_id"] or saved["object_revision"] != item["expected_revision"] or checksum(saved["source_refs"]) != item["scope_revision"] or not {ref["source_id"] for ref in saved["source_refs"]}.issubset(set(selected_refs)):
            raise web.HTTPConflict(text="业务意图内容或来源已经变化")
        return saved
    params = saved["coordinate_input"]
    context = _context(db)
    view = read_projection(business_store, db, context, params["interface_id"])
    origin = next((record for record in view["records"] if record["entity_type"] == params["origin_entity_type"] and record["record_id"] == params["origin_record_id"]), None)
    refs = bound_source_references(db, context, params["origin_entity_type"], origin) if origin is not None else None
    if item["action"] != "boss.supply_quality.coordinate" or saved["next_operation"] != item["action"] or saved["preparation_sha256"] != item["payload_digest"] or checksum(params) != item["payload_digest"] or params["origin_record_id"] != item["object_id"] or params["origin_version"] != item["expected_revision"] or origin is None or origin["version"] != item["expected_revision"] or view["review_sha256"] != params["review_sha256"] or not refs or refs != saved["source_refs"] or not {ref["source_id"] for ref in refs}.issubset(set(selected_refs)) or checksum({"dataset_id": context["dataset_id"], "dataset_version": context["dataset_version"], "source_refs": refs}) != item["scope_revision"]:
        raise web.HTTPConflict(text="意图来源或内容已经变化")
    return saved


def validate_domain_snapshot(db, scope, item, run, saved):
    from hermes_domain_intents import preview_domain_intent
    from hermes_source_invalidation import require_source_cleanup_complete
    require_source_cleanup_complete(db, run["run_id"], invalid=lambda message: web.HTTPConflict(text=message))
    current = preview_domain_intent(db, scope.store, scope, run, item["action"], saved["params"], allow_waiting=True)
    expected = {key: value for key, value in saved.items() if key not in {"plan_digest", "budget_digest"}}
    if current != expected or saved["goal_revision"] != run["goal_revision"]:
        raise web.HTTPConflict(text="业务意图预览已经变化")


def validate_domain_intent_provenance(db, item):
    from hermes_domain_schema import FIELDS
    if not db.in_transaction or item["action"] not in FIELDS:
        raise web.HTTPConflict(text="业务意图来源不可核查")
    saved = json.loads(item["preview"])
    content = {"action": item["action"], "params": saved["params"]}
    tools = {"prepare_domain_intent": None, "meetingConfirm": "boss.meeting.confirm", "meetingCancel": "boss.meeting.cancel", "meetingHeld": "boss.meeting.held"}
    reservation = db.execute("SELECT request_digest,tool_name,lease_epoch FROM agent_tool_reservations WHERE run_id=? AND request_key=?", (item["run_id"], item["request_key"])).fetchone()
    if reservation is None or reservation[1] not in tools or tools[reservation[1]] not in (None, item["action"]):
        raise web.HTTPConflict(text="业务意图工具预留不可核查")
    tool = reservation[1]
    digest = checksum(content if tool == "prepare_domain_intent" else {**content, "tool_name": tool})
    if reservation[0] != digest or item["request_digest"] != digest:
        raise web.HTTPConflict(text="业务意图原请求不一致")
    events = db.execute("SELECT seq,type,payload,lease_epoch FROM agent_run_events WHERE run_id=? AND (origin_event_id IN (?,?) OR (type='INTENT_PREPARED' AND json_extract(payload,'$.intent_id')=?)) ORDER BY seq", (item["run_id"], "intent-tool-start:" + item["request_key"], "intent-tool-finish:" + item["request_key"], item["intent_id"])).fetchall()
    expected = [("TOOL_STARTED", {"tool_id": tool, "call_id": item["request_key"]}), ("TOOL_FINISHED", {"tool_id": tool, "call_id": item["request_key"], "outcome": "RETURNED"}), ("INTENT_PREPARED", {"intent_id": item["intent_id"]})]
    if len(events) != 3 or any((row[1], json.loads(row[2]), row[3]) != (kind, payload, reservation[2]) for row, (kind, payload) in zip(events, expected)) or not events[0][0] < events[1][0] < events[2][0]:
        raise web.HTTPConflict(text="业务意图工具事件不可核查")


def validate_domain_decision_receipt(item, receipt, *, db=None, decision_key=None, decision_digest=None):
    if not isinstance(receipt, dict) or receipt.get("intent_id") != item["intent_id"] or receipt.get("status") != item["status"] or receipt.get("revision") != item["revision"] or item["status"] not in {"SUCCEEDED", "REJECTED"}:
        raise web.HTTPConflict(text="本人决定回执与意图不一致")
    if item["status"] == "REJECTED":
        if db is None or not db.in_transaction or not isinstance(decision_key, str) or not isinstance(decision_digest, str):
            raise web.HTTPConflict(text="原决定请求不可核查")
        original = {"intent_id": item["intent_id"], "decision": "REJECT", "expected_revision": item["revision"] - 1, "payload_digest": item["payload_digest"], "request_key": decision_key}
        if receipt != {"intent_id": item["intent_id"], "status": "REJECTED", "revision": item["revision"]} or checksum(original) != decision_digest:
            raise web.HTTPConflict(text="原决定与回执不一致")
    if item["status"] == "SUCCEEDED":
        preview = json.loads(item["preview"])
        if receipt.get("action") != item["action"] or receipt.get("authorization_id") != item["authorization_id"] or receipt.get("result_ref") != item["client_request_id"] or item["result_ref"] != item["client_request_id"] or receipt.get("goal_revision") != preview["goal_revision"] or receipt.get("source_refs") != preview["source_refs"]:
            raise web.HTTPConflict(text="本人决定回执与领域请求不一致")
        if db is None or not db.in_transaction or not isinstance(decision_key, str) or not isinstance(decision_digest, str) or checksum(preview) != item["payload_digest"]:
            raise web.HTTPConflict(text="原决定请求不可核查")
        domain = db.execute("SELECT digest,result FROM idempotency WHERE namespace=? AND operation=? AND key=?", (item["space_id"], item["action"], item["client_request_id"])).fetchone()
        if domain is None:
            raise web.HTTPConflict(text="领域原回执不存在")
        original = {"intent_id": item["intent_id"], "decision": "CONFIRM", "expected_revision": item["revision"] - 1, "payload_digest": item["payload_digest"], "request_key": decision_key}
        decisions = [original]
        if item["action"] == "boss.meeting.confirm":
            decisions.extend({**original, "acknowledge_conflict": value} for value in (False, True))
        matched = []
        for decision in decisions:
            params = dict(preview["params"])
            if item["action"] == "boss.meeting.confirm":
                params["acknowledge_conflict"] = decision.get("acknowledge_conflict", False)
            if checksum(decision) == decision_digest and checksum({"action": item["action"], "content": params}) == domain[0]:
                matched.append(decision)
        result = json.loads(domain[1])
        identifier = "task_id" if item["action"] in {"boss.assignment.create", "boss.minutes.assignment.create"} else "minute_id" if item["action"] == "boss.minutes.confirm" else "meeting_id"
        if len(matched) != 1 or result.get(identifier) != receipt.get("business_object_id") or result.get("version") != receipt.get("business_object_version") or result.get("authorization_id") != receipt.get("authorization_id"):
            raise web.HTTPConflict(text="原决定与领域回执不一致")


def read_domain_decision_receipt_in_transaction(db, intent_id, decision_key, decision_digest, receipt):
    if not db.in_transaction or db.row_factory is not sqlite3.Row:
        raise ValueError("本人决定读取需要同一数据库事务")
    item = db.execute("SELECT * FROM agent_intents WHERE intent_id=?", (intent_id,)).fetchone()
    if item is None:
        raise web.HTTPNotFound(text="原决定回执不存在")
    validate_domain_intent_provenance(db, item)
    validate_domain_decision_receipt(item, receipt, db=db, decision_key=decision_key, decision_digest=decision_digest)
    return receipt


def execute_domain_decision(db, commands, item, saved, payload):
    from boss_meeting_approval import minutes_assignment_create, minutes_confirm
    from boss_meetings import MeetingAPI
    from hermes_domain_schema import FIELDS
    database = db.execute("PRAGMA database_list").fetchone()
    if not db.in_transaction or database is None or database[1] != "main" or Path(database[2]).resolve() != commands.store.path.resolve():
        raise web.HTTPConflict(text="业务决定需要同一数据库事务")
    action = item["action"]
    if action not in FIELDS or payload.get("decision") != "CONFIRM" or item["status"] != "WAITING_CONFIRMATION" or payload.get("expected_revision") != item["revision"] or payload.get("payload_digest") != item["payload_digest"] or item["client_request_id"] != "intent-" + item["intent_id"] or saved.get("action") != action or not isinstance(saved.get("params"), dict) or set(saved["params"]) != FIELDS[action] or checksum(saved) != item["payload_digest"] or saved.get("object_id") != item["object_id"] or saved.get("object_revision") != item["expected_revision"] or checksum(saved.get("source_refs")) != item["scope_revision"]:
        raise web.HTTPConflict(text="业务决定与预览关联不一致")
    if "acknowledge_conflict" in payload and (action != "boss.meeting.confirm" or payload["decision"] != "CONFIRM"):
        raise web.HTTPBadRequest(text="冲突确认不适用于当前决定")
    params = {**saved["params"], "client_request_id": item["client_request_id"]}
    if action == "boss.meeting.confirm":
        params["acknowledge_conflict"] = payload.get("acknowledge_conflict", False)
    key, digest, previous = commands._check_existing(db, action, params)
    if previous is not None:
        raise web.HTTPConflict(text="领域请求已经存在，请读取原决定回执")
    meeting_api = MeetingAPI(commands.store)
    data = meeting_api._data(db)
    if action == "boss.meeting.confirm":
        result = meeting_api._confirm(db, data, params)
    elif action in {"boss.meeting.cancel", "boss.meeting.held"}:
        result = meeting_api._finish(db, data, action.rsplit(".", 1)[1], params)
    elif action == "boss.minutes.confirm":
        result = minutes_confirm(commands, db, data, params)
    elif action == "boss.minutes.assignment.create":
        result = minutes_assignment_create(commands, db, data, params, key)
    elif action == "boss.assignment.create":
        result = commands._create(db, data, params, key)
    else:
        raise web.HTTPBadRequest(text="业务操作不支持")
    commands._record(db, action, params, key, digest, result)
    object_id = result["task_id"] if action in {"boss.minutes.assignment.create", "boss.assignment.create"} else result["minute_id"] if action == "boss.minutes.confirm" else result["meeting_id"]
    from boss_execution_scope import NAMESPACE
    kind = "task" if action in {"boss.minutes.assignment.create", "boss.assignment.create"} else "minutes" if action == "boss.minutes.confirm" else "meeting"
    record_id = params["meeting_id"] if kind == "minutes" else object_id
    record = commands.store.get(db, NAMESPACE, kind, record_id)
    authorization = commands.store.get(db, NAMESPACE, "authorization", result["authorization_id"])
    auth_field = "confirmation_authorization_id" if kind == "minutes" else "authorization_id"
    expected_action = "create_assignment" if kind == "task" else "minutes.confirm" if kind == "minutes" else action.removeprefix("boss.")
    saved_receipt = db.execute("SELECT digest,result FROM idempotency WHERE namespace=? AND operation=? AND key=?", (NAMESPACE, action, key)).fetchone()
    if record["version"] != result["version"] or record[auth_field] != result["authorization_id"] or authorization["owner_id"] != data["owner_id"] or authorization["scope"] != NAMESPACE or authorization["action"] != expected_action or authorization["revoked"] or saved_receipt is None or saved_receipt[0] != digest or json.loads(saved_receipt[1]) != result:
        raise web.HTTPConflict(text="业务对象、授权或回执无法核查")
    return result, object_id


def bind_required_business_receipt(db, broker, identity, request, run_id, goal_revision, intent_id, decision_key):
    from agent_run_business_receipts import RunBusinessReceipts
    from agent_run_requirements import RunRequirements

    broker.require_identity(identity)
    if not isinstance(request, web.Request) or not callable(identity.verify):
        raise web.HTTPUnauthorized(text="业务回执关联需要实际本人会话")
    factory = db.row_factory
    try:
        db.row_factory = None
        requirements = RunRequirements.read_in_transaction(db, run_id, goal_revision)
        if requirements["state"] != "CONFIRMED":
            raise web.HTTPConflict(text="当前目标成果要求尚未确认")
        if "BUSINESS_RECEIPT" not in requirements["required_outputs"]:
            return
        if not RunBusinessReceipts.schema_state(db):
            raise web.HTTPServiceUnavailable(text="业务回执关联迁移尚未安装")
        service = RunBusinessReceipts(broker.store, broker.scope_service)
        service.bind_decision_in_transaction(db, identity, run_id, goal_revision, intent_id, decision_key, request=request)
    finally:
        db.row_factory = factory


def owner_decision_routes(channel, broker):
    from role_channel import RoleChannel

    if not isinstance(channel, RoleChannel) or not isinstance(broker, RunBroker) or not isinstance(broker.scope_service, RunScopeService):
        raise ValueError("需要产品认证与会话范围服务")
    if channel.boss_commands is None or channel.boss_commands.store.path.resolve() != broker.store.path.resolve():
        raise ValueError("本人决定和领域服务需要同一数据库")

    def route_param(request, name):
        return request.get(OWNER_ROUTE_PARAMS, request.match_info).get(name)

    def owner_for_run(db, request, run):
        channel.require_run_subscription(request, run["conversation_id"])
        refs = json.loads(run["selected_refs"])
        proof = broker.scope_service.prove_in_transaction(db, run["conversation_id"], refs)
        identity = RunIdentity(proof.owner_id, proof.namespace, "BOSS", frozenset({proof.chat_id}), frozenset(refs), verify=lambda: channel.require_run_subscription(request, run["conversation_id"]))
        broker.require_identity(identity)
        broker.owned(db, identity, run["run_id"])
        broker.require_current_scope(identity, run, db)
        return identity

    def require_domain_authority(db, request, run, saved):
        from agent_run_dispatcher import AgentRunDispatcher
        from hermes_product import SERVICES_KEY
        channel.require_run_api_role(request)
        channel.require_run_subscription(request, run["conversation_id"])
        factory = db.row_factory
        try:
            db.row_factory = None
            plan, budget = AgentRunDispatcher(request.app[SERVICES_KEY]).approved_budget_in_transaction(db, run["run_id"])
        finally:
            db.row_factory = factory
        if checksum(plan) != saved["plan_digest"] or checksum(budget) != saved["budget_digest"] or (plan.get("owner_id"), plan.get("conversation_id"), plan.get("purpose"), plan.get("source_refs"), plan.get("scope_proof")) != (run["actor_id"], run["conversation_id"], run["goal"], json.loads(run["selected_refs"]), json.loads(run["scope_proof"])):
            raise web.HTTPConflict(text="运行计划或授权已经变化")
        channel.require_run_subscription(request, run["conversation_id"])

    async def preview(request):
        channel.require_run_api_role(request)
        if request.query:
            raise web.HTTPBadRequest(text="请求格式无效")
        from agent_run_api import require_product_engine_ready
        require_product_engine_ready()
        with broker.store.connect() as db:
            db.execute("BEGIN")
            db.row_factory = sqlite3.Row
            run = db.execute("SELECT * FROM agent_runs WHERE run_id=?", (route_param(request, "run_id"),)).fetchone()
            if run is None:
                raise web.HTTPNotFound(text="运行不存在")
            identity = owner_for_run(db, request, run)
            items = db.execute("SELECT * FROM agent_intents WHERE run_id=? AND actor_id=? AND space_id=? AND status='WAITING_CONFIRMATION' LIMIT 2", (run["run_id"], identity.actor_id, identity.space_id)).fetchall()
            if len(items) != 1:
                raise web.HTTPNotFound(text="当前没有唯一待确认意图")
            item = items[0]
            if run["status"] != "WAITING_CONFIRMATION" or run["cancel_requested_at"] is not None or run["goal_revision"] != run["applied_goal_revision"]:
                raise web.HTTPConflict(text="运行状态已经变化")
            if run["lease_owner"] is None or run["lease_expires_at"] is None or datetime.fromisoformat(run["lease_expires_at"]) <= utc_now():
                raise web.HTTPConflict(text="运行租约已经失效")
            RunStore.require_active_lineage(db, run["run_id"])
            saved = validate_current_preview(db, channel.boss_commands.store, item, json.loads(run["selected_refs"]))
            if item["action"] != "boss.supply_quality.coordinate":
                validate_domain_intent_provenance(db, item)
                validate_domain_snapshot(db, broker.scope_service, item, run, saved)
                require_domain_authority(db, request, run, saved)
            broker.require_identity(identity)
            return web.json_response(preview_response(item, saved))

    async def decision_receipt(request):
        channel.require_run_api_role(request)
        if request.query:
            raise web.HTTPBadRequest(text="请求格式无效")
        from agent_run_api import require_product_engine_ready
        require_product_engine_ready()
        key = route_param(request, "request_key")
        if not isinstance(key, str) or not 8 <= len(key) <= 128 or not key.isascii() or not all(char.isalnum() or char in "-_." for char in key):
            raise web.HTTPBadRequest(text="请求编号无效")
        with broker.store.connect() as db:
            db.execute("BEGIN")
            db.row_factory = sqlite3.Row
            from boss_simulation_api import _context
            context = _context(db)
            row = db.execute("SELECT d.actor_id,d.space_id,d.receipt,d.request_digest,i.run_id,i.intent_id,i.action FROM agent_intent_decisions d JOIN agent_intents i ON i.intent_id=d.intent_id WHERE d.request_key=? AND d.actor_id=? AND d.space_id=?", (key, context["owner_id"], context["namespace"])).fetchall()
            if len(row) != 1:
                raise web.HTTPNotFound(text="原决定回执不存在")
            run = db.execute("SELECT * FROM agent_runs WHERE run_id=? AND actor_id=? AND space_id=?", (row[0]["run_id"], row[0]["actor_id"], row[0]["space_id"])).fetchone()
            if run is None:
                raise web.HTTPNotFound(text="原决定回执不存在")
            identity = owner_for_run(db, request, run)
            if row[0]["action"] != "boss.supply_quality.coordinate":
                read_domain_decision_receipt_in_transaction(db, row[0]["intent_id"], key, row[0]["request_digest"], json.loads(row[0]["receipt"]))
            broker.require_identity(identity)
            return web.json_response(decision_response(key, json.loads(row[0]["receipt"])))

    async def decide(request):
        channel.require_run_api_role(request)
        if request.query or request.content_type != "application/json":
            raise web.HTTPBadRequest(text="请求格式无效")
        payload = await request.json()
        validate_owner_decision(payload)
        from agent_run_api import require_product_engine_ready
        require_product_engine_ready()
        intent_id = request.get(DECISION_INTENT_KEY, request.match_info.get("intent_id"))
        with broker.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.row_factory = sqlite3.Row
            item = db.execute("SELECT * FROM agent_intents WHERE intent_id=?", (intent_id,)).fetchone()
            if item is None:
                raise web.HTTPNotFound(text="意图不存在")
            run = db.execute("SELECT * FROM agent_runs WHERE run_id=?", (item["run_id"],)).fetchone()
            if run is None or run["actor_id"] != item["actor_id"] or run["space_id"] != item["space_id"]:
                raise web.HTTPNotFound(text="意图不存在")
            identity = owner_for_run(db, request, run)
            if item["action"] != "boss.supply_quality.coordinate":
                validate_domain_intent_provenance(db, item)
            digest = checksum({"intent_id": intent_id, **payload})
            previous = db.execute("SELECT request_digest,receipt FROM agent_intent_decisions WHERE actor_id=? AND space_id=? AND request_key=?", (identity.actor_id, identity.space_id, payload["request_key"])).fetchone()
            if previous is not None:
                if previous["request_digest"] != digest:
                    raise web.HTTPConflict(text="本人决定请求编号内容冲突")
                if item["action"] != "boss.supply_quality.coordinate":
                    validate_domain_decision_receipt(item, json.loads(previous["receipt"]), db=db, decision_key=payload["request_key"], decision_digest=previous["request_digest"])
                broker.require_identity(identity)
                return web.json_response(decision_response(payload["request_key"], json.loads(previous["receipt"])))
            validate_decision_state(item, run, payload)
            if payload["decision"] == "CONFIRM":
                RunStore._require_lease(db, run["run_id"], run["lease_owner"], run["lease_epoch"])
                RunStore.require_active_lineage(db, run["run_id"])
                preview = json.loads(item["preview"])
                if item["action"] != "boss.supply_quality.coordinate":
                    saved = validate_current_preview(db, channel.boss_commands.store, item, json.loads(run["selected_refs"]))
                    validate_domain_snapshot(db, broker.scope_service, item, run, saved)
                    require_domain_authority(db, request, run, saved)
                    broker.require_identity(identity)
                    result, object_id = execute_domain_decision(db, channel.boss_commands, item, saved, payload)
                    require_domain_authority(db, request, run, saved)
                    broker.require_identity(identity)
                    auth_id = result["authorization_id"]
                    receipt = {"intent_id": intent_id, "status": "SUCCEEDED", "revision": item["revision"] + 1, "authorization_id": auth_id, "result_ref": item["client_request_id"], "action": item["action"], "goal_revision": saved["goal_revision"], "business_object_id": object_id, "business_object_version": result["version"], "source_refs": saved["source_refs"]}
                    db.execute("UPDATE agent_intents SET status='SUCCEEDED',authorization_id=?,result_ref=?,revision=revision+1 WHERE intent_id=? AND revision=?", (auth_id, item["client_request_id"], intent_id, item["revision"]))
                    db.execute("INSERT INTO agent_intent_decisions VALUES (?, ?, ?, ?, ?, ?, ?)", (identity.actor_id, identity.space_id, payload["request_key"], digest, intent_id, json.dumps(receipt, ensure_ascii=False, sort_keys=True), utc_now().isoformat()))
                    bind_required_business_receipt(db, broker, identity, request, run["run_id"], saved["goal_revision"], intent_id, payload["request_key"])
                    require_domain_authority(db, request, run, saved)
                    broker.require_identity(identity)
                    return web.json_response(decision_response(payload["request_key"], receipt))
                if "acknowledge_conflict" in payload:
                    raise web.HTTPBadRequest(text="冲突确认不适用于当前决定")
                params = preview["coordinate_input"]
                if item["action"] != "boss.supply_quality.coordinate" or preview["next_operation"] != item["action"] or checksum(params) != item["payload_digest"] or params["origin_record_id"] != item["object_id"] or params["origin_version"] != item["expected_revision"]:
                    raise web.HTTPConflict(text="意图内容与预览不一致")
                broker.require_identity(identity)
                result = channel.boss_commands.coordinate_in_transaction(db, {**params, "client_request_id": item["client_request_id"]}, actor_id=identity.actor_id, space_id=identity.space_id, scope_revision=item["scope_revision"])
                broker.require_identity(identity)
                auth_id = result["authorization_id"]
                verified = channel.boss_commands.verify_coordinate_receipt_in_transaction(db, actor_id=identity.actor_id, space_id=identity.space_id, payload={**params, "client_request_id": item["client_request_id"]}, source_refs=preview["source_refs"], authorization_id=auth_id)
                if verified != result:
                    raise web.HTTPConflict(text="领域回执与当前结果不符")
                db.execute("UPDATE agent_intents SET status='SUCCEEDED',authorization_id=?,result_ref=?,revision=revision+1 WHERE intent_id=? AND revision=?", (auth_id, item["client_request_id"], intent_id, item["revision"]))
                receipt = {"intent_id": intent_id, "status": "SUCCEEDED", "revision": item["revision"] + 1, "authorization_id": auth_id, "result_ref": item["client_request_id"], "task_id": result["task_id"]}
                db.execute("INSERT INTO agent_intent_decisions VALUES (?, ?, ?, ?, ?, ?, ?)", (identity.actor_id, identity.space_id, payload["request_key"], digest, intent_id, json.dumps(receipt), utc_now().isoformat()))
                bind_required_business_receipt(db, broker, identity, request, run["run_id"], run["goal_revision"], intent_id, payload["request_key"])
                broker.require_identity(identity)
                return web.json_response(decision_response(payload["request_key"], receipt))
            if "acknowledge_conflict" in payload:
                raise web.HTTPBadRequest(text="拒绝决定不接受冲突确认")
            broker.require_identity(identity)
            db.execute("UPDATE agent_intents SET status='REJECTED',revision=revision+1 WHERE intent_id=? AND revision=?", (intent_id, payload["expected_revision"]))
            receipt = {"intent_id": intent_id, "status": "REJECTED", "revision": item["revision"] + 1}
            db.execute("INSERT INTO agent_intent_decisions VALUES (?, ?, ?, ?, ?, ?, ?)", (identity.actor_id, identity.space_id, payload["request_key"], digest, intent_id, json.dumps(receipt), utc_now().isoformat()))
            return web.json_response(decision_response(payload["request_key"], receipt))

    return [web.post("/api/v2/intents/{intent_id}/decision", decide), web.get("/api/v2/runs/{run_id}/intent", preview), web.get("/api/v2/intent-decisions/{request_key}", decision_receipt)]


def install_owner_decision(app, channel, broker, *, public_port):
    if type(public_port) is not int or not 1 <= public_port <= 65535:
        raise ValueError("本人决定入口缺少同源端口")
    endpoints = []
    for definition in owner_decision_routes(channel, broker):
        endpoint = DynamicResource(definition.path)
        endpoint.add_route(definition.method, definition.handler)
        endpoints.append(endpoint)
    expected_host = "127.0.0.1:" + str(public_port)
    expected_origin = "http://" + expected_host

    @web.middleware
    async def decision_dispatch(request, handler):
        for endpoint in endpoints:
            match, allowed = await endpoint.resolve(request)
            if match is None:
                if allowed:
                    raise web.HTTPMethodNotAllowed(request.method, allowed)
                continue
            origin = request.headers.get("Origin")
            if request.headers.get("Host") != expected_host or origin not in (None, expected_origin) or request.method != "GET" and origin != expected_origin or request.headers.get("Sec-Fetch-Site") not in (None, "same-origin"):
                raise web.HTTPForbidden(text="本人决定请求来源无效")
            request[OWNER_ROUTE_PARAMS] = dict(match)
            if "intent_id" in match:
                request[DECISION_INTENT_KEY] = match["intent_id"]
            return await match.handler(request)
        return await handler(request)

    app.middlewares.append(decision_dispatch)
