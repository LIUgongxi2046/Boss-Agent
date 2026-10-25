import json

from aiohttp import web

from business import checksum, now, require, validate as validate_business
from boss_alert_policy import GENERATOR, get, items, material, owner_role, validate
from boss_alert_rules import commands_for, scope

ACTIONS = {"ack": "Decision", "snooze": "Snooze", "close": "Decision", "meeting.link": "MeetingLink", "assignment.create": "Assignment"}


class BusinessAlertsAPI:
    def __init__(self, store):
        self.store = store
        self.commands = commands_for(store)

    def read(self, role, event_id=None):
        owner_role(role)
        if event_id is not None:
            validate("Id", event_id)
        with self.store.connect() as db:
            db.execute("BEGIN")
            return self.project_in_transaction(role, db, event_id)

    def project_in_transaction(self, role, db, event_id=None):
        owner_role(role)
        if event_id is not None:
            validate("Id", event_id)
        return self._project(db, event_id)

    def _project(self, db, event_id):
        context = scope(db)
        ns = context["namespace"]
        data = self.store.get(db, ns, "initial", "snapshot")
        events = [self.store.get(db, ns, "event", event_id)] if event_id else [json.loads(row[0]) for row in db.execute(
            "SELECT body FROM objects WHERE namespace=? AND kind='event' AND json_extract(body,'$.generated_by')=? AND json_extract(body,'$.owner_id')=? ORDER BY id", (ns, GENERATOR, context["owner_id"])).fetchall()]
        views = []
        for event in events:
            view = material(self.store, db, ns, data, event)
            for field, kind in (("dispatch_history", "dispatch_history"), ("recovery_history", "business_alert_recovery"),
                                ("actions", "business_alert_action"), ("meeting_links", "notification_meeting_link"), ("assignment_references", "notification_assignment_reference")):
                view[field] = [row for row in items(db, ns, kind) if row["event_id"] == event["event_id"]]
            views.append(view)
        return validate("Read", {"source_type": "SIMULATED", "business_clock": self.store.get(db, ns, "clock", "current")["at"], "items": views,
            "coverage_state": "PARTIAL" if views else "UNAVAILABLE", "missing_sources": ["CURRENT_APPROVED_SIMULATION_ONLY"], "execution_owner": "CronService"})

    def execute(self, role, action, payload):
        owner_role(role)
        require(action in ACTIONS, "未知经营提醒动作", web.HTTPNotFound)
        validate(ACTIONS[action], payload)
        operation = "boss.alert." + action
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            context = scope(db)
            ns = context["namespace"]
            key, digest, previous = self.commands._check_existing(db, operation, payload)
            if previous is not None:
                return previous
            require(db.execute("SELECT 1 FROM idempotency WHERE namespace<>? AND operation=? AND key=?", (ns, operation, key)).fetchone() is None,
                    "原提醒请求属于其他执行空间")
            data = self.store.get(db, ns, "initial", "snapshot")
            event = self.store.get(db, ns, "event", payload["event_id"])
            view = material(self.store, db, ns, data, event)
            reminder = view["reminder"]
            require(view["event_version"] == payload["event_version"] and view["reminder_version"] == payload["expected_version"]
                    and view["review_sha256"] == payload["review_sha256"], "提醒、规则、来源或当前确认范围已变化")
            require(reminder is not None and reminder["state"] != "CLOSED", "当前没有可处理的开放提醒")
            require(action == "close" or view["adoption_state"] == "CURRENT" and event["state"] != "CANCELED", "当前来源或事件不能用于此决定", web.HTTPConflict)
            bound = {field: value for field, value in payload.items() if field != "client_request_id"}
            if action == "snooze":
                from boss_command_api import _aware_due
                until = _aware_due(payload["until"], "Asia/Shanghai")
                clock = self.store.get(db, ns, "clock", "current")["at"]
                from datetime import datetime
                require(0 < (until - datetime.fromisoformat(clock)).total_seconds() <= 31 * 86400, "暂缓时间必须晚于业务时钟且不超过31天", web.HTTPBadRequest)
            if action == "meeting.link":
                require(payload["meeting_id"] == view["meeting_reference"]["meeting_id"] and payload["meeting_version"] == view["meeting_reference"]["version"], "当前会议或版本已变化")
                require(view["meeting_reference"]["adoption_state"] == "CURRENT", "当前会议材料需要重新核查")
                from boss_meetings import meeting_materials
                meeting = meeting_materials(db, data)["meeting"]
                require(meeting.get("status", "DRAFT") not in ("HELD", "CANCELED"), "当前会议不可加入经营事项")
            auth = self.commands._authorize(db, "business_alert." + action, bound, event["event_id"], event["version"])
            version = str(int(reminder["version"]) + 1)
            result = {"source_type": "SIMULATED", "event_id": event["event_id"], "event_version": event["version"], "version": version,
                "action": action, "authorization_id": auth, "external_message_sent": False}
            updated = {**reminder, "version": version, "last_action_authorization_id": auth}
            if action in ("ack", "snooze", "close"):
                updated.update(state={"ack": "ACKNOWLEDGED", "snooze": "SNOOZED", "close": "CLOSED"}[action],
                    until=payload["until"] if action == "snooze" else None, authorization_id=auth, event_version=event["version"])
            elif action == "meeting.link":
                identifier = event["event_id"] + ":" + event["version"] + ":" + payload["meeting_id"] + ":" + payload["meeting_version"]
                require(get(db, ns, "notification_meeting_link", identifier) is None, "此事项已经关联当前会议")
                link = {"event_id": event["event_id"], "event_version": event["version"], "meeting_id": payload["meeting_id"],
                    "meeting_version": payload["meeting_version"], "authorization_id": auth, "source_refs": event["source_refs"], "created_at": now()}
                self.store.put(db, ns, "notification_meeting_link", identifier, link)
                result.update(meeting_id=payload["meeting_id"], meeting_version=payload["meeting_version"], meeting_arranged=False)
            else:
                require(bool(payload["purpose"].strip()) and all(value.strip() for value in payload["evidence_requirements"]), "交办目的与产物不可为空白", web.HTTPBadRequest)
                require(payload["coordinator_id"] == event["facts"]["handler_id"], "交办负责人必须匹配当前事件处理人", web.HTTPConflict)
                reference_id = event["event_id"] + ":" + str(view["episode"])
                require(get(db, ns, "notification_assignment_reference", reference_id) is None, "本次提醒已经保存关联交办，需要打开原任务")
                from boss_command_api import _data_envelope
                assignment = {field: payload[field] for field in ("purpose", "coordinator_id", "due_at", "timezone", "evidence_requirements")}
                assignment.update(related_meeting_id=None, related_event_ids=[event["event_id"]], source_refs=[ref["source_id"] for ref in event["source_refs"]], content_version="1")
                assignment_auth = self.commands._authorize(db, "create_assignment", assignment, "new-assignment", "1")
                tool_input = {**assignment, "authorization_id": assignment_auth, "idempotency_key": key, "envelope": _data_envelope(data, key)}
                validate_business("assignment_input", tool_input)
                saved = self.store.create_assignment(db, ns, data, tool_input)
                self.store.put(db, ns, "notification_assignment_reference", reference_id, {"event_id": event["event_id"], "event_version": event["version"], "episode": view["episode"],
                    "task_id": saved["task_id"], "task_version": saved["version"], "authorization_id": assignment_auth, "reminder_authorization_id": auth, "created_at": now()})
                result.update(task_id=saved["task_id"], task_version=saved["version"], task_status=saved["status"], assignment_authorization_id=assignment_auth)
            self.store.put(db, ns, "reminder_revision", event["event_id"] + ":" + reminder["version"], reminder)
            self.store.put(db, ns, "reminder", event["event_id"], updated)
            result.update(state=updated["state"], until=updated.get("until"))
            self.store.put(db, ns, "business_alert_action", operation + ":" + key, {"event_id": event["event_id"], "event_version": event["version"],
                "action": action, "authorization_id": auth, "previous_version": reminder["version"], "version": version, "business_at": self.store.get(db, ns, "clock", "current")["at"],
                "recorded_at": now(), "payload_sha256": checksum(bound)})
            validate("ActionResult", result)
            self.commands._record(db, operation, payload, key, digest, result)
            return result

    def receipt(self, role, action, client_request_id):
        owner_role(role)
        require(action in ACTIONS, "未知经营提醒动作", web.HTTPNotFound)
        validate("Id", client_request_id)
        operation = "boss.alert." + action
        with self.store.connect() as db:
            db.execute("BEGIN")
            ns = scope(db)["namespace"]
            row = db.execute("SELECT result FROM idempotency WHERE namespace=? AND operation=? AND key=?", (ns, operation, client_request_id)).fetchone()
            return validate("Receipt", {"action": operation, "client_request_id": client_request_id, "outcome": "RECORDED" if row else "NOT_FOUND_IN_CURRENT_STORE", "result": json.loads(row[0]) if row else None})
