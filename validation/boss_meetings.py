import json
from datetime import datetime, timedelta

from aiohttp import web

from business import checksum, now, require
from boss_source_access import require_current_simulated_source

NS = "ui-check"


def _object(db, kind, identifier):
    row = db.execute("SELECT body FROM objects WHERE namespace=? AND kind=? AND id=?", (NS, kind, identifier)).fetchone()
    return json.loads(row[0]) if row else None


def _rows(db, kind):
    return [json.loads(row[0]) for row in db.execute("SELECT body FROM objects WHERE namespace=? AND kind=? ORDER BY id", (NS, kind)).fetchall()]


def meeting_materials(db, data):
    initial = data["meeting"]
    current = _object(db, "meeting", initial["meeting_id"])
    if current is None:
        return data
    require(current["owner_id"] == data["owner_id"] and current["meeting_id"] == initial["meeting_id"],
            "会议归属与当前执行空间不符", web.HTTPForbidden)
    return {**data, "meeting": current}


def _state(meeting):
    return meeting.get("state", "DRAFT")


class MeetingAPI:
    def __init__(self, store):
        from boss_command_api import BossCommandAPI
        self.store = store
        self.commands = BossCommandAPI(store)

    @staticmethod
    def _role(role):
        require(role in ("BOSS", "MAINTAINER"), "身份尚未认证", web.HTTPUnauthorized)
        require(role == "BOSS", "会议安排仅限本人访问", web.HTTPForbidden)

    def _data(self, db):
        self.store.active(db, NS)
        return meeting_materials(db, self.store.get(db, NS, "initial", "snapshot"))

    def _preview(self, db, data, details):
        private = _object(db, "private_calendar", data["private_calendar"]["calendar_id"])
        if private is None:
            private = {**data["private_calendar"], "version": "1", "status": "ACTIVE"}
        start, end = datetime.fromisoformat(details["starts_at"]), datetime.fromisoformat(details["ends_at"])
        private_context = {key: private[key] for key in ("calendar_id", "version", "status", "starts_at", "ends_at")}
        private_conflict = private["status"] == "ACTIVE" and start < datetime.fromisoformat(private["ends_at"]) and end > datetime.fromisoformat(private["starts_at"])
        trips = [{"travel_id": row["travel_id"], "version": row["version"], "current": row["current"]}
                 for row in _rows(db, "travel_plan") if row["status"] == "CONFIRMED"]
        overlapping = [row["travel_id"] for row in trips
                       if start < datetime.fromisoformat(row["current"]["ends_at"]) + timedelta(minutes=row["current"]["buffer_minutes"])
                       and end > datetime.fromisoformat(row["current"]["starts_at"]) - timedelta(minutes=row["current"]["buffer_minutes"])]
        sources = []
        for ref in details["source_refs"]:
            document = _object(db, "document", ref["source_id"])
            sources.append({"source_id": ref["source_id"], "version": document["version"] if document else None,
                            "withdrawn": document.get("withdrawn", False) if document else True,
                            "content_sha256": checksum(document) if document else None})
        impact = {"private_calendar": {"version": private["version"], "conflict": private_conflict, "private_body_exposed": False},
                  "overlapping_travel_ids": overlapping, "preparation_deadline_known": details["preparation_due_at"] is not None,
                  "requires_owner_acknowledgement": private_conflict or bool(overlapping), "external_attendance_verified": False}
        context = {"meeting": data["meeting"], "contacts": data["contacts"], "sources": sources,
                   "clock": self.store.get(db, NS, "clock", "current"), "private_calendar": private_context, "trips": trips}
        return impact, checksum({"details": details, "impact": impact, "context": context})

    def read(self, role):
        self._role(role)
        with self.store.connect() as db:
            db.execute("BEGIN")
            data = self._data(db)
            meeting = data["meeting"]
            draft = _object(db, "meeting_draft", meeting["meeting_id"])
            if draft:
                _, current_hash = self._preview(db, data, draft["details"])
                draft = {**draft, "review_current": draft["review_sha256"] == current_hash and draft["state"] == "DRAFT"}
            return {"source_type": "SIMULATED", "meeting": {"state": "DRAFT", "ends_at": None, "preparation_due_at": None, **meeting},
                    "draft": draft, "contacts": data["contacts"], "sources": [
                        {"source_id": row["source_id"], "version": row["version"], "withdrawn": row.get("withdrawn", False)}
                        for row in _rows(db, "document") if row.get("access_scope") == data["owner_id"]],
                    "revisions": [{"version": row["version"], "state": _state(row)} for row in _rows(db, "meeting_revision")],
                    "business_at": self.store.get(db, NS, "clock", "current")["at"], "invitation_sent": False}

    def execute(self, role, action, payload):
        self._role(role)
        require(action in ("draft.save", "confirm", "cancel", "held"), "未知会议操作", web.HTTPNotFound)
        require(isinstance(payload, dict), "会议输入必须为对象", web.HTTPBadRequest)
        operation = "boss.meeting." + action
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            data = self._data(db)
            key, digest, previous = self.commands._check_existing(db, operation, payload)
            if previous is not None:
                return previous
            if action == "draft.save":
                result = self._save(db, data, payload)
            elif action == "confirm":
                result = self._confirm(db, data, payload)
            else:
                result = self._finish(db, data, action, payload)
            self.commands._record(db, operation, payload, key, digest, result)
            return result

    def _clean(self, db, data, payload):
        from boss_command_api import _aware_due, _is_text
        require(_is_text(payload["purpose"], 1200), "会议目的缺少或超出长度", web.HTTPBadRequest)
        start = _aware_due(payload["starts_at"], payload["timezone"])
        end = _aware_due(payload["ends_at"], payload["timezone"])
        clock = datetime.fromisoformat(self.store.get(db, NS, "clock", "current")["at"])
        require(start >= clock and start < end and (end - start).total_seconds() <= 31 * 86400,
                "会议时间须晚于当前业务时间且具有有效结束时间", web.HTTPBadRequest)
        due = payload["preparation_due_at"]
        if due is not None:
            require(clock <= _aware_due(due, payload["timezone"]) <= start, "准备期限须位于当前时间和会议开始之间", web.HTTPBadRequest)
        participants = payload["participant_ids"]
        require(isinstance(participants, list) and 1 <= len(participants) <= 32 and all(isinstance(item, str) for item in participants)
                and len(set(participants)) == len(participants), "参会对象必须使用无重复的联系人标识", web.HTTPBadRequest)
        for identifier in participants:
            matches = [row for row in data["contacts"] if row["contact_id"] == identifier]
            require(len(matches) == 1, "参会对象无法唯一确定", web.HTTPBadRequest)
            person = matches[0]
            require(person["valid_from"] <= clock.date().isoformat() <= person["valid_until"]
                    and person["valid_from"] <= start.date().isoformat() <= person["valid_until"],
                    "参会对象职责在当前或会议日期无效", web.HTTPForbidden)
        refs = payload["source_refs"]
        require(isinstance(refs, list) and len(refs) <= 8, "会议材料数量超出范围", web.HTTPBadRequest)
        seen = set()
        for ref in refs:
            require(isinstance(ref, dict) and set(ref) == {"source_id", "version"} and isinstance(ref["source_id"], str)
                    and ref["source_id"] not in seen, "会议材料引用格式错误或重复", web.HTTPBadRequest)
            seen.add(ref["source_id"])
            document = self.commands._require_current_source(db, data, ref["source_id"])
            require_current_simulated_source(document, data["owner_id"], self.store.get(db, NS, "clock", "current")["at"])
            require(document["version"] == ref["version"], "会议材料版本已经变化")
        return {key: payload[key] for key in ("purpose", "starts_at", "ends_at", "timezone", "preparation_due_at", "participant_ids", "source_refs")}

    @staticmethod
    def _writable(meeting):
        require(_state(meeting) in ("DRAFT", "SCHEDULED"), "已结束的会议不能继续修改")

    def _save(self, db, data, payload):
        self.commands._exact(payload, {"client_request_id", "meeting_id", "meeting_version", "expected_version", "purpose",
                                       "starts_at", "ends_at", "timezone", "preparation_due_at", "participant_ids", "source_refs"})
        meeting = data["meeting"]
        self._writable(meeting)
        require(payload["meeting_id"] == meeting["meeting_id"] and payload["meeting_version"] == meeting["version"], "会议版本已经变化")
        previous = _object(db, "meeting_draft", meeting["meeting_id"])
        version = previous["version"] if previous else "0"
        require(payload["expected_version"] == version, "会议草稿版本已经变化")
        details = self._clean(db, data, payload)
        impact, review_hash = self._preview(db, data, details)
        record = {"meeting_id": meeting["meeting_id"], "meeting_version": meeting["version"], "version": str(int(version) + 1),
                  "state": "DRAFT", "details": details, "impact": impact, "review_sha256": review_hash, "saved_at": now()}
        if previous:
            self.store.put(db, NS, "meeting_draft_revision", meeting["meeting_id"] + ":v" + version, previous)
        self.store.put(db, NS, "meeting_draft", meeting["meeting_id"], record)
        return {key: record[key] for key in ("meeting_id", "meeting_version", "version", "state", "review_sha256")} | {
            "meeting_changed": False, "invitation_sent": False}

    def _write(self, db, current, updated):
        self.store.put(db, NS, "meeting_revision", current["meeting_id"] + ":v" + current["version"], current)
        self.store.put(db, NS, "meeting", current["meeting_id"], updated)
        return {"source_type": "SIMULATED", "meeting_id": updated["meeting_id"], "version": updated["version"],
                "state": updated["state"], "authorization_id": updated["authorization_id"], "invitation_sent": False,
                "external_calendar_updated": False, "independent_tasks_unchanged": True}

    def _confirm(self, db, data, payload):
        self.commands._exact(payload, {"client_request_id", "meeting_id", "meeting_version", "draft_version", "review_sha256", "acknowledge_conflict"})
        meeting = data["meeting"]
        self._writable(meeting)
        require(payload["meeting_id"] == meeting["meeting_id"] and payload["meeting_version"] == meeting["version"], "会议版本已经变化")
        draft = self.store.get(db, NS, "meeting_draft", meeting["meeting_id"])
        require(draft["state"] == "DRAFT" and draft["version"] == payload["draft_version"]
                and draft["meeting_version"] == meeting["version"], "会议草稿状态或版本已经变化")
        impact, review_hash = self._preview(db, data, draft["details"])
        require(review_hash == draft["review_sha256"] == payload["review_sha256"], "资料、安排或职责已经变化，需要重新核查")
        require(isinstance(payload["acknowledge_conflict"], bool), "冲突确认标记类型错误", web.HTTPBadRequest)
        require(not impact["requires_owner_acknowledgement"] or payload["acknowledge_conflict"], "会议与当前安排存在冲突，需要本人确认")
        details = self._clean(db, data, draft["details"])
        authorization = self.commands._authorize(db, "meeting.confirm", {"draft_version": draft["version"], "review_sha256": review_hash}, meeting["meeting_id"], meeting["version"])
        updated = {**meeting, **details, "version": str(int(meeting["version"]) + 1), "state": "SCHEDULED",
                   "material_ids": [ref["source_id"] for ref in details["source_refs"]] + [item for item in meeting["material_ids"] if item == data["event"]["event_id"]],
                   "authorization_id": authorization, "updated_at": now(), "external_attendance_verified": False}
        result = self._write(db, meeting, updated)
        self.store.put(db, NS, "meeting_draft", meeting["meeting_id"], {**draft, "state": "CONFIRMED", "confirmed_meeting_version": updated["version"]})
        return result

    def _finish(self, db, data, action, payload):
        from boss_command_api import _is_text
        self.commands._exact(payload, {"client_request_id", "meeting_id", "expected_version", "reason"})
        meeting = data["meeting"]
        self._writable(meeting)
        require(payload["meeting_id"] == meeting["meeting_id"] and payload["expected_version"] == meeting["version"], "会议版本已经变化")
        require(_is_text(payload["reason"], 1200), "必须明确本次本人决定依据", web.HTTPBadRequest)
        if action == "held":
            require(_state(meeting) == "SCHEDULED" and datetime.fromisoformat(self.store.get(db, NS, "clock", "current")["at"]) >= datetime.fromisoformat(meeting["starts_at"]),
                    "只有已安排且开始时间已经到达的会议可以确认举行")
        authorization = self.commands._authorize(db, "meeting." + action, {"reason_sha256": checksum(payload["reason"])}, meeting["meeting_id"], meeting["version"])
        updated = {**meeting, "version": str(int(meeting["version"]) + 1), "state": "HELD" if action == "held" else "CANCELED",
                   "authorization_id": authorization, "decision_reason": payload["reason"], "updated_at": now()}
        return self._write(db, meeting, updated)
