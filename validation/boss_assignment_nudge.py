"""FR-06 independently authorized follow-up nudges.

A nudge is not an initial assignment, task-state transition, result or
delivery receipt. It is a version-bound BOSS-confirmed SIMULATED outbox record.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from aiohttp import web

from business import checksum, now, require

NS = "ui-check"


def nudge(api, db, data, payload, key):
    api._exact(payload, {
        "client_request_id", "task_id", "task_version", "recipient_id", "body",
    })
    task = api.store.get(db, NS, "task", payload["task_id"])
    require(task["version"] == payload["task_version"], "交办已变更，请重新核对版本")
    require(task["status"] in ("WAITING_FEEDBACK", "IN_PROGRESS"),
            "仅已发送且尚未提交结果的交办允许本人催办")
    require(task["coordinator_id"] == payload["recipient_id"],
            "催办收件人不是当前任务负责人", web.HTTPForbidden)
    require(isinstance(payload["body"], str)
            and 1 <= len(payload["body"].strip()) <= 2400,
            "催办正文须为1—2400字", web.HTTPBadRequest)
    # Re-check both source pins and any referenced original minute before send.
    api._require_current_task_sources(db, data, task)
    clock = api.store.get(db, NS, "clock", "current")
    now_at = datetime.fromisoformat(clock["at"])
    contact = next((c for c in data["contacts"]
                    if c["contact_id"] == task["coordinator_id"]), None)
    require(contact is not None
            and contact["valid_from"] <= now_at.date().isoformat()
            <= contact["valid_until"],
            "负责人身份已不在当前有效期内", web.HTTPForbidden)
    # Use a server-side per-task+version delivery cooldown (not a client flag).
    existing = db.execute(
        "SELECT body FROM objects WHERE namespace=? AND kind='assignment_nudge'"
        " ORDER BY id",
        (NS,),
    ).fetchall()
    import json
    latest = None
    for row in existing:
        item = json.loads(row[0])
        if item["task_id"] != task["task_id"]:
            continue
        if latest is None or item["business_at"] > latest["business_at"]:
            latest = item
    if latest is not None:
        prev = datetime.fromisoformat(latest["business_at"])
        require((now_at - prev).total_seconds() >= 86400,
                "本交办24小时模拟业务时钟内已有催办记录，禁止重复发送")
    msg_id = "sim-nudge-" + str(uuid.uuid4())
    bound = {
        "task_id": task["task_id"],
        "task_version": task["version"],
        "recipient_id": task["coordinator_id"],
        "body_sha256": checksum(payload["body"].strip()),
        "business_at": clock["at"],
    }
    auth_id = api._authorize(
        db, "assignment.nudge", bound, task["task_id"], task["version"],
    )
    message = {
        "message_id": msg_id, "task_id": task["task_id"],
        "task_version": task["version"],
        "recipient_id": task["coordinator_id"],
        "body": payload["body"].strip(),
        "body_sha256": bound["body_sha256"],
        "authorization_id": auth_id,
        "business_at": clock["at"],
        "sent_at": now(),
        "message_status": "SENT_SIMULATED",
        "delivery_state": "NOT_VERIFIED",
        "reply_state": "NOT_RECEIVED",
        "external_channel_invoked": False,
        "source_type": "SIMULATED",
    }
    # Both indexes are part of the one shared SQLite transaction.
    api.store.put(db, NS, "assignment_nudge", msg_id, message)
    return {
        "source_type": "SIMULATED",
        "task_id": task["task_id"], "task_version": task["version"],
        "status": task["status"], "version": task["version"],
        "message_id": msg_id, "recipient_id": task["coordinator_id"],
        "send_state": "SENT_SIMULATED",
        "delivery_state": "NOT_VERIFIED",
        "reply_state": "NOT_RECEIVED",
        "authorization_id": auth_id,
        "cooldown_seconds": 86400,
        "external_channel_invoked": False,
        "task_status_changed": False,
    }
