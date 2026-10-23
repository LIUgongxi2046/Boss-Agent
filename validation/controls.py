import json
import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from aiohttp import web
from jsonschema import Draft202012Validator, FormatChecker

from business import Store, checksum, encode, initial_materials, now, require
from boss_source_access import require_current_simulated_source
from boss_source_policy import source_validity


TEXT = {"type": "string", "minLength": 1}
TIME = {"type": "string", "format": "date-time"}
FIELDS = {
    "feedback": ({"task_id": TEXT, "task_version": TEXT, "author_contact_id": TEXT, "kind": {"enum": ["PROGRESS", "EXTENSION_REQUEST", "RESULT_SUBMITTED"]}, "content": TEXT, "proposed_due_at": TIME, "evidence_refs": {"type": "array", "minItems": 0, "maxItems": 16, "items": TEXT}}, ["task_id", "task_version", "author_contact_id", "kind", "content"]),
    "decide": ({"authorization_id": TEXT, "task_id": TEXT, "task_version": TEXT, "feedback_id": TEXT, "due_at": TIME}, ["authorization_id", "task_id", "task_version", "feedback_id"]),
    "revoke": ({"authorization_id": TEXT}, ["authorization_id"]),
    "withdraw": ({"source_id": TEXT, "version": TEXT}, ["source_id", "version"]),
    "search": ({"query": TEXT}, ["query"]),
    "private_calendar": ({}, []),
    "reference_status": ({"task_id": TEXT}, ["task_id"]),
    "clock": ({"at": TIME}, ["at"]),
    "rules": ({"version": TEXT, "cooldown_seconds": {"type": "integer", "minimum": 0}, "quiet_start": {"type": "integer", "minimum": 0, "maximum": 23}, "quiet_end": {"type": "integer", "minimum": 0, "maximum": 23}, "timezone": {"const": "Asia/Shanghai"}, "important_escalation": {"type": "boolean"}}, ["version", "cooldown_seconds", "quiet_start", "quiet_end", "timezone", "important_escalation"]),
    "event": ({"event_id": TEXT, "version": TEXT, "state": {"enum": ["OPEN", "RECOVERED", "CANCELED"]}, "impact": {"enum": ["NORMAL", "IMPORTANT"]}, "due_at": TIME, "task_id": TEXT}, ["event_id", "version", "state", "impact", "due_at"]),
    "reminder": ({"event_id": TEXT, "state": {"enum": ["SNOOZED", "CLOSED", "ACKNOWLEDGED"]}, "until": TIME}, ["event_id", "state"]),
    "reset": ({"namespace": TEXT}, ["namespace"]),
}


class ControlStore(Store):
    def control(self, ns, action, p):
        properties, required = FIELDS[action]
        errors = list(Draft202012Validator({"type": "object", "properties": properties, "required": required, "additionalProperties": False}, format_checker=FormatChecker()).iter_errors(p))
        require(not errors, "控制参数不符合 Schema", web.HTTPBadRequest)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self.active(db, ns)
            result = getattr(self, "control_" + action)(db, ns, p)
            audit_result = {"calendar_id": result["calendar_id"], "visibility": result["visibility"]} if action == "private_calendar" else result
            audit_input = p
            if action == "feedback":
                audit_input = {k: p[k] for k in ("task_id", "task_version", "author_contact_id", "kind")}
                audit_result = {"feedback_id": result["feedback"]["feedback_id"], "task_id": result["task"]["task_id"],
                                "task_version": result["task"]["version"], "historical_only": result["feedback"].get("historical_only", False)}
            elif action == "search":
                audit_input = {"query_sha256": checksum(p["query"])}
                audit_result = {"source_ids": [row["source_id"] for row in result["results"]],
                                "result_count": len(result["results"])}
            elif action == "decide":
                audit_result = {key: result[key] for key in ("task_id", "version", "status", "due_at")}
            db.execute("INSERT INTO audit(namespace,operation,input,output,created_at) VALUES(?,?,?,?,?)", (ns, action, encode(audit_input), encode(audit_result), now()))
            return result

    def control_feedback(self, db, ns, p):
        task = self.get(db, ns, "task", p["task_id"])
        require(task["version"] == p["task_version"], "任务版本冲突")
        require(p["author_contact_id"] == task["coordinator_id"], "反馈作者不符", web.HTTPForbidden)
        require(p["kind"] in {"PROGRESS", "EXTENSION_REQUEST", "RESULT_SUBMITTED"}, "反馈类型无效", web.HTTPBadRequest)
        require(task["status"] != "COMPLETED_CONFIRMED", "已确认完成的任务不接受进度变更")
        historical_only = task["status"] == "CANCELED"
        feedback_id = str(uuid.uuid4())
        feedback = {**p, "feedback_id": feedback_id, "source_type": "SIMULATED", "submitted_at": now(), "historical_only": historical_only}
        self.put(db, ns, "feedback", feedback_id, feedback)
        task["feedback_ids"].append(feedback_id)
        task["version"] = str(int(task["version"]) + 1)
        if p["kind"] == "PROGRESS" and not historical_only:
            task["status"] = "IN_PROGRESS"
        if p["kind"] == "RESULT_SUBMITTED":
            require(p.get("evidence_refs"), "结果必须包含证据", web.HTTPBadRequest)
            if not historical_only:
                task["status"] = "RESULT_SUBMITTED"
        self.put(db, ns, "task", p["task_id"], task)
        return {"feedback": feedback, "task": task}

    def control_decide(self, db, ns, p):
        auth = self.get(db, ns, "authorization", p["authorization_id"])
        content = {key: value for key, value in p.items() if key != "authorization_id"}
        require(not auth["revoked"] and auth["payload"] == content and datetime.fromisoformat(auth["valid_until"]) > datetime.fromisoformat(now()), "当前授权无效", web.HTTPForbidden)
        task = self.get(db, ns, "task", p["task_id"])
        require(task["version"] == p["task_version"], "任务版本冲突")
        if auth["action"] == "extend_assignment":
            feedback = self.get(db, ns, "feedback", p["feedback_id"])
            require(feedback["kind"] == "EXTENSION_REQUEST" and feedback["task_id"] == p["task_id"], "延期依据不符")
            require(datetime.fromisoformat(p["due_at"]).tzinfo is not None, "期限必须包含时区", web.HTTPBadRequest)
            task["due_at"] = p["due_at"]
        elif auth["action"] == "complete_assignment":
            feedback = self.get(db, ns, "feedback", p["feedback_id"])
            require(task["status"] == "RESULT_SUBMITTED" and feedback["task_id"] == p["task_id"] and feedback["kind"] == "RESULT_SUBMITTED" and feedback["evidence_refs"], "当前结果证据不完整")
            data = self.get(db, ns, "initial", "snapshot")
            clock = self.get(db, ns, "clock", "current")["at"]
            for source_id in set(task["source_refs"]) | set(feedback["evidence_refs"]):
                document = require_current_simulated_source(self.get(db, ns, "document", source_id), data["owner_id"], clock)
                if source_id in task.get("source_versions", {}):
                    require(document["version"] == task["source_versions"][source_id], "完成依据的来源版本已经变化")
            task["status"] = "COMPLETED_CONFIRMED"
            task["completion_authorization_id"] = p["authorization_id"]
        else:
            raise web.HTTPForbidden(text="当前授权不支持此决定")
        task["version"] = str(int(task["version"]) + 1)
        self.put(db, ns, "task", p["task_id"], task)
        return task

    def control_revoke(self, db, ns, p):
        auth = self.get(db, ns, "authorization", p["authorization_id"])
        auth.update(revoked=True, revoked_at=now())
        self.put(db, ns, "authorization", p["authorization_id"], auth)
        return {"authorization_id": p["authorization_id"], "revoked_at": auth["revoked_at"]}

    def control_withdraw(self, db, ns, p):
        document = self.get(db, ns, "document", p["source_id"])
        require(document["version"] == p["version"], "资料版本冲突")
        document.update(withdrawn=True, withdrawn_at=now())
        self.put(db, ns, "document", p["source_id"], document)
        db.execute("DELETE FROM knowledge WHERE namespace=? AND source_id=?", (ns, p["source_id"]))
        return {"source_id": p["source_id"], "withdrawn": True, "derived_summaries": []}

    def control_search(self, db, ns, p):
        rows = db.execute("SELECT source_id,content FROM knowledge WHERE namespace=? AND knowledge MATCH ?", (ns, p["query"])).fetchall()
        data = self.get(db, ns, "initial", "snapshot")
        clock = self.get(db, ns, "clock", "current")["at"]
        results = []
        for source_id, indexed in rows:
            document = self.get(db, ns, "document", source_id)
            if (document.get("source_type") == "SIMULATED" and document.get("access_scope") == data["owner_id"]
                    and source_validity(document, clock) == "VALID"):
                require(indexed == document["content"], "资料索引与当前原文不一致，需要重新摄取")
                results.append({"source_id": source_id, "content": document["content"]})
        return {"results": results}

    def control_private_calendar(self, db, ns, p):
        return self.get(db, ns, "initial", "snapshot")["private_calendar"]

    def control_reference_status(self, db, ns, p):
        task = self.get(db, ns, "task", p["task_id"])
        data = self.get(db, ns, "initial", "snapshot")
        clock = self.get(db, ns, "clock", "current")["at"]
        sources = []
        for source_id in task["source_refs"]:
            document = self.get(db, ns, "document", source_id)
            require(document.get("source_type") == "SIMULATED" and document.get("access_scope") == data["owner_id"], "资料不属于当前本人获准范围", web.HTTPForbidden)
            state = source_validity(document, clock)
            sources.append({"source_id": source_id, "version": document["version"], "state": "ACTIVE" if state == "VALID" else state})
        return {"task_id": task["task_id"], "sources": sources}

    def control_clock(self, db, ns, p):
        old = self.get(db, ns, "clock", "current")
        value = datetime.fromisoformat(p["at"])
        require(value.tzinfo is not None and value >= datetime.fromisoformat(old["at"]), "业务时钟必须按含时区时间递增", web.HTTPBadRequest)
        current = {"at": p["at"], "version": str(int(old["version"]) + 1)}
        self.put(db, ns, "clock", "current", current)
        return current

    def control_rules(self, db, ns, p):
        require(p["cooldown_seconds"] >= 0 and p["quiet_start"] in range(24) and p["quiet_end"] in range(24), "提醒规则无效", web.HTTPBadRequest)
        ZoneInfo(p["timezone"])
        self.put(db, ns, "rules", "current", p)
        return p

    def control_event(self, db, ns, p):
        require(p["state"] in {"OPEN", "RECOVERED", "CANCELED"}, "事件状态无效", web.HTTPBadRequest)
        require(p["impact"] in {"NORMAL", "IMPORTANT"}, "事件影响无效", web.HTTPBadRequest)
        require(p["version"].isdecimal() and 1 <= int(p["version"]) <= 99999999, "事件版本必须为有效十进制字符串", web.HTTPBadRequest)
        row = db.execute("SELECT body FROM objects WHERE namespace=? AND kind='event' AND id=?", (ns, p["event_id"])).fetchone()
        event = dict(p)
        if row:
            previous = json.loads(row[0])
            if previous["version"] == p["version"]:
                require(all(previous.get(key) == value for key, value in p.items()), "相同事件版本不能更改内容")
                return previous
            require(int(p["version"]) == int(previous["version"]) + 1, "事件版本必须基于当前版本递增")
            if previous.get("owner_plan_id"):
                event["owner_plan_id"] = previous["owner_plan_id"]
        self.put(db, ns, "event", p["event_id"], event)
        return event

    def control_reminder(self, db, ns, p):
        event = self.get(db, ns, "event", p["event_id"])
        require(p["state"] in {"SNOOZED", "CLOSED", "ACKNOWLEDGED"}, "提醒状态无效", web.HTTPBadRequest)
        current = {"state": p["state"], "until": p.get("until"), "event_id": event["event_id"]}
        if p["state"] == "SNOOZED":
            require("until" in p, "暂缓时间缺少", web.HTTPBadRequest)
            require(datetime.fromisoformat(p["until"]) > datetime.fromisoformat(self.get(db, ns, "clock", "current")["at"]), "暂缓时间必须晚于当前业务时间", web.HTTPBadRequest)
        self.put(db, ns, "reminder", p["event_id"], current)
        return current

    def control_reset(self, db, ns, p):
        require(db.execute("SELECT 1 FROM spaces WHERE namespace=?", (p["namespace"],)).fetchone() is None, "目标执行空间已经存在")
        data = initial_materials()
        self.initialize_in_transaction(db, p["namespace"], data)
        db.execute("UPDATE spaces SET active=0 WHERE namespace=?", (ns,))
        return {"namespace": p["namespace"], "snapshot_sha256": checksum(data)}

    def dispatch_due(self, ns):
        """Scheduled execution owns a fresh transaction, unchanged for CronService."""
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            return self.dispatch_due_in_transaction(db, ns)

    def dispatch_due_in_transaction(self, db, ns, only_event_id=None):
        """Same canonical dispatcher for Cron and an authorized manual test event.

        Caller must own BEGIN IMMEDIATE; no external messaging occurs here.
        """
        self.active(db, ns)
        schedule = self.get(db, ns, "schedule", "current")
        rules_row = db.execute("SELECT body FROM objects WHERE namespace=? AND kind='rules' AND id='current'", (ns,)).fetchone()
        if rules_row is None:
            return []
        rules = json.loads(rules_row[0])
        clock = datetime.fromisoformat(self.get(db, ns, "clock", "current")["at"])
        local = clock.astimezone(ZoneInfo(rules["timezone"]))
        from boss_owner_preferences import owner_notification_suppression
        data = self.get(db, ns, "initial", "snapshot")
        results = []
        for row in db.execute("SELECT body FROM objects WHERE namespace=? AND kind='event'", (ns,)).fetchall():
            event = json.loads(row[0])
            if only_event_id is not None and event["event_id"] != only_event_id:
                continue
            if datetime.fromisoformat(event["due_at"]) > clock:
                continue
            previous_row = db.execute("SELECT body FROM objects WHERE namespace=? AND kind='delivery' AND id=?", (ns, event["event_id"])).fetchone()
            previous = json.loads(previous_row[0]) if previous_row else None
            reminder_row = db.execute("SELECT body FROM objects WHERE namespace=? AND kind='reminder' AND id=?", (ns, event["event_id"])).fetchone()
            reminder = json.loads(reminder_row[0]) if reminder_row else None
            reason = None
            owner_notice_version = None
            from boss_owner_plans import suppression
            plan_reason = suppression(self, db, ns, event, clock)
            if not schedule["enabled"] or schedule["canceled"]:
                reason = "PLAN_PAUSED_OR_CANCELED"
            elif plan_reason:
                reason = plan_reason
            elif event["state"] == "CANCELED":
                reason = "SOURCE_CANCELED"
            elif reminder and reminder["state"] == "CLOSED":
                reason = "BOSS_CLOSED"
            elif reminder and reminder["state"] == "SNOOZED" and datetime.fromisoformat(reminder["until"]) > clock:
                reason = "BOSS_SNOOZED"
            elif event.get("task_id") and self.get(db, ns, "task", event["task_id"])["status"] in {"COMPLETED_CONFIRMED", "CANCELED"}:
                reason = "TASK_ENDED"
            elif previous and previous["event_version"] == event["version"]:
                reason = "DUPLICATE_EVENT"
            else:
                owner_reason, owner_notice_version = owner_notification_suppression(
                    db, data, clock, event, rules,
                )
                if owner_reason:
                    reason = owner_reason
                else:
                    start, end = rules["quiet_start"], rules["quiet_end"]
                    quiet = (local.hour >= start or local.hour < end) if start > end else start <= local.hour < end
                    escalation = rules["important_escalation"] and event["impact"] == "IMPORTANT"
                    if quiet and not escalation:
                        reason = "QUIET_HOURS"
                    elif previous and (clock - datetime.fromisoformat(previous["delivered_at"])).total_seconds() < rules["cooldown_seconds"] and event["state"] != "RECOVERED" and not escalation:
                        reason = "COOLDOWN"
            result = {"event_id": event["event_id"], "event_version": event["version"], "state": "SUPPRESSED" if reason else "DELIVERED", "reason": reason, "rule_version": rules["version"], "schedule_version": schedule["version"], "business_at": clock.isoformat()}
            if event.get("owner_plan_id"):
                result["owner_plan_id"] = event["owner_plan_id"]
            if owner_notice_version is not None:
                result["owner_notice_version"] = owner_notice_version
            self.put(db, ns, "dispatch", event["event_id"], result)
            if reason is None:
                delivery = {**result, "delivered_at": clock.isoformat(), "source_type": "SIMULATED"}
                self.put(db, ns, "delivery", event["event_id"], delivery)
                self.put(db, ns, "notification", event["event_id"] + ":" + event["version"], delivery)
            results.append(result)
        return results
