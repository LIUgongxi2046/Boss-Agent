import json
from datetime import datetime
from pathlib import Path

from business import encode


def append_memory_deletion(store, db, namespace, previous, updated, authorization_id):
    if not db.in_transaction:
        raise ValueError("记忆删除记录需要当前事务")
    initial = store.get(db, namespace, "initial", "snapshot")
    authorization = store.get(db, namespace, "authorization", authorization_id)
    if (authorization.get("authorization_id") != authorization_id or authorization.get("action") != "memory.delete"
            or authorization.get("owner_id") != initial["owner_id"] or authorization.get("issuer_identity") != "BOSS"
            or authorization.get("scope") != namespace or authorization.get("target_id") != previous["memory_id"]
            or authorization.get("content_version") != previous["version"] or authorization.get("payload") != {"expected_version": previous["version"]}
            or authorization.get("revoked") is not False or updated.get("confirmation_state") != "DELETED"
            or updated.get("deletion_authorization_id") != authorization_id
            or updated.get("memory_id") != previous["memory_id"] or int(updated["version"]) != int(previous["version"]) + 1):
        raise ValueError("记忆删除授权或版本不可核查")
    identifier = previous["memory_id"] + ":" + updated["version"]
    event = {"event_id": identifier, "namespace": namespace, "owner_id": initial["owner_id"],
             "dataset_id": initial["dataset_id"], "dataset_version": initial["dataset_version"],
             "memory_id": previous["memory_id"], "previous_version": previous["version"],
             "deleted_version": updated["version"], "authorization_id": authorization_id,
             "deleted_at": updated["deleted_at"], "result": "CURRENT_AND_HISTORY_CLEARED"}
    db.execute("INSERT INTO objects VALUES (?,?,?,?)", (namespace, "memory_deletion_event", identifier, encode(event)))
    return identifier


def memory_deletion_event_exists(db, namespace, memory_id, version):
    identifier = memory_id + ":" + version
    row = db.execute("SELECT body FROM objects WHERE namespace=? AND kind='memory_deletion_event' AND id=?", (namespace, identifier)).fetchone()
    if row is None:
        return False
    event = json.loads(row[0])
    if not isinstance(event, dict) or event.get("event_id") != identifier or event.get("namespace") != namespace or event.get("memory_id") != memory_id or event.get("deleted_version") != version or event.get("result") != "CURRENT_AND_HISTORY_CLEARED":
        raise ValueError("记忆删除事件不可核查")
    auth_row = db.execute("SELECT body FROM objects WHERE namespace=? AND kind='authorization' AND id=?", (namespace, event.get("authorization_id"))).fetchone()
    if auth_row is None:
        raise ValueError("记忆删除事件缺少授权记录")
    authorization = json.loads(auth_row[0])
    if authorization.get("authorization_id") != event.get("authorization_id") or authorization.get("action") != "memory.delete" or authorization.get("target_id") != memory_id or authorization.get("content_version") != event.get("previous_version") or authorization.get("owner_id") != event.get("owner_id") or authorization.get("scope") != namespace or authorization.get("issuer_identity") != "BOSS" or authorization.get("payload") != {"expected_version": event.get("previous_version")} or int(version) != int(event["previous_version"]) + 1:
        raise ValueError("记忆删除事件授权不符")
    return True


def inspect_memory_deletion_history_in_transaction(store, db, namespace):
    main = db.execute("PRAGMA database_list").fetchone()
    if not db.in_transaction or main is None or main[1] != "main" or Path(main[2]).resolve() != store.path.resolve():
        raise ValueError("记忆删除历史核查需要同一数据库事务")
    store.active(db, namespace)
    initial = store.get(db, namespace, "initial", "snapshot")
    kinds = ("memory", "memory_revision", "memory_deletion", "memory_deletion_event")
    entries = db.execute("SELECT kind,id,body FROM objects WHERE namespace=? AND kind IN (?,?,?,?)", (namespace, *kinds)).fetchall()
    records = {(kind, identifier): json.loads(body) for kind, identifier, body in entries}
    if any(not isinstance(value, dict) for value in records.values()):
        raise ValueError("记忆删除历史记录格式无效")
    markers = {identifier: value for (kind, identifier), value in records.items() if kind == "memory_deletion"}
    events = {identifier: value for (kind, identifier), value in records.items() if kind == "memory_deletion_event"}
    pending = set()
    matched = set()
    for identifier, event in events.items():
        memory_id, version = event.get("memory_id"), event.get("deleted_version")
        previous = event.get("previous_version")
        if any(not isinstance(value, str) or not value for value in (memory_id, version, previous)) or not version.isascii() or not version.isdecimal() or str(int(version)) != version or not previous.isascii() or not previous.isdecimal() or str(int(previous)) != previous:
            raise ValueError("记忆删除事件版本无效")
        if identifier != memory_id + ":" + version or (event.get("owner_id"), event.get("dataset_id"), event.get("dataset_version")) != (initial["owner_id"], initial["dataset_id"], initial["dataset_version"]):
            raise ValueError("记忆删除事件身份不可核查")
        if not memory_deletion_event_exists(db, namespace, memory_id, version):
            raise ValueError("记忆删除事件不可核查")
        authorization = store.get(db, namespace, "authorization", event["authorization_id"])
        if authorization.get("issuer") != initial["owner_id"]:
            raise ValueError("记忆删除决定主体不可核查")
        at = datetime.fromisoformat(event["deleted_at"])
        start = datetime.fromisoformat(authorization["valid_from"])
        end = datetime.fromisoformat(authorization["valid_until"])
        if any(value.tzinfo is None or value.utcoffset() is None for value in (at, start, end)) or not start <= at < end:
            raise ValueError("记忆删除决定时间不可核查")
        marker = markers.get(memory_id)
        marker_version = marker.get("version") if marker is not None else None
        if not isinstance(marker_version, str) or not marker_version.isascii() or not marker_version.isdecimal() or int(marker_version) < int(version):
            pending.add("MEMORY_DELETION_MARKER_MISSING")
        else:
            matched.add((memory_id, version))
        if ("memory_revision", memory_id + ":" + previous) not in records:
            pending.add("MEMORY_DELETION_REVISION_MISSING")
        for (kind, _), revision in records.items():
            if kind != "memory_revision" or revision.get("memory_id") != memory_id:
                continue
            revision_version = revision.get("version")
            if not isinstance(revision_version, str) or not revision_version.isascii() or not revision_version.isdecimal():
                raise ValueError("记忆历史版本无效")
            if int(revision_version) <= int(previous) and (revision.get("confirmation_state") != "DELETED" or revision.get("text") != "" or revision.get("source_note") != "" or revision.get("source_ids") != []):
                pending.add("MEMORY_DELETED_CONTENT_REMAINS")
    for memory_id, marker in markers.items():
        version = marker.get("version")
        if not isinstance(version, str) or (memory_id, version) not in matched:
            pending.add("MEMORY_DELETION_HISTORY_MISSING")
        current = records.get(("memory", "current"))
        if current is None or current.get("memory_id") != memory_id:
            pending.add("MEMORY_DELETION_CURRENT_UNVERIFIED")
        elif isinstance(version, str) and version.isascii() and version.isdecimal():
            current_version = current.get("version")
            if not isinstance(current_version, str) or not current_version.isascii() or not current_version.isdecimal() or int(current_version) < int(version):
                pending.add("MEMORY_DELETION_CURRENT_UNVERIFIED")
            elif int(current_version) == int(version) and (current.get("confirmation_state") != "DELETED" or current.get("text") != "" or current.get("source_note") != "" or current.get("source_ids") != []):
                pending.add("MEMORY_DELETED_CONTENT_REMAINS")
    current = records.get(("memory", "current"))
    if current is not None and current.get("confirmation_state") == "DELETED" and current.get("memory_id") not in markers:
        pending.add("MEMORY_DELETION_HISTORY_MISSING")
    return {"event_count": len(events), "marker_count": len(markers), "pending": sorted(pending), "history_complete": False}


def require_memory_deletion_propagation_in_transaction(store, db, namespace):
    if db.execute("SELECT 1 FROM objects WHERE namespace=? AND kind='memory_deletion' LIMIT 1", (namespace,)).fetchone() is None:
        return {"event_count": 0, "marker_count": 0, "pending": []}
    result = inspect_memory_deletion_history_in_transaction(store, db, namespace)
    if result["pending"]:
        raise ValueError("个人记忆删除传播尚未核查")
    return result
