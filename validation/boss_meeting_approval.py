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
from boss_meetings import meeting_materials
from boss_source_access import require_current_business_source

from boss_execution_scope import NAMESPACE as NS
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
    require_current_business_source(api.store, db, NS, owner_id, source_id)
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
    data = meeting_materials(db, data)
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
    data = meeting_materials(db, data)
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



def minutes_assignment_create(api, db, data, payload, key):
    """Create ONE explicitly authorized task from a CONFIRMED minute entry.

    Both task and minute-entry link commit inside BossCommandAPI's original
    BEGIN IMMEDIATE transaction. This action never sends messages. Confirming
    the minutes alone cannot create a task.
    """
    api._exact(payload, {
        "client_request_id", "meeting_id", "minute_version",
        "entry_id", "purpose", "coordinator_id", "due_at",
        "timezone", "evidence_requirements",
    })
    data = meeting_materials(db, data)
    meeting = data["meeting"]
    require(payload["meeting_id"] == meeting["meeting_id"],
            "交办草稿所属会议不符", web.HTTPBadRequest)
    minute = api.store.get(db, NS, "minutes", meeting["meeting_id"])
    require(minute["state"] == "CONFIRMED"
            and minute["meeting_version"] == meeting["version"],
            "纪要尚未确认，或者关联会议版本已变化")
    require(minute["version"] == payload["minute_version"],
            "纪要确认版本已变化，必须重新核查")
    require(isinstance(payload["entry_id"], str)
            and payload["entry_id"].startswith("entry-"),
            "纪要交办条目 ID 无效", web.HTTPBadRequest)
    entry = next(
        (item for item in minute["entries"]
         if item["entry_id"] == payload["entry_id"]), None,
    )
    require(entry is not None and entry["kind"] == "ASSIGNMENT_DRAFT",
            "仅已确认纪要中的交办草稿能够逐项创建", web.HTTPBadRequest)
    doc = valid_source(
        api, db, data["owner_id"], minute["source_id"], minute["source_version"]
    )
    require(entry["source_id"] == doc["source_id"]
            and entry["source_version"] == doc["version"]
            and entry["source_anchor"] in doc.get("content", ""),
            "交办草稿原文已更改或无法验证", web.HTTPForbidden)
    # Each *confirmed minute version* has its own immutable entry identity.
    # A newer, independently reconfirmed revision may define new work without
    # rewriting or silently resending the old task.
    link_id = (
        meeting["meeting_id"] + ":v" + minute["version"]
        + ":" + entry["entry_id"]
    )
    require(existing(db, "minutes_assignment_link", link_id) is None,
            "该纪要条目已经创建关联任务，请读取任务状态；不可重复创建")

    # The existing verified FR-06 creation path owns assignment semantics,
    # contact/date checks, source authorization and task construction.
    # FR-05 cannot relax it or invent a different simulation data scope.
    original = {
        "client_request_id": key,
        "purpose": payload["purpose"],
        "coordinator_id": payload["coordinator_id"],
        "due_at": payload["due_at"],
        "timezone": payload["timezone"],
        "evidence_requirements": payload["evidence_requirements"],
        "related_meeting_id": meeting["meeting_id"],
        "related_event_ids": [data["event"]["event_id"]],
        "source_refs": ["finance-note"],
        "content_version": "1",
    }
    created = api._create(db, data, original, key)
    task_id = created["task_id"]
    origin = {
        "origin_minute_id": minute["minute_id"],
        "origin_minute_version": minute["version"],
        "origin_entry_id": entry["entry_id"],
        "origin_source_id": doc["source_id"],
        "origin_source_version": doc["version"],
    }
    task = api.store.get(db, NS, "task", task_id)
    task.update(origin)
    api.store.put(db, NS, "task", task_id, task)
    binding = api.store.get(db, NS, "assignment_source_binding", task_id)
    binding["origin_source"] = {"source_id": doc["source_id"], "version": doc["version"], "sha256": checksum(doc)}
    api.store.put(db, NS, "assignment_source_binding", task_id, binding)
    link = {
        "link_id": link_id,
        "meeting_id": meeting["meeting_id"],
        "minute_id": minute["minute_id"],
        "minute_version": minute["version"],
        "entry_id": entry["entry_id"],
        "entry_kind": "ASSIGNMENT_DRAFT",
        "entry_text_sha256": checksum(entry["text"]),
        "source_id": doc["source_id"],
        "source_version": doc["version"],
        "task_id": task_id,
        "authorization_id": created["authorization_id"],
        "linked_at": now(),
        "task_status_at_link": "OPEN",
        "message_sent_at_link": False,
        "source_type": "SIMULATED",
    }
    api.store.put(db, NS, "minutes_assignment_link", link_id, link)
    return {
        "source_type": "SIMULATED",
        "meeting_id": meeting["meeting_id"],
        "minute_id": minute["minute_id"],
        "minute_version": minute["version"],
        "entry_id": entry["entry_id"],
        "task_id": task_id,
        "status": "OPEN",
        "version": created["version"],
        "authorization_id": created["authorization_id"],
        "message_sent": False,
        "independent_send_required": True,
    }


def application_seed(api, db, data, payload):
    """MAINTAINER provides a new synthetic application and attachment.

    The owner is NOT impersonated and no approval is inferred.
    """
    api._exact(payload, {
        "client_request_id", "application_id", "applicant_contact_id",
        "amount_cny", "title", "description", "attachment_text",
    })
    require(payload["application_id"] in {"application-1", *data.get("simulation_application_ids", [])},
            "申请编号不在当前获准模拟资料中", web.HTTPBadRequest)
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
        "valid_from": api.store.get(db, NS, "clock", "current")["at"],
        "valid_until": None, "validity_state": "VALID",
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



def application_revise(api, db, data, payload):
    """MAINTAINER replaces missing/withdrawn synthetic material after request-more.

    Old application & source versions are archived for traceability; they can
    no longer authorize approval. The new file is an *explicit* simulation.
    """
    api._exact(payload, {
        "client_request_id", "application_id", "expected_version",
        "applicant_contact_id", "amount_cny", "title", "description",
        "attachment_text",
    })
    app = api.store.get(db, NS, "application", payload["application_id"])
    require(app["state"] == "WAITING_MATERIAL",
            "仅收到本人请求补充材料的申请可以由维护端更新")
    require(app["version"] == payload["expected_version"],
            "申请版本已变化，禁止使用旧材料覆盖")
    require(app["applicant_contact_id"] == payload["applicant_contact_id"],
            "模拟申请对象改变必须作为新申请审查", web.HTTPBadRequest)
    amount = currency_amount(payload["amount_cny"])
    title = validate_text(payload["title"], 100)
    description = validate_text(payload["description"], 1500)
    attachment = validate_text(payload["attachment_text"], 2500)
    require(len(attachment) >= 12, "模拟补充附件内容不足", web.HTTPBadRequest)
    doc = api.store.get(db, NS, "document", app["source_id"])
    require(doc["version"] == app["source_version"] and
            doc.get("access_scope") == data["owner_id"] and
            doc.get("source_type") == "SIMULATED",
            "申请附件身份或版本变化", web.HTTPForbidden)
    old_version = doc["version"]
    api.store.put(db, NS, "document_revision",
                  f'{doc["source_id"]}:v{old_version}', doc)
    api.store.put(db, NS, "application_revision",
                  f'{app["application_id"]}:v{app["version"]}', app)
    doc["version"] = str(int(doc["version"]) + 1)
    doc["content"] = attachment
    doc["published_at"] = now()
    doc["valid_from"] = api.store.get(db, NS, "clock", "current")["at"]
    doc["valid_until"] = None
    doc["validity_state"] = "VALID"
    doc["withdrawn"] = False
    doc["withdrawn_at"] = None
    doc["replaced_source_version"] = old_version
    api.store.put(db, NS, "document", doc["source_id"], doc)
    db.execute("DELETE FROM knowledge WHERE namespace=? AND source_id=?",
               (NS, doc["source_id"]))
    db.execute("INSERT INTO knowledge(namespace,source_id,content) VALUES(?,?,?)",
               (NS, doc["source_id"], attachment))
    app["version"] = str(int(app["version"]) + 1)
    app["source_version"] = doc["version"]
    app["title"], app["description"], app["amount"] = title, description, amount
    app["state"] = "PENDING_DECISION"
    app["decision_id"] = None
    app["updated_at"] = now()
    app["funds_transferred"] = False
    app["professional_release_issued"] = False
    api.store.put(db, NS, "application", app["application_id"], app)
    return {
        "application_id": app["application_id"],
        "version": app["version"], "source_version": app["source_version"],
        "source_id": app["source_id"], "state": app["state"],
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
