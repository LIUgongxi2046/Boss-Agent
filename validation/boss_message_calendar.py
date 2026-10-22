"""FR-08 and FR-12 scoped messaging and private-calendar transactions.

All operations are SIMULATED and only operate on the authenticated owner or
a MAINTAINER injecting a tagged synthetic reply. No real external connector.
Mutations are called within BossCommandAPI's BEGIN IMMEDIATE transaction,
idempotency key and redacted-audit boundary.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta

from aiohttp import web

from business import checksum, now, require

NS = "ui-check"
MAX_TEXT = 2400


def _text(value, name, limit=MAX_TEXT):
    require(isinstance(value, str) and 0 < len(value.strip()) <= limit,
            f"{name}缺失或超出限制", web.HTTPBadRequest)
    return value.strip()


def _optional_text(value, name, limit=240):
    require(isinstance(value, str) and len(value) <= limit,
            f"{name}格式无效", web.HTTPBadRequest)
    return value.strip()


def _exists(db, kind, identifier):
    row = db.execute(
        "SELECT body FROM objects WHERE namespace=? AND kind=? AND id=?",
        (NS, kind, identifier),
    ).fetchone()
    return json.loads(row[0]) if row else None


def _contact(api, db, data, contact_id):
    require(isinstance(contact_id, str), "联系人 ID 缺少", web.HTTPBadRequest)
    matches = [c for c in data["contacts"] if c["contact_id"] == contact_id]
    require(len(matches) == 1, "无法唯一识别当前联系人 ID", web.HTTPBadRequest)
    person = matches[0]
    # Current simulation business time, never a frozen historical meeting.
    business_clock = api.store.get(db, NS, "clock", "current")
    today = datetime.fromisoformat(business_clock["at"]).date().isoformat()
    require(person["valid_from"] <= today <= person["valid_until"],
            "当前资料未确认联系人仍然有效", web.HTTPForbidden)
    return person


def _source_refs(api, db, data, refs):
    require(isinstance(refs, list) and len(refs) <= 5,
            "附件引用数量不合法", web.HTTPBadRequest)
    sources = []
    seen = set()
    for row in refs:
        require(isinstance(row, dict) and set(row) == {"source_id", "version"},
                "附件必须明确来源和版本", web.HTTPBadRequest)
        require(isinstance(row["source_id"], str) and isinstance(row["version"], str),
                "附件引用类型无效", web.HTTPBadRequest)
        require(row["source_id"] not in seen,
                "重复的来源标识不得以不同版本重复授权", web.HTTPBadRequest)
        seen.add(row["source_id"])
        doc = api._require_current_source(db, data, row["source_id"])
        require(doc["version"] == row["version"],
                "附件版本已变化，须重新授权")
        sources.append({"source_id": doc["source_id"], "version": doc["version"]})
    return sources


def _time(api, value, timezone):
    from boss_command_api import _aware_due
    return _aware_due(value, timezone)


def message_save(api, db, data, payload):
    api._exact(payload, {
        "client_request_id", "draft_id", "expected_version", "recipient_id",
        "related_task_id", "body", "attachment_refs", "visibility",
    })
    ident = payload["draft_id"]
    require(ident is None or (isinstance(ident, str)
            and ident.startswith("draft-") and len(ident) <= 80),
            "草稿标识无效", web.HTTPBadRequest)
    recipient = _contact(api, db, data, payload["recipient_id"])
    body = _text(payload["body"], "消息草稿")
    require(payload["visibility"] == "RECIPIENT_ONLY",
            "不能向未经核验的范围广播", web.HTTPForbidden)
    sources = _source_refs(api, db, data, payload["attachment_refs"])
    task_id = payload["related_task_id"]
    if task_id is not None:
        require(isinstance(task_id, str), "关联任务 ID 无效", web.HTTPBadRequest)
        task = api.store.get(db, NS, "task", task_id)
        require(task["status"] not in ("CANCELED", "COMPLETED_CONFIRMED"),
                "关联任务已结束")
        require(task["coordinator_id"] == recipient["contact_id"],
                "关联任务负责人和收件人不同", web.HTTPBadRequest)
    previous = _exists(db, "message_draft", ident) if ident is not None else None
    require(payload["expected_version"] == (previous["version"] if previous else "0"),
            "草稿版本变化，须重新读取并核对")
    if previous:
        require(previous["status"] == "DRAFT", "已发送草稿不能修改")
        api.store.put(db, NS, "message_draft_revision",
                      f'{ident}:v{previous["version"]}', previous)
    else:
        ident = "draft-" + str(uuid.uuid4())
    version = str(int(payload["expected_version"]) + 1)
    result = {
        "draft_id": ident, "version": version, "status": "DRAFT",
        "recipient_id": recipient["contact_id"],
        "recipient_name_at_save": recipient["name"],
        "organization_at_save": recipient["organization"],
        "related_task_id": task_id, "body": body,
        "attachment_refs": sources, "visibility": "RECIPIENT_ONLY",
        "content_sha256": checksum({
            "recipient_id": recipient["contact_id"], "body": body,
            "attachment_refs": sources, "task_id": task_id,
        }),
        "source_type": "SIMULATED", "updated_at": now(),
        "message_id": None,
    }
    api.store.put(db, NS, "message_draft", ident, result)
    return {
        "source_type": "SIMULATED", "draft_id": ident,
        "version": version, "status": "DRAFT",
        "message_sent": False,
    }


def message_send(api, db, data, payload):
    api._exact(payload, {
        "client_request_id", "draft_id", "expected_version",
        "recipient_id", "expected_content_sha256",
    })
    draft = api.store.get(db, NS, "message_draft", payload["draft_id"])
    require(draft["status"] == "DRAFT"
            and draft["version"] == payload["expected_version"],
            "草稿已发出或版本变化，不能重复发送")
    require(payload["recipient_id"] == draft["recipient_id"],
            "收件人不符合已保存草稿", web.HTTPForbidden)
    require(payload["expected_content_sha256"] == draft["content_sha256"],
            "草稿内容已变化，必须重新核查", web.HTTPForbidden)
    _contact(api, db, data, draft["recipient_id"])
    _source_refs(api, db, data, draft["attachment_refs"])
    if draft["related_task_id"]:
        task = api.store.get(db, NS, "task", draft["related_task_id"])
        require(task["coordinator_id"] == draft["recipient_id"]
                and task["status"] in ("WAITING_FEEDBACK", "IN_PROGRESS"),
                "关联任务尚未由老板单独发送，或当前状态不允许进展回复")
    # Signed payload contains a digest and version only, not confidential body.
    auth_id = api._authorize(db, "message.send", {
        "draft_id": draft["draft_id"], "version": draft["version"],
        "recipient_id": draft["recipient_id"],
        "content_sha256": draft["content_sha256"],
        "attachment_refs": draft["attachment_refs"],
    }, draft["draft_id"], draft["version"])
    message_id = "sim-msg-" + str(uuid.uuid4())
    message = {
        "message_id": message_id, "draft_id": draft["draft_id"],
        "draft_version": draft["version"], "recipient_id": draft["recipient_id"],
        "related_task_id": draft["related_task_id"],
        "body": draft["body"], "attachment_refs": draft["attachment_refs"],
        "visibility": "RECIPIENT_ONLY", "authorization_id": auth_id,
        "source_type": "SIMULATED", "sent_at": now(),
        "send_state": "SENT_SIMULATED",
        "delivery_state": "NOT_VERIFIED",
        "reply_state": "NOT_RECEIVED",
        "external_channel_invoked": False,
    }
    api.store.put(db, NS, "message_outbox", message_id, message)
    draft["status"] = "SENT_SIMULATED"
    draft["message_id"] = message_id
    api.store.put(db, NS, "message_draft", draft["draft_id"], draft)
    return {
        "source_type": "SIMULATED", "draft_id": draft["draft_id"],
        "draft_version": draft["version"], "message_id": message_id,
        "recipient_id": draft["recipient_id"],
        "send_state": "SENT_SIMULATED",
        "delivery_state": "NOT_VERIFIED", "reply_state": "NOT_RECEIVED",
        "authorization_id": auth_id, "external_channel_invoked": False,
    }


def message_reply(api, db, data, payload):
    """A named, synthetic contact response; never an authenticated employee."""
    api._exact(payload, {
        "client_request_id", "message_id", "author_contact_id", "text",
    })
    message = api.store.get(db, NS, "message_outbox", payload["message_id"])
    require(message["send_state"] == "SENT_SIMULATED",
            "尚未模拟发送的消息不能收到回复")
    require(message["recipient_id"] == payload["author_contact_id"],
            "回复者不是原模拟收件人", web.HTTPForbidden)
    require(message["reply_state"] == "NOT_RECEIVED",
            "当前消息已有回复，不能重复注入")
    _contact(api, db, data, payload["author_contact_id"])
    text = _text(payload["text"], "模拟反馈")
    # Only a previously *separately sent* assignment may receive
    # task PROGRESS. Arbitrary message replies never create/complete tasks.
    task_feedback_id = None
    task_status = None
    if message["related_task_id"]:
        task = api.store.get(db, NS, "task", message["related_task_id"])
        require(task["coordinator_id"] == payload["author_contact_id"],
                "关联交办负责人已变化", web.HTTPForbidden)
        if task["status"] in ("WAITING_FEEDBACK", "IN_PROGRESS"):
            updated = api.store.control_feedback(db, NS, {
                "task_id": task["task_id"],
                "task_version": task["version"],
                "author_contact_id": payload["author_contact_id"],
                "kind": "PROGRESS", "content": text,
                "evidence_refs": [],
            })
            task_feedback_id = updated["feedback"]["feedback_id"]
            task_status = updated["task"]["status"]
    reply_id = "sim-reply-" + str(uuid.uuid4())
    reply = {
        "reply_id": reply_id, "reply_to": message["message_id"],
        "author_contact_id": payload["author_contact_id"],
        "text": text, "source_type": "SIMULATED",
        "received_at": now(), "related_task_id": message["related_task_id"],
        "task_completion_confirmed": False,
        "task_feedback_id": task_feedback_id,
        "task_status_after_reply": task_status,
    }
    api.store.put(db, NS, "message_reply", reply_id, reply)
    message["reply_state"] = "RECEIVED_SIMULATED"
    message["reply_id"] = reply_id
    api.store.put(db, NS, "message_outbox", message["message_id"], message)
    return {
        "source_type": "SIMULATED", "reply_id": reply_id,
        "reply_to": message["message_id"], "reply_state": "RECEIVED_SIMULATED",
        "task_completion_confirmed": False,
        "task_feedback_id": task_feedback_id,
        "task_status_after_reply": task_status,
    }


def _calendar(db, data):
    return _exists(db, "private_calendar", "private-1") or {
        **data["private_calendar"],
        "version": "1", "status": "ACTIVE",
        "title": "", "location": "", "attachment_refs": [],
    }



def work_meeting_conflict(start, end, meeting_start):
    """Explain the *known* selected meeting start without inferring an end.

    Returns the same acknowledgement decision used by calendar.save, so the
    preflight UI and persisted mutation never disagree about the known input.
    """
    if start <= meeting_start < end:
        status = "KNOWN_MEETING_START_OVERLAP"
        acknowledgement = True
    elif 0 <= (start - meeting_start).total_seconds() < 86400:
        status = "POSSIBLE_CONFLICT_MEETING_END_UNKNOWN"
        acknowledgement = True
    elif 0 <= (meeting_start - end).total_seconds() < 86400:
        status = "ENDS_BEFORE_KNOWN_MEETING_START"
        acknowledgement = True
    else:
        status = "NO_OVERLAP_IDENTIFIED_WITH_KNOWN_START"
        acknowledgement = False
    return {
        "status": status,
        "meeting_starts_at": meeting_start.isoformat(),
        "meeting_ends_at": None,
        "meeting_end_known": False,
        "requires_owner_acknowledgement": acknowledgement,
        "conflict_proven_absent": False,
        "coverage": "CURRENT_APPROVED_SIMULATED_MEETING_ONLY",
    }


def calendar_save(api, db, data, payload):
    api._exact(payload, {
        "client_request_id", "expected_version", "starts_at", "ends_at",
        "timezone", "title", "private_body", "location",
        "attachment_refs", "acknowledge_conflict",
    })
    current = _calendar(db, data)
    require(current["status"] == "ACTIVE",
            "已删除的私人日程不能在旧标识上恢复")
    require(current["version"] == payload["expected_version"],
            "私人日程版本变化，须重新读取")
    tz = payload["timezone"]
    start = _time(api, payload["starts_at"], tz)
    end = _time(api, payload["ends_at"], tz)
    require(start < end, "私人日程结束时间必须晚于开始", web.HTTPBadRequest)
    require((end - start).total_seconds() <= 31*86400,
            "私人日程最长31天", web.HTTPBadRequest)
    require(isinstance(payload["acknowledge_conflict"], bool),
            "工作冲突确认标记类型错误", web.HTTPBadRequest)
    title = _optional_text(payload["title"], "日程标题", 160)
    body = _text(payload["private_body"], "私人正文", 2000)
    location = _optional_text(payload["location"], "地点", 240)
    sources = _source_refs(api, db, data, payload["attachment_refs"])
    meeting = data["meeting"]
    mstart = datetime.fromisoformat(meeting["starts_at"])
    # The selected fixture does not provide a meeting end; we *cannot*
    # infer an exact duration or claim a full conflict check.
    conflict = work_meeting_conflict(start, end, mstart)
    require(not conflict["requires_owner_acknowledgement"]
            or payload["acknowledge_conflict"],
            "会议缺少结束时间，邻近安排必须由本人确认冲突风险")
    if _exists(db, "private_calendar", "private-1"):
        api.store.put(db, NS, "private_calendar_revision",
                      f'private-1:v{current["version"]}', current)
    updated = {
        **current, "version": str(int(current["version"]) + 1),
        "starts_at": payload["starts_at"], "ends_at": payload["ends_at"],
        "timezone": tz, "title": title, "private_body": body,
        "location": location, "attachment_refs": sources,
        "visibility": "PRIVATE", "status": "ACTIVE",
        "updated_at": now(),
        "calendar_conflict_proven_absent": False,
        "meeting_end_unknown": True,
    }
    auth_id = api._authorize(db, "calendar.save", {
        "calendar_id": "private-1", "expected_version": current["version"],
        "content_sha256": checksum({
            "title": title, "body": body, "location": location,
            "starts_at": payload["starts_at"], "ends_at": payload["ends_at"],
            "attachments": sources, "timezone": tz,
        }),
    }, "private-1", current["version"])
    api.store.put(db, NS, "private_calendar", "private-1", updated)
    # Previously authorized busy shares are no longer current after an edit.
    shares = db.execute(
        "SELECT id,body FROM objects WHERE namespace=? AND kind='calendar_share'",
        (NS,),
    ).fetchall()
    for ident, raw in shares:
        share = json.loads(raw)
        if share.get("revoked") is False:
            share["revoked"] = True
            share["revoked_at"] = now()
            share["revocation_reason"] = "CALENDAR_VERSION_CHANGED"
            api.store.put(db, NS, "calendar_share", ident, share)
    return {
        "source_type": "SIMULATED", "calendar_id": "private-1",
        "version": updated["version"], "status": "ACTIVE",
        "authorization_id": auth_id,
        "active_shares_invalidated": True,
        "calendar_conflict_proven_absent": False,
        "conflict_status": conflict["status"],
        "external_calendar_updated": False,
    }


def calendar_share(api, db, data, payload):
    api._exact(payload, {
        "client_request_id", "expected_version",
        "recipient_id", "purpose", "expires_at", "fields",
    })
    current = _calendar(db, data)
    require(current["status"] == "ACTIVE"
            and current["version"] == payload["expected_version"],
            "私人日程版本已变化，须重新确认")
    recipient = _contact(api, db, data, payload["recipient_id"])
    purpose = _text(payload["purpose"], "分享用途", 240)
    end = _time(api, payload["expires_at"], current["timezone"])
    start = datetime.fromisoformat(current["starts_at"])
    clock = datetime.fromisoformat(api.store.get(db, NS, "clock", "current")["at"])
    require(end > clock, "分享授权必须在当前模拟业务时钟之后到期", web.HTTPBadRequest)
    require(end > start, "分享过期时间必须晚于开始时间", web.HTTPBadRequest)
    require(end <= clock + timedelta(days=366),
            "分享授权超过最长366天", web.HTTPBadRequest)
    require(payload["fields"] == ["busy","starts_at","ends_at","timezone"],
            "仅允许分享占用状态与时段，禁止标题或正文", web.HTTPForbidden)
    share_id = "busy-share-" + str(uuid.uuid4())
    auth_id = api._authorize(db, "calendar.share", {
        "calendar_id": "private-1", "version": current["version"],
        "recipient_id": recipient["contact_id"], "purpose_sha256": checksum(purpose),
        "expires_at": payload["expires_at"], "fields": payload["fields"],
    }, "private-1", current["version"])
    share = {
        "share_id": share_id, "calendar_id": "private-1",
        "calendar_version": current["version"],
        "recipient_id": recipient["contact_id"],
        "purpose_sha256": checksum(purpose),
        "busy": True, "starts_at": current["starts_at"],
        "ends_at": current["ends_at"], "timezone": current["timezone"],
        "expires_at": payload["expires_at"], "authorization_id": auth_id,
        "revoked": False, "revoked_at": None,
        "source_type": "SIMULATED", "external_delivery_created": False,
    }
    api.store.put(db, NS, "calendar_share", share_id, share)
    return {
        "source_type": "SIMULATED", "share_id": share_id,
        "calendar_version": current["version"], "recipient_id": recipient["contact_id"],
        "fields": payload["fields"], "authorization_id": auth_id,
        "share_status": "ACTIVE_SIMULATED",
        "external_delivery_created": False,
    }


def calendar_revoke(api, db, data, payload):
    api._exact(payload, {"client_request_id","share_id","expected_version"})
    share = api.store.get(db, NS, "calendar_share", payload["share_id"])
    require(share["calendar_version"] == payload["expected_version"],
            "分享的日程版本不符")
    require(not share["revoked"], "分享已撤销，不能重复新动作")
    auth_id = api._authorize(db, "calendar.share.revoke", {
        "share_id": share["share_id"], "calendar_version": share["calendar_version"],
        "recipient_id": share["recipient_id"],
    }, share["share_id"], share["calendar_version"])
    share["revoked"] = True
    share["revoked_at"] = now()
    api.store.put(db, NS, "calendar_share", share["share_id"], share)
    return {
        "source_type": "SIMULATED", "share_id": share["share_id"],
        "share_status": "REVOKED", "authorization_id": auth_id,
        "external_recall_verified": False,
    }


def calendar_delete(api, db, data, payload):
    api._exact(payload, {"client_request_id","expected_version"})
    current = _calendar(db, data)
    require(current["status"] == "ACTIVE"
            and current["version"] == payload["expected_version"],
            "日程版本变化或此前已删除")
    auth_id = api._authorize(db, "calendar.delete", {
        "calendar_id": "private-1", "version": current["version"],
    }, "private-1", current["version"])
    api.store.put(db, NS, "private_calendar_revision",
                  f'private-1:v{current["version"]}', current)
    current["private_body"] = ""
    current["title"] = ""
    current["location"] = ""
    current["attachment_refs"] = []
    current["status"] = "DELETED"
    current["version"] = str(int(current["version"]) + 1)
    api.store.put(db, NS, "private_calendar", "private-1", current)
    for row in db.execute(
        "SELECT id,body FROM objects WHERE namespace=? AND kind='calendar_share'",
        (NS,),
    ).fetchall():
        share = json.loads(row[1])
        if share.get("revoked") is False:
            share["revoked"] = True
            share["revoked_at"] = now()
            api.store.put(db, NS, "calendar_share", row[0], share)
    return {
        "calendar_id": "private-1", "version": current["version"],
        "status": "DELETED", "source_type": "SIMULATED",
        "future_visibility_stopped": True,
        "physical_secure_erasure_verified": False,
        "authorization_id": auth_id,
    }
