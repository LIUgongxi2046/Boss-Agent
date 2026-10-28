from datetime import datetime
from zoneinfo import ZoneInfo

from aiohttp import web

from business import checksum, require
from boss_meeting_approval import approval_decide
from boss_message_calendar import message_save, message_send
from boss_morning_projection import project
from boss_simulation_api import _context
from boss_v7_store import NAMESPACE, optional, rows, text


def current_actions(store, db, snapshot):
    clock = store.get(db, NAMESPACE, "clock", "current")["at"]
    timezone = snapshot["boss_profile"]["timezone"]
    day = {"date": datetime.fromisoformat(clock).astimezone(ZoneInfo(timezone)).date().isoformat(), "timezone": timezone}
    view, objects = project(store, db, _context(db), day)
    items = []
    for item in view["items"]:
        value = {**item, "approval": None}
        if item["kind"] == "application":
            application = objects["objects"][item["item_id"]]
            value["approval"] = {key: application[key] for key in ("application_id", "version", "source_id", "source_version", "amount", "currency")}
        items.append(value)
    return {"date": day["date"], "timezone": timezone, "items": items,
            "snapshot_sha256": checksum(items), "secretary": optional(db, "secretary_configuration", "current")}


def read_actions(store, db, snapshot):
    messages = [row for row in rows(db, "message_outbox") if row.get("purpose") == "SECRETARY_DELEGATION"]
    identifiers = {row["message_id"] for row in messages}
    return {**current_actions(store, db, snapshot), "messages": messages,
            "replies": [row for row in rows(db, "message_reply") if row["reply_to"] in identifiers]}


def act(api, db, snapshot, action, payload):
    fields = {"client_request_id", "snapshot_sha256", "item_ids", "comment"}
    if action == "delegate":
        fields |= {"secretary_version"}
    api._exact(payload, fields)
    current = current_actions(api.store, db, snapshot)
    require(payload["snapshot_sha256"] == current["snapshot_sha256"], "当前事项已经变化，请重新查看后确认")
    identifiers = payload["item_ids"]
    require(isinstance(identifiers, list) and 1 <= len(identifiers) <= 50 and all(isinstance(item, str) for item in identifiers), "请选择需要处理的事项", web.HTTPBadRequest)
    require(len(set(identifiers)) == len(identifiers), "事项不能重复选择", web.HTTPBadRequest)
    available = {item["item_id"]: item for item in current["items"]}
    require(all(identifier in available for identifier in identifiers), "选中事项已经变化")
    selected = [available[identifier] for identifier in identifiers]
    comment = text(payload["comment"], "处理说明", 1200)
    if action in {"approve", "reject"}:
        require(all(item["approval"] is not None for item in selected), "同意和驳回仅适用于待决定申请", web.HTTPBadRequest)
        results = []
        for item in selected:
            application = item["approval"]
            results.append(approval_decide(api, db, snapshot, {
                "client_request_id": payload["client_request_id"], "application_id": application["application_id"],
                "expected_version": application["version"], "source_id": application["source_id"], "source_version": application["source_version"],
                "amount": application["amount"], "currency": application["currency"],
                "decision": "APPROVE" if action == "approve" else "REJECT", "comment": comment}))
        return {"state": "RECORDED", "results": results}
    require(action == "delegate", "处理方式无效", web.HTTPBadRequest)
    secretary = current["secretary"]
    require(secretary is not None, "请管理员配置秘书接收方式", web.HTTPConflict)
    require(secretary["version"] == payload["secretary_version"], "秘书接收方式已经变化，请重新确认")
    body = comment + "\n\n" + "\n".join(f'{index + 1}. {item["title"]}；{item["reason"]}' for index, item in enumerate(selected))
    draft_result = message_save(api, db, snapshot, {"client_request_id": payload["client_request_id"], "draft_id": None,
        "expected_version": "0", "recipient_id": secretary["recipient_id"], "related_task_id": None,
        "body": body, "attachment_refs": [], "visibility": "RECIPIENT_ONLY"})
    draft = api.store.get(db, NAMESPACE, "message_draft", draft_result["draft_id"])
    sent = message_send(api, db, snapshot, {"client_request_id": payload["client_request_id"], "draft_id": draft["draft_id"],
        "expected_version": draft["version"], "recipient_id": secretary["recipient_id"], "expected_content_sha256": draft["content_sha256"]})
    message = api.store.get(db, NAMESPACE, "message_outbox", sent["message_id"])
    message.update(purpose="SECRETARY_DELEGATION", channel=secretary["channel"], address=secretary["address"],
                   recipient_name=secretary["recipient_name"], secretary_version=secretary["version"], item_ids=identifiers)
    api.store.put(db, NAMESPACE, "message_outbox", message["message_id"], message)
    return {**sent, "state": "SENT_SIMULATED"}
