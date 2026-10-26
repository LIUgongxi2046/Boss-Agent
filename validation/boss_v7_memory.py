from aiohttp import web
from uuid import uuid4

from business import checksum, now, require
from boss_memory import confirmed_memory, current_memory
from boss_owner_history import owner_spaces
from boss_v7_store import NAMESPACE, aware_time, optional, rows, text


def _view(memory, state=None):
    return {
        "memory_id": memory["memory_id"], "version": memory["version"],
        "text": memory.get("text", ""), "state": state or memory["confirmation_state"],
        "visibility": memory.get("visibility", "BOSS_ONLY"), "valid_until": memory.get("valid_until"),
        "source_note": memory.get("source_note", ""), "confirmed_at": memory.get("confirmed_at"),
        "authorization_id": memory.get("authorization_id"), "source_ids": memory.get("source_ids", []),
    }


def archived_memory(db, snapshot):
    result = []
    for namespace, initial, archive in owner_spaces(db, snapshot):
        if archive is None:
            continue
        current = current_memory(db, namespace)
        versions = rows(db, "memory_revision", namespace)
        if current is not None:
            versions.append(current)
        deleted_through = {}
        for memory in versions:
            if memory["confirmation_state"] == "DELETED":
                deleted_through[memory["memory_id"]] = max(deleted_through.get(memory["memory_id"], 0), int(memory["version"]))
        for memory in versions:
            view = _view(memory)
            if int(memory["version"]) <= deleted_through.get(memory["memory_id"], 0):
                view.update(text="", source_note="", source_ids=[], state="DELETED")
            result.append({**view, "namespace": namespace, "dataset_id": initial["dataset_id"],
                           "dataset_version": initial["dataset_version"], "archived_at": archive["archived_at"],
                           "effective_state": "READ_ONLY_HISTORY", "current_evidence_eligible": False})
    return sorted(result, key=lambda row: (row["archived_at"], row["namespace"], int(row["version"])), reverse=True)


def read_memory(store, db, snapshot):
    current = current_memory(db, NAMESPACE)
    candidate = optional(db, "memory", "candidate")
    eligible = confirmed_memory(db, NAMESPACE, current, snapshot["owner_id"]) is not None
    state = current["confirmation_state"] if current else "ABSENT"
    if state == "CONFIRMED" and not eligible:
        state = "NOT_EFFECTIVE"
    adoption = []
    for run in rows(db, "runtime_run"):
        reference = run.get("memory_reference")
        if current and reference and reference.get("memory_id") == current["memory_id"] and reference.get("eligible") is True:
            adoption.append({"session_id": run["session_id"], "memory_version": reference["version"],
                             "adopted_at": run["started_at"], "scope": run["namespace"]})
    deleted = current is not None and current["confirmation_state"] == "DELETED"
    propagation = optional(db, "memory_deletion", current["memory_id"]) if current else None
    return {
        "current": _view(current, state) if current else None, "candidate": _view(candidate) if candidate else None,
        "history": [_view(row) for row in sorted(rows(db, "memory_revision"), key=lambda value: int(value["version"]), reverse=True)],
        "archived_history": archived_memory(db, snapshot),
        "adoption": sorted(adoption, key=lambda value: value["adopted_at"], reverse=True),
        "deletion": {"state": propagation["state"] if propagation else "NOT_REQUESTED",
                     "future_adoption": "STOPPED" if deleted or not eligible else "CURRENT_CONFIRMED_VERSION",
                     "index_state": propagation["index_state"] if propagation else "NO_DERIVED_MEMORY_INDEX",
                     "failure_reason": propagation.get("failure_reason") if propagation else None,
                     "requested_at": propagation["requested_at"] if propagation else None,
                     "loaded_sessions": propagation.get("loaded_sessions", "NOT_VERIFIED") if propagation else "NOT_REQUESTED",
                     "sessions_checked": propagation.get("sessions_checked") if propagation else None,
                     "sessions_checked_at": propagation.get("sessions_checked_at") if propagation else None,
                     "backups": propagation.get("backups", "NOT_VERIFIED") if propagation else "NOT_REQUESTED"},
    }


def delete_memory_records(store, db, current, authorization):
    updated = {**current, "text": "", "source_note": "", "source_ids": [], "confirmation_state": "DELETED",
               "version": str(int(current["version"]) + 1), "memory_version": str(int(current["version"]) + 1),
               "deleted_at": now(), "deletion_authorization_id": authorization}
    store.put(db, NAMESPACE, "memory_revision", current["memory_id"] + ":" + current["version"],
              {**updated, "version": current["version"], "memory_version": current["version"]})
    store.put(db, NAMESPACE, "memory", "current", updated)
    for revision in rows(db, "memory_revision"):
        if revision["memory_id"] == current["memory_id"]:
            revision.update(text="", source_note="", source_ids=[], confirmation_state="DELETED")
            store.put(db, NAMESPACE, "memory_revision", revision["memory_id"] + ":" + revision["version"], revision)
    db.execute("DELETE FROM objects WHERE namespace=? AND kind='memory' AND id='candidate'", (NAMESPACE,))
    store.put(db, NAMESPACE, "memory_deletion", current["memory_id"], {
        "state": "CURRENT_AND_HISTORY_CLEARED", "index_state": "NO_DERIVED_MEMORY_INDEX",
        "requested_at": now(), "version": updated["version"], "failure_reason": None,
        "loaded_sessions": "REQUIRES_CONTEXT_REFRESH", "backups": "NOT_VERIFIED",
    })
    return updated


def mutate_memory(api, db, snapshot, action, payload):
    if action == "reconcile":
        api._exact(payload, {"client_request_id", "expected_version"})
        current = current_memory(db, NAMESPACE)
        require(current is not None and current["confirmation_state"] == "DELETED", "当前没有已确认的删除请求")
        require(current["version"] == payload["expected_version"], "个人要求版本已经变化")
        require(api.runtime_control is not None, "原生会话服务尚未准备", web.HTTPServiceUnavailable)
        return {"memory_id": current["memory_id"], "version": current["version"], "state": "PROPAGATION_REQUESTED"}
    common = {"client_request_id", "expected_version", "expected_candidate_version", "confirmation"}
    api._exact(payload, common | ({"values"} if action == "confirm" else set()))
    require(payload["confirmation"] is True, "需要本人确认当前操作", web.HTTPForbidden)
    current = current_memory(db, NAMESPACE)
    candidate = optional(db, "memory", "candidate")
    require((current["version"] if current else "0") == payload["expected_version"], "个人要求版本已经变化")
    require((candidate["version"] if candidate else "0") == payload["expected_candidate_version"], "候选要求版本已经变化")
    if action == "confirm":
        previous = current
        if current is None:
            current = {"memory_id": "memory-" + str(uuid4()), "version": "0"}
        values = payload["values"]
        require(isinstance(values, dict), "要求字段无效", web.HTTPBadRequest)
        api._exact(values, {"text", "visibility", "valid_until", "source_note"})
        content = text(values["text"], "个人要求")
        source_note = text(values["source_note"], "来源说明", 1600)
        require(values["visibility"] in {"BOSS_ONLY", "AUTHORIZED_SHARED"}, "可见范围无效", web.HTTPBadRequest)
        until = aware_time(values["valid_until"]) if values["valid_until"] is not None else None
        clock = aware_time(api.store.get(db, NAMESPACE, "clock", "current")["at"])
        require(until is None or until > clock, "有效期限需要晚于当前业务时间", web.HTTPBadRequest)
        authorization = api._authorize(db, "memory.confirm", {
            "expected_version": current["version"], "text_sha256": checksum({"text": content}),
            "visibility": values["visibility"], "valid_until": values["valid_until"], "source_note_sha256": checksum(source_note),
        }, current["memory_id"], current["version"])
        if previous is not None:
            api.store.put(db, NAMESPACE, "memory_revision", current["memory_id"] + ":" + current["version"], current)
        updated = {**current, "text": content, "source_note": source_note, "visibility": values["visibility"],
                   "valid_until": until.isoformat() if until else None, "confirmed_at": now(),
                   "confirmation_state": "CONFIRMED", "authorization_id": authorization,
                   "version": str(int(current["version"]) + 1), "memory_version": str(int(current["version"]) + 1)}
        api.store.put(db, NAMESPACE, "memory", "current", updated)
        if candidate:
            db.execute("DELETE FROM objects WHERE namespace=? AND kind='memory' AND id='candidate'", (NAMESPACE,))
    else:
        require(action == "delete", "未知个人要求操作", web.HTTPBadRequest)
        require(current is not None, "当前没有可删除的个人要求", web.HTTPNotFound)
        require(current["confirmation_state"] != "DELETED", "该要求已经删除")
        authorization = api._authorize(db, "memory.delete", {"expected_version": current["version"]}, current["memory_id"], current["version"])
        updated = delete_memory_records(api.store, db, current, authorization)
    return {"memory_id": current["memory_id"], "version": updated["version"],
            "state": updated["confirmation_state"], "authorization_id": authorization}
