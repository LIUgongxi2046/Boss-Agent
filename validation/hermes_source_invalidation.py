import json
from pathlib import Path

from aiohttp import web

from business import checksum, now, require


def append_source_withdrawal_in_transaction(store, db, namespace, source_id, source_version, operation, request_id, receipt_kind):
    if not db.in_transaction or any(not isinstance(value, str) or not value for value in (namespace, source_id, source_version, operation, request_id)) or receipt_kind not in {"audit", "idempotency"}:
        raise ValueError("来源撤销事件参数无效")
    main = db.execute("PRAGMA database_list").fetchone()
    if main is None or main[1] != "main" or Path(main[2]).resolve() != store.path.resolve():
        raise ValueError("来源撤销事件需要当前数据库事务")
    initial = store.get(db, namespace, "initial", "snapshot")
    document = store.get(db, namespace, "document", source_id)
    if document.get("source_id") != source_id or document.get("access_scope") != initial["owner_id"] or document.get("withdrawn") is not True or not document.get("withdrawn_at"):
        raise ValueError("来源撤销结果不可核查")
    expected_version = source_version if receipt_kind == "audit" else str(int(source_version) + 1)
    if document.get("version") != expected_version:
        raise ValueError("来源撤销版本不可核查")
    if receipt_kind == "audit":
        row = db.execute("SELECT namespace,operation FROM audit WHERE id=?", (request_id,)).fetchone()
        if row != (namespace, operation):
            raise ValueError("来源撤销审计不可核查")
    existing = db.execute("SELECT id,body FROM objects WHERE namespace=? AND kind='source_withdrawal_event'", (namespace,)).fetchall()
    sequences = []
    for identifier, body in existing:
        event = json.loads(body)
        if not isinstance(event, dict) or event.get("event_id") != identifier or event.get("namespace") != namespace or type(event.get("sequence")) is not int or event["sequence"] <= 0:
            raise ValueError("来源撤销事件序号不可核查")
        sequences.append(event["sequence"])
    if sorted(sequences) != list(range(1, len(sequences) + 1)):
        raise ValueError("来源撤销事件序号不连续")
    event_id = checksum({"namespace": namespace, "operation": operation, "request_id": request_id})
    event = {"event_id": event_id, "sequence": len(sequences) + 1, "namespace": namespace,
             "owner_id": initial["owner_id"], "dataset_id": initial["dataset_id"], "dataset_version": initial["dataset_version"],
             "source_id": source_id, "source_version": source_version, "withdrawn_version": document["version"],
             "withdrawn_at": document["withdrawn_at"], "operation": operation, "request_id": request_id,
             "receipt_kind": receipt_kind, "result": "WITHDRAWN"}
    db.execute("INSERT INTO objects(namespace,kind,id,body) VALUES (?,?,?,?)", (namespace, "source_withdrawal_event", event_id, json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":"))))
    marker_row = db.execute("SELECT body FROM objects WHERE namespace=? AND kind='hermes_source_cleanup' AND id=?", (namespace, source_id)).fetchone()
    if marker_row is not None:
        marker = json.loads(marker_row[0])
        if marker.get("source_id") != source_id or marker.get("version") != source_version or marker.get("state") != "COMPLETED" or "withdrawal_event_id" in marker:
            raise ValueError("来源清理与撤销事件不符")
        marker["withdrawal_event_id"] = event_id
        store.put(db, namespace, "hermes_source_cleanup", source_id, marker)
    return event_id


def verify_source_withdrawals_in_transaction(store, db, namespace):
    main = db.execute("PRAGMA database_list").fetchone()
    if not db.in_transaction or main is None or main[1] != "main" or Path(main[2]).resolve() != store.path.resolve():
        raise ValueError("来源撤销事件核查需要当前数据库事务")
    db.execute("UPDATE spaces SET active=active WHERE 0")
    initial = store.get(db, namespace, "initial", "snapshot")
    rows = db.execute("SELECT id,body FROM objects WHERE namespace=? AND kind='source_withdrawal_event'", (namespace,)).fetchall()
    events = []
    deleted = set()
    for identifier, body in rows:
        event = json.loads(body)
        if not isinstance(event, dict) or event.get("event_id") != identifier or event.get("namespace") != namespace or type(event.get("sequence")) is not int or event["sequence"] <= 0:
            raise ValueError("来源撤销事件不可核查")
        expected_id = checksum({"namespace": namespace, "operation": event.get("operation"), "request_id": event.get("request_id")})
        if identifier != expected_id or (event.get("owner_id"), event.get("dataset_id"), event.get("dataset_version")) != (initial["owner_id"], initial["dataset_id"], initial["dataset_version"]) or event.get("result") != "WITHDRAWN":
            raise ValueError("来源撤销事件身份不可核查")
        document_row = db.execute("SELECT body FROM objects WHERE namespace=? AND kind='document' AND id=?", (namespace, event["source_id"])).fetchone()
        if document_row is None:
            deleted.add(event["source_id"])
            events.append(event)
            continue
        document = json.loads(document_row[0])
        if document.get("withdrawn") is not True or document.get("version") != event.get("withdrawn_version") or document.get("withdrawn_at") != event.get("withdrawn_at"):
            raise ValueError("来源撤销结果已经变化")
        if event.get("receipt_kind") == "audit":
            row = db.execute("SELECT operation,input,output FROM audit WHERE namespace=? AND id=?", (namespace, event.get("request_id"))).fetchone()
            if row is None or row[0] != event.get("operation") or json.loads(row[1]).get("source_id") != event["source_id"] or json.loads(row[1]).get("version") != event.get("source_version") or json.loads(row[2]).get("withdrawn") is not True:
                raise ValueError("来源撤销审计不可核查")
        elif event.get("receipt_kind") == "idempotency":
            row = db.execute("SELECT result FROM idempotency WHERE namespace=? AND operation=? AND key=?", (namespace, event.get("operation"), event.get("request_id"))).fetchone()
            result = json.loads(row[0]) if row is not None else None
            if isinstance(result, dict) and isinstance(result.get("result"), dict):
                result = result["result"]
            if not isinstance(result, dict) or result.get("source_id") != event["source_id"] or result.get("version") != event.get("withdrawn_version") or not (result.get("withdrawn") is True or result.get("record_state") == "WITHDRAWN"):
                raise ValueError("来源撤销回执不可核查")
            previous = store.get(db, namespace, "document_revision", event["source_id"] + ":v" + event["source_version"])
            if previous.get("source_id") != event["source_id"] or previous.get("version") != event["source_version"] or previous.get("withdrawn") is True or event["withdrawn_version"] != str(int(event["source_version"]) + 1):
                raise ValueError("来源撤销前版本不可核查")
        else:
            raise ValueError("来源撤销回执类型无效")
        marker = db.execute("SELECT body FROM objects WHERE namespace=? AND kind='hermes_source_cleanup' AND id=?", (namespace, event["source_id"])).fetchone()
        if marker is not None:
            cleanup = json.loads(marker[0])
            if cleanup.get("withdrawal_event_id") != identifier or cleanup.get("state") != "COMPLETED" or cleanup.get("version") != event.get("source_version"):
                raise ValueError("来源清理关联不可核查")
        events.append(event)
    if sorted(event["sequence"] for event in events) != list(range(1, len(events) + 1)):
        raise ValueError("来源撤销事件序号不连续")
    withdrawn = set()
    for identifier, body in db.execute("SELECT id,body FROM objects WHERE namespace=? AND kind='document'", (namespace,)):
        document = json.loads(body)
        if document.get("withdrawn") is True or document.get("validity_state") == "WITHDRAWN":
            withdrawn.add(identifier)
    missing = sorted((withdrawn - {event["source_id"] for event in events}) | deleted)
    return {"event_count": len(events), "missing_source_ids": missing, "history_complete": False}


def begin_source_cleanup(store, namespace, source_id, version, *, operation=None, request_id=None, maintainer_source=False):
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        store.active(db, namespace)
        if operation is not None and db.execute("SELECT 1 FROM idempotency WHERE namespace=? AND operation=? AND key=?", (namespace, operation, request_id)).fetchone() is not None:
            return False
        document = store.get(db, namespace, "document", source_id)
        if maintainer_source:
            initial = store.get(db, namespace, "initial", "snapshot")
            require(document.get("created_by_role") == "MAINTAINER" and document.get("access_scope") == initial["owner_id"], "来源不属于维护范围", web.HTTPForbidden)
        require(document.get("version") == version, "来源版本已经变化")
        row = db.execute("SELECT body FROM objects WHERE namespace=? AND kind='hermes_source_cleanup' AND id=?", (namespace, source_id)).fetchone()
        previous = json.loads(row[0]) if row else None
        if previous is not None and previous.get("state") == "COMPLETED" and document.get("withdrawn") is True:
            return False
        if previous is not None and previous.get("version") != version:
            raise ValueError("已有来源清理版本不匹配")
        store.put(db, namespace, "hermes_source_cleanup", source_id,
                  {"source_id": source_id, "version": version, "state": "PENDING", "updated_at": now()})
        return True


def finish_source_cleanup_in_transaction(store, db, namespace, source_id):
    row = db.execute("SELECT body FROM objects WHERE namespace=? AND kind='hermes_source_cleanup' AND id=?", (namespace, source_id)).fetchone()
    if row is None:
        return
    marker = json.loads(row[0])
    if marker.get("source_id") != source_id or marker.get("state") not in {"PENDING", "FAILED", "COMPLETED"}:
        raise ValueError("来源清理状态无效")
    sessions = getattr(store, "hermes_source_sessions", None)
    if sessions is not None:
        if sessions.business_store is not store or sessions.namespace != namespace:
            raise ValueError("来源传播会话服务不匹配")
        sessions.source_withdrawn_in_transaction(db, source_id)
    marker["session_state"] = "PENDING"
    marker.update(state="COMPLETED", updated_at=now())
    store.put(db, namespace, "hermes_source_cleanup", source_id, marker)


def complete_source_session_cleanup(store, namespace, source_id):
    sessions = getattr(store, "hermes_source_sessions", None)
    if sessions is None:
        return
    if sessions.business_store is not store or sessions.namespace != namespace:
        raise ValueError("来源传播会话服务不匹配")
    completed = False
    try:
        sessions.source_withdrawn(source_id)
        from boss_memory_sessions import MemorySessionManager
        persisted = MemorySessionManager(sessions.workspace, business_store=store, namespace=namespace, sessions_root=sessions.sessions_dir.parent)
        if persisted.sessions_dir.resolve() != sessions.sessions_dir.resolve():
            raise ValueError("来源传播会话目录不匹配")
        persisted.source_withdrawn(source_id)
        completed = True
    finally:
        with store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            marker = store.get(db, namespace, "hermes_source_cleanup", source_id)
            if marker.get("state") != "COMPLETED":
                raise ValueError("来源清理状态不可核查")
            marker.update(session_state="COMPLETED" if completed else "FAILED", updated_at=now())
            store.put(db, namespace, "hermes_source_cleanup", source_id, marker)


def recover_source_session_cleanups(store, namespace):
    if getattr(store, "hermes_source_sessions", None) is None:
        raise ValueError("来源传播会话服务未装配")
    with store.connect() as db:
        db.execute("BEGIN")
        store.active(db, namespace)
        rows = db.execute("SELECT id,body FROM objects WHERE namespace=? AND kind='hermes_source_cleanup'", (namespace,)).fetchall()
        pending = []
        for source_id, body in rows:
            marker = json.loads(body)
            if marker.get("state") == "COMPLETED":
                state = marker.get("session_state")
                if state in {None, "PENDING", "FAILED"}:
                    pending.append(source_id)
                elif state != "COMPLETED":
                    raise ValueError("来源传播状态无效")
    for source_id in pending:
        complete_source_session_cleanup(store, namespace, source_id)
    return len(pending)


def fail_source_cleanup(store, namespace, source_id):
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        marker = store.get(db, namespace, "hermes_source_cleanup", source_id)
        if marker.get("state") == "PENDING":
            marker.update(state="FAILED", updated_at=now())
            store.put(db, namespace, "hermes_source_cleanup", source_id, marker)


def require_source_cleanup_complete(db, run_id, *, invalid=ValueError, revoked=None):
    current = run_id
    seen = set()
    while current is not None:
        if current in seen:
            raise invalid("运行关系无效")
        seen.add(current)
        row = db.execute("SELECT parent_run_id,space_id,selected_refs FROM agent_runs WHERE run_id=?", (current,)).fetchone()
        if row is None:
            raise invalid("运行不存在")
        refs = json.loads(row[2]) if row[2] is not None else []
        if not isinstance(refs, list) or any(not isinstance(ref, str) or not ref for ref in refs):
            raise invalid("运行来源范围无效")
        for source_id in refs:
            marker = db.execute("SELECT body FROM objects WHERE namespace=? AND kind='hermes_source_cleanup' AND id=?", (row[1], source_id)).fetchone()
            if marker is not None:
                state = json.loads(marker[0]).get("state")
                if state == "COMPLETED" and revoked is not None:
                    raise revoked("来源已经撤销")
                raise invalid("来源已经撤销" if state == "COMPLETED" else "来源清理尚未完成")
        current = row[0]


def invalidate_document_results_in_transaction(db, namespace, source_id):
    if not db.in_transaction or not isinstance(namespace, str) or not namespace or not isinstance(source_id, str) or not source_id:
        raise ValueError("来源失效处理需要当前事务和来源编号")
    rows = db.execute("SELECT id,body FROM objects WHERE namespace=? AND kind='hermes_document_result'", (namespace,)).fetchall()
    affected = []
    for identifier, body in rows:
        saved = json.loads(body)
        if not isinstance(saved, dict) or any(not isinstance(saved.get(field), str) or not saved[field] for field in ("run_id", "call_id", "request_digest")):
            raise ValueError("工具结果记录无法核查")
        if saved.get("state") == "REVOKED":
            if "result" in saved or not isinstance(saved.get("result_sha256"), str):
                raise ValueError("工具结果失效记录无法核查")
            continue
        result = saved.get("result")
        if not isinstance(result, dict) or not isinstance(result.get("records"), list) or not result["records"] or not isinstance(result.get("sources"), list) or not result["sources"]:
            raise ValueError("工具结果来源无法核查")
        refs = []
        for record in result["records"]:
            if not isinstance(record, dict) or not isinstance(record.get("source_refs"), list) or not record["source_refs"]:
                raise ValueError("工具结果来源无法核查")
            refs.extend(record["source_refs"])
        refs.extend(result["sources"])
        if any(not isinstance(ref, dict) or not isinstance(ref.get("source_id"), str) or not ref["source_id"] for ref in refs):
            raise ValueError("工具结果来源无法核查")
        if source_id not in {ref["source_id"] for ref in refs}:
            continue
        marker = {"run_id": saved["run_id"], "call_id": saved["call_id"], "request_digest": saved["request_digest"],
                  "state": "REVOKED", "revoked_source_id": source_id, "result_sha256": checksum(result), "invalidated_at": now()}
        db.execute("UPDATE objects SET body=? WHERE namespace=? AND kind='hermes_document_result' AND id=?", (json.dumps(marker, ensure_ascii=False, sort_keys=True, separators=(",", ":")), namespace, identifier))
        affected.append({"run_id": saved["run_id"], "call_id": saved["call_id"]})
    return affected
