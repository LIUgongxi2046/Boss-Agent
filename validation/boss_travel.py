"""FR-11 owner-reviewed simulated travel plans, scoped to the existing SQLite store.

No ticketing, transport reservation, external calendar mutation or forecast is
performed. Drafts, confirmations and cancellations share BossCommandAPI's
BEGIN IMMEDIATE, role check, idempotency receipt and minimal audit.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from aiohttp import web

from business import checksum, now, require
from boss_meetings import meeting_materials
from boss_source_access import require_current_simulated_source

NS = "ui-check"
FINAL_STATES = ("CONFIRMED", "CANCELED")


def _get(db, kind, item_id):
    row = db.execute(
        "SELECT body FROM objects WHERE namespace=? AND kind=? AND id=?",
        (NS, kind, item_id),
    ).fetchone()
    return json.loads(row[0]) if row else None


def _plans(db):
    return [json.loads(row[0]) for row in db.execute(
        "SELECT body FROM objects WHERE namespace=? AND kind='travel_plan' ORDER BY id",
        (NS,),
    ).fetchall()]


def _timestamp(raw, zone):
    require(isinstance(zone, str) and 0 < len(zone) <= 80,
            "必须提供 IANA 时区", web.HTTPBadRequest)
    require(isinstance(raw, str) and 10 < len(raw) <= 64,
            "行程时间必须为含偏移的 ISO 时间", web.HTTPBadRequest)
    try:
        tz = ZoneInfo(zone)
        value = datetime.fromisoformat(raw)
    except (ValueError, ZoneInfoNotFoundError, TypeError):
        raise web.HTTPBadRequest(text="行程时间或 IANA 时区不合法") from None
    require(value.tzinfo is not None and value.utcoffset() is not None,
            "行程时间必须明确 UTC 偏移，避免夏令时重复时刻",
            web.HTTPBadRequest)
    local = value.astimezone(tz)
    require(local.replace(tzinfo=None) == value.replace(tzinfo=None)
            and local.utcoffset() == value.utcoffset(),
            "本地时刻在该 IANA 时区不存在，或 UTC 偏移不一致",
            web.HTTPBadRequest)
    return value


def _label(value, field, limit=240):
    require(isinstance(value, str) and 0 < len(value.strip()) <= limit,
            field + "缺失或格式无效", web.HTTPBadRequest)
    return value.strip()


def _contact(api, db, data, contact_id):
    require(isinstance(contact_id, str) and len(contact_id) <= 128,
            "接待联系人需要明确稳定 ID", web.HTTPBadRequest)
    matches = [row for row in data["contacts"] if row["contact_id"] == contact_id]
    require(len(matches) == 1, "联系人 ID 不存在或不唯一", web.HTTPBadRequest)
    clock = api.store.get(db, NS, "clock", "current")["at"]
    day = datetime.fromisoformat(clock).date().isoformat()
    require(matches[0]["valid_from"] <= day <= matches[0]["valid_until"],
            "该联系人在当前业务时钟下的职责已失效",
            web.HTTPForbidden)
    return matches[0]


def _details(api, db, data, payload):
    start = _timestamp(payload["starts_at"], payload["timezone"])
    end = _timestamp(payload["ends_at"], payload["timezone"])
    require(start < end and (end-start) <= timedelta(days=31),
            "出行结束必须晚于开始且时长不超过31天",
            web.HTTPBadRequest)
    clock = datetime.fromisoformat(api.store.get(db, NS, "clock", "current")["at"])
    require(start > clock, "行程开始不能早于或等于当前模拟业务时钟",
            web.HTTPBadRequest)
    buffer = payload["buffer_minutes"]
    require(type(buffer) is int and 0 <= buffer <= 360,
            "行程缓冲只能是0—360分钟", web.HTTPBadRequest)
    contact = _contact(api, db, data, payload["host_contact_id"])
    refs = payload["transport_refs"]
    require(isinstance(refs, list) and len(refs) <= 5,
            "交通依据数量超限", web.HTTPBadRequest)
    checked, seen = [], set()
    for ref in refs:
        require(isinstance(ref, dict) and set(ref) == {"source_id", "version"},
                "交通依据必须固定资料 ID 和版本", web.HTTPBadRequest)
        require(isinstance(ref["source_id"], str) and ref["source_id"] not in seen
                and isinstance(ref["version"], str),
                "交通依据标识无效或重复", web.HTTPBadRequest)
        seen.add(ref["source_id"])
        source = api.store.get(db, NS, "document", ref["source_id"])
        require(not source.get("withdrawn")
                and source.get("access_scope") == data["owner_id"]
                and source.get("source_type") == "SIMULATED",
                "交通资料已撤销或不在本人当前获准范围", web.HTTPForbidden)
        require_current_simulated_source(source, data["owner_id"], api.store.get(db, NS, "clock", "current")["at"])
        require(source["version"] == ref["version"],
                "交通来源已换版，须重新核查", web.HTTPConflict)
        checked.append({"source_id": ref["source_id"], "version": source["version"]})
    return {
        "origin": _label(payload["origin"], "起点"),
        "destination": _label(payload["destination"], "目的地"),
        "starts_at": start.isoformat(), "ends_at": end.isoformat(),
        "starts_at_utc": start.astimezone(timezone.utc).isoformat(),
        "ends_at_utc": end.astimezone(timezone.utc).isoformat(),
        "timezone": payload["timezone"],
        "host_contact_id": contact["contact_id"],
        "host_responsibility": contact["responsibility"],
        "buffer_minutes": buffer, "transport_refs": checked,
    }


def _impact(api, db, data, details, exclude_travel_id=None):
    data = meeting_materials(db, data)
    start = datetime.fromisoformat(details["starts_at"]) - timedelta(
        minutes=details["buffer_minutes"])
    end = datetime.fromisoformat(details["ends_at"]) + timedelta(
        minutes=details["buffer_minutes"])
    meeting = data["meeting"]
    meeting_start = datetime.fromisoformat(meeting["starts_at"])
    meeting_active = meeting.get("state", "DRAFT") not in ("CANCELED", "HELD")
    meeting_end = datetime.fromisoformat(meeting["ends_at"]) if meeting.get("ends_at") else None
    meeting_inside = meeting_active and (start <= meeting_start < end if meeting_end is None else start < meeting_end and end > meeting_start)
    meeting_near = abs((meeting_start - end).total_seconds()) < 86400 or (
        0 <= (start - meeting_start).total_seconds() < 86400
    )
    meeting_risk = meeting_inside or (meeting_active and meeting_end is None and meeting_near)
    private = _get(db, "private_calendar", "private-1") or {
        **data["private_calendar"], "version": "1", "status": "ACTIVE",
    }
    private_overlap = False
    if private.get("status") == "ACTIVE":
        pstart = datetime.fromisoformat(private["starts_at"])
        pend = datetime.fromisoformat(private["ends_at"])
        private_overlap = start < pend and end > pstart
    due = []
    tasks = [data["historical_task"]] + [
        json.loads(row[0]) for row in db.execute(
            "SELECT body FROM objects WHERE namespace=? AND kind='task'",
            (NS,),
        ).fetchall()
    ]
    for task in tasks:
        if task.get("status") in ("CANCELED", "COMPLETED_CONFIRMED"):
            continue
        due_at = task.get("due_at")
        if isinstance(due_at, str) and start <= datetime.fromisoformat(due_at) < end:
            due.append({
                "task_id": task["task_id"], "version": task.get("version", "1"),
                "due_at": due_at, "status": task["status"],
            })
    overlaps = []
    for plan in _plans(db):
        if plan["travel_id"] == exclude_travel_id or plan["status"] != "CONFIRMED":
            continue
        active = plan.get("current")
        if not active:
            continue
        other_start = datetime.fromisoformat(active["starts_at"])
        other_end = datetime.fromisoformat(active["ends_at"])
        if start < other_end and end > other_start:
            overlaps.append({"travel_id": plan["travel_id"], "version": plan["version"]})
    return {
        "meeting": {
            "meeting_id": meeting["meeting_id"],
            "version": meeting["version"],
            "starts_at": meeting["starts_at"],
            "ends_at": meeting.get("ends_at"), "state": meeting.get("state", "DRAFT"),
            "end_known": meeting_end is not None, "requires_review": meeting_risk,
            "start_overlap": meeting_inside,
        },
        "private_calendar": {
            "version": private["version"], "status": private["status"],
            "conflict": private_overlap, "private_body_exposed": False,
        },
        "task_deadlines": sorted(due, key=lambda row: row["task_id"]),
        "other_confirmed_trips": sorted(overlaps, key=lambda row: row["travel_id"]),
        "transport_missing": len(details["transport_refs"]) == 0,
        "weather_source_present": False,
        "external_booking_verified": False,
        "conflicts_need_acknowledgement": bool(
            meeting_risk or private_overlap or due or overlaps
        ),
        "coverage": "APPROVED_SIMULATED_MEETING_CALENDAR_TASKS_ONLY",
    }


def review(api, db, data, payload):
    api._exact(payload, {
        "client_request_id", "travel_id", "expected_version",
        "origin", "destination", "starts_at", "ends_at", "timezone",
        "host_contact_id", "buffer_minutes", "transport_refs",
    })
    identifier = payload["travel_id"]
    require(identifier is None or (
        isinstance(identifier, str) and len(identifier) <= 128
    ), "行程标识无效", web.HTTPBadRequest)
    previous = _get(db, "travel_plan", identifier) if identifier else None
    require((previous is not None) if identifier else payload["expected_version"] == "0",
            "行程不存在或创建版本不符", web.HTTPConflict)
    if previous:
        require(previous["status"] != "CANCELED"
                and previous["version"] == payload["expected_version"],
                "行程已取消或版本变化，请重读", web.HTTPConflict)
    details = _details(api, db, data, payload)
    impact = _impact(api, db, data, details, exclude_travel_id=identifier)
    digest = checksum({"details": details, "impact": impact,
                       "dataset_version": data["dataset_version"]})
    if previous:
        api.store.put(db, NS, "travel_revision",
                      identifier + ":v" + previous["version"], previous)
    else:
        identifier = "travel-" + str(uuid.uuid4())
    version = str(int(previous["version"]) + 1) if previous else "1"
    record = {
        "travel_id": identifier, "version": version,
        "status": previous["status"] if previous else "DRAFT_REVIEWED",
        "current": previous.get("current") if previous else None,
        "pending": {
            "details": details, "impact": impact,
            "review_sha256": digest, "reviewed_at": now(),
        },
        "created_at": previous["created_at"] if previous else now(),
        "updated_at": now(), "source_type": "SIMULATED",
    }
    api.store.put(db, NS, "travel_plan", identifier, record)
    return {
        "travel_id": identifier, "version": version, "status": record["status"],
        "pending_review": True, "review_sha256": digest,
        "impact": impact, "external_booking_created": False,
    }


def confirm(api, db, data, payload):
    api._exact(payload, {
        "client_request_id", "travel_id", "expected_version",
        "review_sha256", "acknowledge_conflicts", "acknowledge_missing_transport",
    })
    record = api.store.get(db, NS, "travel_plan", payload["travel_id"])
    require(record["version"] == payload["expected_version"]
            and record["status"] in ("DRAFT_REVIEWED", "CONFIRMED")
            and record.get("pending") is not None,
            "行程版本变化、已取消或没有待确认方案", web.HTTPConflict)
    pending = record["pending"]
    require(payload["review_sha256"] == pending["review_sha256"],
            "待确认方案摘要不一致", web.HTTPConflict)
    require(type(payload["acknowledge_conflicts"]) is bool
            and type(payload["acknowledge_missing_transport"]) is bool,
            "确认选择值无效", web.HTTPBadRequest)
    details = pending["details"]
    # Recheck identity, sources, time-zone, business clock and all live
    # dependencies under this same SQLite write transaction.
    live = _details(api, db, data, details)
    require(details == live, "已核查行程字段变化，请重做预检")
    impact = _impact(api, db, data, live, exclude_travel_id=record["travel_id"])
    digest = checksum({"details": live, "impact": impact,
                       "dataset_version": data["dataset_version"]})
    require(digest == pending["review_sha256"],
            "会议、任务、私人日程或其他行程已变化，请重新核查", web.HTTPConflict)
    require(not impact["conflicts_need_acknowledgement"] or
            payload["acknowledge_conflicts"],
            "存在会议或任务冲突，必须明确确认", web.HTTPConflict)
    require(not impact["transport_missing"] or
            payload["acknowledge_missing_transport"],
            "交通和预订依据缺失，必须明确知晓", web.HTTPConflict)
    auth_id = api._authorize(db, "travel.confirm", {
        "travel_id": record["travel_id"], "plan_version": record["version"],
        "review_sha256": digest,
    }, record["travel_id"], record["version"])
    api.store.put(db, NS, "travel_revision",
                  record["travel_id"] + ":v" + record["version"], record)
    record["current"] = live
    record["pending"] = None
    record["status"] = "CONFIRMED"
    record["version"] = str(int(record["version"]) + 1)
    record["updated_at"] = now()
    record["authorization_id"] = auth_id
    record["impact_at_confirmation"] = impact
    api.store.put(db, NS, "travel_plan", record["travel_id"], record)
    return {
        "travel_id": record["travel_id"], "version": record["version"],
        "status": "CONFIRMED", "authorization_id": auth_id,
        "impact": impact, "external_booking_created": False,
        "external_calendar_updated": False, "real_world_travel_verified": False,
    }


def cancel(api, db, data, payload):
    api._exact(payload, {
        "client_request_id", "travel_id", "expected_version", "reason",
    })
    reason = _label(payload["reason"], "取消原因", 400)
    record = api.store.get(db, NS, "travel_plan", payload["travel_id"])
    require(record["version"] == payload["expected_version"]
            and record["status"] in ("CONFIRMED", "DRAFT_REVIEWED"),
            "行程版本或当前状态不允许取消", web.HTTPConflict)
    auth_id = api._authorize(db, "travel.cancel", {
        "travel_id": record["travel_id"], "expected_version": record["version"],
        "reason_sha256": checksum(reason),
    }, record["travel_id"], record["version"])
    api.store.put(db, NS, "travel_revision",
                  record["travel_id"] + ":v" + record["version"], record)
    record["status"] = "CANCELED"
    record["pending"] = None
    record["version"] = str(int(record["version"]) + 1)
    record["updated_at"] = now()
    record["cancel_reason"] = reason
    record["authorization_id"] = auth_id
    api.store.put(db, NS, "travel_plan", record["travel_id"], record)
    return {
        "travel_id": record["travel_id"], "version": record["version"],
        "status": "CANCELED", "authorization_id": auth_id,
        "external_cancellation_performed": False,
    }


def meeting_impacts(db, meeting):
    """Stable dependency for F04; do not mix withdrawn or draft trip with facts."""
    start = datetime.fromisoformat(meeting["starts_at"])
    result = []
    if meeting.get("state", "DRAFT") in ("CANCELED", "HELD"):
        return result
    end = datetime.fromisoformat(meeting["ends_at"]) if meeting.get("ends_at") else None
    for plan in _plans(db):
        if plan["status"] != "CONFIRMED" or not plan.get("current"):
            continue
        detail = plan["current"]
        window_start = datetime.fromisoformat(detail["starts_at"]) - timedelta(
            minutes=detail["buffer_minutes"])
        window_end = datetime.fromisoformat(detail["ends_at"]) + timedelta(
            minutes=detail["buffer_minutes"])
        overlap = window_start <= start < window_end if end is None else window_start < end and window_end > start
        if overlap or (
            0 <= (window_start - start).total_seconds() < 86400
        ) or (0 <= (start - window_end).total_seconds() < 86400):
            result.append({"travel_id": plan["travel_id"],
                           "version": plan["version"], "meeting_end_known": meeting.get("ends_at") is not None})
    return sorted(result, key=lambda entry: entry["travel_id"])


def projection(api, db, data):
    data = meeting_materials(db, data)
    plans = []
    for record in _plans(db):
        result = dict(record)
        if record.get("pending"):
            pending = record["pending"]
            fresh = False
            try:
                live = _details(api, db, data, pending["details"])
                current = _impact(api, db, data, live, record["travel_id"])
                fresh = checksum({
                    "details": live, "impact": current,
                    "dataset_version": data["dataset_version"],
                }) == pending["review_sha256"]
            except (web.HTTPException, KeyError, ValueError, TypeError):
                pass
            result["pending_is_current"] = fresh
        plans.append(result)
    clock = api.store.get(db, NS, "clock", "current")
    return {
        "plans": plans, "business_clock": clock["at"],
        "owner_timezone": data["boss_profile"]["timezone"],
        "contacts": [{
            "contact_id": c["contact_id"], "name": c["name"],
            "organization": c["organization"], "responsibility": c["responsibility"],
            "valid_from": c["valid_from"], "valid_until": c["valid_until"],
        } for c in data["contacts"]],
        "meeting": {
            "meeting_id": data["meeting"]["meeting_id"],
            "version": data["meeting"]["version"],
            "starts_at": data["meeting"]["starts_at"],
            "ends_at": data["meeting"].get("ends_at"),
            "state": data["meeting"].get("state", "DRAFT"),
            "end_known": data["meeting"].get("ends_at") is not None,
        },
        "real_transport_bookings": False,
        "real_weather_retrieval": False,
        "visibility": "BOSS_ONLY",
    }
