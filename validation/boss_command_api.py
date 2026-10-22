"""Boss-Agent owner-approved commands over nanobot's authenticated WebUI socket.

First bounded implementation of PRD FR-06 / FR-28. The existing
ControlStore and Store domain methods remain the only business-state owner.
The UI cannot provide owner_id, dataset, namespace, authorization_id or
successful execution status. Everything is SIMULATED, not external delivery.

A successful response is a *persisted result*; it never implies the model or
an external service has finished. Each command is atomic: authorization,
business transition, idempotency receipt and audit share one SQLite tx.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from aiohttp import web
from jsonschema import Draft202012Validator, FormatChecker

from business import checksum, encode, now, require, validate
from controls import FIELDS

NAMESPACE = "ui-check"
MAX_PURPOSE = 1600
MAX_MESSAGE = 2400
ERROR_CODE = {
    400: "INVALID_INPUT", 401: "UNAUTHENTICATED",
    403: "FORBIDDEN", 404: "NOT_FOUND",
    409: "VERSION_OR_IDEMPOTENCY_CONFLICT", 410: "SOURCE_WITHDRAWN",
}


def _is_text(value, max_chars=MAX_PURPOSE):
    return isinstance(value, str) and 0 < len(value.strip()) <= max_chars


def _client_key(value):
    require(
        isinstance(value, str) and 8 <= len(value) <= 128 and
        value.isascii() and all(c.isalnum() or c in "-_." for c in value),
        "幂等标识必须是 8—128 位 ASCII 字符",
        web.HTTPBadRequest,
    )
    return value


def _aware_due(value, tzname):
    require(_is_text(value, 100) and _is_text(tzname, 80), "截止时间和时区缺失", web.HTTPBadRequest)
    try:
        tz = ZoneInfo(tzname)
        dt = datetime.fromisoformat(value)
    except (ValueError, ZoneInfoNotFoundError):
        raise web.HTTPBadRequest(text="时区或日期格式无效") from None
    require(dt.tzinfo is not None and dt.utcoffset() is not None, "截止时间必须带 UTC 偏移", web.HTTPBadRequest)
    require(dt.astimezone(tz).utcoffset() == dt.utcoffset(), "截止时间偏移和 IANA 时区不匹配", web.HTTPBadRequest)
    return dt


def _data_envelope(data, request_id):
    return {
        "request_id": request_id, "owner_id": data["owner_id"],
        "execution_namespace": NAMESPACE, "dataset_id": data["dataset_id"],
        "dataset_version": data["dataset_version"], "session_id": "boss-desktop",
    }


class BossCommandAPI:
    ACTION_ROLES = {
        "boss.assignment.create": "BOSS",
        "boss.assignment.send": "BOSS",
        "boss.assignment.complete": "BOSS",
        "boss.assignment.extend": "BOSS",
        "boss.assignment.cancel": "BOSS",
        "boss.simulation.feedback": "MAINTAINER",
    }

    def __init__(self, store):
        self.store = store

    def execute(self, role, action, payload):
        if role not in ("BOSS", "MAINTAINER"):
            return 401, {"error": "UNAUTHENTICATED"}
        expected_role = self.ACTION_ROLES.get(action)
        if not expected_role:
            return 404, {"error": "UNKNOWN_COMMAND"}
        if role != expected_role:
            return 403, {"error": "FORBIDDEN"}
        if not isinstance(payload, dict):
            return 400, {"error": "PAYLOAD_MUST_BE_OBJECT"}
        try:
            result = self._transaction(action, payload)
            return 200, result
        except web.HTTPException as exc:
            return exc.status, {"error": ERROR_CODE.get(exc.status, "BUSINESS_REJECTED"), "status": exc.status}
        except (TypeError, ValueError, KeyError):
            # Never leak a Python exception or private source data to renderer.
            return 400, {"error": "INVALID_INPUT"}

    @staticmethod
    def _exact(payload, keys):
        require(set(payload) == set(keys), "输入字段缺失或越权字段", web.HTTPBadRequest)

    def _check_existing(self, db, action, payload):
        key = _client_key(payload.get("client_request_id"))
        content = {k: v for k, v in payload.items() if k != "client_request_id"}
        digest = checksum({"action": action, "content": content})
        row = db.execute(
            "SELECT digest,result FROM idempotency WHERE namespace=? AND operation=? AND key=?",
            (NAMESPACE, action, key),
        ).fetchone()
        if row is not None:
            require(row[0] == digest, "同一幂等标识不得提交不同内容")
            return key, digest, json.loads(row[1])
        return key, digest, None

    def _record(self, db, action, payload, key, digest, result):
        db.execute(
            "INSERT INTO idempotency(namespace,operation,key,digest,result) VALUES (?,?,?,?,?)",
            (NAMESPACE, action, key, digest, encode(result)),
        )
        # This audit is permission-scoped metadata and deliberately excludes
        # raw message, purpose, feedback text and source body.
        audit_in = {
            "client_request_id": key,
            "task_id": payload.get("task_id"),
            "action": action,
            "source_type": "SIMULATED",
        }
        audit_out = {
            "task_id": result.get("task_id") or result.get("task", {}).get("task_id"),
            "status": result.get("status") or result.get("task", {}).get("status"),
            "authorization_id": result.get("authorization_id"),
        }
        db.execute(
            "INSERT INTO audit(namespace,operation,input,output,created_at) VALUES(?,?,?,?,?)",
            (NAMESPACE, action, encode(audit_in), encode(audit_out), now()),
        )

    def _authorize(self, db, action, bound_payload, target_id, content_version):
        auth_id = str(uuid.uuid4())
        auth = {
            "authorization_id": auth_id, "owner_id": "boss-1",
            "issuer_identity": "BOSS", "issuer": "boss-1",
            "source_instruction_id": str(uuid.uuid4()),
            "source_instruction": "本人在已认证桌面 UI 确认当前动作",
            "action": action, "target_id": target_id,
            "content_version": content_version, "scope": NAMESPACE,
            "payload": bound_payload, "version": "1", "revoked": False,
            "revoked_at": None, "valid_from": now(),
            "valid_until": (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat(),
        }
        self.store.put(db, NAMESPACE, "authorization", auth_id, auth)
        return auth_id

    def _require_current_source(self, db, data, source_id):
        require(_is_text(source_id, 128), "来源标识无效", web.HTTPBadRequest)
        doc = self.store.get(db, NAMESPACE, "document", source_id)
        require(
            not doc.get("withdrawn") and doc.get("access_scope") == data["owner_id"]
            and doc.get("source_type") == "SIMULATED",
            "来源已撤销或不可作为当前执行依据",
            web.HTTPForbidden,
        )
        return doc

    def _transaction(self, action, payload):
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self.store.active(db, NAMESPACE)
            key, digest, prev = self._check_existing(db, action, payload)
            if prev is not None:
                return prev
            data = self.store.get(db, NAMESPACE, "initial", "snapshot")
            if action == "boss.assignment.create":
                result = self._create(db, data, payload, key)
            elif action == "boss.assignment.send":
                result = self._send(db, data, payload, key)
            elif action in ("boss.assignment.complete", "boss.assignment.extend"):
                result = self._decide(db, payload, action)
            elif action == "boss.assignment.cancel":
                result = self._cancel(db, payload)
            elif action == "boss.simulation.feedback":
                result = self._feedback(db, payload)
            else:
                raise web.HTTPNotFound()
            self._record(db, action, payload, key, digest, result)
            return result

    def _create(self, db, data, payload, key):
        self._exact(payload, {
            "client_request_id", "purpose", "coordinator_id", "due_at",
            "timezone", "evidence_requirements", "related_meeting_id",
            "related_event_ids", "source_refs", "content_version",
        })
        require(_is_text(payload["purpose"]), "交办内容不能为空或过长", web.HTTPBadRequest)
        require(payload["content_version"] == "1", "当前只接受演示内容版本 1", web.HTTPBadRequest)
        require(payload["coordinator_id"] in {c["contact_id"] for c in data["contacts"]},
                "负责人不在当前获准资料内", web.HTTPBadRequest)
        require(payload["coordinator_id"] == "coordinator-1",
                "当前模拟交办仅允许经过验证的统筹负责人", web.HTTPBadRequest)
        require(payload["related_meeting_id"] == data["meeting"]["meeting_id"],
                "关联会议不符", web.HTTPBadRequest)
        require(payload["related_event_ids"] == [data["event"]["event_id"]],
                "关联事项不符", web.HTTPBadRequest)
        refs = payload["source_refs"]
        require(isinstance(refs, list) and refs == ["finance-note"],
                "当前交办资料范围不符", web.HTTPBadRequest)
        for source_id in refs:
            self._require_current_source(db, data, source_id)
        due = _aware_due(payload["due_at"], payload["timezone"])
        clock = self.store.get(db, NAMESPACE, "clock", "current")
        require(due > datetime.fromisoformat(clock["at"]), "期限必须在模拟业务时钟之后", web.HTTPBadRequest)
        evidence = payload["evidence_requirements"]
        require(isinstance(evidence, list) and 1 <= len(evidence) <= 8 and
                all(_is_text(t, 160) for t in evidence),
                "证据要求缺少或无效", web.HTTPBadRequest)
        bound = {k: v for k, v in payload.items() if k != "client_request_id"}
        auth_id = self._authorize(db, "create_assignment", bound, "new-assignment", "1")
        tool_input = {
            **bound, "authorization_id": auth_id, "idempotency_key": key,
            "envelope": _data_envelope(data, key),
        }
        validate("assignment_input", tool_input)
        result = self.store.create_assignment(db, NAMESPACE, data, tool_input)
        validate("assignment_output", result)
        return {**result, "source_type": "SIMULATED", "authorization_scope": "BOSS_CONFIRMED"}

    def _send(self, db, data, payload, key):
        self._exact(payload, {
            "client_request_id", "task_id", "task_version", "recipient_id",
            "body", "content_version",
        })
        require(_is_text(payload["body"], MAX_MESSAGE), "消息正文无效", web.HTTPBadRequest)
        require(payload["content_version"] == "1", "消息版本不符", web.HTTPBadRequest)
        task = self.store.get(db, NAMESPACE, "task", payload["task_id"])
        require(task["status"] == "OPEN" and task["version"] == payload["task_version"],
                "任务版本变化或已经发送")
        require(task["coordinator_id"] == payload["recipient_id"],
                "收件人不是当前唯一负责人", web.HTTPForbidden)
        for source_id in task.get("source_refs", []):
            self._require_current_source(db, data, source_id)
        bound = {k: v for k, v in payload.items() if k != "client_request_id"}
        auth_id = self._authorize(db, "send_assignment", bound, payload["task_id"], "1")
        tool_input = {**bound, "authorization_id": auth_id,
                      "idempotency_key": key, "envelope": _data_envelope(data, key)}
        validate("send_input", tool_input)
        result = self.store.send_assignment(db, NAMESPACE, data, tool_input)
        validate("send_output", result)
        return {**result, "authorization_id": auth_id}

    def _feedback(self, db, payload):
        required = {
            "client_request_id", "task_id", "task_version", "author_contact_id",
            "kind", "content", "evidence_refs",
        }
        if payload.get("kind") == "EXTENSION_REQUEST":
            required.add("proposed_due_at")
        self._exact(payload, required)
        require(_is_text(payload["content"], MAX_MESSAGE),
                "反馈内容缺少或过长", web.HTTPBadRequest)
        fields, required = FIELDS["feedback"]
        body = {k: v for k, v in payload.items() if k != "client_request_id"}
        validator = Draft202012Validator(
            {"type": "object", "properties": fields,
             "required": required, "additionalProperties": False},
            format_checker=FormatChecker(),
        )
        require(not list(validator.iter_errors(body)), "反馈 Schema 无效", web.HTTPBadRequest)
        # Feedback may cite only currently available, scope-checked simulated
        # sources. The maintainer has no capability to forge a source ID.
        data = self.store.get(db, NAMESPACE, "initial", "snapshot")
        for source_id in body["evidence_refs"]:
            self._require_current_source(db, data, source_id)
        # No BOSS authorization is granted by simulated feedback; simulation
        # authors cannot approve a deadline or mark the task completed.
        result = self.store.control_feedback(db, NAMESPACE, body)
        return {"source_type": "SIMULATED", "task": {
            "task_id": result["task"]["task_id"],
            "version": result["task"]["version"],
            "status": result["task"]["status"],
        }, "feedback_id": result["feedback"]["feedback_id"],
                "feedback_kind": result["feedback"]["kind"]}

    def _decide(self, db, payload, action):
        fields = {"client_request_id", "task_id", "task_version", "feedback_id"}
        if action.endswith(".extend"):
            fields.add("due_at")
        self._exact(payload, fields)
        task = self.store.get(db, NAMESPACE, "task", payload["task_id"])
        require(task["version"] == payload["task_version"], "任务版本变化")
        feedback = self.store.get(db, NAMESPACE, "feedback", payload["feedback_id"])
        require(feedback["task_id"] == task["task_id"], "反馈对象不符", web.HTTPBadRequest)
        if action.endswith(".complete"):
            require(task["status"] == "RESULT_SUBMITTED" and
                    feedback["kind"] == "RESULT_SUBMITTED" and
                    feedback.get("evidence_refs"),
                    "缺少已提交的完成证据", web.HTTPBadRequest)
            data = self.store.get(db, NAMESPACE, "initial", "snapshot")
            for source_id in feedback["evidence_refs"]:
                self._require_current_source(db, data, source_id)
            action_name = "complete_assignment"
        else:
            require(feedback["kind"] == "EXTENSION_REQUEST" and
                    task["status"] not in ("CANCELED", "COMPLETED_CONFIRMED"),
                    "延期申请或任务状态无效", web.HTTPBadRequest)
            require(_is_text(payload["due_at"], 100), "新期限缺少", web.HTTPBadRequest)
            requested = _aware_due(payload["due_at"], task["timezone"])
            require(requested > datetime.fromisoformat(task["due_at"]),
                    "延期后的期限必须晚于当前有效期限", web.HTTPBadRequest)
            action_name = "extend_assignment"
        bound = {k: v for k, v in payload.items() if k != "client_request_id"}
        auth_id = self._authorize(db, action_name, bound, payload["task_id"],
                                  task["version"])
        result = self.store.control_decide(
            db, NAMESPACE, {"authorization_id": auth_id, **bound}
        )
        return {"source_type": "SIMULATED", "task_id": result["task_id"],
                "version": result["version"], "status": result["status"],
                "due_at": result.get("due_at"), "authorization_id": auth_id}

    def _cancel(self, db, payload):
        self._exact(payload, {"client_request_id", "task_id", "task_version", "reason"})
        require(_is_text(payload["reason"], 500), "取消原因缺少", web.HTTPBadRequest)
        task = self.store.get(db, NAMESPACE, "task", payload["task_id"])
        require(task["version"] == payload["task_version"], "任务版本变化")
        require(task["status"] not in ("CANCELED", "COMPLETED_CONFIRMED"),
                "已结束任务不能取消")
        self._authorize(
            db, "cancel_assignment",
            {k: v for k, v in payload.items() if k != "client_request_id"},
            task["task_id"], task["version"],
        )
        task["status"] = "CANCELED"
        task["version"] = str(int(task["version"]) + 1)
        task["cancellation_reason"] = payload["reason"]
        task["canceled_at"] = now()
        self.store.put(db, NAMESPACE, "task", task["task_id"], task)
        return {"source_type": "SIMULATED", "task_id": task["task_id"],
                "status": "CANCELED", "version": task["version"],
                "previous_message_ids": task.get("message_ids", [])}
