import json


def notification_snapshot(db, namespace, event, notification):
    result = {**notification, "event_snapshot": event}
    if event.get("task_id"):
        found = db.execute("SELECT body FROM objects WHERE namespace=? AND kind='task' AND id=?",
                           (namespace, event["task_id"])).fetchone()
        if found:
            task = json.loads(found[0])
            result["task_snapshot"] = {key: task[key] for key in (
                "task_id", "version", "objective", "coordinator_id", "due_at", "status", "deliverable",
                "evidence_requirement", "source_refs", "source_versions",
            ) if key in task}
    return result
