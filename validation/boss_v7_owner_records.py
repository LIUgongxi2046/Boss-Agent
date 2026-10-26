import json
from datetime import datetime, timezone

from boss_owner_authorizations import CONTINUING_USE_ACTIONS, authorization_can_revoke
from boss_memory import confirmed_memory
from boss_owner_history import owner_spaces
from boss_source_policy import source_validity
from boss_v7_store import NAMESPACE, optional, rows

ACTION_NAMES = {
    "memory.confirm": "确认个人要求", "memory.delete": "删除个人要求", "authorization.revoke": "撤销授权",
    "create_assignment": "创建交办", "send_assignment": "发送交办", "complete_assignment": "确认完成",
    "extend_assignment": "延长交办", "cancel_assignment": "取消交办", "minutes.confirm": "确认会议纪要",
    "approval.decide": "申请决定", "owner_goals.confirm": "确认本人目标", "owner_notice.confirm": "确认通知要求",
    "calendar.share": "共享忙闲安排", "owner_plan.save": "保存本人计划", "owner_plan.resume": "恢复本人计划",
}


def _base(identifier, title, kind, snapshot, namespace):
    return {"id": identifier, "title": title, "kind": kind, "target_id": None, "task_id": None,
            "version": "", "authorization_version": None, "state": "", "effective_state": "", "action": None,
            "authorization_id": None, "valid_until": None, "created_at": "", "namespace": namespace,
            "dataset_id": snapshot["dataset_id"], "source_ids": [], "scope": [], "values": [],
            "missing": [], "changed_conditions": [], "timeline": [], "can_revoke": False, "can_continue": False,
            "current_target_id": None, "current_page": None, "request_id": None,
            "historical": namespace != NAMESPACE, "archived_at": None, "sources": [],
            "original_records": [], "current_evidence_eligible": namespace == NAMESPACE}


def authorizations(db, snapshot, namespace=NAMESPACE, archive=None):
    audits = [(row[0], row[1], json.loads(row[2]), json.loads(row[3]), row[4]) for row in db.execute(
        "SELECT id,operation,input,output,created_at FROM audit WHERE namespace=? ORDER BY id", (namespace,)
    ).fetchall()]
    result = []
    for item in rows(db, "authorization", namespace):
        if item.get("owner_id") != snapshot["owner_id"] or item.get("scope") != namespace or item.get("issuer_identity") != "BOSS":
            continue
        identifier = item["authorization_id"]
        action = item["action"]
        history = [row for row in audits if row[3].get("authorization_id") == identifier]
        used = db.execute(
            "SELECT kind,id FROM objects WHERE namespace=? AND kind NOT IN ('authorization','authorization_binding') "
            "AND json_extract(body,'$.authorization_id')=?", (namespace, identifier),
        ).fetchall()
        expiry = datetime.fromisoformat(item["valid_until"])
        revoked = item.get("revoked") is True
        reference_time = datetime.fromisoformat(archive["archived_at"]) if archive else datetime.now(timezone.utc)
        state = "REVOKED" if revoked else "EXECUTED" if used and action not in CONTINUING_USE_ACTIONS else "EXPIRED" if expiry <= reference_time and action not in CONTINUING_USE_ACTIONS else "CURRENT"
        if not revoked and action in CONTINUING_USE_ACTIONS:
            state = "CURRENT_OBJECT_CHECK_REQUIRED"
            if action == "memory.confirm":
                memory = optional(db, "memory", "current", namespace)
                state = "SUPERSEDED" if memory is None or memory.get("authorization_id") != identifier else "CURRENT" if confirmed_memory(db, namespace, memory, snapshot["owner_id"]) is not None else "NOT_EFFECTIVE"
        record = _base(identifier, ACTION_NAMES.get(action, action), "AUTHORIZATION", snapshot, namespace)
        record.update(target_id=item["target_id"], version=item["content_version"], authorization_version=item["version"],
                      state=state, effective_state=state, action=action, authorization_id=identifier,
                      valid_until=item["valid_until"], created_at=item["valid_from"], scope=[namespace],
                      can_revoke=authorization_can_revoke(item, snapshot["owner_id"], namespace))
        payload = item.get("payload", {})
        record["values"] = [{"label": "对象", "value": item["target_id"]}, {"label": "动作", "value": record["title"]},
                            {"label": "内容版本", "value": item["content_version"]}, {"label": "授权版本", "value": item["version"]},
                            {"label": "确认依据", "value": item.get("source_instruction")},
                            {"label": "确认时内容", "value": json.dumps(payload, ensure_ascii=False, indent=2)}]
        record["source_ids"] = [value for value in payload.get("source_refs", payload.get("source_ids", [])) if isinstance(value, str)]
        record["timeline"] = [{"id": str(row[0]), "title": ACTION_NAMES.get(action, action), "at": row[4],
                               "state": row[3].get("status", row[3].get("state", "RECORDED")),
                               "description": row[1], "version": row[3].get("version"), "source_ids": record["source_ids"]}
                              for row in history]
        task = optional(db, "task", item["target_id"], namespace)
        if task:
            record.update(task_id=task["task_id"], current_target_id=task["task_id"], current_page="F06", can_continue=True)
            if task["version"] != item["content_version"]:
                record["changed_conditions"].append("事项当前版本为 " + task["version"])
        elif action.startswith("memory."):
            record.update(current_target_id=item["target_id"], current_page="F13", can_continue=True)
        if history:
            record["request_id"] = history[-1][2].get("client_request_id")
            record["action"] = history[-1][1]
        record["sources"] = decision_sources(db, snapshot, namespace, payload)
        record["source_ids"] = sorted(set(record["source_ids"]) | {row["source_id"] for row in record["sources"]})
        record["original_records"] = decision_records(db, namespace, item)
        if archive:
            record.update(id=namespace + ":" + identifier, effective_state="READ_ONLY_HISTORY",
                          archived_at=archive["archived_at"], can_revoke=False, can_continue=False,
                          current_target_id=None, current_page=None, task_id=None, request_id=None)
            record["changed_conditions"].append("原执行空间已经归档；当前没有已登记的对应事项。")
        result.append(record)
    return sorted(result, key=lambda row: row["created_at"], reverse=True)


def decisions(db, snapshot):
    result = [record for namespace, initial, archive in owner_spaces(db, snapshot)
              for record in authorizations(db, initial, namespace, archive)]
    return sorted(result, key=lambda row: (row["created_at"], row["id"]), reverse=True)


def decision_sources(db, snapshot, namespace, payload):
    references = dict(payload.get("source_versions", {}))
    if isinstance(payload.get("source_id"), str):
        references[payload["source_id"]] = payload.get("source_version")
    for identifier in payload.get("source_refs", payload.get("source_ids", [])):
        if isinstance(identifier, str):
            references.setdefault(identifier, None)
        elif isinstance(identifier, dict) and isinstance(identifier.get("source_id"), str):
            references[identifier["source_id"]] = identifier.get("version")
    clock = optional(db, "clock", "current", namespace)["at"]
    result = []
    for identifier, version in sorted(references.items()):
        current = optional(db, "document", identifier, namespace)
        allowed = current is not None and current.get("access_scope") == snapshot["owner_id"]
        document = current if allowed and current.get("version") == version else None
        if allowed and version is not None and document is None:
            document = optional(db, "document_revision", identifier + ":v" + version, namespace)
        available = document is not None and document.get("source_id") == identifier and document.get("version") == version and document.get("access_scope") == snapshot["owner_id"]
        result.append({"source_id": identifier, "version": version, "namespace": namespace,
                       "state": "ACCESS_UNAVAILABLE" if not allowed else "VERSION_NOT_RECORDED" if version is None else "VERSION_UNAVAILABLE" if not available else "HISTORICAL_VERSION" if current["version"] != version else source_validity(current, clock),
                       "current_source_state": source_validity(current, clock) if allowed else "ACCESS_UNAVAILABLE",
                       "content": document.get("content") if available else None,
                       "author": document.get("author_contact_id", document.get("author")) if available else None,
                       "published_at": document.get("published_at") if available else None,
                       "current_evidence_eligible": False})
    return result


def decision_records(db, namespace, authorization):
    identifier, action = authorization["authorization_id"], authorization["action"]
    if action == "approval.decide":
        return [{"kind": "APPLICATION_DECISION", "id": row["decision_id"], "version": row["application_version"],
                 "content": row["comment"], "decision": row["action"]}
                for row in rows(db, "application_decision", namespace) if row.get("authorization_id") == identifier]
    if action == "minutes.confirm":
        payload = authorization["payload"]
        row = optional(db, "minutes_revision", payload["meeting_id"] + ":v" + authorization["content_version"], namespace)
        if row is not None and row["minute_id"] == authorization["target_id"]:
            return [{"kind": "MINUTES", "id": row["minute_id"], "version": row["version"],
                     "content": "\n".join(entry["text"] for entry in row["entries"]), "decision": "CONFIRMED"}]
    return []


def notification_history(db, snapshot):
    result = []
    for namespace, source_snapshot, archive in owner_spaces(db, snapshot):
        for kind, identifier, body in db.execute("SELECT kind,id,body FROM objects WHERE namespace=? AND kind IN ('notification','notification_revision') ORDER BY kind,id", (namespace,)).fetchall():
            item = json.loads(body)
            if item.get("owner_id", source_snapshot["owner_id"]) != source_snapshot["owner_id"]:
                continue
            event = optional(db, "event", item["event_id"], namespace)
            record = _base(namespace + ":" + kind + ":" + identifier, item["event_id"], "NOTIFICATION", source_snapshot, namespace)
            record.update(target_id=item["event_id"], version=item.get("event_version", ""), state=item["state"],
                          effective_state="READ_ONLY_HISTORY", created_at=item.get("created_at", item.get("delivered_at", item.get("business_at", ""))),
                          scope=[namespace], archived_at=archive["archived_at"] if archive else None,
                          current_evidence_eligible=False)
            record["values"] = [{"label": "原执行空间", "value": namespace}, {"label": "原数据集", "value": source_snapshot["dataset_id"]},
                                {"label": "当时状态", "value": item["state"]}, {"label": "规则版本", "value": item.get("rule_version")},
                                {"label": "计划版本", "value": item.get("schedule_version")}, {"label": "参与原因", "value": item.get("reason")}]
            record["timeline"] = [{"id": identifier, "title": "原通知记录", "at": record["created_at"], "state": item["state"],
                                   "description": "按原执行空间与来源版本读取", "version": record["version"], "source_ids": []}]
            original = item.get("event_snapshot")
            if original is None and item.get("event_version"):
                original = optional(db, "business_alert_observation", item["event_id"] + ":v" + item["event_version"], namespace)
            if original is None and event and event.get("version") == item.get("event_version"):
                original = event
            if original and original.get("event_id") == item["event_id"] and original.get("version") == item.get("event_version"):
                content = {key: original[key] for key in ("state", "impact", "due_at", "observed_at", "facts", "task_id", "task_version") if key in original}
                record["original_records"].append({"kind": "EVENT", "id": original["event_id"], "version": original["version"],
                                                   "content": json.dumps(content, ensure_ascii=False, indent=2), "decision": "READ_ONLY_HISTORY"})
                record["sources"] = decision_sources(db, source_snapshot, namespace, original)
            else:
                record["missing"].append("当时的事件版本正文未保存，当前只展示原通知记录。")
            task_snapshot = item.get("task_snapshot")
            if task_snapshot and original and task_snapshot["task_id"] == original.get("task_id"):
                record["original_records"].append({"kind": "TASK", "id": task_snapshot["task_id"], "version": task_snapshot["version"],
                                                   "content": json.dumps(task_snapshot, ensure_ascii=False, indent=2), "decision": "READ_ONLY_HISTORY"})
                known = {source["source_id"] for source in record["sources"]}
                record["sources"].extend(source for source in decision_sources(db, source_snapshot, namespace, task_snapshot) if source["source_id"] not in known)
            record["source_ids"] = [source["source_id"] for source in record["sources"]]
            record["values"].append({"label": "原通知版本", "value": item.get("version")})
            record["values"].append({"label": "原数据集版本", "value": source_snapshot["dataset_version"]})
            if archive:
                record["changed_conditions"].append("原执行空间已经归档；当前没有已登记的对应事项。")
            elif event and event.get("version") != item.get("event_version"):
                record["changed_conditions"].append("事件当前版本为 " + event["version"] + "，本记录保留原版本。")
            if namespace == NAMESPACE and event and event.get("task_id"):
                task = optional(db, "task", event["task_id"], namespace)
                if task:
                    record.update(task_id=task["task_id"], current_target_id=task["task_id"], current_page="F06", can_continue=True)
            result.append(record)
    return sorted(result, key=lambda row: row["created_at"], reverse=True)
