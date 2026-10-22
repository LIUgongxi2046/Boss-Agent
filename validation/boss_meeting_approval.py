"""PRD FR-05 and FR-07: versioned minutes and simulated application decisions.

The current sample dataset contains a synthetic meeting and source notes, but
NO application. Applications must be explicitly seeded by MAINTAINER as
SIMULATED data. No automatic approval, payment, task creation, or external send.
Business owner signs each decision; idempotency, audit and roles are enforced
by BossCommandAPI in one SQLite transaction.
"""
from __future__ import annotations

import json
import re
import uuid
from decimal import Decimal, InvalidOperation
from datetime import datetime

from aiohttp import web

from business import checksum, now, require

NS = "ui-check"
ENTRY_KINDS = frozenset({"OPINION", "SUGGESTION", "DECISION", "ASSIGNMENT_DRAFT"})
DECISIONS = frozenset({"APPROVE", "REJECT", "REQUEST_MORE"})


def validate_text(value, max_chars=1400):
    require(isinstance(value, str) and 0 < len(value.strip()) <= max_chars,
            "业务说明不能为空或超过限制", web.HTTPBadRequest)
    return value.strip()


def existing(db, kind, key):
    row = db.execute(
        "SELECT body FROM objects WHERE namespace=? AND kind=? AND id=?",
        (NS, kind, key),
    ).fetchone()
    return json.loads(row[0]) if row else None


def valid_source(api, db, owner_id, source_id, version):
    require(isinstance(source_id, str) and isinstance(version, str),
            "来源和版本缺少", web.HTTPBadRequest)
    doc = api._require_current_source(db, {"owner_id": owner_id}, source_id)
    require(doc["version"] == version, "来源版本已经变化")
    return doc


def currency_amount(value):
    require(isinstance(value, str) and re.fullmatch(r"[0-9]{1,12}(?:\.[0-9]{1,2})?", value),
            "金额必须是明确的十进制 CNY 数值", web.HTTPBadRequest)
    try:
        amount = Decimal(value)
    except InvalidOperation:
        raise web.HTTPBadRequest(text="金额不可解析") from None
    require(amount > 0, "金额必须大于零", web.HTTPBadRequest)
    return str(amount.quantize(Decimal("0.01")))


def minutes_save(api, db, data, payload):
    api._exact(payload, {
        "client_request_id", "meeting_id", "meeting_version",
        "source_id", "source_version", "expected_version", "entries",
    })
    meeting = data["meeting"]
    require(payload["meeting_id"] == meeting["meeting_id"]
            and payload["meeting_version"] == meeting["version"],
            "纪要关联会议或会议版本无效")
    doc = valid_source(api, db, data["owner_id"], payload["source_id"], payload["source_version"])
    require(payload["source_id"] in meeting["material_ids"],
            "纪要来源不属于该会议", web.HTTPBadRequest)
    rows = payload["entries"]
    require(isinstance(rows, list) and 1 <= len(rows) <= 30,
            "纪要必须包含1至30条已分类内容", web.HTTPBadRequest)
    cleaned = []
    for i, row in enumerate(rows):
        require(isinstance(row, dict) and set(row) == {"kind", "text", "source_anchor"},
                "每条纪要必须保留分类、正文与原文位置", web.HTTPBadRequest)
        require(row["kind"] in ENTRY_KINDS, "纪要分类无效", web.HTTPBadRequest)
        anchor = validate_text(row["source_anchor"], 200)
        require(anchor in doc.get("content", ""),
                "原文位置无法在当前版本资料中核查", web.HTTPBadRequest)
        cleaned.append({
            "entry_id": f"entry-{i+1:02d}",
            "kind": row["kind"],
            "text": validate_text(row["text"]),
            "source_anchor": anchor,
            "source_id": doc["source_id"],
            "source_version": doc["version"],
            "task_created": False,
            "message_sent": False,
        })
    previous = existing(db, "minutes", payload["meeting_id"])
    previous_version = previous["version"] if previous else "0"
    require(payload["expected_version"] == previous_version,
            "纪要版本冲突，请重读当前草稿")
    if previous:
        api.store.put(db, NS, "minutes_revision",
                      f'{payload["meeting_id"]}:v{previous_version}', previous)
    minute = {
        "minute_id": "minutes:" + meeting["meeting_id"],
        "meeting_id": meeting["meeting_id"],
        "meeting_version": meeting["version"],
        "source_id": doc["source_id"],
        "source_version": doc["version"],
        "entries": cleaned,
        "version": str(int(previous_version) + 1),
        "state": "DRAFT_REVIEW",
        "confirmed_at": None,
        "confirmation_authorization_id": None,
        "updated_at": now(),
        "source_type": "SIMULATED",
        "task_count_created": 0,
        "message_count_sent": 0,
    }
    api.store.put(db, NS, "minutes", meeting["meeting_id"], minute)
    return {
        "minute_id": minute["minute_id"], "meeting_id": meeting["meeting_id"],
        "version": minute["version"], "state": minute["state"],
        "entry_count": len(cleaned),
        "decision_count_confirmed": 0,
        "tasks_created": 0, "messages_sent": 0,
        "source_type": "SIMULATED",
    }


def minutes_confirm(api, db, data, payload):
    api._exact(payload, {
        "client_request_id", "meeting_id", "expected_version",
        "source_id", "source_version",
    })
    current = api.store.get(db, NS, "minutes", payload["meeting_id"])
    require(payload["meeting_id"] == data["meeting"]["meeting_id"]
            and current["meeting_version"] == data["meeting"]["version"],
            "会议版本已变更")
    require(current["version"] == payload["expected_version"],
            "纪要内容版本变化")
    require(current["state"] == "DRAFT_REVIEW",
            "本次纪要已确认，不能重复用新请求编号确认")
    require(current["source_id"] == payload["source_id"] and
            current["source_version"] == payload["source_version"],
            "确认的资料标识或版本与草稿不同")
    valid_source(api, db, data["owner_id"], current["source_id"], current["source_version"])
    # Authorize only the *digest*, not raw private meeting text.
    auth_id = api._authorize(db, "minutes.confirm", {
        "meeting_id": current["meeting_id"], "minute_version": current["version"],
        "source_id": current["source_id"],
        "source_version": current["source_version"],
        "entries_sha256": checksum(current["entries"]),
    }, current["minute_id"], current["version"])
    api.store.put(db, NS, "minutes_revision",
                  f'{current["meeting_id"]}:v{current["version"]}', current)
    current["version"] = str(int(current["version"]) + 1)
    current["state"] = "CONFIRMED"
    current["confirmed_at"] = now()
    current["confirmation_authorization_id"] = auth_id
    current["updated_at"] = current["confirmed_at"]
    api.store.put(db, NS, "minutes", current["meeting_id"], current)
    return {
        "minute_id": current["minute_id"],
        "meeting_id": current["meeting_id"], "version": current["version"],
        "state": "CONFIRMED", "authorization_id": auth_id,
        "decision_count_confirmed": sum(1 for row in current["entries"] if row["kind"] == "DECISION"),
        "tasks_created": 0, "messages_sent": 0,
        "source_type": "SIMULATED",
    }


def application_seed(api, db, data, payload):
    """MAINTAINER provides a new synthetic application and attachment.

    The owner is NOT impersonated and no approval is inferred.
    """
    api._exact(payload, {
        "client_request_id", "application_id", "applicant_contact_id",
        "amount_cny", "title", "description", "attachment_text",
    })
    require(payload["application_id"] == "application-1",
            "当前获准模拟数据集只允许 application-1", web.HTTPBadRequest)
    require(payload["applicant_contact_id"] in {
        c["contact_id"] for c in data["contacts"] if c["contact_id"] != "contact-2"
    }, "申请联系人须来自当前内部模拟资料", web.HTTPBadRequest)
    require(existing(db, "application", payload["application_id"]) is None,
            "模拟申请已经存在，先读取当前版本")
    amount = currency_amount(payload["amount_cny"])
    title = validate_text(payload["title"], 100)
    description = validate_text(payload["description"], 1500)
    attachment = validate_text(payload["attachment_text"], 2500)
    require(len(attachment) >= 12,
            "模拟申请必须具有完整附件内容", web.HTTPBadRequest)
    source_id = payload["application_id"] + "-attachment"
    doc = {
        "source_id": source_id, "version": "1",
        "source_type": "SIMULATED",
        "author_contact_id": payload["applicant_contact_id"],
        "access_scope": data["owner_id"],
        "published_at": now(), "withdrawn": False,
        "original_locator": "sqlite:applications/" + source_id,
        "content": attachment,
    }
    api.store.put(db, NS, "document", source_id, doc)
    db.execute(
        "INSERT INTO knowledge(namespace,source_id,content) VALUES (?,?,?)",
        (NS, source_id, attachment),
    )
    application = {
        "application_id": payload["application_id"], "title": title,
        "description": description,
        "applicant_contact_id": payload["applicant_contact_id"],
        "amount": amount, "currency": "CNY",
        "version": "1", "source_id": source_id,
        "source_version": "1", "state": "PENDING_DECISION",
        "source_type": "SIMULATED",
        "seeded_by_role": "MAINTAINER",
        "created_at": now(),
        "decision_id": None,
        "funds_transferred": False,
        "professional_release_issued": False,
    }
    api.store.put(db, NS, "application", application["application_id"], application)
    return {
        "application_id": application["application_id"],
        "source_id": source_id, "version": "1", "source_version": "1",
        "state": "PENDING_DECISION",
        "source_type": "SIMULATED",
        "owner_authorization_created": False,
        "funds_transferred": False,
    }


def approval_decide(api, db, data, payload):
    api._exact(payload, {
        "client_request_id", "application_id", "expected_version",
        "source_id", "source_version", "amount", "currency",
        "decision", "comment",
    })
    app = api.store.get(db, NS, "application", payload["application_id"])
    require(app["version"] == payload["expected_version"],
            "申请版本冲突，必须重新审阅附件、金额和币种")
    require(app["state"] in ("PENDING_DECISION", "WAITING_MATERIAL"),
            "此版本申请已有有效终态")
    require(payload["source_id"] == app["source_id"]
            and payload["source_version"] == app["source_version"],
            "附件版本或标识变化")
    require(payload["currency"] == app["currency"] == "CNY"
            and payload["amount"] == app["amount"],
            "金额或币种变化，旧授权无效")
    require(payload["decision"] in DECISIONS,
            "本次决定不属于获准动作", web.HTTPBadRequest)
    comment = validate_text(payload["comment"], 1200)
    if payload["decision"] == "APPROVE":
        valid_source(api, db, data["owner_id"], app["source_id"], app["source_version"])
        require(app["amount"] not in (None, "0", "0.00"),
                "当前申请缺少有效金额及依据", web.HTTPBadRequest)
    else:
        # When requesting additional material, a revoked original is allowed:
        # the owner is not approving or relying upon the invalid attachment.
        if payload["decision"] == "REJECT":
            valid_source(api, db, data["owner_id"], app["source_id"], app["source_version"])
    authorization_id = api._authorize(
        db, "approval.decide", {
            "application_id": app["application_id"],
            "version": app["version"], "source_id": app["source_id"],
            "source_version": app["source_version"],
            "amount": app["amount"], "currency": app["currency"],
            "decision": payload["decision"],
            "comment_sha256": checksum(comment),
        }, app["application_id"], app["version"],
    )
    state = {
        "APPROVE": "APPROVED_RECORDED",
        "REJECT": "REJECTED_RECORDED",
        "REQUEST_MORE": "WAITING_MATERIAL",
    }[payload["decision"]]
    decision_id = str(uuid.uuid4())
    decision = {
        "decision_id": decision_id,
        "application_id": app["application_id"],
        "application_version": app["version"],
        "source_id": app["source_id"], "source_version": app["source_version"],
        "amount": app["amount"], "currency": app["currency"],
        "action": payload["decision"], "comment": comment,
        "authorization_id": authorization_id, "recorded_at": now(),
        "source_type": "SIMULATED",
        "funds_transferred": False, "professional_release_issued": False,
    }
    api.store.put(db, NS, "application_decision", decision_id, decision)
    api.store.put(db, NS, "application_revision",
                  f'{app["application_id"]}:v{app["version"]}', app)
    app["state"] = state
    app["version"] = str(int(app["version"]) + 1)
    app["decision_id"] = decision_id
    app["decision_authorization_id"] = authorization_id
    app["updated_at"] = now()
    api.store.put(db, NS, "application", app["application_id"], app)
    return {
        "application_id": app["application_id"], "version": app["version"],
        "state": state, "decision_id": decision_id,
        "authorization_id": authorization_id, "decision": payload["decision"],
        "source_type": "SIMULATED",
        "funds_transferred": False, "professional_release_issued": False,
    }
