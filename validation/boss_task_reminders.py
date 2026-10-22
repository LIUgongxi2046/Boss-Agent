"""FR-06 task reminder lifecycle tied to owner-authorized business state.

An OPEN draft has NO reminder. Independently authorized send creates a
versioned task-due event. Extensions CAS-update its deadline; completion
and cancellation revoke further due dispatch. The actual CronService remains
the only dispatcher and requires enabled rules. All updates share the
original business SQLite BEGIN IMMEDIATE transaction and idempotency key.
"""
from __future__ import annotations

import json

from business import now, require

NS = "ui-check"
TERMINAL = frozenset({"CANCELED", "COMPLETED_CONFIRMED"})


def current(db, task_id):
    record = db.execute(
        "SELECT body FROM objects WHERE namespace=? AND kind='event' AND id=?",
        (NS, "task-due:" + task_id),
    ).fetchone()
    return json.loads(record[0]) if record else None


def synchronize_task_due(store, db, task, *, reason):
    task_id = task["task_id"]
    old = current(db, task_id)
    event_id = "task-due:" + task_id
    if old is None:
        require(reason == "AUTHORIZED_SEND" and
                task["status"] == "WAITING_FEEDBACK",
                "未经老板发送的草稿不能创建催办事件")
        version = "1"
        state = "OPEN"
    else:
        require(reason in ("AUTHORIZED_EXTEND", "OWNER_CANCEL", "OWNER_COMPLETE"),
                "当前事件变更动作不合法")
        require(old.get("task_id") == task_id and
                old.get("source_type") == "SIMULATED",
                "任务催办事件来源或归属不符")
        version = str(int(old["version"]) + 1)
        state = "CANCELED" if task["status"] in TERMINAL else "OPEN"
    data = {
        "event_id": event_id,
        "task_id": task_id,
        "version": version,
        "state": state,
        "impact": "NORMAL",
        "due_at": task["due_at"],
        "source_type": "SIMULATED",
        "generated_by": "BOSS_AUTHORIZED_TASK",
        "task_version": task["version"],
        "updated_at": now(),
        "transition_reason": reason,
        "automatic_external_delivery": False,
    }
    store.put(db, NS, "event", event_id, data)
    return {
        "event_id": event_id, "event_version": version,
        "event_state": state,
        "task_id": task_id, "task_version": task["version"],
        "due_at": task["due_at"],
        "cron_dispatch_claimed": False,
    }
