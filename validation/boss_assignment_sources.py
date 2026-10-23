import json

from aiohttp import web
from jsonschema import Draft202012Validator

from business import ROOT, checksum, now, require
from boss_source_access import require_current_simulated_source
from boss_source_policy import source_validity

NS = "ui-check"
ACTION = "boss.assignment.sources.confirm"
REVIEW_STATES = {"OPEN", "WAITING_FEEDBACK", "IN_PROGRESS", "WAITING_MATERIAL", "RESULT_SUBMITTED"}
SCHEMA = json.loads((ROOT.parent / "specs/assignment-source-review.schema.json").read_text())
INPUT = Draft202012Validator({**SCHEMA, "$ref": "#/$defs/ConfirmationInput"})


def _optional(db, kind, identifier):
    row = db.execute("SELECT body FROM objects WHERE namespace=? AND kind=? AND id=?", (NS, kind, identifier)).fetchone()
    return json.loads(row[0]) if row is not None else None


class AssignmentSourcesAPI:
    def __init__(self, store):
        from boss_command_api import BossCommandAPI
        self.store = store
        self.commands = BossCommandAPI(store)

    @staticmethod
    def _role(role):
        require(role is not None, "本人身份尚未认证", web.HTTPUnauthorized)
        require(role == "BOSS", "交办来源仅限本人核查", web.HTTPForbidden)

    def _context(self, db, task_id):
        self.store.active(db, NS)
        data = self.store.get(db, NS, "initial", "snapshot")
        task = self.store.get(db, NS, "task", task_id)
        require(task["task_id"] == task_id and task["execution_namespace"] == NS, "交办不属于当前执行空间", web.HTTPForbidden)
        if "owner_id" in task:
            require(task["owner_id"] == data["owner_id"], "交办不属于当前本人", web.HTTPForbidden)
        binding = _optional(db, "assignment_source_binding", task_id)
        if binding is not None:
            require(binding["task_id"] == task_id and binding["owner_id"] == data["owner_id"]
                    and binding["dataset_id"] == data["dataset_id"] and binding["dataset_version"] == data["dataset_version"],
                    "交办来源绑定不属于当前范围", web.HTTPForbidden)
            require(isinstance(binding["source_versions"], dict) and isinstance(binding["source_fingerprints"], dict),
                    "交办来源绑定字段无效")
        source_ids = set(task["source_refs"])
        require(source_ids and len(source_ids) == len(task["source_refs"]), "交办来源缺少或重复")
        if task.get("origin_source_id"):
            source_ids.add(task["origin_source_id"])
        documents = {identifier: _optional(db, "document", identifier) for identifier in sorted(source_ids)}
        clock = self.store.get(db, NS, "clock", "current")
        return data, task, binding, documents, clock

    @staticmethod
    def _state(identifier, document, data, clock):
        if document is None:
            return "MISSING"
        if (document.get("source_id") != identifier or document.get("access_scope") != data["owner_id"]
                or document.get("source_type") != "SIMULATED"):
            return "FORBIDDEN"
        return source_validity(document, clock["at"])

    def _result_evidence(self, db, task, data, clock):
        if task["status"] != "RESULT_SUBMITTED":
            return None
        feedbacks = [self.store.get(db, NS, "feedback", identifier) for identifier in task["feedback_ids"]]
        results = [feedback for feedback in feedbacks if feedback["kind"] == "RESULT_SUBMITTED" and not feedback.get("historical_only")]
        require(results, "当前结果状态没有对应反馈记录")
        feedback = results[-1]
        versions, fingerprints = feedback.get("evidence_versions"), feedback.get("evidence_fingerprints")
        if not isinstance(versions, dict) or not isinstance(fingerprints, dict) or set(versions) != set(fingerprints) or set(versions) != set(feedback["evidence_refs"]):
            return False
        for identifier in feedback["evidence_refs"]:
            document = _optional(db, "document", identifier)
            if (self._state(identifier, document, data, clock) != "VALID" or versions[identifier] != document["version"]
                    or fingerprints[identifier] != checksum(document)):
                return False
        return True

    def _view(self, db, context):
        data, task, binding, documents, clock = context
        source_rows = []
        current = binding is not None
        versions = binding.get("source_versions", {}) if binding is not None else {}
        fingerprints = binding.get("source_fingerprints", {}) if binding is not None else {}
        current = current and set(versions) == set(fingerprints) == set(task["source_refs"])
        for identifier, document in documents.items():
            state = self._state(identifier, document, data, clock)
            origin = identifier == task.get("origin_source_id")
            origin_pin = binding.get("origin_source") if binding is not None and origin else None
            pinned = origin_pin["version"] if origin_pin is not None else versions.get(identifier)
            if state != "VALID":
                current = False
            elif identifier in task["source_refs"] and (versions.get(identifier) != document["version"] or fingerprints.get(identifier) != checksum(document)):
                current = False
            if origin:
                if document is None or origin_pin != {"source_id": identifier, "version": document["version"], "sha256": checksum(document)}:
                    current = False
            visible = state not in {"MISSING", "FORBIDDEN"}
            source_rows.append({"source_id": identifier, "pinned_version": pinned, "current_version": document["version"] if visible else None,
                "source_status": state, "excerpt": document.get("content", "")[:500] if state == "VALID" else None,
                **{field: document.get(field) if visible else None for field in ("published_at", "valid_from", "valid_until")},
                "is_minute_origin": origin})
        binding_state = "MISSING" if binding is None else "CURRENT" if current else "NEEDS_REVIEW"
        result_current = self._result_evidence(db, task, data, clock)
        history = [json.loads(row[0]) for row in db.execute("SELECT body FROM objects WHERE namespace=? AND kind='assignment_source_binding_revision' AND json_extract(body,'$.task_id')=? ORDER BY json_extract(body,'$.archived_at') DESC,id DESC", (NS, task["task_id"])).fetchall()]
        digest = checksum({"task": task, "binding": binding, "documents": documents, "clock": clock,
                           "owner_id": data["owner_id"], "dataset_id": data["dataset_id"], "dataset_version": data["dataset_version"]})
        return {"source_type": "SIMULATED", "task": {field: task[field] for field in ("task_id", "version", "status", "purpose")},
            "binding_state": binding_state, "sources": source_rows, "review_sha256": digest, "business_at": clock["at"],
            "can_confirm": binding_state != "CURRENT" and task["status"] in REVIEW_STATES and all(row["source_status"] == "VALID" for row in source_rows),
            "result_evidence_current": result_current, "result_evidence_requires_resubmission": result_current is False,
            "history": [{field: revision[field] for field in ("before_task_version", "archived_at")}
                        | {"source_versions": revision["binding"]["source_versions"], "review_reason": revision["binding"].get("review_reason"),
                           "origin_source": {field: revision["binding"]["origin_source"][field] for field in ("source_id", "version")}
                           if "origin_source" in revision["binding"] else None} for revision in history],
            "confirmed_reason": binding.get("review_reason") if binding is not None else None, "read_at": now()}

    def read(self, role, task_id):
        self._role(role)
        require(isinstance(task_id, str) and 1 <= len(task_id) <= 128, "交办标识无效", web.HTTPBadRequest)
        with self.store.connect() as db:
            db.execute("BEGIN")
            return self.project_in_transaction(role, db, task_id)

    def project_in_transaction(self, role, db, task_id):
        self._role(role)
        return self._view(db, self._context(db, task_id))

    def execute(self, role, payload):
        self._role(role)
        require(isinstance(payload, dict), "来源确认输入必须为对象", web.HTTPBadRequest)
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self.store.active(db, NS)
            key, digest, previous = self.commands._check_existing(db, ACTION, payload)
            if previous is not None:
                return previous
            require(not list(INPUT.iter_errors(payload)) and payload["reason"].strip(), "来源确认输入不符合Schema", web.HTTPBadRequest)
            context = self._context(db, payload["task_id"])
            data, task, binding, documents, clock = context
            require(task["version"] == payload["task_version"], "交办版本已经变化")
            require(task["status"] in REVIEW_STATES, "当前交办状态不允许重新确认来源")
            for identifier, document in documents.items():
                require(document is not None, "来源资料不存在", web.HTTPNotFound)
                require(document.get("source_id") == identifier, "来源标识与引用不符", web.HTTPForbidden)
                require_current_simulated_source(document, data["owner_id"], clock["at"])
            view = self._view(db, context)
            require(view["review_sha256"] == payload["review_sha256"], "资料、任务或核查范围已经变化")
            require(view["can_confirm"], "当前来源已经核查，或者不满足确认条件")
            authorization_id = self.commands._authorize(db, "assignment.sources.confirm", {
                "task_id": task["task_id"], "task_version": task["version"], "review_sha256": payload["review_sha256"],
                "reason_sha256": checksum(payload["reason"].strip())}, task["task_id"], task["version"])
            if binding is not None:
                self.store.put(db, NS, "assignment_source_binding_revision", task["task_id"] + ":v" + task["version"], {
                    "task_id": task["task_id"], "before_task_version": task["version"], "binding": binding, "archived_at": now()})
            new_version = str(int(task["version"]) + 1)
            updated = {"task_id": task["task_id"], "owner_id": data["owner_id"], "dataset_id": data["dataset_id"], "dataset_version": data["dataset_version"],
                "source_versions": {identifier: documents[identifier]["version"] for identifier in task["source_refs"]},
                "source_fingerprints": {identifier: checksum(documents[identifier]) for identifier in task["source_refs"]},
                "confirmation_authorization_id": authorization_id, "confirmed_task_version": new_version, "confirmed_at": now(),
                "review_sha256": payload["review_sha256"], "review_reason": payload["reason"].strip(),
                "previous_binding_sha256": checksum(binding) if binding is not None else None}
            if task.get("origin_source_id"):
                origin = documents[task["origin_source_id"]]
                updated["origin_source"] = {"source_id": origin["source_id"], "version": origin["version"], "sha256": checksum(origin)}
            self.store.put(db, NS, "assignment_source_binding", task["task_id"], updated)
            task.update(version=new_version, source_versions=updated["source_versions"])
            self.store.put(db, NS, "task", task["task_id"], task)
            result = {"source_type": "SIMULATED", "task_id": task["task_id"], "version": new_version, "task_version": new_version,
                "status": task["status"], "authorization_id": authorization_id, "sources_reconfirmed": True,
                "business_status_unchanged": True, "message_sent": False, "review_sha256": payload["review_sha256"],
                "result_evidence_requires_resubmission": view["result_evidence_requires_resubmission"]}
            self.commands._record(db, ACTION, payload, key, digest, result)
            return result
