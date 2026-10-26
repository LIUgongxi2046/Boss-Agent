import json
from datetime import datetime
from urllib.parse import parse_qs

from aiohttp import web

from business import require
from boss_execution_scope import NAMESPACE
from boss_v7_owner_records import notification_history


def notification_target(store, role, namespace, query_string):
    require(role == "BOSS", "通知返回需要本人身份", web.HTTPForbidden)
    values = parse_qs(query_string, keep_blank_values=True)
    require({"event_id", "event_version"} <= set(values) <= {"event_id", "event_version", "execution_namespace"}
            and all(len(items) == 1 and 0 < len(items[0]) <= 200 for items in values.values()),
            "通知目标参数无效", web.HTTPBadRequest)
    event_id, version = values["event_id"][0], values["event_version"][0]
    require(namespace == NAMESPACE, "通知执行范围无效", web.HTTPConflict)
    with store.connect() as db:
        db.execute("BEGIN")
        store.active(db, namespace)
        data = store.get(db, namespace, "initial", "snapshot")
        original_namespace = values.get("execution_namespace", [namespace])[0]
        if original_namespace != namespace:
            matches = [row for row in notification_history(db, data)
                       if row["namespace"] == original_namespace and row["target_id"] == event_id and row["version"] == version]
            require(bool(matches), "原通知不属于获准历史空间或已经不可访问", web.HTTPNotFound)
            return {"source_type": "SIMULATED", "execution_namespace": original_namespace,
                    "event_id": event_id, "event_version": version, "category": "经营提醒", "page_id": "D09",
                    "record_id": matches[0]["id"], "notification_saved": True, "system_delivery_verified": False}
        event = store.get(db, namespace, "event", event_id)
        require(event.get("owner_id", data["owner_id"]) == data["owner_id"] == "boss-1", "通知不属于当前本人", web.HTTPForbidden)
        require(event["version"] == version, "通知引用的事件版本已经变化", web.HTTPConflict)
        require(event["state"] != "CANCELED", "当前事件已经取消", web.HTTPConflict)
        schedule = store.get(db, namespace, "schedule", "current")
        require(schedule["enabled"] and not schedule["canceled"], "当前技术计划暂停或已经取消", web.HTTPConflict)
        from boss_owner_plans import suppression
        from boss_owner_preferences import effective_owner_notice

        business_at = datetime.fromisoformat(store.get(db, namespace, "clock", "current")["at"])
        require(suppression(store, db, namespace, event, business_at) is None, "当前本人计划不允许通知", web.HTTPConflict)
        notice = effective_owner_notice(db, data, namespace)
        require(not notice or notice["content"]["notifications_enabled"], "本人已经暂停通知", web.HTTPConflict)
        if event.get("generated_by") == "BUSINESS_ALERT_INPUT":
            from boss_business_alerts import BusinessAlertsAPI

            current = BusinessAlertsAPI(store).project_in_transaction(role, db, event_id)["items"][0]
            require(current["adoption_state"] == "CURRENT" and current["notification"] is not None
                    and current["rule_state"] == "ACTIVE", "当前经营提醒依据或规则已经失效", web.HTTPConflict)
        if event.get("task_id"):
            task = store.get(db, namespace, "task", event["task_id"])
            require(task["status"] not in {"CANCELED", "COMPLETED_CONFIRMED"}, "关联交办已经结束", web.HTTPConflict)
        row = db.execute("SELECT body FROM objects WHERE namespace=? AND kind='reminder' AND id=?", (namespace, event_id)).fetchone()
        if row:
            reminder = json.loads(row[0])
            require(reminder["state"] != "CLOSED", "当前提醒已经关闭", web.HTTPConflict)
            if reminder["state"] == "SNOOZED":
                clock = store.get(db, namespace, "clock", "current")
                require(datetime.fromisoformat(reminder["until"]) <= datetime.fromisoformat(clock["at"]), "当前提醒仍在暂缓期间", web.HTTPConflict)
        saved = db.execute("SELECT 1 FROM objects WHERE namespace=? AND kind='notification' AND json_extract(body,'$.event_id')=? AND json_extract(body,'$.event_version')=? AND json_extract(body,'$.state')='DELIVERED'", (namespace, event_id, version)).fetchone()
        require(saved is not None, "当前版本尚未保存通知", web.HTTPConflict)
    return {"source_type": "SIMULATED", "execution_namespace": namespace, "event_id": event_id, "event_version": version, "category": "经营提醒", "page_id": "F02", "notification_saved": True, "system_delivery_verified": False}
