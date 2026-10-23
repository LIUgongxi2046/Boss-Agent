import json
from datetime import datetime
from zoneinfo import ZoneInfo

from aiohttp import web

from business import checksum, require
from boss_command_api import BossCommandAPI
from boss_message_calendar import _calendar
from boss_owner_preferences import owner_profile
from boss_meetings import meeting_materials

NS = "ui-check"
FINAL = {"CANCELED", "COMPLETED_CONFIRMED"}


class TodayAPI:
    def __init__(self, store):
        self.store = store
        self.commands = BossCommandAPI(store)

    @staticmethod
    def _role(role):
        require(role in ("BOSS", "MAINTAINER"), "身份尚未认证", web.HTTPUnauthorized)
        require(role == "BOSS", "今日资料仅限本人读取", web.HTTPForbidden)

    @staticmethod
    def _rows(db, kind):
        return [json.loads(row[0]) for row in db.execute(
            "SELECT body FROM objects WHERE namespace=? AND kind=? ORDER BY id", (NS, kind),
        ).fetchall()]

    def _read(self, db):
        self.store.active(db, NS)
        data = meeting_materials(db, self.store.get(db, NS, "initial", "snapshot"))
        clock = self.store.get(db, NS, "clock", "current")
        zone = data["boss_profile"]["timezone"]
        date = datetime.fromisoformat(clock["at"]).astimezone(ZoneInfo(zone)).date().isoformat()
        items = []

        def append(kind, identifier, version, title, category, reason, page, due=None, important=False):
            items.append({"item_id": kind + ":" + identifier, "object_id": identifier,
                          "version": version, "title": title, "category": category,
                          "reason": reason, "page_id": page, "due_at": due,
                          "important": important, "source_refs": [{"kind": kind, "id": identifier, "version": version}]})

        tasks = self._rows(db, "task")
        historical = data.get("historical_task")
        historical_ids = set()
        if historical and not any(t["task_id"] == historical["task_id"] for t in tasks):
            tasks.append(historical)
            historical_ids.add(historical["task_id"])
        for task in tasks:
            if task["status"] in FINAL:
                continue
            is_historical = task["task_id"] in historical_ids
            append("historical_task" if is_historical else "task", task["task_id"], task["version"], task.get("purpose", "历史承诺"),
                   "DECIDE" if task["status"] == "RESULT_SUBMITTED" else "COORDINATE",
                   "本人需要核查完成证据" if task["status"] == "RESULT_SUBMITTED" else "交办仍需跟进当前负责人和期限",
                   "F04" if is_historical else "F06", task.get("due_at"))
            if is_historical:
                items[-1]["target_id"] = data["meeting"]["meeting_id"]
                items[-1]["read_only"] = True
        for row in self._rows(db, "self_commitment"):
            if row["status"] not in FINAL:
                append("self_commitment", row["commitment_id"], row["version"], row["purpose"], "COORDINATE",
                       "本人承诺仍待履行和证据核查", "N05", row["due_at"], row["importance"] == "IMPORTANT")
        for row in self._rows(db, "application"):
            if row["state"] in ("PENDING_DECISION", "WAITING_MATERIAL"):
                append("application", row["application_id"], row["version"], row["title"], "DECIDE",
                       "申请需要本人决定或补充材料", "F07")
        meeting = data["meeting"]
        if meeting.get("state", "DRAFT") not in ("CANCELED", "HELD"):
            append("meeting", meeting["meeting_id"], meeting["version"], "会议与会前材料", "COORDINATE",
                   "本人参加会议，需要核对当前资料和历史承诺", "F04", meeting["starts_at"])
        for event in self._rows(db, "event"):
            related_task = event.get("task_id")
            if event["event_id"] == data["event"]["event_id"]:
                related_task = data["event"].get("task_id")
            related_item = next((item for item in items if item["object_id"] == related_task), None)
            if related_item is not None:
                related_item["source_refs"].append({"kind": "event", "id": event["event_id"], "version": event["version"]})
                related_item["important"] = related_item["important"] or (event["state"] == "OPEN" and event["impact"] == "IMPORTANT")
            elif event["state"] != "CANCELED":
                append("event", event["event_id"], event["version"], "经营事件", "INFORM",
                       "查看当前事件及处理依据", "F02", event["due_at"], event["impact"] == "IMPORTANT")
        private = _calendar(db, data)
        if private.get("status", "ACTIVE") == "ACTIVE":
            append("private_calendar", private["calendar_id"], private.get("version", "1"), "本人私人安排", "INFORM",
                   "本人需要协调工作与私人占用时间", "F12", private["starts_at"])
        priority = {"DECIDE": 0, "COORDINATE": 1, "INFORM": 2}
        items.sort(key=lambda i: (not i["important"], priority[i["category"]], i["due_at"] or "9999", i["item_id"]))
        snapshot = checksum({"date": date, "clock": clock, "items": items, "profile": owner_profile(db, data)})
        rows = db.execute("SELECT body FROM objects WHERE namespace=? AND kind='today_order' AND id=?", (NS, date)).fetchone()
        preference = json.loads(rows[0]) if rows else None
        if preference:
            positions = {identifier: index for index, identifier in enumerate(preference["item_ids"])}
            items.sort(key=lambda i: (not i["important"], positions.get(i["item_id"], len(positions))))
        return {"source_type": "SIMULATED", "date": date, "timezone": zone,
                "business_clock": clock["at"], "items": items, "snapshot_sha256": snapshot,
                "order_version": preference["version"] if preference else "0",
                "ordering_reason": "重要事项优先，其余采用本人已保存次序；新增事项按分类和期限排列",
                "coverage_state": "PARTIAL", "missing_sources": ["完整日历结束时间与冲突范围", "未提供区域和农业专题资料"],
                "profile": owner_profile(db, data), "conflict_state": "INSUFFICIENT_EVIDENCE"}

    def read(self, role):
        self._role(role)
        with self.store.connect() as db:
            return self._read(db)

    def reorder(self, role, payload):
        self._role(role)
        require(isinstance(payload, dict), "排序输入必须为对象", web.HTTPBadRequest)
        self.commands._exact(payload, {"client_request_id", "expected_version", "snapshot_sha256", "item_ids"})
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self.store.active(db, NS)
            key, digest, previous = self.commands._check_existing(db, "boss.today.reorder", payload)
            if previous is not None:
                return previous
            view = self._read(db)
            require(view["snapshot_sha256"] == payload["snapshot_sha256"] and view["order_version"] == payload["expected_version"],
                    "今日资料或排序版本已变化，必须重新读取")
            identifiers = payload["item_ids"]
            require(isinstance(identifiers, list) and all(isinstance(i, str) for i in identifiers)
                    and len(identifiers) == len(set(identifiers))
                    and set(identifiers) == {i["item_id"] for i in view["items"]},
                    "本人次序必须包含当前全部事项且不得重复", web.HTTPBadRequest)
            version = str(int(view["order_version"]) + 1)
            auth = self.commands._authorize(db, "today.reorder", {"item_ids": identifiers, "snapshot_sha256": view["snapshot_sha256"]}, view["date"], version)
            result = {"source_type": "SIMULATED", "date": view["date"], "version": version,
                      "item_ids": identifiers, "authorization_id": auth}
            self.store.put(db, NS, "today_order", view["date"], result)
            self.commands._record(db, "boss.today.reorder", payload, key, digest, result)
            return result
