import json
from datetime import datetime
from pathlib import Path

from boss_simulation_api import _context
from business import checksum


def _require_transaction(store, db):
    main = db.execute("PRAGMA database_list").fetchone()
    if not db.in_transaction or main is None or main[1] != "main" or Path(main[2]).resolve() != store.path.resolve():
        raise ValueError("抑制回执核查需要同一业务数据库事务")


def require_prior_notification_in_transaction(store, db, event_id, event_version, plan_id, suppressed):
    _require_transaction(store, db)
    context = _context(db)
    row = db.execute("SELECT body FROM objects WHERE namespace=? AND kind='notification' AND id=?", (context["namespace"], event_id + ":" + event_version)).fetchone()
    if row is None:
        return
    notification = json.loads(row[0])
    if not isinstance(notification, dict) or (notification.get("event_id"), notification.get("event_version"), notification.get("owner_plan_id"), notification.get("state"), notification.get("reason")) != (event_id, event_version, plan_id, "DELIVERED", None):
        raise ValueError("已有通知记录不可核查")
    suppressed_at = datetime.fromisoformat(suppressed["recorded_at"])
    if suppressed_at.tzinfo is None or suppressed_at.utcoffset() is None:
        raise ValueError("抑制记录时间不可核查")
    rows = db.execute("SELECT id,body FROM objects WHERE namespace=? AND kind='dispatch_history' AND json_extract(body,'$.event_id')=? AND json_extract(body,'$.event_version')=? AND json_extract(body,'$.state')='DELIVERED'", (context["namespace"], event_id, event_version)).fetchall()
    matches = []
    for identifier, body in rows:
        delivered = json.loads(body)
        if not isinstance(delivered, dict) or delivered.get("dispatch_id") != identifier or checksum({key: value for key, value in delivered.items() if key not in {"dispatch_id", "recorded_at"}}) != identifier:
            raise ValueError("已有通知派发记录不可核查")
        if delivered.get("owner_plan_id") != plan_id or delivered.get("reason") is not None:
            continue
        if any(notification.get(key) != delivered.get(key) for key in ("event_id", "event_version", "state", "reason", "business_at", "rule_version", "schedule_version")) or notification.get("delivered_at") != delivered.get("business_at"):
            continue
        delivered_at = datetime.fromisoformat(delivered["recorded_at"])
        if delivered_at.tzinfo is None or delivered_at.utcoffset() is None:
            raise ValueError("通知派发时间不可核查")
        if delivered_at <= suppressed_at:
            matches.append(identifier)
    if len(matches) != 1:
        raise ValueError("已有通知与原派发记录不可唯一核查")


def read_suppressed_receipt_in_transaction(store, db, plan_id, event_id, event_version=None, occurrence_id=None, dispatch_id=None):
    _require_transaction(store, db)
    if any(not isinstance(value, str) or not value.strip() for value in (plan_id, event_id)):
        raise ValueError("计划或事件编号无效")
    context = _context(db)
    plan = store.get(db, context["namespace"], "owner_plan", plan_id)
    if plan.get("plan_id") != plan_id or plan.get("owner_id") != context["owner_id"] or plan.get("source_type") != "SIMULATED":
        raise ValueError("本人计划不可核查")
    expected_event_version = plan.get("event_versions", {}).get(event_id)
    if expected_event_version is None:
        raise ValueError("事件不属于本人计划")
    event = store.get(db, context["namespace"], "event", event_id)
    if event.get("owner_plan_id") != plan_id or event.get("version") != expected_event_version:
        raise ValueError("本人计划事件已经变化")
    if event_version is not None and event_version != expected_event_version:
        raise ValueError("事件版本已经变化")
    rows = db.execute("SELECT id,body FROM objects WHERE namespace=? AND kind='dispatch_history' AND json_extract(body,'$.event_id')=? AND json_extract(body,'$.event_version')=? AND json_extract(body,'$.owner_plan_id')=? AND json_extract(body,'$.state')='SUPPRESSED' ORDER BY id",
                      (context["namespace"], event_id, expected_event_version, plan_id)).fetchall()
    link = None
    if occurrence_id is not None:
        if not isinstance(occurrence_id, str) or not occurrence_id.strip():
            raise ValueError("计划发生编号无效")
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='hermes_schedule_notification_links'").fetchone() is None:
            raise ValueError("抑制回执发生关联不可核查")
        link = db.execute("SELECT l.dispatch_id,l.status,r.run_id,c.namespace,c.dataset_id,c.dataset_version,c.plan_id FROM hermes_schedule_notification_links l JOIN hermes_schedule_run_links r ON r.occurrence_id=l.occurrence_id JOIN hermes_schedule_plan_candidates c ON c.occurrence_id=l.occurrence_id WHERE l.occurrence_id=? AND l.event_id=? AND l.event_version=?",
                          (occurrence_id, event_id, expected_event_version)).fetchone()
        if link is None or link[1] != "SUPPRESSED" or link[3:] != (context["namespace"], context["dataset_id"], context["dataset_version"], plan_id):
            raise ValueError("抑制回执缺少发生关联")
        rows = [row for row in rows if row[0] == link[0]]
    if dispatch_id is not None:
        if not isinstance(dispatch_id, str) or not dispatch_id.strip():
            raise ValueError("原调度回执编号无效")
        rows = [row for row in rows if row[0] == dispatch_id]
    if len(rows) != 1:
        raise ValueError("原调度回执不可唯一核查")
    history_id, body = rows[0]
    history = json.loads(body)
    if not isinstance(history, dict):
        raise ValueError("原调度回执不可核查")
    original = {key: value for key, value in history.items() if key not in {"dispatch_id", "recorded_at"}}
    if history.get("dispatch_id") != history_id or checksum(original) != history_id:
        raise ValueError("原调度回执内容不符")
    if (history.get("event_id"), history.get("event_version"), history.get("owner_plan_id"), history.get("state")) != (event_id, expected_event_version, plan_id, "SUPPRESSED"):
        raise ValueError("原调度回执内容不符")
    if not isinstance(history.get("reason"), str) or not history["reason"].strip():
        raise ValueError("抑制原因不可核查")
    require_prior_notification_in_transaction(store, db, event_id, expected_event_version, plan_id, history)
    return {"plan_id": plan_id, "plan_version": plan.get("version"), "event_id": event_id, "event_version": expected_event_version,
            "occurrence_id": occurrence_id if link is not None else None, "run_id": link[2] if link is not None else None,
            "dispatch_id": history_id, "status": "SUPPRESSED", "reason": history["reason"],
            "business_at": history.get("business_at"), "rule_version": history.get("rule_version"),
            "schedule_version": history.get("schedule_version"), "source_type": "SIMULATED",
            "occurrence_binding": "VERIFIED" if link is not None else "UNVERIFIED"}


def recovery_decision_in_transaction(store, db, plan_id, event_id, event_version=None, occurrence_id=None, dispatch_id=None):
    receipt = read_suppressed_receipt_in_transaction(store, db, plan_id, event_id, event_version, occurrence_id, dispatch_id)
    context = _context(db)
    plan = store.get(db, context["namespace"], "owner_plan", plan_id)
    event = store.get(db, context["namespace"], "event", event_id)
    if plan.get("state") != "ACTIVE":
        state, reason, action = "BLOCKED", "PLAN_INACTIVE", "WAIT_FOR_PLAN_ACTIVE"
    elif event.get("version") != receipt["event_version"]:
        state, reason, action = "BLOCKED", "EVENT_CHANGED", "CREATE_NEW_EVENT"
    else:
        state, reason, action = "READY_FOR_NEW_OCCURRENCE", None, "NEW_OCCURRENCE"
    return {"receipt": receipt, "recovery_state": state, "reason": reason, "required_action": action,
            "redispatch_same_occurrence": False}


def list_suppressed_receipts_in_transaction(store, db, plan_id, event_id):
    _require_transaction(store, db)
    if any(not isinstance(value, str) or not value.strip() for value in (plan_id, event_id)):
        raise ValueError("计划或事件编号无效")
    context = _context(db)
    plan = store.get(db, context["namespace"], "owner_plan", plan_id)
    if plan.get("plan_id") != plan_id or plan.get("owner_id") != context["owner_id"] or plan.get("source_type") != "SIMULATED" or event_id not in plan.get("event_ids", []):
        raise ValueError("本人计划或事件范围不可核查")
    version = plan.get("event_versions", {}).get(event_id)
    event = store.get(db, context["namespace"], "event", event_id)
    if not isinstance(version, str) or event.get("owner_plan_id") != plan_id or event.get("version") != version:
        raise ValueError("本人计划事件已经变化")
    rows = db.execute("SELECT id FROM objects WHERE namespace=? AND kind='dispatch_history' AND json_extract(body,'$.event_id')=? AND json_extract(body,'$.event_version')=? AND json_extract(body,'$.owner_plan_id')=? AND json_extract(body,'$.state')='SUPPRESSED' ORDER BY id", (context["namespace"], event_id, version, plan_id)).fetchall()
    receipts = []
    for (dispatch_id,) in rows:
        links = []
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='hermes_schedule_notification_links'").fetchone() is not None:
            links = db.execute("SELECT occurrence_id FROM hermes_schedule_notification_links WHERE dispatch_id=? AND event_id=? AND event_version=? ORDER BY occurrence_id", (dispatch_id, event_id, version)).fetchall()
        if len(links) > 1:
            raise ValueError("抑制回执发生关联不唯一")
        receipts.append(read_suppressed_receipt_in_transaction(store, db, plan_id, event_id, version, links[0][0] if links else None, dispatch_id))
    return {"plan_id": plan_id, "plan_version": plan["version"], "event_id": event_id, "event_version": version, "receipts": receipts}
