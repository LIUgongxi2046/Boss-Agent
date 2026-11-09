import hashlib
import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from aiohttp import web
from filelock import FileLock

from agent_run_broker import RunBroker
from agent_run_requirements import RunRequirements
from agent_run_scope import RunScopeService
from agent_run_store import RunStore
from boss_command_api import BossCommandAPI
from boss_simulation_api import _context
from boss_source_access import require_current_business_source
from business import checksum


VERSION = "upgrade2_business_receipts_001"
MIGRATION = Path(__file__).parent / "migrations" / (VERSION + ".sql")


class RunBusinessReceipts:
    def __init__(self, runs, scope, *, allow_migration=False):
        if not isinstance(runs, RunStore) or not isinstance(scope, RunScopeService) or runs.path.resolve() != scope.store.path.resolve():
            raise ValueError("业务回执与运行数据库不一致")
        self.runs, self.scope = runs, scope
        with FileLock(str(runs.path) + ".migration.lock", timeout=10), runs.connect() as db:
            if self.schema_state(db):
                return
            if not allow_migration:
                raise ValueError("业务回执关联迁移尚未安装")
            source = MIGRATION.read_bytes()
            db.executescript("BEGIN IMMEDIATE;\n" + source.decode("utf-8"))
            db.execute("INSERT INTO agent_schema_migrations VALUES (?,?)", (VERSION, hashlib.sha256(source).hexdigest()))

    @staticmethod
    def schema_state(db):
        version = db.execute("SELECT sha256 FROM agent_schema_migrations WHERE version=?", (VERSION,)).fetchone()
        table = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='agent_run_business_receipts'").fetchone()
        if version is None and table is None:
            return False
        if version is None or table is None or version[0] != hashlib.sha256(MIGRATION.read_bytes()).hexdigest():
            raise ValueError("业务回执关联迁移不可核查")
        return True

    def _transaction(self, db):
        main = db.execute("PRAGMA database_list").fetchone()
        if not db.in_transaction or main is None or main[1] != "main" or Path(main[2]).resolve() != self.runs.path.resolve():
            raise ValueError("业务回执需要同一数据库事务")
        if not self.schema_state(db):
            raise ValueError("业务回执关联迁移尚未安装")

    def _verify(self, db, run_id, goal_revision, intent_id, decision_key, *, terminal=False, expected_lease_epoch=None):
        if type(goal_revision) is not int or goal_revision < 1 or any(not isinstance(value, str) or not value.strip() or len(value) > 160 for value in (run_id, intent_id, decision_key)):
            raise ValueError("业务回执关联参数无效")
        run = db.execute("SELECT actor_id,space_id,conversation_id,selected_refs,scope_proof,status,cancel_requested_at,goal_revision,applied_goal_revision,lease_owner,lease_epoch FROM agent_runs WHERE run_id=?", (run_id,)).fetchone()
        statuses = {"SUCCEEDED", "FAILED", "CANCELED", "INTERRUPTED"} if terminal else {"RUNNING", "WAITING_CONFIRMATION"}
        if run is None or run[5] not in statuses or run[7:9] != (goal_revision, goal_revision):
            raise ValueError("业务回执的运行或目标版本不可核查")
        if not terminal:
            if run[6] is not None:
                raise ValueError("业务回执的运行或目标版本不可核查")
            self.runs._require_lease(db, run_id, run[9], run[10])
        if terminal:
            self.runs.require_terminal_lineage(db, run_id)
        else:
            self.runs.require_active_lineage(db, run_id)
        from hermes_source_invalidation import require_source_cleanup_complete
        require_source_cleanup_complete(db, run_id)
        proof = self.scope.prove_in_transaction(db, run[2], json.loads(run[3]))
        if (proof.owner_id, proof.namespace) != run[:2] or json.loads(json.dumps(asdict(proof))) != json.loads(run[4]):
            raise ValueError("业务回执来源范围已经变化")
        requirements = RunRequirements.read_in_transaction(db, run_id, goal_revision)
        if requirements["state"] != "CONFIRMED" or "BUSINESS_RECEIPT" not in requirements["required_outputs"]:
            raise ValueError("当前目标没有选择业务回执")
        item = db.execute("SELECT actor_id,space_id,action,object_id,expected_revision,payload_digest,client_request_id,preview,status,authorization_id,result_ref,revision,scope_revision FROM agent_intents WHERE run_id=? AND intent_id=?", (run_id, intent_id)).fetchone()
        if item is None or item[:2] != run[:2] or item[8] != "SUCCEEDED" or item[10] != item[6]:
            raise ValueError("业务意图或本人决定不可核查")
        events = db.execute("SELECT seq,payload,lease_epoch FROM agent_run_events WHERE run_id=? AND type='INTENT_PREPARED' AND json_extract(payload,'$.intent_id')=?", (run_id, intent_id)).fetchall()
        inputs = db.execute("SELECT i.input_id,i.input_seq,i.goal_revision,e.seq,e.type,e.payload FROM agent_run_inputs i LEFT JOIN agent_run_events e ON e.event_id=i.applied_event_id AND e.run_id=i.run_id WHERE i.run_id=? ORDER BY i.input_seq", (run_id,)).fetchall()
        if len(inputs) + 1 != goal_revision:
            raise ValueError("补充输入与目标版本不一致")
        for index, entry in enumerate(inputs, 1):
            if entry[1] != index or entry[2] != index + 1 or entry[4] != "INPUT_APPLIED" or json.loads(entry[5]) != {"input_id": entry[0], "input_seq": index, "goal_revision": entry[2]}:
                raise ValueError("补充输入采用记录不可核查")
        last_input = inputs[-1][3] if inputs else 0
        lease_epoch = expected_lease_epoch if terminal else run[10]
        if len(events) != 1 or events[0][0] <= last_input or events[0][2] != lease_epoch or json.loads(events[0][1]) != {"intent_id": intent_id}:
            raise ValueError("业务意图与目标版本不一致")
        decision = db.execute("SELECT request_digest,receipt FROM agent_intent_decisions WHERE actor_id=? AND space_id=? AND request_key=? AND intent_id=?", (run[0], run[1], decision_key, intent_id)).fetchone()
        if decision is None:
            raise ValueError("本人决定回执不存在")
        receipt = json.loads(decision[1])
        if item[2] != "boss.supply_quality.coordinate":
            self._verify_domain(db, run, goal_revision, intent_id, decision_key, item, decision[0], receipt, proof)
            return (run_id, goal_revision, intent_id, run[0], run[1], decision_key, item[2], item[3], item[4], item[5], decision[0], checksum(receipt))
        expected = checksum({"intent_id": intent_id, "decision": "CONFIRM", "expected_revision": item[11] - 1, "payload_digest": item[5], "request_key": decision_key})
        if decision[0] != expected or receipt != {"intent_id": intent_id, "status": "SUCCEEDED", "revision": item[11], "authorization_id": item[9], "result_ref": item[10], "task_id": receipt.get("task_id")} or not isinstance(receipt.get("task_id"), str):
            raise ValueError("本人决定回执内容不一致")
        preview = json.loads(item[7])
        params, refs = preview["coordinate_input"], preview["source_refs"]
        if preview["next_operation"] != item[2] or preview["preparation_sha256"] != item[5] or checksum(params) != item[5] or params["origin_record_id"] != item[3] or params["origin_version"] != item[4] or checksum({"dataset_id": proof.dataset_id, "dataset_version": proof.dataset_version, "source_refs": refs}) != item[12]:
            raise ValueError("业务意图与预览不一致")
        pins = {pin[0]: (pin[1], pin[2]) for pin in proof.source_pins}
        if not refs or any(pins.get(ref["source_id"]) != (ref["version"], ref["source_sha256"]) for ref in refs):
            raise ValueError("业务来源与当前选择不一致")
        for ref in refs:
            document = require_current_business_source(self.scope.store, db, run[1], run[0], ref["source_id"])
            if document["version"] != ref["version"] or checksum(document) != ref["source_sha256"]:
                raise ValueError("业务来源已经变化")
        result = BossCommandAPI(self.scope.store).verify_coordinate_receipt_in_transaction(db, actor_id=run[0], space_id=run[1], payload={**params, "client_request_id": item[6]}, source_refs=refs, authorization_id=item[9])
        task = self.scope.store.get(db, run[1], "task", receipt["task_id"])
        authorization = self.scope.store.get(db, run[1], "authorization", item[9])
        context = _context(db)
        initial = self.scope.store.get(db, run[1], "initial", "snapshot")
        from boss_supply_quality import bound_source_references
        origin = self.scope.store.get(db, run[1], params["origin_entity_type"], item[3])
        if origin["version"] != item[4] or origin.get("record_state") != "ACTIVE" or bound_source_references(db, context, params["origin_entity_type"], origin) != refs:
            raise ValueError("业务来源对象已经变化")
        self.scope.store.require_current_assignment_sources(db, run[1], initial, task)
        self.scope.store.require_current_authorization(authorization, run[1], initial, "create_assignment", authorization["payload"])
        if result["task_id"] != receipt["task_id"] or task["version"] != result["version"] or task["status"] != result["status"] or task.get("execution_namespace") != run[1] or authorization.get("revoked") or context["owner_id"] != run[0] or context["namespace"] != run[1]:
            raise ValueError("业务对象或授权状态已经变化")
        return (run_id, goal_revision, intent_id, run[0], run[1], decision_key, item[2], item[3], item[4], item[5], decision[0], checksum(receipt))

    def _verify_domain(self, db, run, goal_revision, intent_id, decision_key, item, decision_digest, receipt, proof):
        from hermes_domain_intents import FIELDS

        action = item[2]
        if action not in FIELDS or not isinstance(receipt, dict):
            raise ValueError("业务回执类型不可核查")
        preview = json.loads(item[7])
        params, refs = preview["params"], preview["source_refs"]
        if set(params) != FIELDS[action] or preview["action"] != action or preview["object_id"] != item[3] or preview["object_revision"] != item[4] or preview["goal_revision"] != goal_revision or checksum(preview) != item[5] or checksum(refs) != item[12]:
            raise ValueError("业务意图与目标版本不一致")
        if receipt != {"intent_id": intent_id, "status": "SUCCEEDED", "revision": item[11], "authorization_id": item[9], "result_ref": item[10], "action": action, "goal_revision": goal_revision, "business_object_id": receipt.get("business_object_id"), "business_object_version": receipt.get("business_object_version"), "source_refs": refs} or not isinstance(receipt.get("business_object_id"), str) or not isinstance(receipt.get("business_object_version"), str):
            raise ValueError("本人决定回执内容不一致")
        decisions = [{"intent_id": intent_id, "decision": "CONFIRM", "expected_revision": item[11] - 1, "payload_digest": item[5], "request_key": decision_key}]
        if action == "boss.meeting.confirm":
            decisions.extend({**decisions[0], "acknowledge_conflict": value} for value in (False, True))
        domain = db.execute("SELECT digest,result FROM idempotency WHERE namespace=? AND operation=? AND key=?", (run[1], action, item[6])).fetchone()
        if domain is None:
            raise ValueError("领域回执不存在")
        matches = []
        for decision in decisions:
            bound = dict(params)
            if action == "boss.meeting.confirm":
                bound["acknowledge_conflict"] = decision.get("acknowledge_conflict", False)
            if checksum(decision) == decision_digest and checksum({"action": action, "content": bound}) == domain[0]:
                matches.append(decision)
        if len(matches) != 1:
            raise ValueError("本人决定与领域请求不一致")
        pins = {pin[0]: (pin[1], pin[2]) for pin in proof.source_pins}
        if not refs or any(pins.get(ref["source_id"]) != (ref["version"], ref["source_sha256"]) for ref in refs):
            raise ValueError("业务来源与当前选择不一致")
        for ref in refs:
            source = require_current_business_source(self.scope.store, db, run[1], run[0], ref["source_id"])
            if source["version"] != ref["version"] or checksum(source) != ref["source_sha256"]:
                raise ValueError("业务来源已经变化")
        result = json.loads(domain[1])
        object_id = receipt["business_object_id"]
        kind = "task" if action in {"boss.assignment.create", "boss.minutes.assignment.create"} else "minutes" if action == "boss.minutes.confirm" else "meeting"
        record_id = params["meeting_id"] if kind == "minutes" else object_id
        record = self.scope.store.get(db, run[1], kind, record_id)
        auth = self.scope.store.get(db, run[1], "authorization", item[9])
        action_name = "create_assignment" if kind == "task" else "minutes.confirm" if kind == "minutes" else action.removeprefix("boss.")
        field = "confirmation_authorization_id" if kind == "minutes" else "authorization_id"
        id_field = "task_id" if kind == "task" else "minute_id" if kind == "minutes" else "meeting_id"
        if result.get(id_field) != object_id or result.get("version") != receipt["business_object_version"] or result.get("authorization_id") != item[9] or record.get(id_field) != object_id or record.get("version") != result["version"] or record.get(field) != item[9] or auth.get("owner_id") != run[0] or auth.get("scope") != run[1] or auth.get("issuer_identity") != "BOSS" or auth.get("issuer") != run[0] or auth.get("action") != action_name or auth.get("revoked") is not False:
            raise ValueError("业务对象、授权或领域回执不一致")
        start, end = datetime.fromisoformat(auth["valid_from"]), datetime.fromisoformat(auth["valid_until"])
        if start.tzinfo is None or end.tzinfo is None or not start <= datetime.now(timezone.utc) < end:
            raise ValueError("本人授权当前不可用")
        if action == "boss.meeting.confirm":
            draft = self.scope.store.get(db, run[1], "meeting_draft", object_id)
            if record.get("state") != "SCHEDULED" or result.get("state") != "SCHEDULED" or auth.get("target_id") != item[3] or auth.get("content_version") != item[4] or auth.get("payload") != {"draft_version": params["draft_version"], "review_sha256": params["review_sha256"]} or any(record.get(field) != value for field, value in preview["details"].items()) or draft.get("state") != "CONFIRMED" or draft.get("confirmed_meeting_version") != result["version"]:
                raise ValueError("会议状态或授权内容已经变化")
        elif action in {"boss.meeting.cancel", "boss.meeting.held"}:
            expected_state = "CANCELED" if action == "boss.meeting.cancel" else "HELD"
            original = self.scope.store.get(db, run[1], "meeting_revision", object_id + ":v" + item[4])
            details = preview["details"]
            version = item[4]
            if not isinstance(version, str) or not version.isascii() or not version.isdecimal() or str(int(version)) != version or result["version"] != str(int(version) + 1):
                raise ValueError("会议决定版本不可核查")
            changed = {"version", "state", "authorization_id", "decision_reason", "updated_at"}
            if record.get("state") != expected_state or result.get("state") != expected_state or record.get("owner_id") != run[0] or original.get("owner_id") != run[0] or record.get("decision_reason") != params["reason"] or auth.get("target_id") != object_id or auth.get("content_version") != version or auth.get("payload") != {"reason_sha256": checksum(params["reason"])} or details != {"meeting_id": object_id, "version": version, "state": original.get("state", "DRAFT"), "starts_at": original.get("starts_at"), "reason": params["reason"]} or original.get("meeting_id") != object_id or original.get("version") != version or {key: value for key, value in record.items() if key not in changed} != {key: value for key, value in original.items() if key not in changed} or action == "boss.meeting.held" and original.get("state") != "SCHEDULED" or result.get("invitation_sent") is not False or result.get("external_calendar_updated") is not False or result.get("independent_tasks_unchanged") is not True:
                raise ValueError("会议决定状态或依据不可核查")
        elif kind == "minutes":
            expected = {"meeting_id": params["meeting_id"], "minute_version": params["expected_version"], "source_id": params["source_id"], "source_version": params["source_version"], "entries_sha256": checksum(preview["details"]["entries"])}
            from boss_meetings import meeting_materials
            meeting = meeting_materials(db, self.scope.store.get(db, run[1], "initial", "snapshot"))["meeting"]
            if record.get("state") != "CONFIRMED" or result.get("state") != "CONFIRMED" or checksum(record["entries"]) != expected["entries_sha256"] or record.get("meeting_version") != meeting.get("version") or (record.get("source_id"), record.get("source_version")) != (params["source_id"], params["source_version"]) or auth.get("target_id") != item[3] or auth.get("content_version") != item[4] or auth.get("payload") != expected:
                raise ValueError("纪要状态或授权内容已经变化")
        else:
            initial = self.scope.store.get(db, run[1], "initial", "snapshot")
            self.scope.store.require_current_assignment_sources(db, run[1], initial, record)
            self.scope.store.require_current_authorization(auth, run[1], initial, "create_assignment", auth["payload"])
            fields = ("purpose", "coordinator_id", "due_at", "timezone", "evidence_requirements")
            if record.get("status") != "OPEN" or result.get("status") != "OPEN" or record.get("execution_namespace") != run[1] or any(record.get(field) != params[field] or auth["payload"].get(field) != params[field] for field in fields):
                raise ValueError("交办状态或授权内容已经变化")
            if action == "boss.assignment.create" and any(record.get(field) != params[field] or auth["payload"].get(field) != params[field] for field in ("related_meeting_id", "related_event_ids", "source_refs")):
                raise ValueError("交办关联对象已经变化")
            if action == "boss.minutes.assignment.create":
                link_id = params["meeting_id"] + ":v" + params["minute_version"] + ":" + params["entry_id"]
                link = self.scope.store.get(db, run[1], "minutes_assignment_link", link_id)
                if link.get("task_id") != object_id or link.get("authorization_id") != item[9] or link.get("meeting_id") != params["meeting_id"] or link.get("minute_id") != item[3] or link.get("minute_version") != item[4] or link.get("entry_id") != params["entry_id"] or record.get("origin_minute_id") != item[3] or record.get("origin_minute_version") != item[4] or record.get("origin_entry_id") != params["entry_id"] or record.get("related_meeting_id") != params["meeting_id"] or record.get("related_event_ids") != [initial["event"]["event_id"]] or record.get("source_refs") != ["finance-note"] or any(auth["payload"].get(field) != record.get(field) for field in ("related_meeting_id", "related_event_ids", "source_refs")):
                    raise ValueError("纪要交办关联已经变化")

    def bind_decision_in_transaction(self, db, identity, run_id, goal_revision, intent_id, decision_key, *, request):
        self._transaction(db)
        RunBroker.require_identity(identity)
        if not isinstance(request, web.Request) or not callable(identity.verify):
            raise ValueError("业务回执关联需要本人会话验证")
        run = db.execute("SELECT actor_id,space_id,conversation_id,selected_refs FROM agent_runs WHERE run_id=?", (run_id,)).fetchone()
        if run is None or run[:2] != (identity.actor_id, identity.space_id) or run[2] not in identity.conversation_ids or not set(json.loads(run[3])).issubset(identity.source_refs):
            raise ValueError("本人身份或会话范围不一致")
        values = self._verify(db, run_id, goal_revision, intent_id, decision_key)
        old = db.execute("SELECT * FROM agent_run_business_receipts WHERE run_id=? AND goal_revision=? AND intent_id=?", (run_id, goal_revision, intent_id)).fetchone()
        if old is not None:
            if tuple(old) != values:
                raise ValueError("业务回执关联内容已经变化")
            RunBroker.require_identity(identity)
            return
        db.execute("INSERT INTO agent_run_business_receipts VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", values)
        RunBroker.require_identity(identity)

    def inspect_in_transaction(self, db, run_id, goal_revision):
        self._transaction(db)
        if not isinstance(run_id, str) or not run_id.strip() or type(goal_revision) is not int or goal_revision < 1:
            raise ValueError("业务回执核查参数无效")
        run = db.execute("SELECT status,cancel_requested_at,goal_revision,applied_goal_revision,lease_owner,lease_epoch FROM agent_runs WHERE run_id=?", (run_id,)).fetchone()
        if run is None or run[0] not in {"RUNNING", "WAITING_CONFIRMATION"} or run[1] is not None or run[2:4] != (goal_revision, goal_revision):
            raise ValueError("业务回执的运行或目标版本不可核查")
        self.runs._require_lease(db, run_id, run[4], run[5])
        self.runs.require_active_lineage(db, run_id)
        requirements = RunRequirements.read_in_transaction(db, run_id, goal_revision)
        if requirements["state"] != "CONFIRMED" or "BUSINESS_RECEIPT" not in requirements["required_outputs"]:
            raise ValueError("当前目标没有选择业务回执")
        rows = db.execute("SELECT * FROM agent_run_business_receipts WHERE run_id=? AND goal_revision=? ORDER BY intent_id", (run_id, goal_revision)).fetchall()
        for row in rows:
            if self._verify(db, run_id, goal_revision, row[2], row[5]) != tuple(row):
                raise ValueError("业务回执关联内容已经变化")
        return {"state": "RECORD_PRESENT" if rows else "NOT_VERIFIED", "count": len(rows)}

    def inspect_terminal_in_transaction(self, db, run_id, goal_revision, expected_lease_epoch):
        self._transaction(db)
        if not isinstance(run_id, str) or not run_id.strip() or type(goal_revision) is not int or goal_revision < 1 or type(expected_lease_epoch) is not int or expected_lease_epoch < 1:
            raise ValueError("终态业务回执核查参数无效")
        run = db.execute("SELECT status,goal_revision,applied_goal_revision,actor_id,space_id,conversation_id,selected_refs,scope_proof FROM agent_runs WHERE run_id=?", (run_id,)).fetchone()
        if run is None or run[0] not in {"SUCCEEDED", "FAILED", "CANCELED", "INTERRUPTED"} or run[1:3] != (goal_revision, goal_revision):
            raise ValueError("终态业务回执的运行或目标版本不可核查")
        self.runs.require_terminal_lineage(db, run_id)
        from hermes_source_invalidation import require_source_cleanup_complete
        require_source_cleanup_complete(db, run_id)
        proof = self.scope.prove_in_transaction(db, run[5], json.loads(run[6]))
        if (proof.owner_id, proof.namespace) != run[3:5] or json.loads(json.dumps(asdict(proof))) != json.loads(run[7]):
            raise ValueError("终态业务回执来源范围已经变化")
        requirements = RunRequirements.read_in_transaction(db, run_id, goal_revision)
        if requirements["state"] != "CONFIRMED" or "BUSINESS_RECEIPT" not in requirements["required_outputs"]:
            raise ValueError("当前目标没有选择业务回执")
        rows = db.execute("SELECT * FROM agent_run_business_receipts WHERE run_id=? AND goal_revision=? ORDER BY intent_id", (run_id, goal_revision)).fetchall()
        for row in rows:
            if self._verify(db, run_id, goal_revision, row[2], row[5], terminal=True, expected_lease_epoch=expected_lease_epoch) != tuple(row):
                raise ValueError("业务回执关联内容已经变化")
        return {"state": "RECORD_PRESENT" if rows else "NOT_VERIFIED", "count": len(rows)}
