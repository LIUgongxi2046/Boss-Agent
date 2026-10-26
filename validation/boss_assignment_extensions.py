import json
from pathlib import Path

from aiohttp import web
from jsonschema import Draft202012Validator, FormatChecker

from business import require
from boss_execution_scope import NAMESPACE
from boss_command_api import BossCommandAPI
from boss_simulation_api import _context
from boss_task_reminders import current, synchronize_task_due

ACTION = "boss.assignment.extension.decide"
SCHEMA = json.loads((Path(__file__).resolve().parents[1] / "specs/assignment-extension.schema.json").read_text())


def validate(name, value):
    require(not list(Draft202012Validator({**SCHEMA, "$ref": "#/$defs/" + name}, format_checker=FormatChecker()).iter_errors(value)),
            "延期决定不符合Schema", web.HTTPBadRequest)
    return value


class AssignmentExtensionAPI:
    def __init__(self, store):
        self.store = store
        self.commands = BossCommandAPI(store)

    @staticmethod
    def _role(role):
        require(role in ("BOSS", "MAINTAINER"), "本人身份尚未认证", web.HTTPUnauthorized)
        require(role == "BOSS", "延期决定与正文仅限本人", web.HTTPForbidden)

    def _context(self, db):
        context = _context(db)
        require(context["namespace"] == NAMESPACE and context["owner_id"] == "boss-1", "延期决定不属于当前本人范围", web.HTTPForbidden)
        return context

    def execute(self, role, payload):
        self._role(role)
        validate("DecisionInput", payload)
        require(bool(payload["reason"].strip()), "本人决定需要明确理由", web.HTTPBadRequest)
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            context = self._context(db)
            ns = context["namespace"]
            key, digest, previous = self.commands._check_existing(db, ACTION, payload)
            if previous is not None:
                return previous
            require(db.execute("SELECT 1 FROM idempotency WHERE namespace<>? AND operation=? AND key=?", (ns, ACTION, key)).fetchone() is None,
                    "原决定请求属于其他空间")
            task = self.store.get(db, ns, "task", payload["task_id"])
            old_due_at = task["due_at"]
            bound = {field: payload[field] for field in ("task_id", "task_version", "feedback_id", "reason")}
            if payload["decision"] == "APPROVE":
                bound["due_at"] = payload["due_at"]
            action = "extend_assignment" if payload["decision"] == "APPROVE" else "reject_assignment_extension"
            # 仅供真实本人确认入口；模型工具不能调用本入口签发决定。
            authorization = self.commands._authorize(db, action, bound, payload["task_id"], payload["task_version"])
            updated = self.store.control_decide(db, ns, {**bound, "authorization_id": authorization})
            reminder = synchronize_task_due(self.store, db, updated, reason="AUTHORIZED_EXTEND") if payload["decision"] == "APPROVE" and current(db, updated["task_id"]) else None
            result = validate("Result", {"source_type": "SIMULATED", "task_id": updated["task_id"], "version": updated["version"], "status": updated["status"],
                "decision_id": payload["task_id"] + ":" + payload["feedback_id"], "feedback_id": payload["feedback_id"], "decision": payload["decision"],
                "old_due_at": old_due_at, "due_at": updated["due_at"], "authorization_id": authorization, "task_due_event": reminder})
            self.commands._record(db, ACTION, payload, key, digest, result)
            return result

    def read(self, role, task_id):
        self._role(role)
        validate("Id", task_id)
        with self.store.connect() as db:
            db.execute("BEGIN")
            ns = self._context(db)["namespace"]
            task = self.store.get(db, ns, "task", task_id)
            decisions = [json.loads(row[0]) for row in db.execute(
                "SELECT body FROM objects WHERE namespace=? AND kind='assignment_extension_decision' AND json_extract(body,'$.task_id')=? ORDER BY json_extract(body,'$.decided_at'),id", (ns, task_id)).fetchall()]
            return {"source_type": "SIMULATED", "task_id": task_id, "task_version": task["version"], "due_at": task["due_at"], "decisions": decisions}

    def receipt(self, role, client_request_id):
        self._role(role)
        validate("Id", client_request_id)
        with self.store.connect() as db:
            db.execute("BEGIN")
            ns = self._context(db)["namespace"]
            row = db.execute("SELECT result FROM idempotency WHERE namespace=? AND operation=? AND key=?", (ns, ACTION, client_request_id)).fetchone()
            return {"action": ACTION, "client_request_id": client_request_id, "outcome": "RECORDED" if row else "NOT_FOUND_IN_CURRENT_STORE",
                    "result": json.loads(row[0]) if row else None}
