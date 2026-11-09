import hashlib
import json
import sqlite3
from contextlib import nullcontext
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable
from uuid import uuid4

from aiohttp import web

from agent_run_store import utc_now
from business import checksum
from agent_run_requirements import RunRequirements, VALIDATOR as REQUIREMENTS_VALIDATOR


@dataclass(frozen=True)
class RunIdentity:
    actor_id: str
    space_id: str
    role: str
    conversation_ids: frozenset[str]
    source_refs: frozenset[str]
    verify: Callable[[], None] | None = None


def fail(exception, code, message, *, actual_size=None):
    actions = {"UNAUTHENTICATED": "NONE", "FORBIDDEN": "NONE", "NOT_FOUND": "NONE", "SCOPE_FORBIDDEN": "NONE", "SCOPE_CHANGED": "READ_CURRENT", "REQUEST_KEY_CONFLICT": "READ_ORIGINAL_RESULT", "REVISION_CONFLICT": "READ_CURRENT", "INVALID_INPUT": "SUPPLY_INPUT", "INPUT_TOO_LARGE": "SUPPLY_INPUT", "EXECUTION_SPACE_CHANGED": "READ_CURRENT", "SERVICE_NOT_READY": "NONE", "CREATE_NOT_ADMITTED": "NONE"}
    body = json.dumps({"code": code, "message": message, "run_id": None, "trace_id": str(uuid4()), "failed_step": "request", "completed_refs": [], "recovery_action": actions[code]}, ensure_ascii=False)
    if code == "INPUT_TOO_LARGE":
        raise exception(max_size=131072, actual_size=actual_size, text=body, content_type="application/json")
    raise exception(text=body, content_type="application/json")


def digest_request(method, path, payload):
    encoded = json.dumps({"method": method, "path": path, "schema_version": 1, "payload": payload}, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class RunBroker:
    def __init__(self, store, *, scope_service=None, method_selection=None, object_scope=None):
        self.store = store
        if scope_service is not None and scope_service.store.path.resolve() != store.path.resolve():
            raise ValueError("运行与范围核查必须使用同一数据库")
        self.scope_service = scope_service
        if method_selection is not None:
            from agent_run_method_selection import AgentRunMethodSelection
            if not isinstance(method_selection, AgentRunMethodSelection) or method_selection.store.path.resolve() != store.path.resolve() or method_selection.scope is not scope_service:
                raise ValueError("运行方法选择服务不属于当前环境")
        self.method_selection = method_selection
        if object_scope is not None:
            from agent_run_object_scope import AgentRunObjectScope
            if not isinstance(object_scope, AgentRunObjectScope) or object_scope.runs.path.resolve() != store.path.resolve() or object_scope.scope is not scope_service:
                raise ValueError("运行对象范围服务不属于当前环境")
        self.object_scope = object_scope

    @staticmethod
    def require_identity(identity):
        if not isinstance(identity, RunIdentity) or not identity.actor_id or not identity.space_id:
            fail(web.HTTPUnauthorized, "UNAUTHENTICATED", "当前身份无效")
        if identity.role != "BOSS":
            fail(web.HTTPForbidden, "FORBIDDEN", "当前身份无权操作运行")
        if identity.verify is not None:
            identity.verify()

    @staticmethod
    def owned(db, identity, run_id):
        db.row_factory = sqlite3.Row
        row = db.execute("SELECT * FROM agent_runs WHERE run_id=? AND actor_id=? AND space_id=?", (run_id, identity.actor_id, identity.space_id)).fetchone()
        if row is None or row["conversation_id"] not in identity.conversation_ids:
            fail(web.HTTPNotFound, "NOT_FOUND", "运行不存在")
        return row

    @staticmethod
    def replay_request(db, identity, key, digest):
        row = db.execute("SELECT request_digest, receipt FROM agent_api_requests WHERE actor_id=? AND space_id=? AND request_key=?", (identity.actor_id, identity.space_id, key)).fetchone()
        if row is not None:
            if row[0] != digest:
                fail(web.HTTPConflict, "REQUEST_KEY_CONFLICT", "请求键对应的内容已经变化")
            return json.loads(row[1])
        return None

    @staticmethod
    def save_request(db, identity, key, digest, run_id, operation, receipt):
        db.execute("INSERT INTO agent_api_requests VALUES (?, ?, ?, ?, ?, ?, ?)", (identity.actor_id, identity.space_id, key, digest, run_id, operation, json.dumps(receipt, ensure_ascii=False)))

    def require_current_scope(self, identity, row, db):
        if not set(json.loads(row["selected_refs"])).issubset(identity.source_refs):
            fail(web.HTTPForbidden, "SCOPE_CHANGED", "来源范围已经变化")
        if self.scope_service is not None:
            proof = self.scope_service.prove_in_transaction(db, row["conversation_id"], json.loads(row["selected_refs"]))
            if proof.owner_id != identity.actor_id or proof.namespace != identity.space_id or row["scope_proof"] is None or json.loads(row["scope_proof"]) != json.loads(json.dumps(asdict(proof))):
                fail(web.HTTPConflict, "REVISION_CONFLICT", "会话或来源版本已经变化")

    @staticmethod
    def allowed_actions(row):
        result = ["READ_EVENTS"]
        if row["cancel_requested_at"] is None:
            if row["status"] in {"QUEUED", "RUNNING", "WAITING_INPUT", "WAITING_CONFIRMATION"}:
                result.append("ADD_INPUT")
            if row["status"] in {"QUEUED", "RUNNING", "WAITING_INPUT", "WAITING_CONFIRMATION", "RECONCILING", "INTERRUPTED"}:
                result.append("CANCEL")
        return result

    def request_receipt(self, identity, request_key):
        self.require_identity(identity)
        with self.store.connect() as db:
            db.execute("BEGIN")
            record = db.execute("SELECT run_id,operation,receipt FROM agent_api_requests WHERE actor_id=? AND space_id=? AND request_key=?", (identity.actor_id, identity.space_id, request_key)).fetchone()
            if record is None:
                fail(web.HTTPNotFound, "NOT_FOUND", "当前范围没有原请求回执")
            run = self.owned(db, identity, record[0])
            self.require_current_scope(identity, run, db)
            if self.scope_service is not None:
                from agent_run_memory_guard import require_current_run_memory_in_transaction
                require_current_run_memory_in_transaction(db, self.scope_service.store, record[0])
            if record[1] == "inputs":
                self.verify_input_receipt_in_transaction(db, record[0], request_key, json.loads(record[2]))
            self.require_identity(identity)
            return {"request_key": request_key, "run_id": record[0], "operation": record[1], "outcome": "RECORDED", "receipt": json.loads(record[2])}

    @staticmethod
    def verify_input_receipt_in_transaction(db, run_id, request_key, receipt):
        if not db.in_transaction or not isinstance(receipt, dict) or set(receipt) != {"input_id", "input_seq", "goal_revision"}:
            raise ValueError("补充输入回执不可核查")
        item = db.execute("SELECT input_id,input_seq,goal_revision,content FROM agent_run_inputs WHERE run_id=? AND request_key=?", (run_id, request_key)).fetchone()
        if item is None or type(item[1]) is not int or item[1] < 1 or item[2] != item[1] + 1 or receipt != {"input_id": item[0], "input_seq": item[1], "goal_revision": item[2]}:
            raise ValueError("补充输入记录与回执不符")
        events = db.execute("SELECT payload FROM agent_run_events WHERE run_id=? AND type='INPUT_RECEIVED' AND json_extract(payload,'$.input_id')=?", (run_id, item[0])).fetchall()
        if len(events) != 1 or json.loads(events[0][0]) != receipt:
            raise ValueError("补充输入接收事件不可核查")
        payload = {"input": item[3], "expected_goal_revision": item[2] - 1, "request_key": request_key}
        if RunRequirements.schema_state(db):
            requirements = db.execute("SELECT request_key,required_outputs FROM agent_run_requirements WHERE run_id=? AND goal_revision=?", (run_id, item[2])).fetchone()
            if requirements is not None and requirements[0] == request_key:
                payload["required_outputs"] = json.loads(requirements[1])
        run = db.execute("SELECT actor_id,space_id FROM agent_runs WHERE run_id=?", (run_id,)).fetchone()
        saved = db.execute("SELECT operation,request_digest,run_id,receipt FROM agent_api_requests WHERE actor_id=? AND space_id=? AND request_key=?", (*run, request_key)).fetchone() if run is not None else None
        if saved is None or saved[0] != "inputs" or saved[1] != digest_request("POST", "/api/v2/runs/" + run_id + "/inputs", payload) or saved[2] != run_id or json.loads(saved[3]) != receipt:
            raise ValueError("补充输入原请求不可核查")
        return item

    def create(self, identity, payload, *, request=None, chat_budget=None):
        if "method_selection" in payload:
            if self.method_selection is None:
                fail(web.HTTPServiceUnavailable, "SERVICE_NOT_READY", "运行方法选择服务尚未装配")
            return self.method_selection.create(self, identity, payload, request=request, chat_budget=chat_budget)
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            return self.create_in_transaction(db, identity, payload, request=request, chat_budget=chat_budget)

    def create_in_transaction(self, db, identity, payload, *, request=None, chat_budget=None):
        if "method_selection" in payload:
            raise ValueError("方法选择创建需要方法配置锁和运行事务")
        return self._create_in_transaction(db, identity, payload, request=request, chat_budget=chat_budget)

    def _create_in_transaction(self, db, identity, payload, *, request=None, chat_budget=None):
        self.require_identity(identity)
        if not db.in_transaction:
            raise ValueError("运行创建需要已有事务")
        main = db.execute("PRAGMA database_list").fetchone()
        if main is None or main[1] != "main" or Path(main[2]).resolve() != self.store.path.resolve():
            raise ValueError("运行创建数据库不匹配")
        if chat_budget is not None:
            from agent_chat_budget import AgentChatBudget
            if not isinstance(chat_budget, AgentChatBudget) or chat_budget.store.path.resolve() != self.store.path.resolve() or self.scope_service is not chat_budget.scope:
                raise ValueError("聊天预算服务与运行环境不一致")
        if payload["conversation_id"] not in identity.conversation_ids or not set(payload["selected_refs"]).issubset(identity.source_refs):
            fail(web.HTTPForbidden, "SCOPE_FORBIDDEN", "会话或来源不在当前范围")
        if "required_outputs" in payload:
            self.require_requirements_request(db, identity, request, payload["required_outputs"])
        digest = digest_request("POST", "/api/v2/runs", payload)
        previous = self.replay_request(db, identity, payload["request_key"], digest)
        if previous is not None:
            original_factory = db.row_factory
            prior = self.owned(db, identity, previous["run_id"])
            self.require_current_scope(identity, prior, db)
            db.row_factory = original_factory
            if chat_budget is not None:
                chat_budget.read_in_transaction(db, previous["run_id"])
            self.require_identity(identity)
            return previous
        scope_json = None
        if self.scope_service is not None:
            proof = self.scope_service.prove_in_transaction(db, payload["conversation_id"], payload["selected_refs"])
            if proof.owner_id != identity.actor_id or proof.namespace != identity.space_id:
                fail(web.HTTPForbidden, "SCOPE_FORBIDDEN", "身份与资料范围不符")
            scope_json = json.dumps(asdict(proof), ensure_ascii=False, sort_keys=True)
        run_id = str(uuid4())
        db.execute("INSERT INTO agent_runs (run_id,actor_id,space_id,conversation_id,goal,selected_refs,scope_proof,revision,status,goal_revision,applied_goal_revision,last_input_seq,lease_epoch,last_event_seq,created_at) VALUES (?,?,?,?,?,?,?,0,'QUEUED',1,1,0,0,0,?)", (run_id, identity.actor_id, identity.space_id, payload["conversation_id"], payload["goal"], json.dumps(payload["selected_refs"], ensure_ascii=False), scope_json, utc_now().isoformat()))
        if "required_outputs" in payload:
            RunRequirements.save_in_transaction(db, run_id, 1, payload["request_key"], payload["required_outputs"])
        if chat_budget is not None:
            chat_budget.bind_in_transaction(db, request, run_id)
        receipt = {"run_id": run_id, "status": "QUEUED", "revision": 0}
        self.require_identity(identity)
        self.save_request(db, identity, payload["request_key"], digest, run_id, "create", receipt)
        return receipt

    def read(self, identity, run_id):
        self.require_identity(identity)
        method_lock = self.method_selection.drafts._locked() if self.method_selection is not None else nullcontext()
        with method_lock, self.store.connect() as db:
            db.execute("BEGIN")
            row = self.owned(db, identity, run_id)
            refs = json.loads(row["selected_refs"])
            self.require_current_scope(identity, row, db)
            if self.scope_service is not None:
                from agent_run_memory_guard import require_current_run_memory_in_transaction
                require_current_run_memory_in_transaction(db, self.scope_service.store, run_id)
            requirements = RunRequirements.read_in_transaction(db, run_id, row["goal_revision"])
            self.require_identity(identity)
            result = {"run_id": row["run_id"], "conversation_id": row["conversation_id"], "goal": row["goal"], "selected_refs": refs, "status": row["status"], "revision": row["revision"], "goal_revision": row["goal_revision"], "applied_goal_revision": row["applied_goal_revision"], "last_event_seq": row["last_event_seq"], "cancel_requested_at": row["cancel_requested_at"], "allowed_actions": self.allowed_actions(row), "requirements": requirements}
            from agent_run_method_selection import AgentRunMethodSelection
            method_selection = AgentRunMethodSelection.read_in_transaction(db, run_id)
            if method_selection is not None:
                result["method_selection"] = method_selection
            if self.method_selection is not None and self.method_selection.can_reselect_in_transaction(db, row, identity):
                result["allowed_actions"].append("SELECT_METHOD")
            waiting = self._waiting_input_in_transaction(db, row)
            if waiting is not None:
                result["waiting_input"] = waiting
            self.require_identity(identity)
            return result

    @staticmethod
    def _waiting_input_in_transaction(db, run, *, include_answered=False):
        if run["status"] != "WAITING_INPUT" or run["cancel_requested_at"] is not None:
            return None
        wait = db.execute("SELECT seq,lease_epoch,payload FROM agent_run_events WHERE run_id=? AND type='STATUS_CHANGED' AND json_extract(payload,'$.to')='WAITING_INPUT' ORDER BY seq DESC LIMIT 1", (run["run_id"],)).fetchone()
        if wait is None:
            raise ValueError("等待状态事件不可核查")
        payload = json.loads(wait[2])
        if payload.get("reason") != "INPUT_REQUIRED":
            return None
        goal_revision = payload.get("goal_revision")
        if type(goal_revision) is not int or goal_revision < 1 or goal_revision > run["goal_revision"]:
            raise ValueError("等待补充目标版本不可核查")
        if goal_revision != run["goal_revision"] and not include_answered:
            return None
        if set(payload) != {"from", "to", "reason", "goal_revision", "input_required_event_id"} or payload["from"] != "RUNNING" or wait[1] != run["lease_epoch"]:
            raise ValueError("等待补充事件不可核查")
        event = db.execute("SELECT seq,lease_epoch,type,payload,origin_event_id FROM agent_run_events WHERE run_id=? AND event_id=?", (run["run_id"], payload["input_required_event_id"])).fetchone()
        if event is None or event[1] != wait[1] or event[2] != "INPUT_REQUIRED" or event[0] >= wait[0] or not event[4].startswith("input-required:"):
            raise ValueError("补充问题事件不可核查")
        question = json.loads(event[3])
        if set(question) != {"question", "goal_revision"} or question["goal_revision"] != goal_revision or not isinstance(question["question"], str) or not question["question"].strip() or len(question["question"]) > 2000:
            raise ValueError("补充问题内容不可核查")
        call_id = event[4].removeprefix("input-required:")
        started = db.execute("SELECT seq,payload FROM agent_run_events WHERE run_id=? AND lease_epoch=? AND origin_event_id=? AND type='TOOL_STARTED'", (run["run_id"], wait[1], "input-request-start:" + call_id)).fetchone()
        finished = db.execute("SELECT seq,payload FROM agent_run_events WHERE run_id=? AND lease_epoch=? AND origin_event_id=? AND type='TOOL_FINISHED'", (run["run_id"], wait[1], "input-request-finish:" + call_id)).fetchone()
        if not call_id or started is None or finished is None or not started[0] < event[0] < finished[0] < wait[0] or json.loads(started[1]) != {"tool_id": "request_additional_input", "call_id": call_id} or json.loads(finished[1]) != {"tool_id": "request_additional_input", "call_id": call_id, "outcome": "RETURNED", "goal_revision": goal_revision}:
            raise ValueError("补充问题工具事件不可核查")
        from business import checksum
        reservation = db.execute("SELECT request_digest,tool_name,lease_epoch FROM agent_tool_reservations WHERE run_id=? AND request_key=?", (run["run_id"], call_id)).fetchone()
        expected = checksum({"goal_revision": goal_revision, "question": question["question"], "scope_proof": json.loads(run["scope_proof"]) if run["scope_proof"] else None})
        if reservation is None or tuple(reservation) != (expected, "request_additional_input", wait[1]):
            raise ValueError("补充问题工具预留不可核查")
        return {"event_id": payload["input_required_event_id"], "goal_revision": goal_revision, "question": question["question"]}

    @staticmethod
    def require_requirements_request(db, identity, request, outputs):
        if not isinstance(request, web.Request) or not callable(identity.verify):
            fail(web.HTTPUnauthorized, "UNAUTHENTICATED", "成果要求需要实际本人会话")
        if not REQUIREMENTS_VALIDATOR.is_valid(outputs):
            fail(web.HTTPBadRequest, "INVALID_INPUT", "成果要求字段无效")
        if not RunRequirements.schema_state(db):
            fail(web.HTTPServiceUnavailable, "SERVICE_NOT_READY", "成果要求服务尚未安装")

    def mutate(self, identity, run_id, operation, payload, *, request=None):
        self.require_identity(identity)
        digest = digest_request("POST", "/api/v2/runs/" + run_id + "/" + operation, payload)
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self.owned(db, identity, run_id)
            self.require_current_scope(identity, row, db)
            if operation == "inputs" and "required_outputs" in payload:
                self.require_requirements_request(db, identity, request, payload["required_outputs"])
            previous = self.replay_request(db, identity, payload["request_key"], digest)
            if previous is not None:
                if operation == "inputs":
                    self.verify_input_receipt_in_transaction(db, run_id, payload["request_key"], previous)
                self.require_identity(identity)
                return previous
            if operation == "inputs":
                if row["status"] not in {"QUEUED", "RUNNING", "WAITING_INPUT", "WAITING_CONFIRMATION"} or row["cancel_requested_at"] is not None or row["goal_revision"] != payload["expected_goal_revision"]:
                    fail(web.HTTPConflict, "REVISION_CONFLICT", "运行状态或目标版本已经变化")
                input_id, seq, goal_revision = str(uuid4()), row["last_input_seq"] + 1, row["goal_revision"] + 1
                db.execute("INSERT INTO agent_run_inputs VALUES (?, ?, ?, ?, ?, ?, NULL)", (input_id, run_id, seq, goal_revision, payload["request_key"], payload["input"]))
                db.execute("UPDATE agent_runs SET last_input_seq=?, goal_revision=?, revision=revision+1 WHERE run_id=?", (seq, goal_revision, run_id))
                if "required_outputs" in payload:
                    RunRequirements.save_in_transaction(db, run_id, goal_revision, payload["request_key"], payload["required_outputs"])
                self.store._record_event(db, run_id, "INPUT_RECEIVED", {"input_id": input_id, "input_seq": seq, "goal_revision": goal_revision})
                receipt = {"input_id": input_id, "input_seq": seq, "goal_revision": goal_revision}
            else:
                if row["revision"] != payload["expected_revision"] or row["cancel_requested_at"] is not None or row["status"] not in {"QUEUED", "RUNNING", "WAITING_INPUT", "WAITING_CONFIRMATION", "RECONCILING", "INTERRUPTED"}:
                    fail(web.HTTPConflict, "REVISION_CONFLICT", "运行状态或版本已经变化")
                status = "CANCELED" if row["status"] == "QUEUED" else row["status"] if row["status"] in {"RECONCILING", "INTERRUPTED"} else "CANCEL_REQUESTED"
                db.execute("UPDATE agent_runs SET status=?, cancel_requested_at=?, revision=revision+1 WHERE run_id=?", (status, utc_now().isoformat(), run_id))
                self.store._record_event(db, run_id, "STATUS_CHANGED", {"from": row["status"], "to": status})
                receipt = {"run_id": run_id, "status": status, "revision": row["revision"] + 1}
            self.require_identity(identity)
            self.save_request(db, identity, payload["request_key"], digest, run_id, operation, receipt)
            return receipt

    def events(self, identity, run_id, after_seq):
        self.require_identity(identity)
        with self.store.connect() as db:
            db.execute("BEGIN")
            row = self.owned(db, identity, run_id)
            self.require_current_scope(identity, row, db)
            if self.scope_service is not None:
                from agent_run_memory_guard import require_current_run_memory_in_transaction
                require_current_run_memory_in_transaction(db, self.scope_service.store, run_id)
            page = self.store.event_page_in_transaction(db, run_id, after_seq)
            self.require_identity(identity)
            return page

    def usage(self, identity, run_id):
        self.require_identity(identity)
        if self.scope_service is None:
            fail(web.HTTPServiceUnavailable, "SERVICE_NOT_READY", "用量查询需要来源范围服务")
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self.owned(db, identity, run_id)
            self.require_current_scope(identity, row, db)
            from hermes_source_invalidation import require_source_cleanup_complete
            require_source_cleanup_complete(db, run_id)
            if self.scope_service is not None:
                from agent_run_memory_guard import require_current_run_memory_in_transaction
                require_current_run_memory_in_transaction(db, self.scope_service.store, run_id)
            from agent_run_usage import latest_usage_snapshot_in_transaction, usage_lineage_in_transaction
            contributors = usage_lineage_in_transaction(db, run_id)
            snapshot = latest_usage_snapshot_in_transaction(db, run_id)
            if snapshot is None:
                fail(web.HTTPNotFound, "NOT_FOUND", "用量快照不存在")
            root = self.owned(db, identity, snapshot["root_run_id"])
            self.require_current_scope(identity, root, db)
            if not contributors:
                fail(web.HTTPServiceUnavailable, "SERVICE_NOT_READY", "用量来源边界无法核查")
            for contributor in contributors:
                contributor_row = self.owned(db, identity, contributor["run_id"])
                self.require_current_scope(identity, contributor_row, db)
                require_source_cleanup_complete(db, contributor["run_id"])
                if self.scope_service is not None:
                    require_current_run_memory_in_transaction(db, self.scope_service.store, contributor["run_id"])
            self.require_identity(identity)
            return snapshot

    def completion_inspection(self, identity, run_id, finish_event_id=None):
        self.require_identity(identity)
        if finish_event_id is not None and (not isinstance(finish_event_id, str) or not finish_event_id or len(finish_event_id) > 128):
            fail(web.HTTPBadRequest, "INVALID_INPUT", "完成核查事件无效")
        with self.store.connect() as db:
            db.execute("BEGIN")
            row = self.owned(db, identity, run_id)
            self.require_current_scope(identity, row, db)
            from hermes_source_invalidation import require_source_cleanup_complete
            require_source_cleanup_complete(db, run_id)
            if self.scope_service is not None:
                from agent_run_memory_guard import require_current_run_memory_in_transaction
                require_current_run_memory_in_transaction(db, self.scope_service.store, run_id)
            if finish_event_id is None:
                saved = db.execute("SELECT expected_revision,receipt FROM agent_run_operations WHERE run_id=? AND operation='completion_inspection' ORDER BY rowid DESC LIMIT 1", (run_id,)).fetchone()
            else:
                saved = db.execute("SELECT expected_revision,receipt FROM agent_run_operations WHERE run_id=? AND operation='completion_inspection' AND request_key=?", (run_id, "completion-inspection:engine-finish:" + finish_event_id)).fetchone()
            if saved is None:
                fail(web.HTTPNotFound, "NOT_FOUND", "完成核查不存在")
            receipt = json.loads(saved[1])
            self.require_identity(identity)
            stale = self._completion_stale(db, row, receipt, saved[0])
            return {"run_id": run_id, "goal_revision": receipt["goal_revision"], "current_goal_revision": row["goal_revision"],
                    "inspection_revision": saved[0], "run_revision": row["revision"], "stale": stale,
                    "result_event_id": receipt["result_event_id"], "finish_event_id": receipt["finish_event_id"],
                    "completion_state": receipt["completion_state"], "blockers": receipt["blockers"],
                    "output_checks": receipt["output_checks"], "requirements": receipt["requirements"],
                    "brief_section_audits": receipt.get("brief_section_audits", [])}

    def _completion_stale(self, db, row, receipt, saved_revision):
        if row["goal_revision"] != receipt["goal_revision"]:
            return True
        result = self.store.result_in_transaction(db, row["run_id"], row["goal_revision"])
        if result is None or result["event_id"] != receipt["result_event_id"]:
            return True
        stored_artifacts = [{key: item.get(key) for key in ("artifact_id", "version", "sha256", "verification_status", "status")} for item in receipt.get("artifacts", [])]
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='agent_artifacts'").fetchone() is not None:
            current_artifacts = [{key: value for key, value in zip(("artifact_id", "version", "sha256", "verification_status", "status"), item)} for item in db.execute("SELECT artifact_id,version,sha256,verification_status,status FROM agent_artifacts WHERE run_id=? ORDER BY artifact_id", (row["run_id"],)).fetchall()]
            if current_artifacts != stored_artifacts:
                return True
        elif stored_artifacts:
            return True
        from agent_artifacts import verify_stored_artifact_file_in_transaction
        for item in stored_artifacts:
            try:
                verified = verify_stored_artifact_file_in_transaction(db, item["artifact_id"], item["version"])
            except (ValueError, OSError):
                return True
            if verified["sha256"] != item["sha256"]:
                return True
        if "pending_file_reservations" in receipt and db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='agent_file_reservations'").fetchone() is not None:
            if db.execute("SELECT count(*) FROM agent_file_reservations WHERE run_id=? AND status='RESERVED'", (row["run_id"],)).fetchone()[0] != receipt["pending_file_reservations"]:
                return True
        if "requirements" in receipt:
            from agent_run_requirements import RunRequirements
            if RunRequirements.read_in_transaction(db, row["run_id"], row["goal_revision"]) != receipt["requirements"]:
                return True
        if receipt.get("brief_section_audits") or "action_draft_inspection" in receipt:
            return True
        if "intent_state_sha256" not in receipt or "process_evidence_sha256" not in receipt:
            return True
        intents = db.execute("SELECT intent_id,action,status,revision,request_key,authorization_id,result_ref,payload_digest FROM agent_intents WHERE run_id=? ORDER BY intent_id", (row["run_id"],)).fetchall() if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='agent_intents'").fetchone() is not None else []
        if checksum([tuple(item) for item in intents]) != receipt["intent_state_sha256"]:
            return True
        processes = db.execute("SELECT request_key,state,exit_code,exit_scope FROM hermes_process_evidence WHERE run_id=? ORDER BY request_key", (row["run_id"],)).fetchall() if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='hermes_process_evidence'").fetchone() is not None else []
        if checksum([tuple(item) for item in processes]) != receipt["process_evidence_sha256"]:
            return True
        if "vm_tree_evidence_sha256" in receipt:
            from agent_run_result import vm_tree_exit_evidence
            tree_rows, _ = vm_tree_exit_evidence(db, row["run_id"], receipt["lease_epoch"])
            if checksum(tree_rows) != receipt["vm_tree_evidence_sha256"]:
                return True
        if "pending_intents" in receipt and db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='agent_intents'").fetchone() is not None:
            if db.execute("SELECT count(*) FROM agent_intents WHERE run_id=? AND status NOT IN ('SUCCEEDED','FAILED','REJECTED','EXPIRED')", (row["run_id"],)).fetchone()[0] != receipt["pending_intents"]:
                return True
        if "business_receipt_inspection" in receipt:
            from agent_run_business_receipts import RunBusinessReceipts
            receipts = RunBusinessReceipts(self.store, self.scope_service)
            if row["status"] in {"SUCCEEDED", "FAILED", "CANCELED", "INTERRUPTED"}:
                current = receipts.inspect_terminal_in_transaction(db, row["run_id"], row["goal_revision"], receipt["lease_epoch"])
            else:
                current = receipts.inspect_in_transaction(db, row["run_id"], row["goal_revision"])
            if current != receipt["business_receipt_inspection"]:
                return True
        finish = db.execute("SELECT seq FROM agent_run_events WHERE run_id=? AND event_id=?", (row["run_id"], receipt["finish_event_id"])).fetchone()
        if finish is None:
            return True
        for event_type, payload in db.execute("SELECT type,payload FROM agent_run_events WHERE run_id=? AND seq>? ORDER BY seq", (row["run_id"], finish[0])).fetchall():
            if event_type == "USAGE_RECORDED":
                continue
            if event_type == "STATUS_CHANGED" and json.loads(payload).get("to") in {"SUCCEEDED", "FAILED", "CANCELED"}:
                continue
            return True
        return False

    def requeue_waiting(self, identity, run_id, expected_revision, expected_goal_revision, request_key, *, request):
        self.require_identity(identity)
        if not isinstance(request, web.Request) or not callable(identity.verify) or self.scope_service is None:
            fail(web.HTTPUnauthorized, "UNAUTHENTICATED", "运行恢复需要实际本人会话")
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self.owned(db, identity, run_id)
            self.require_current_scope(identity, row, db)
            from agent_run_memory_guard import require_current_run_memory_in_transaction
            require_current_run_memory_in_transaction(db, self.scope_service.store, run_id)
            self.require_identity(identity)
            saved = db.execute("SELECT operation,expected_revision,receipt FROM agent_run_operations WHERE run_id=? AND request_key=?", (run_id, "waiting-resume:" + request_key)).fetchone()
            if saved is not None:
                receipt = json.loads(saved[2])
                if not isinstance(receipt, dict) or set(receipt) != {"run_id", "status", "revision", "goal_revision"} or receipt["run_id"] != run_id or receipt["status"] != "QUEUED" or type(receipt["revision"]) is not int or type(receipt["goal_revision"]) is not int or receipt["revision"] != saved[1] + 2:
                    raise ValueError("运行恢复回执不可核查")
                if saved[0] != "waiting_resume" or saved[1] != expected_revision or receipt["goal_revision"] != expected_goal_revision:
                    fail(web.HTTPConflict, "REQUEST_KEY_CONFLICT", "运行恢复请求内容已经变化")
                self.require_identity(identity)
                return receipt
            if row["revision"] != expected_revision or row["goal_revision"] != expected_goal_revision or row["status"] != "WAITING_INPUT" or row["cancel_requested_at"] is not None:
                fail(web.HTTPConflict, "REVISION_CONFLICT", "运行状态或目标版本已经变化")
            receipt = self.store.requeue_waiting_in_transaction(db, run_id, expected_revision, expected_goal_revision, request_key)
            self.require_identity(identity)
            return receipt

    def waiting_resume_inspection(self, identity, run_id, *, request_key=None):
        self.require_identity(identity)
        if not callable(identity.verify) or self.scope_service is None:
            fail(web.HTTPUnauthorized, "UNAUTHENTICATED", "运行恢复查询需要实际本人会话")
        with self.store.connect() as db:
            db.execute("BEGIN")
            row = self.owned(db, identity, run_id)
            self.require_current_scope(identity, row, db)
            from agent_run_memory_guard import require_current_run_memory_in_transaction
            require_current_run_memory_in_transaction(db, self.scope_service.store, run_id)
            reasons = ["ENGINE_BOUNDARY_UNVERIFIED", "PROCESS_RECOVERY_UNVERIFIED", "BUDGET_REVALIDATION_REQUIRED"]
            if row["status"] != "WAITING_INPUT" or row["cancel_requested_at"] is not None:
                reasons.append("RUN_STATE_UNAVAILABLE")
            requirements = RunRequirements.read_in_transaction(db, run_id, row["goal_revision"])
            if requirements["state"] != "CONFIRMED":
                reasons.append("REQUIRED_OUTPUTS_UNCONFIRMED")
            if row["lease_expires_at"] is not None and datetime.fromisoformat(row["lease_expires_at"]) > utc_now():
                reasons.append("ORIGINAL_LEASE_ACTIVE")
            waiting = db.execute("SELECT seq,payload FROM agent_run_events WHERE run_id=? AND type='STATUS_CHANGED' AND json_extract(payload,'$.to')='WAITING_INPUT' ORDER BY seq DESC LIMIT 1", (run_id,)).fetchone()
            received = db.execute("SELECT seq,payload FROM agent_run_events WHERE run_id=? AND type='INPUT_RECEIVED' AND json_extract(payload,'$.goal_revision')=?", (run_id, row["goal_revision"])).fetchall()
            question = self._waiting_input_in_transaction(db, row, include_answered=True) if row["status"] == "WAITING_INPUT" else None
            entry = db.execute("SELECT input_id,input_seq,goal_revision,request_key FROM agent_run_inputs WHERE run_id=? AND goal_revision=?", (run_id, row["goal_revision"])).fetchone()
            if waiting is None or len(received) != 1 or entry is None or received[0][0] <= waiting[0] or question is not None and entry[2] <= question["goal_revision"]:
                reasons.append("ADDITIONAL_INPUT_REQUIRED")
            else:
                saved_input = db.execute("SELECT receipt FROM agent_api_requests WHERE actor_id=? AND space_id=? AND run_id=? AND request_key=? AND operation='inputs'", (row["actor_id"], row["space_id"], run_id, entry[3])).fetchone()
                if saved_input is None:
                    reasons.append("ADDITIONAL_INPUT_REQUIRED")
                else:
                    self.verify_input_receipt_in_transaction(db, run_id, entry[3], json.loads(saved_input[0]))
            if row["parent_run_id"] is not None:
                reasons.append("CHILD_RUN_RECOVERY_UNAVAILABLE")
            for version, table in (("upgrade2_concurrency_001", "agent_concurrency_reservations"), ("hermes_process_evidence_001", "hermes_process_evidence")):
                migration = Path(__file__).parent / "migrations" / (version + ".sql")
                saved_version = db.execute("SELECT sha256 FROM agent_schema_migrations WHERE version=?", (version,)).fetchone()
                exists = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
                if saved_version is None or saved_version[0] != hashlib.sha256(migration.read_bytes()).hexdigest() or exists is None:
                    reasons.append("PROCESS_RECORDS_UNAVAILABLE")
                    break
            else:
                if db.execute("SELECT 1 FROM agent_concurrency_reservations WHERE root_run_id=? AND state IN ('ACTIVE','UNKNOWN') LIMIT 1", (run_id,)).fetchone() is not None:
                    reasons.append("PROCESS_CAPACITY_UNRESOLVED")
                from agent_run_result import root_vm_tree_exits_verified
                if not root_vm_tree_exits_verified(db, run_id):
                    reasons.append("PRIOR_PROCESS_SCOPE_UNVERIFIED")
            receipt = None
            if request_key is not None:
                if not isinstance(request_key, str) or not request_key.strip() or len(request_key) > 128:
                    fail(web.HTTPBadRequest, "INVALID_INPUT", "运行恢复请求编号无效")
                saved = db.execute("SELECT operation,receipt,expected_revision FROM agent_run_operations WHERE run_id=? AND request_key=?", (run_id, "waiting-resume:" + request_key)).fetchone()
                if saved is not None:
                    if saved[0] != "waiting_resume":
                        raise ValueError("运行恢复回执不可核查")
                    receipt = json.loads(saved[1])
                    if not isinstance(receipt, dict) or set(receipt) != {"run_id", "status", "revision", "goal_revision"} or receipt["run_id"] != run_id or receipt["status"] != "QUEUED" or type(receipt["revision"]) is not int or type(receipt["goal_revision"]) is not int or receipt["revision"] != saved[2] + 2:
                        raise ValueError("运行恢复回执不可核查")
            self.require_identity(identity)
            return {"run_id": run_id, "status": row["status"], "revision": row["revision"], "goal_revision": row["goal_revision"], "allowed_actions": [], "waiting_reasons": reasons, "original_receipt": receipt}

    def result(self, identity, run_id):
        self.require_identity(identity)
        with self.store.connect() as db:
            db.execute("BEGIN")
            row = self.owned(db, identity, run_id)
            self.require_current_scope(identity, row, db)
            if self.scope_service is not None:
                from agent_run_memory_guard import require_current_run_memory_in_transaction
                require_current_run_memory_in_transaction(db, self.scope_service.store, run_id)
            event = self.store.result_in_transaction(db, run_id, row["goal_revision"])
            checks = self.result_citation_checks_in_transaction(db, identity.space_id, run_id, event)
            self.require_identity(identity)
            return {"run_id": run_id, "goal_revision": row["goal_revision"], "result": event, "citation_checks": checks}

    @staticmethod
    def result_citation_checks_in_transaction(db, namespace, run_id, event):
        if not db.in_transaction or not isinstance(namespace, str) or not namespace:
            raise ValueError("引用核查读取需要当前事务及空间")
        if event is None:
            return None
        if event["run_id"] != run_id or event["type"] != "RESULT_RECORDED":
            raise ValueError("引用核查与结果不匹配")
        row = db.execute("SELECT body FROM objects WHERE namespace=? AND kind='hermes_result_citation_checks' AND id=?", (namespace, event["event_id"])).fetchone()
        if row is None:
            return None
        saved = json.loads(row[0])
        expected = {"run_id": run_id, "event_id": event["event_id"], "citations": [{**citation, "locator_verification": "NOT_VERIFIED"} for citation in event["payload"]["citations"]]}
        if saved != expected:
            raise ValueError("引用核查记录不可核查")
        return saved["citations"]
