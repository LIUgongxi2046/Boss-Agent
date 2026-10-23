import json
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

from aiohttp import web

from business import now, require
from boss_command_api import BossCommandAPI

NS = "ui-check"


def _items(db, kind):
    return [json.loads(row[0]) for row in db.execute(
        "SELECT body FROM objects WHERE namespace=? AND kind=? ORDER BY id", (NS, kind),
    ).fetchall()]


def suppression(store, db, ns, event, clock):
    identifier = event.get("owner_plan_id")
    if identifier is None:
        return None
    plan = store.get(db, ns, "owner_plan", identifier)
    if plan["state"] != "ACTIVE":
        return "OWNER_PLAN_" + plan["state"]
    if event["event_id"] not in plan["event_ids"]:
        return "OWNER_PLAN_SCOPE_CHANGED"
    if plan["event_versions"][event["event_id"]] != event["version"]:
        return "OWNER_PLAN_SOURCE_CHANGED"
    auth = store.get(db, ns, "authorization", plan["authorization_id"])
    if auth["revoked"]:
        return "OWNER_PLAN_AUTHORIZATION_REVOKED"
    require(auth["scope"] == ns and auth["target_id"] == identifier
            and auth["action"] in ("owner_plan.save", "owner_plan.resume"),
            "本人计划授权关联无效", web.HTTPForbidden)
    if clock < datetime.fromisoformat(plan["not_before"]):
        return "OWNER_PLAN_NOT_DUE"
    return None


class OwnerPlansAPI:
    def __init__(self, store):
        self.store = store
        self.commands = BossCommandAPI(store)

    @staticmethod
    def _role(role):
        require(role in ("BOSS", "MAINTAINER"), "身份尚未认证", web.HTTPUnauthorized)
        require(role == "BOSS", "本人计划仅限本人访问", web.HTTPForbidden)

    def read(self, role):
        self._role(role)
        with self.store.connect() as db:
            self.store.active(db, NS)
            plans = _items(db, "owner_plan")
            events = _items(db, "event")
            return {
                "source_type": "SIMULATED", "plans": plans,
                "events": [{k: e[k] for k in ("event_id", "version", "state", "due_at")} for e in events],
                "results": [r for r in _items(db, "notification") if r.get("owner_plan_id")],
                "dispatches": [r for r in _items(db, "dispatch") if r.get("owner_plan_id")],
                "technical_schedule": {k: self.store.get(db, NS, "schedule", "current")[k]
                                       for k in ("version", "enabled", "canceled")},
                "execution_owner": "CronService", "external_delivery_verified": False,
            }

    def execute(self, role, action, payload):
        self._role(role)
        require(action in ("save", "pause", "resume", "cancel"), "未知计划操作", web.HTTPNotFound)
        require(isinstance(payload, dict), "计划输入必须为对象", web.HTTPBadRequest)
        operation = "boss.owner.plan." + action
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self.store.active(db, NS)
            key, digest, previous = self.commands._check_existing(db, operation, payload)
            if previous is not None:
                return previous
            if action == "save":
                result = self._save(db, payload)
            else:
                result = self._status(db, action, payload)
            self.commands._record(db, operation, payload, key, digest, result)
            return result

    def _save(self, db, payload):
        self.commands._exact(payload, {
            "client_request_id", "plan_id", "expected_version", "purpose",
            "event_ids", "timezone", "not_before",
        })
        identifier = payload["plan_id"]
        require(isinstance(identifier, str) and len(identifier) <= 128, "计划标识无效", web.HTTPBadRequest)
        current = self.store.get(db, NS, "owner_plan", identifier) if identifier else None
        require(payload["expected_version"] == (current["version"] if current else "0"), "本人计划版本冲突")
        require(not current or current["state"] != "CANCELED", "已取消计划不能修改")
        purpose = payload["purpose"]
        require(isinstance(purpose, str) and 0 < len(purpose.strip()) <= 400, "计划用途缺少或过长", web.HTTPBadRequest)
        require(payload["timezone"] == "Asia/Shanghai", "当前业务时钟使用 Asia/Shanghai", web.HTTPBadRequest)
        instant = datetime.fromisoformat(payload["not_before"])
        require(instant.tzinfo is not None and instant.utcoffset() == instant.astimezone(ZoneInfo(payload["timezone"])).utcoffset(),
                "计划时间必须与时区一致", web.HTTPBadRequest)
        clock = datetime.fromisoformat(self.store.get(db, NS, "clock", "current")["at"])
        require(instant > clock, "计划时间必须晚于当前业务时间", web.HTTPBadRequest)
        require((instant - clock).total_seconds() <= 366 * 86400, "本人计划时间不能超过366天", web.HTTPBadRequest)
        identifiers = payload["event_ids"]
        require(isinstance(identifiers, list) and 1 <= len(identifiers) <= 32
                and all(isinstance(e, str) and 0 < len(e) <= 128 for e in identifiers)
                and len(set(identifiers)) == len(identifiers), "事件范围缺少、重复或无效", web.HTTPBadRequest)
        events = [self.store.get(db, NS, "event", e) for e in identifiers]
        identifier = identifier or str(uuid.uuid4())
        for event in events:
            require(event["state"] != "CANCELED", "已取消事件不能加入计划")
            other = event.get("owner_plan_id")
            if other and other != identifier:
                require(self.store.get(db, NS, "owner_plan", other)["state"] == "CANCELED", "事件已有本人计划")
        version = str(int(current["version"]) + 1) if current else "1"
        content = {k: payload[k] for k in ("purpose", "event_ids", "timezone", "not_before")}
        content["event_versions"] = {e["event_id"]: e["version"] for e in events}
        auth = self.commands._authorize(db, "owner_plan.save", content, identifier, version)
        plan = {**content, "plan_id": identifier, "version": version,
                "state": current["state"] if current else "ACTIVE", "authorization_id": auth,
                "owner_id": "boss-1", "source_type": "SIMULATED", "updated_at": now(),
                "execution_owner": "CronService"}
        if current:
            self.store.put(db, NS, "owner_plan_revision", identifier + ":" + current["version"], current)
        self.store.put(db, NS, "owner_plan", identifier, plan)
        for event in events:
            self.store.put(db, NS, "event", event["event_id"], {**event, "owner_plan_id": identifier})
        return plan

    def _status(self, db, action, payload):
        self.commands._exact(payload, {"client_request_id", "plan_id", "expected_version"})
        plan = self.store.get(db, NS, "owner_plan", payload["plan_id"])
        require(plan["version"] == payload["expected_version"], "本人计划版本冲突")
        allowed = {"pause": ("ACTIVE",), "resume": ("PAUSED",), "cancel": ("ACTIVE", "PAUSED")}
        require(plan["state"] in allowed[action], "当前计划状态不支持该操作")
        self.store.put(db, NS, "owner_plan_revision", plan["plan_id"] + ":" + plan["version"], plan)
        auth = self.commands._authorize(db, "owner_plan." + action, {
            "plan_id": plan["plan_id"], "expected_version": plan["version"],
        }, plan["plan_id"], plan["version"])
        plan = {**plan, "version": str(int(plan["version"]) + 1),
                "state": {"pause": "PAUSED", "resume": "ACTIVE", "cancel": "CANCELED"}[action],
                "updated_at": now(), "last_action_authorization_id": auth}
        if action == "resume":
            plan["authorization_id"] = auth
        self.store.put(db, NS, "owner_plan", plan["plan_id"], plan)
        return plan
