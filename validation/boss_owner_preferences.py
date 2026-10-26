"""BOSS-only long-term goals and notification preferences (N07/N08).

Persisted drafts NEVER become effective until a separate, owner-authorized
CAS confirmation. The existing synthetic fixture is not treated as a fresh
owner confirmation. No employee account, external share or delivery is made.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from aiohttp import web

from business import checksum, now, require

from boss_execution_scope import NAMESPACE as NS
GOAL_SCOPES = ("OWNER_WORKSPACE", "DAILY_BRIEF", "MEETING_PREP")
READING_FORMATS = ("ACTIONS_FIRST", "SUMMARY", "DETAIL")
READING_LIMIT = 800


def _get(db, kind, key="current", namespace=NS):
    row = db.execute(
        "SELECT body FROM objects WHERE namespace=? AND kind=? AND id=?",
        (namespace, kind, key),
    ).fetchone()
    return json.loads(row[0]) if row else None


def _versions(db, kind):
    return [
        json.loads(row[0]) for row in db.execute(
            "SELECT body FROM objects WHERE namespace=? AND kind=? ORDER BY id",
            (NS, kind),
        ).fetchall()
    ]


def _version(value):
    require(isinstance(value, str) and value.isdecimal()
            and 0 <= int(value) <= 99999999,
            "当前版本格式无效", web.HTTPBadRequest)
    return value


def _business_clock(api, db):
    return datetime.fromisoformat(
        api.store.get(db, NS, "clock", "current")["at"]
    )


def _time(value, clock):
    if value is None:
        return None
    require(isinstance(value, str) and 16 <= len(value) <= 64,
            "有效期需要含 UTC 偏移的 ISO 时间", web.HTTPBadRequest)
    try:
        instant = datetime.fromisoformat(value)
    except ValueError:
        raise web.HTTPBadRequest(text="有效期格式不合法") from None
    require(instant.tzinfo is not None and instant.utcoffset() is not None,
            "有效期必须有时区偏移", web.HTTPBadRequest)
    require(clock < instant <= clock + timedelta(days=366),
            "有效期必须晚于当前业务时间且不超过366天", web.HTTPBadRequest)
    return instant.isoformat()


def _texts(values, label, limit, max_items, min_items=0):
    require(isinstance(values, list) and min_items <= len(values) <= max_items,
            f"{label}数量超出限制", web.HTTPBadRequest)
    require(all(isinstance(v, str) and 0 < len(v.strip()) <= limit for v in values),
            f"{label}缺少有效内容", web.HTTPBadRequest)
    normalized = [v.strip() for v in values]
    require(len(normalized) == len(set(normalized)), f"{label}不能重复",
            web.HTTPBadRequest)
    return normalized


def _goal_content(payload, clock):
    scope = payload["scope"]
    require(scope in GOAL_SCOPES, "目标适用范围无效", web.HTTPBadRequest)
    reading = payload["reading_requirement"]
    require(isinstance(reading, str) and 0 < len(reading.strip()) <= READING_LIMIT,
            "本人阅读要求需填写 1—800 字", web.HTTPBadRequest)
    return {
        "goals": _texts(payload["goals"], "目标", 160, 8, 1),
        "topics": _texts(payload["topics"], "关注主题", 120, 10),
        "reading_requirement": reading.strip(),
        "scope": scope,
        "valid_until": _time(payload["valid_until"], clock),
        "source": "OWNER_EXPLICIT_INPUT",
    }


def _notification_content(payload, clock):
    zone = payload["timezone"]
    require(isinstance(zone, str) and 0 < len(zone) <= 80,
            "通知时区缺少", web.HTTPBadRequest)
    try:
        ZoneInfo(zone)
    except ZoneInfoNotFoundError:
        raise web.HTTPBadRequest(text="必须选择真实 IANA 时区") from None
    for k in ("quiet_start", "quiet_end"):
        require(type(payload[k]) is int and 0 <= payload[k] <= 23,
                f"{k}只能是0—23小时", web.HTTPBadRequest)
    for k in ("notifications_enabled", "important_during_quiet"):
        require(type(payload[k]) is bool, "通知开关必须为明确布尔值",
                web.HTTPBadRequest)
    require(payload["reading_format"] in READING_FORMATS,
            "阅读格式不在获准范围", web.HTTPBadRequest)
    require(payload["visibility"] == "BOSS_ONLY",
            "通知偏好不得将老板私人正文扩权", web.HTTPForbidden)
    require(payload["calendar_share_limit"] == "BUSY_ONLY",
            "私人日历分享必须由 F12 逐对象授权", web.HTTPForbidden)
    return {
        "timezone": zone,
        "quiet_start": payload["quiet_start"],
        "quiet_end": payload["quiet_end"],
        "notifications_enabled": payload["notifications_enabled"],
        "important_during_quiet": payload["important_during_quiet"],
        "reading_format": payload["reading_format"],
        "visibility": "BOSS_ONLY",
        "calendar_share_limit": "BUSY_ONLY",
        "valid_until": _time(payload["valid_until"], clock),
        "source": "OWNER_EXPLICIT_INPUT",
    }


def _save(api, db, data, payload, domain, body_keys, content_validator):
    api._exact(payload, {"client_request_id", "expected_version", *body_keys})
    current = _get(db, domain + "_draft")
    previous_version = current["version"] if current else "0"
    require(_version(payload["expected_version"]) == previous_version,
            "本人设置草稿版本已变化，须重读后修改")
    content = content_validator(payload, _business_clock(api, db))
    version = str(int(previous_version) + 1)
    if current:
        api.store.put(db, NS, domain + "_draft_revision",
                      "current:v" + previous_version, current)
    draft = {
        "id": domain + ":current", "version": version,
        "state": "DRAFT_NOT_EFFECTIVE", "content": content,
        "content_sha256": checksum(content), "saved_at": now(),
        "source_type": "SIMULATED", "author_identity": "BOSS",
        "confirmed": False,
    }
    api.store.put(db, NS, domain + "_draft", "current", draft)
    return {
        "source_type": "SIMULATED", "version": version,
        "state": "DRAFT_NOT_EFFECTIVE",
        "content_sha256": draft["content_sha256"],
        "active_unchanged": True, "authorization_created": False,
    }


def _confirm(api, db, data, payload, domain):
    api._exact(payload, {
        "client_request_id", "expected_draft_version",
        "expected_active_version", "content_sha256",
    })
    draft = api.store.get(db, NS, domain + "_draft", "current")
    active = _get(db, domain + "_active")
    active_version = active["version"] if active else "0"
    require(_version(payload["expected_draft_version"]) == draft["version"]
            and _version(payload["expected_active_version"]) == active_version
            and payload["content_sha256"] == draft["content_sha256"],
            "设置内容、草稿或有效版本已变化，必须重新核实")
    current_clock = _business_clock(api, db)
    expiry = draft["content"].get("valid_until")
    require(expiry is None or datetime.fromisoformat(expiry) > current_clock,
            "草稿有效期已经到达，不能激活")
    next_version = str(int(active_version) + 1)
    auth = api._authorize(
        db, domain + ".confirm",
        {"draft_version": draft["version"], "active_version": active_version,
         "content_sha256": draft["content_sha256"]},
        domain + ":current", active_version,
    )
    if active:
        api.store.put(db, NS, domain + "_active_revision",
                      "current:v" + active_version, active)
    confirmed = {
        "id": domain + ":current", "version": next_version,
        "state": "CONFIRMED", "source_type": "SIMULATED",
        "author_identity": "BOSS", "content": draft["content"],
        "content_sha256": draft["content_sha256"],
        "source_draft_version": draft["version"],
        "authorization_id": auth, "confirmed_at": now(),
    }
    api.store.put(db, NS, domain + "_active", "current", confirmed)
    return {
        "source_type": "SIMULATED", "state": "CONFIRMED",
        "version": next_version,
        "source_draft_version": draft["version"],
        "authorization_id": auth,
        "active_adoptable": True, "external_delivery_performed": False,
    }


GOAL_FIELDS = {"goals", "topics", "reading_requirement", "scope", "valid_until"}
NOTICE_FIELDS = {
    "timezone", "quiet_start", "quiet_end", "notifications_enabled",
    "important_during_quiet", "reading_format",
    "visibility", "calendar_share_limit", "valid_until",
}


def goals_save(api, db, data, payload):
    return _save(api, db, data, payload, "owner_goals", GOAL_FIELDS, _goal_content)


def goals_confirm(api, db, data, payload):
    return _confirm(api, db, data, payload, "owner_goals")


def notice_save(api, db, data, payload):
    return _save(api, db, data, payload, "owner_notice", NOTICE_FIELDS,
                 _notification_content)


def notice_confirm(api, db, data, payload):
    return _confirm(api, db, data, payload, "owner_notice")


def _effective(db, data, domain, namespace=NS):
    space = db.execute("SELECT active FROM spaces WHERE namespace=?", (namespace,)).fetchone()
    require(space is not None and space[0] == 1, "执行空间已失效")
    active = _get(db, domain + "_active", namespace=namespace)
    if active is None or active.get("state") != "CONFIRMED":
        return None
    authorization = _get(db, "authorization", active["authorization_id"], namespace=namespace)
    require(authorization is not None, "本人设置缺少确认授权", web.HTTPConflict)
    require(active["id"] == domain + ":current" and active["author_identity"] == "BOSS"
            and active["source_type"] == "SIMULATED"
            and authorization["authorization_id"] == active["authorization_id"]
            and authorization["owner_id"] == data["owner_id"]
            and authorization["scope"] == namespace
            and authorization["issuer_identity"] == "BOSS"
            and authorization["issuer"] == data["owner_id"]
            and authorization["action"] == domain + ".confirm"
            and authorization["target_id"] == active["id"]
            and int(authorization["content_version"]) + 1 == int(active["version"])
            and authorization["payload"]["active_version"] == authorization["content_version"]
            and authorization["payload"]["draft_version"] == active["source_draft_version"]
            and authorization["payload"]["content_sha256"] == active["content_sha256"] == checksum(active["content"]),
            "本人设置与当前确认授权的身份、范围或内容绑定不符", web.HTTPForbidden)
    if authorization["revoked"]:
        return None
    expiry = active["content"].get("valid_until")
    if expiry is not None:
        clock = _get(db, "clock", namespace=namespace)
        require(clock is not None, "当前执行空间缺少业务时钟")
        if datetime.fromisoformat(expiry) <= datetime.fromisoformat(clock["at"]):
            return None
    return active


def effective_owner_goals(db, data, namespace=NS):
    return _effective(db, data, "owner_goals", namespace)


def effective_owner_notice(db, data, namespace=NS):
    return _effective(db, data, "owner_notice", namespace)


def owner_goal_reference(db, data, namespace=NS):
    effective = effective_owner_goals(db, data, namespace)
    if not effective or effective["content"]["scope"] not in ("OWNER_WORKSPACE", "MEETING_PREP"):
        return {"status": "NO_APPLICABLE_CONFIRMED_MEETING_GOALS",
                "active_version": None, "scope": None}
    return {
        "status": "CONFIRMED", "active_version": effective["version"],
        "scope": effective["content"]["scope"],
        "goal_count": len(effective["content"]["goals"]),
        "topic_count": len(effective["content"]["topics"]),
    }


def owner_profile(db, data, namespace=NS):
    active = effective_owner_goals(db, data, namespace)
    if active is None or active["content"]["scope"] not in (
        "OWNER_WORKSPACE", "DAILY_BRIEF",
    ):
        return {
            "timezone": data["boss_profile"]["timezone"],
            "goals": [], "reading_requirement": None, "topics": [],
            "owner_confirmation": "NOT_CONFIRMED",
            "sample_profile_present": True, "active_version": None,
        }
    content = active["content"]
    return {
        "timezone": data["boss_profile"]["timezone"],
        "goals": content["goals"],
        "reading_requirement": content["reading_requirement"],
        "topics": content["topics"],
        "owner_confirmation": "CONFIRMED", "active_version": active["version"],
        "applicability": content["scope"],
    }


def record_runtime_goal_context_load(store, namespace=NS):
    """A context-provider invocation is NOT proof the model followed a goal."""
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        store.active(db, namespace)
        data = store.get(db, namespace, "initial", "snapshot")
        active = effective_owner_goals(db, data, namespace)
        if active is None or active["content"]["scope"] != "OWNER_WORKSPACE":
            # The generic chat context cannot prove a DAILY_BRIEF/MEETING_PREP
            # request. Do not leak scoped instructions into unrelated turns.
            return None
        current = _get(db, "owner_goals_runtime_use", active["version"], namespace=namespace)
        count = int(current.get("context_load_count", 0)) if current else 0
        observation = {
            "active_version": active["version"],
            "context_load_count": count + 1,
            "last_loaded_at": now(),
            "observation": "RUNTIME_CONTEXT_PROVIDER_INVOKED",
            "actual_model_compliance_verified": False,
        }
        store.put(db, namespace, "owner_goals_runtime_use",
                  active["version"], observation)
        return {
            "version": active["version"], "scope": active["content"]["scope"],
            "goals": active["content"]["goals"],
            "topics": active["content"]["topics"],
            "reading_requirement": active["content"]["reading_requirement"],
            "source": "BOSS_CONFIRMED",
            "applies_only_within_scope": True,
        }


def goals_projection(api, db, data):
    draft = _get(db, "owner_goals_draft")
    active = _get(db, "owner_goals_active")
    effective = effective_owner_goals(db, data)
    count = _get(db, "owner_goals_runtime_use", active["version"]) if active else None
    return {
        "draft": draft, "active": active,
        "active_is_effective": bool(effective),
        "current_owner_profile": owner_profile(db, data),
        "runtime_context_observation": count or {
            "context_load_count": 0, "observation": "NOT_OBSERVED",
            "actual_model_compliance_verified": False,
        },
        "history": [{
            "version": r["version"], "state": r["state"],
            "confirmed_at": r.get("confirmed_at"),
        } for r in _versions(db, "owner_goals_active_revision")],
        "fixture_goals_are_owner_confirmed": False,
        "owner_permissions": "BOSS_ONLY",
    }


def notice_projection(api, db, data):
    draft = _get(db, "owner_notice_draft")
    active = _get(db, "owner_notice_active")
    effective = effective_owner_notice(db, data)
    tech = _get(db, "rules")
    schedule = api.store.get(db, NS, "schedule", "current")
    return {
        "draft": draft, "active": active,
        "active_is_effective": bool(effective),
        "technical_rules": {
            k: tech[k] for k in (
                "version", "quiet_start", "quiet_end", "timezone",
                "important_escalation", "cooldown_seconds",
            ) if tech and k in tech
        },
        "technical_schedule": {
            k: schedule[k] for k in ("version", "enabled", "canceled")
            if k in schedule
        },
        "history": [{
            "version": r["version"], "state": r["state"],
            "confirmed_at": r.get("confirmed_at"),
        } for r in _versions(db, "owner_notice_active_revision")],
        "sharing_externally_authorized_here": False,
        "calendar_share_per_contact_requires_F12": True,
        "owner_permissions": "BOSS_ONLY",
    }


def owner_notification_suppression(db, data, clock, event, technical_rules, namespace=NS):
    """Only add restrictions; never override technical suppressions.

    OWNER-important override applies to OWNER quiet hours only when the
    technical rule also allows escalation. No new event is created here.
    """
    active = effective_owner_notice(db, data, namespace)
    if active is None:
        return None, None
    content = active["content"]
    if not content["notifications_enabled"]:
        return "OWNER_NOTIFICATIONS_PAUSED", active["version"]
    hour = clock.astimezone(ZoneInfo(content["timezone"])).hour
    start, end = content["quiet_start"], content["quiet_end"]
    quiet = (hour >= start or hour < end) if start > end else (
        start <= hour < end if start < end else False
    )
    if quiet and not (
        content["important_during_quiet"]
        and technical_rules["important_escalation"]
        and event["impact"] == "IMPORTANT"
    ):
        return "OWNER_QUIET_HOURS", active["version"]
    return None, active["version"]
