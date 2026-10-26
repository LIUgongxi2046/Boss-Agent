"""A13 technical scheduling configuration, validated activation and safe pause.

MAINTAINER only. Saving or validating a technical draft does not activate it
or create events. Activation changes the local simulated scheduler and rules,
not BOSS business authorization, external messaging, or personal preferences.
"""
from __future__ import annotations

import json
from zoneinfo import ZoneInfo
from croniter import croniter

from aiohttp import web
from business import now, require

from boss_execution_scope import NAMESPACE as NS
TRIGGER = "EVENT_OR_TIME"
PLAN_DEFAULTS = {"name": "本人获准事件检查", "executor_component": "CronService", "expression": "* * * * *",
                 "authorized_scope": ["SIMULATED_EVENTS", "OWNER_TASKS", "OWNER_COMMITMENTS", "OWNER_PLANS", "BUSINESS_ALERTS"],
                 "restart_policy": "CHECK_DUE_ON_RESTART"}
SCOPES = {"SIMULATED_EVENTS": "获准模拟事件", "OWNER_TASKS": "本人授权任务", "OWNER_COMMITMENTS": "本人承诺",
          "OWNER_PLANS": "本人计划", "BUSINESS_ALERTS": "经营提醒"}
RESTART_POLICIES = {"CHECK_DUE_ON_RESTART": "重启后核查当前到期事项", "PAUSE_ON_RESTART": "重启后暂停等待手动恢复"}


def plan_fields(body):
    return {key: body.get(key, value) for key, value in PLAN_DEFAULTS.items()}


def event_in_scope(schedule, event):
    scope = "OWNER_PLANS" if event.get("owner_plan_id") else {
        "BOSS_AUTHORIZED_TASK": "OWNER_TASKS", "BOSS_OWN_COMMITMENT": "OWNER_COMMITMENTS",
        "BUSINESS_ALERT_INPUT": "BUSINESS_ALERTS",
    }.get(event.get("generated_by"), "SIMULATED_EVENTS")
    return scope in plan_fields(schedule)["authorized_scope"]


def _get(db, kind, key):
    row = db.execute(
        "SELECT body FROM objects WHERE namespace=? AND kind=? AND id=?",
        (NS, kind, key),
    ).fetchone()
    return json.loads(row[0]) if row else None


def _as_version(value):
    require(isinstance(value, str) and value.isdecimal() and len(value) <= 8,
            "缺少可识别的当前版本", web.HTTPBadRequest)
    return value


def _config(body):
    require(body.get("trigger") in {TRIGGER, "CRON", "EVENT"}, "调度触发类型无效",
            web.HTTPBadRequest)
    timezone = body.get("timezone")
    require(isinstance(timezone, str), "调度时区无效", web.HTTPBadRequest)
    ZoneInfo(timezone)
    plan = plan_fields(body)
    require(isinstance(plan["name"], str) and 0 < len(plan["name"].strip()) <= 120, "计划名称无效", web.HTTPBadRequest)
    require(plan["executor_component"] == "CronService", "执行责任组件必须为CronService", web.HTTPBadRequest)
    require(isinstance(plan["expression"], str) and (body["trigger"] == "EVENT" or croniter.is_valid(plan["expression"])),
            "调度表达式无效", web.HTTPBadRequest)
    require(isinstance(plan["authorized_scope"], list) and bool(plan["authorized_scope"])
            and all(isinstance(item, str) and item in SCOPES for item in plan["authorized_scope"])
            and len(set(plan["authorized_scope"])) == len(plan["authorized_scope"]), "获准任务范围无效", web.HTTPBadRequest)
    require(plan["restart_policy"] in RESTART_POLICIES, "重启恢复策略无效", web.HTTPBadRequest)
    for name in ("quiet_start", "quiet_end"):
        value = body.get(name)
        require(type(value) is int and 0 <= value <= 23,
                name + "必须为0—23的小时", web.HTTPBadRequest)
    cooldown = body.get("cooldown_seconds")
    require(type(cooldown) is int and 0 <= cooldown <= 86400,
            "去重冷却须为0—86400秒", web.HTTPBadRequest)
    require(type(body.get("important_escalation")) is bool,
            "重要提醒升级开关必须明确为布尔值", web.HTTPBadRequest)
    return {
        **plan,
        "trigger": body["trigger"],
        "timezone": timezone,
        "quiet_start": body["quiet_start"],
        "quiet_end": body["quiet_end"],
        "cooldown_seconds": cooldown,
        "important_escalation": body["important_escalation"],
    }


def save(api, db, data, payload):
    fields = {
        "client_request_id", "expected_version", "trigger", "timezone",
        "quiet_start", "quiet_end", "cooldown_seconds",
        "important_escalation",
    }
    require(set(payload) in (fields, fields | set(PLAN_DEFAULTS)), "调度字段缺少或包含未知字段", web.HTTPBadRequest)
    proposed = _config(payload)
    existing = _get(db, "scheduler_draft", "current")
    original = existing["version"] if existing else "0"
    require(_as_version(payload["expected_version"]) == original,
            "技术调度草稿版本变化，须重新核查")
    next_version = str(int(original) + 1)
    if existing:
        api.store.put(db, NS, "scheduler_draft_revision",
                      "current:v" + original, existing)
    draft = {
        "draft_id": "schedule-draft",
        "version": next_version,
        "configuration": proposed,
        "validation_state": "DRAFT",
        "validated_at": None,
        "activated_at": None,
        "source_type": "SIMULATED",
        "saved_at": now(),
        "schedule_activated": False,
    }
    api.store.put(db, NS, "scheduler_draft", "current", draft)
    return {
        "source_type": "SIMULATED", "draft_id": draft["draft_id"],
        "version": next_version, "validation_state": "DRAFT",
        "schedule_activated": False, "business_action_executed": False,
    }


def validate(api, db, data, payload):
    api._exact(payload, {"client_request_id", "expected_version"})
    draft = api.store.get(db, NS, "scheduler_draft", "current")
    require(draft["version"] == _as_version(payload["expected_version"]),
            "调度草稿版本冲突")
    require(draft["validation_state"] == "DRAFT",
            "调度草稿已验证或启用；不能重复使用新请求")
    _config(draft["configuration"])
    schedule = api.store.get(db, NS, "schedule", "current")
    require(not schedule["canceled"],
            "调度已被明确取消，禁止在原执行空间重新启动")
    api.store.put(db, NS, "scheduler_draft_revision",
                  "current:v" + draft["version"], draft)
    draft["version"] = str(int(draft["version"]) + 1)
    draft["validation_state"] = "VALIDATED"
    draft["validated_at"] = now()
    draft["schedule_version_at_validation"] = schedule["version"]
    api.store.put(db, NS, "scheduler_draft", "current", draft)
    return {
        "source_type": "SIMULATED",
        "draft_id": draft["draft_id"], "version": draft["version"],
        "validation_state": "VALIDATED", "schedule_activated": False,
        "business_action_executed": False,
    }


def activate(api, db, data, payload):
    api._exact(payload, {
        "client_request_id", "expected_draft_version",
        "expected_schedule_version", "expected_rules_version",
    })
    draft = api.store.get(db, NS, "scheduler_draft", "current")
    schedule = api.store.get(db, NS, "schedule", "current")
    rules = _get(db, "rules", "current")
    old_rules = rules["version"] if rules else "0"
    require(draft["version"] == _as_version(payload["expected_draft_version"])
            and draft["validation_state"] == "VALIDATED",
            "只能启用已经验证的当前草稿")
    require(schedule["version"] == _as_version(payload["expected_schedule_version"]),
            "调度当前版本变化，须重新读取")
    require(old_rules == _as_version(payload["expected_rules_version"]),
            "提醒规则版本变化，须重新核查")
    require(schedule["version"] == draft.get("schedule_version_at_validation"),
            "草稿校验后调度被其他操作改变，必须重新验证")
    require(not schedule["canceled"],
            "已经取消的原执行计划不能恢复或重新启用")
    cfg = _config(draft["configuration"])
    schedule = {
        **schedule, "version": str(int(schedule["version"]) + 1),
        "schedule_version": str(int(schedule["schedule_version"]) + 1),
        "timezone": cfg["timezone"], "trigger": cfg["trigger"],
        **plan_fields(cfg),
        "enabled": True, "canceled": False,
        "active_draft_version": draft["version"],
        "last_configured_at": now(),
    }
    next_rules = {
        "version": str(int(old_rules) + 1),
        "timezone": cfg["timezone"],
        "quiet_start": cfg["quiet_start"],
        "quiet_end": cfg["quiet_end"],
        "cooldown_seconds": cfg["cooldown_seconds"],
        "important_escalation": cfg["important_escalation"],
    }
    api.store.put(db, NS, "schedule", "current", schedule)
    api.store.put(db, NS, "rules", "current", next_rules)
    draft["validation_state"] = "ACTIVE"
    draft["activated_at"] = now()
    api.store.put(db, NS, "scheduler_draft", "current", draft)
    return {
        "source_type": "SIMULATED", "schedule_id": schedule["schedule_id"],
        "version": schedule["version"], "schedule_version": schedule["schedule_version"],
        "rules_version": next_rules["version"],
        "validation_state": "ACTIVE", "enabled": True,
        "external_message_sent": False, "owner_authorization_granted": False,
        "manual_dispatch_executed": False,
    }


def set_status(api, db, data, payload, action):
    api._exact(payload, {"client_request_id", "expected_version"})
    schedule = api.store.get(db, NS, "schedule", "current")
    require(schedule["version"] == _as_version(payload["expected_version"]),
            "调度配置版本变化，请刷新")
    if action == "pause":
        require(schedule["enabled"] and not schedule["canceled"],
                "当前调度未启用或已取消")
        schedule["enabled"] = False
    elif action == "resume":
        require(not schedule["enabled"] and not schedule["canceled"],
                "取消的计划不能恢复，或调度已经启用")
        schedule["enabled"] = True
    elif action == "cancel":
        require(not schedule["canceled"], "该计划已取消")
        schedule["enabled"] = False
        schedule["canceled"] = True
    else:
        raise web.HTTPBadRequest(text="技术调度动作无效")
    schedule["version"] = str(int(schedule["version"]) + 1)
    schedule["schedule_version"] = str(int(schedule["schedule_version"]) + 1)
    schedule["last_configured_at"] = now()
    api.store.put(db, NS, "schedule", "current", schedule)
    return {
        "source_type": "SIMULATED", "schedule_id": schedule["schedule_id"],
        "version": schedule["version"],
        "schedule_version": schedule["schedule_version"],
        "enabled": schedule["enabled"], "canceled": schedule["canceled"],
        "manual_dispatch_executed": False, "external_message_sent": False,
        "owner_authorization_granted": False,
    }



def manual_run(api, db, data, payload):
    """Run the actual *simulated* dispatcher for ONE versioned approved event."""
    api._exact(payload, {
        "client_request_id", "event_id", "event_version",
        "expected_schedule_version", "expected_rules_version",
    })
    schedule = api.store.get(db, NS, "schedule", "current")
    rules = _get(db, "rules", "current")
    require(schedule["enabled"] and not schedule["canceled"]
            and isinstance(schedule.get("active_draft_version"), str),
            "手动调度需已经验证并启用的技术计划；当前未满足")
    require(schedule["version"] == _as_version(payload["expected_schedule_version"]),
            "调度启用版本变化，必须重新读取")
    require(rules is not None and rules["version"] ==
            _as_version(payload["expected_rules_version"]),
            "提醒规则版本变化，请重新检查")
    identifier = payload["event_id"]
    require(isinstance(identifier, str) and 0 < len(identifier) <= 128,
            "事件标识无效", web.HTTPBadRequest)
    event = api.store.get(db, NS, "event", identifier)
    require(event["version"] == payload["event_version"],
            "当前事件版本变化，禁止按旧版本触发")
    # Technical operation never edits or creates arbitrary business events.
    allowed = identifier == data["event"]["event_id"] or event.get("generated_by") in (
        "BOSS_AUTHORIZED_TASK", "BOSS_OWN_COMMITMENT", "BUSINESS_ALERT_INPUT",
    )
    require(allowed and event.get("source_type") == "SIMULATED",
            "事件并非获准模拟数据或已授权业务范围", web.HTTPForbidden)
    require(event_in_scope(schedule, event), "事件不在当前计划的获准范围", web.HTTPForbidden)
    result = api.store.dispatch_due_in_transaction(
        db, NS, only_event_id=identifier,
    )
    outcome = result[0] if result else None
    return {
        "source_type": "SIMULATED",
        "event_id": identifier, "event_version": event["version"],
        "schedule_version": schedule["version"],
        "rules_version": rules["version"],
        "dispatch_state": outcome["state"] if outcome else "NOT_DUE",
        "dispatch_reason": outcome["reason"] if outcome else "EVENT_NOT_YET_DUE",
        "business_at": outcome["business_at"] if outcome else
                       api.store.get(db, NS, "clock", "current")["at"],
        "manual_dispatch_executed": True,
        "external_message_sent": False,
        "external_delivery_verified": False,
        "owner_business_authorization_granted": False,
    }
