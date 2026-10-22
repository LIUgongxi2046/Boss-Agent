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
from boss_prompt_lifecycle import draft_save as prompt_draft_save, validate as prompt_validate, activate as prompt_activate
from boss_message_calendar import (
    message_save, message_send, message_reply, calendar_save,
    calendar_share, calendar_revoke, calendar_delete,
)
from boss_meeting_brief import prepare as meeting_brief_prepare
from boss_knowledge_ingestion import create as source_create, revise as source_revise, withdraw as source_withdraw
from boss_prompt_config import save as prompt_save, validate as prompt_validate, activate as prompt_activate, deactivate as prompt_deactivate
from boss_research import prepare as research_prepare
from boss_task_reminders import synchronize_task_due, current as task_due_event
from boss_meeting_approval import (
    minutes_save, minutes_confirm, minutes_assignment_create,
    application_seed, application_revise, approval_decide,
)

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
        "boss.simulation.event.seed": "MAINTAINER",
        "boss.simulation.clock.advance": "MAINTAINER",
        "boss.memory.confirm": "BOSS",
        "boss.memory.delete": "BOSS",
        "boss.reminder.ack": "BOSS",
        "boss.reminder.snooze": "BOSS",
        "boss.reminder.close": "BOSS",
        "boss.meeting.brief.prepare": "BOSS",
        "boss.research.prepare": "BOSS",
        "boss.minutes.save": "BOSS",
        "boss.minutes.confirm": "BOSS",
        "boss.minutes.assignment.create": "BOSS",
        "boss.prompt.draft.save": "MAINTAINER",
        "boss.prompt.validate": "MAINTAINER",
        "boss.prompt.activate": "MAINTAINER",
        "boss.knowledge.source.create": "MAINTAINER",
        "boss.knowledge.source.revise": "MAINTAINER",
        "boss.knowledge.source.withdraw": "MAINTAINER",
        "boss.prompt.save": "MAINTAINER",
        "boss.prompt.validate": "MAINTAINER",
        "boss.prompt.activate": "MAINTAINER",
        "boss.prompt.deactivate": "MAINTAINER",
        "boss.approval.decide": "BOSS",
        "boss.simulation.application.seed": "MAINTAINER",
        "boss.simulation.application.revise": "MAINTAINER",
        "boss.message.draft.save": "BOSS",
        "boss.message.send": "BOSS",
        "boss.simulation.message.reply": "MAINTAINER",
        "boss.calendar.save": "BOSS",
        "boss.calendar.share": "BOSS",
        "boss.calendar.share.revoke": "BOSS",
        "boss.calendar.delete": "BOSS",
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
            "meeting_id": payload.get("meeting_id"),
            "application_id": payload.get("application_id"),
            "action": action,
            "source_type": "SIMULATED",
        }
        audit_out = {
            "task_id": result.get("task_id") or result.get("task", {}).get("task_id"),
            "meeting_id": result.get("meeting_id"),
            "application_id": result.get("application_id"),
            "decision_id": result.get("decision_id"),
            "status": result.get("status") or result.get("state") or result.get("task", {}).get("status"),
            "version": result.get("version") or result.get("task", {}).get("version"),
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

    def _require_current_task_sources(self, db, data, task):
        """Task contents are not safe to send/close on unpinned provenance."""
        sources = task.get("source_refs", [])
        pinned = task.get("source_versions")
        require(isinstance(pinned, dict) and set(pinned) == set(sources),
                "当前任务没有完整的创建时来源版本；须重新核查后再执行")
        for source_id in sources:
            doc = self._require_current_source(db, data, source_id)
            require(doc.get("version") == pinned[source_id],
                    "任务原始来源已经换版，旧授权不能用于新的材料")
        origin_source = task.get("origin_source_id")
        if origin_source:
            source = self._require_current_source(db, data, origin_source)
            require(source.get("version") == task.get("origin_source_version"),
                    "纪要创建任务所引用的原始资料版本已变化，必须重新核查")

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
            elif action == "boss.simulation.event.seed":
                result = self._seed_event(db, data, payload)
            elif action == "boss.simulation.clock.advance":
                result = self._advance_clock(db, data, payload)
            elif action == "boss.memory.confirm":
                result = self._memory_confirm(db, payload)
            elif action == "boss.memory.delete":
                result = self._memory_delete(db, payload)
            elif action.startswith("boss.reminder."):
                result = self._reminder(db, payload, action)
            elif action == "boss.meeting.brief.prepare":
                result = meeting_brief_prepare(self, db, data, payload)
            elif action == "boss.research.prepare":
                result = research_prepare(self, db, data, payload)
            elif action == "boss.minutes.save":
                result = minutes_save(self, db, data, payload)
            elif action == "boss.minutes.confirm":
                result = minutes_confirm(self, db, data, payload)
            elif action == "boss.minutes.assignment.create":
                result = minutes_assignment_create(self, db, data, payload, key)
            elif action == "boss.prompt.draft.save":
                result = prompt_draft_save(self, db, data, payload)
            elif action == "boss.prompt.validate":
                result = prompt_validate(self, db, data, payload)
            elif action == "boss.prompt.activate":
                result = prompt_activate(self, db, data, payload)
            elif action == "boss.knowledge.source.create":
                result = source_create(self, db, data, payload)
            elif action == "boss.knowledge.source.revise":
                result = source_revise(self, db, data, payload)
            elif action == "boss.knowledge.source.withdraw":
                result = source_withdraw(self, db, data, payload)
            elif action == "boss.prompt.save":
                result = prompt_save(self, db, data, payload)
            elif action == "boss.prompt.validate":
                result = prompt_validate(self, db, data, payload)
            elif action == "boss.prompt.activate":
                result = prompt_activate(self, db, data, payload)
            elif action == "boss.prompt.deactivate":
                result = prompt_deactivate(self, db, data, payload)
            elif action == "boss.simulation.application.seed":
                result = application_seed(self, db, data, payload)
            elif action == "boss.simulation.application.revise":
                result = application_revise(self, db, data, payload)
            elif action == "boss.approval.decide":
                result = approval_decide(self, db, data, payload)
            elif action == "boss.message.draft.save":
                result = message_save(self, db, data, payload)
            elif action == "boss.message.send":
                result = message_send(self, db, data, payload)
            elif action == "boss.simulation.message.reply":
                result = message_reply(self, db, data, payload)
            elif action == "boss.calendar.save":
                result = calendar_save(self, db, data, payload)
            elif action == "boss.calendar.share":
                result = calendar_share(self, db, data, payload)
            elif action == "boss.calendar.share.revoke":
                result = calendar_revoke(self, db, data, payload)
            elif action == "boss.calendar.delete":
                result = calendar_delete(self, db, data, payload)
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
        current_clock = self.store.get(db, NAMESPACE, "clock", "current")
        today = datetime.fromisoformat(current_clock["at"]).date().isoformat()
        coordinator = next(c for c in data["contacts"]
                           if c["contact_id"] == payload["coordinator_id"])
        require(coordinator["valid_from"] <= today <= coordinator["valid_until"],
                "负责人在当前模拟业务时钟下已失效", web.HTTPForbidden)
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
        pinned_versions = {
            source_id: self._require_current_source(db, data, source_id)["version"]
            for source_id in refs
        }
        persisted = self.store.get(db, NAMESPACE, "task", result["task_id"])
        persisted["source_versions"] = pinned_versions
        self.store.put(db, NAMESPACE, "task", result["task_id"], persisted)
        return {**result, "source_type": "SIMULATED",
                "authorization_scope": "BOSS_CONFIRMED"}

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
        clock = self.store.get(db, NAMESPACE, "clock", "current")
        today = datetime.fromisoformat(clock["at"]).date().isoformat()
        person = next((c for c in data["contacts"]
                       if c["contact_id"] == task["coordinator_id"]), None)
        require(person is not None
                and person["valid_from"] <= today <= person["valid_until"],
                "当前任务负责人已不在有效联系人期内，禁止发送",
                web.HTTPForbidden)
        self._require_current_task_sources(db, data, task)
        bound = {k: v for k, v in payload.items() if k != "client_request_id"}
        auth_id = self._authorize(db, "send_assignment", bound, payload["task_id"], "1")
        tool_input = {**bound, "authorization_id": auth_id,
                      "idempotency_key": key, "envelope": _data_envelope(data, key)}
        validate("send_input", tool_input)
        result = self.store.send_assignment(db, NAMESPACE, data, tool_input)
        validate("send_output", result)
        updated = self.store.get(db, NAMESPACE, "task", payload["task_id"])
        reminder = synchronize_task_due(
            self.store, db, updated, reason="AUTHORIZED_SEND",
        )
        return {**result, "authorization_id": auth_id,
                "task_due_event": reminder}

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
        # Feedback is a response to a *sent* assignment, never a way for
        # the maintainer to forge a task state before the owner authorizes send.
        task = self.store.get(db, NAMESPACE, "task", body["task_id"])
        require(task["status"] in ("WAITING_FEEDBACK", "IN_PROGRESS"),
                "当前交办不接受新的模拟反馈")
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
            self._require_current_task_sources(db, data, task)
            for source_id in feedback["evidence_refs"]:
                self._require_current_source(db, data, source_id)
            action_name = "complete_assignment"
        else:
            require(feedback["kind"] == "EXTENSION_REQUEST" and
                    task["status"] not in ("CANCELED", "COMPLETED_CONFIRMED"),
                    "延期申请或任务状态无效", web.HTTPBadRequest)
            require(feedback["feedback_id"] not in
                    task.get("accepted_extension_feedback_ids", []),
                    "该延期申请此前已被老板批准，必须有新的模拟申请才能再次延期")
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
        if action.endswith(".extend"):
            result["accepted_extension_feedback_ids"] = [
                *result.get("accepted_extension_feedback_ids", []),
                feedback["feedback_id"],
            ]
            self.store.put(db, NAMESPACE, "task", result["task_id"], result)
        prior_event = task_due_event(db, result["task_id"])
        reminder = synchronize_task_due(
            self.store, db, result,
            reason="OWNER_COMPLETE" if action.endswith(".complete") else "AUTHORIZED_EXTEND",
        ) if prior_event else None
        return {"source_type": "SIMULATED", "task_id": result["task_id"],
                "version": result["version"], "status": result["status"],
                "due_at": result.get("due_at"), "authorization_id": auth_id,
                "task_due_event": reminder}

    def _cancel(self, db, payload):
        self._exact(payload, {"client_request_id", "task_id", "task_version", "reason"})
        require(_is_text(payload["reason"], 500), "取消原因缺少", web.HTTPBadRequest)
        task = self.store.get(db, NAMESPACE, "task", payload["task_id"])
        require(task["version"] == payload["task_version"], "任务版本变化")
        require(task["status"] not in ("CANCELED", "COMPLETED_CONFIRMED"),
                "已结束任务不能取消")
        auth_id = self._authorize(
            db, "cancel_assignment",
            {k: v for k, v in payload.items() if k != "client_request_id"},
            task["task_id"], task["version"],
        )
        task["cancellation_authorization_id"] = auth_id
        task["status"] = "CANCELED"
        task["version"] = str(int(task["version"]) + 1)
        task["cancellation_reason"] = payload["reason"]
        task["canceled_at"] = now()
        self.store.put(db, NAMESPACE, "task", task["task_id"], task)
        prior_event = task_due_event(db, task["task_id"])
        reminder = synchronize_task_due(
            self.store, db, task, reason="OWNER_CANCEL",
        ) if prior_event else None
        return {"source_type": "SIMULATED", "task_id": task["task_id"],
                "status": "CANCELED", "version": task["version"],
                "authorization_id": auth_id,
                "task_due_event": reminder,
                "previous_message_ids": task.get("message_ids", [])}


    def _memory_confirm(self, db, payload):
        self._exact(payload, {"client_request_id", "expected_version", "text"})
        require(_is_text(payload["text"], 4000),
                "个人要求须为 1—4000 字", web.HTTPBadRequest)
        current = self.store.get(db, NAMESPACE, "memory", "current")
        require(current["version"] == payload["expected_version"],
                "记忆版本已变化，须重新读取后确认")
        fingerprint = checksum({"text": payload["text"]})
        auth_id = self._authorize(
            db, "memory.confirm",
            {"expected_version": current["version"], "text_sha256": fingerprint},
            current["memory_id"], current["version"],
        )
        current.update(
            text=payload["text"].strip(),
            confirmation_state="CONFIRMED",
            version=str(int(current["version"]) + 1),
        )
        current["memory_version"] = current["version"]
        # No raw text in the authorization, idempotency receipt or audit log.
        self.store.put(db, NAMESPACE, "memory", "current", current)
        return {
            "source_type": "SIMULATED", "memory_id": current["memory_id"],
            "version": current["version"], "confirmation_state": "CONFIRMED",
            "adoption_policy": "FUTURE_TURNS_ONLY",
            "authorization_id": auth_id,
        }

    def _memory_delete(self, db, payload):
        self._exact(payload, {"client_request_id", "expected_version"})
        current = self.store.get(db, NAMESPACE, "memory", "current")
        require(current["version"] == payload["expected_version"],
                "记忆版本已变化，须重新读取后确认")
        require(current["confirmation_state"] != "DELETED",
                "此前记忆已删除，禁止重复操作")
        auth_id = self._authorize(
            db, "memory.delete",
            {"expected_version": current["version"]},
            current["memory_id"], current["version"],
        )
        current.update(
            text="", confirmation_state="DELETED",
            version=str(int(current["version"]) + 1),
        )
        current["memory_version"] = current["version"]
        self.store.put(db, NAMESPACE, "memory", "current", current)
        return {
            "source_type": "SIMULATED", "memory_id": current["memory_id"],
            "version": current["version"], "confirmation_state": "DELETED",
            "future_adoption_stopped": True,
            "physical_secure_erasure_verified": False,
            "authorization_id": auth_id,
        }

    def _seed_event(self, db, data, payload):
        self._exact(payload, {"client_request_id", "event_id"})
        event = data["event"]
        require(payload["event_id"] == event["event_id"],
                "事件不属于当前获准模拟数据集", web.HTTPBadRequest)
        exists = db.execute(
            "SELECT 1 FROM objects WHERE namespace=? AND kind='event' AND id=?",
            (NAMESPACE, event["event_id"]),
        ).fetchone()
        require(exists is None, "模拟事件已经注入，先读取原事件版本")
        registered = {
            "event_id": event["event_id"], "version": event["version"],
            "state": event["status"], "impact": "NORMAL",
            "due_at": event["due_at"], "source_type": "SIMULATED",
        }
        self.store.put(db, NAMESPACE, "event", registered["event_id"], registered)
        # Rules are explicitly created by the maintainer's event-seed action.
        # Do not silently start notifications for an unconfigured dataset.
        existing_rules = db.execute(
            "SELECT 1 FROM objects WHERE namespace=? AND kind='rules' AND id='current'",
            (NAMESPACE,),
        ).fetchone()
        if not existing_rules:
            self.store.put(db, NAMESPACE, "rules", "current", {
                "version": "1", "cooldown_seconds": 3600,
                "quiet_start": 22, "quiet_end": 7,
                "timezone": "Asia/Shanghai",
                "important_escalation": False,
            })
        return {"source_type": "SIMULATED", "event_id": registered["event_id"],
                "state": registered["state"], "version": registered["version"],
                "due_at": registered["due_at"], "rules_installed": not bool(existing_rules)}

    def _advance_clock(self, db, data, payload):
        self._exact(payload, {"client_request_id", "at"})
        requested = _aware_due(payload["at"], "Asia/Shanghai")
        old = self.store.get(db, NAMESPACE, "clock", "current")
        original = datetime.fromisoformat(old["at"])
        require(requested >= original, "业务时钟只能前进", web.HTTPBadRequest)
        require((requested - original).total_seconds() <= 366 * 86400,
                "单次模拟时间推进不能超过366天", web.HTTPBadRequest)
        current = self.store.control_clock(db, NAMESPACE, {"at": payload["at"]})
        # The actual CronService owns eventual notification dispatch.
        return {"source_type": "SIMULATED", "at": current["at"],
                "version": current["version"], "dispatch_owner": "CronService",
                "notification_delivery_claimed": False}

    def _reminder(self, db, payload, action):
        kind = action.rsplit(".", 1)[-1]
        keys = {"client_request_id", "event_id", "event_version", "reminder_version"}
        if kind == "snooze":
            keys.add("until")
        self._exact(payload, keys)
        event = self.store.get(db, NAMESPACE, "event", payload["event_id"])
        require(event["version"] == payload["event_version"],
                "事件版本变化，须重新核查")
        require(event["state"] != "CANCELED",
                "源事件已取消，不能再改变提醒")
        previous_row = db.execute(
            "SELECT body FROM objects WHERE namespace=? AND kind='reminder' AND id=?",
            (NAMESPACE, event["event_id"]),
        ).fetchone()
        previous = json.loads(previous_row[0]) if previous_row else None
        previous_version = previous.get("version", "0") if previous else "0"
        require(previous_version == payload["reminder_version"],
                "提醒版本冲突，须先重新读取")
        require(not previous or previous["state"] != "CLOSED",
                "已关闭提醒不可重新开启")
        state = {"ack": "ACKNOWLEDGED", "snooze": "SNOOZED", "close": "CLOSED"}[kind]
        bound = {"event_id": event["event_id"], "state": state}
        if kind == "snooze":
            until = _aware_due(payload["until"], "Asia/Shanghai")
            clock = self.store.get(db, NAMESPACE, "clock", "current")
            before = datetime.fromisoformat(clock["at"])
            require(until > before, "暂缓期限必须晚于当前业务时钟", web.HTTPBadRequest)
            require((until - before).total_seconds() <= 31 * 86400,
                    "单次暂缓不能超过31天", web.HTTPBadRequest)
            bound["until"] = payload["until"]
        auth_id = self._authorize(
            db, "reminder." + kind,
            {"event_id": event["event_id"], "event_version": event["version"],
             "reminder_version": previous_version,
             **({"until": bound["until"]} if kind == "snooze" else {})},
            event["event_id"], event["version"],
        )
        current = self.store.control_reminder(db, NAMESPACE, bound)
        current["version"] = str(int(previous_version) + 1)
        self.store.put(db, NAMESPACE, "reminder", event["event_id"], current)
        return {
            "source_type": "SIMULATED", "event_id": event["event_id"],
            "state": state, "version": current["version"],
            "until": current.get("until"),
            "event_version": event["version"], "authorization_id": auth_id,
        }
