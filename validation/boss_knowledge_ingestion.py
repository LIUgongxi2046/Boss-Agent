"""A07: reviewable, versioned SIMULATED knowledge source lifecycle.

Technical maintainer may only ingest *explicitly supplied* synthetic content
into the fixed approved selection space. No owner authorization, live external
crawling, simulated approval or privileged prompt instruction is inferred.
Business owner alone sees the current authorized source body. All writes join
the existing BossCommandAPI SQLite transaction and idempotency audit.
"""
from __future__ import annotations

import re
import json
from datetime import date

from aiohttp import web
from lxml.html import fragment_fromstring
from markdown_it import MarkdownIt

from business import now, require

NS = "ui-check"
CUSTOM_SOURCE_ID = re.compile(r"sim-doc-[a-z0-9][a-z0-9-]{2,59}\Z")
ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}\Z")
POTENTIAL_SECRET = re.compile(r"\bsk-[A-Za-z0-9_-]{25,}\b")


def _field_text(value, label, max_chars, min_chars=1):
    require(isinstance(value, str) and min_chars <= len(value.strip()) <= max_chars,
            f"{label}须为 {min_chars}—{max_chars} 字",
            web.HTTPBadRequest)
    require(not POTENTIAL_SECRET.search(value),
            "疑似凭据不应作为业务知识导入", web.HTTPBadRequest)
    return value.strip()


def _validate_publication(value):
    require(isinstance(value, str) and ISO_DATE.fullmatch(value),
            "发布日期必须为 YYYY-MM-DD", web.HTTPBadRequest)
    try:
        date.fromisoformat(value)
    except ValueError:
        raise web.HTTPBadRequest(text="发布日期不可解析") from None
    return value


def _validate_source(data, source_id):
    require(isinstance(source_id, str) and CUSTOM_SOURCE_ID.fullmatch(source_id),
            "只能维护当前获准演示的 sim-doc-* 来源标识",
            web.HTTPBadRequest)
    return source_id


def _validate_author(data, contact_id):
    require(isinstance(contact_id, str) and
            contact_id in {x["contact_id"] for x in data["contacts"]},
            "资料作者必须来自当前模拟关系资料", web.HTTPBadRequest)
    return contact_id


def _read(db, source_id):
    row = db.execute(
        "SELECT body FROM objects WHERE namespace=? AND kind='document' AND id=?",
        (NS, source_id),
    ).fetchone()
    return json.loads(row[0]) if row else None


def _reindex(db, source_id, text):
    indexed_text = None
    if text is not None:
        rendered = MarkdownIt("commonmark", {"html": False}).render(text)
        require(bool(rendered.strip()), "资料缺少可检索正文", web.HTTPBadRequest)
        document = fragment_fromstring(rendered, create_parent="div")
        indexed_text = "\n".join(document.itertext()).strip()
        require(bool(indexed_text), "资料缺少可检索正文", web.HTTPBadRequest)
    db.execute("DELETE FROM knowledge WHERE namespace=? AND source_id=?", (NS, source_id))
    if text is not None:
        db.execute(
            "INSERT INTO knowledge(namespace,source_id,content) VALUES(?,?,?)",
            (NS, source_id, indexed_text),
        )


def _change(api, db, data, payload, mode):
    create = mode == "create"
    fields = {
        "client_request_id", "source_id", "title", "author_contact_id",
        "published_at", "content",
    }
    if not create:
        fields.add("expected_version")
    api._exact(payload, fields)
    sid = _validate_source(data, payload["source_id"])
    title = _field_text(payload["title"], "资料标题", 120)
    author = _validate_author(data, payload["author_contact_id"])
    published = _validate_publication(payload["published_at"])
    content = _field_text(payload["content"], "模拟资料内容", 12000, 30)
    existing = _read(db, sid)
    if create:
        require(existing is None, "资料标识已存在，不能覆盖已有内容")
        count = db.execute(
            "SELECT COUNT(*) FROM objects WHERE namespace=? AND kind='document' AND id LIKE 'sim-doc-%'",
            (NS,),
        ).fetchone()[0]
        require(count < 50, "模拟自建资料已达到当前空间允许上限")
        version = "1"
    else:
        require(existing is not None, "当前来源不存在", web.HTTPNotFound)
        require(existing.get("created_by_role") == "MAINTAINER"
                and existing.get("source_type") == "SIMULATED"
                and existing.get("access_scope") == data["owner_id"],
                "无法修改非本次维护录入的来源", web.HTTPForbidden)
        require(not existing.get("withdrawn"),
                "已撤销来源不能在旧标识上静默恢复")
        require(existing["version"] == payload["expected_version"],
                "来源已由其他操作更新，请重新读取版本")
        api.store.put(db, NS, "document_revision",
                      sid + ":v" + existing["version"], existing)
        version = str(int(existing["version"]) + 1)
    record = {
        "source_id": sid,
        "source_type": "SIMULATED",
        "access_scope": data["owner_id"],
        "created_by_role": "MAINTAINER",
        "original_locator": "sqlite:documents/" + sid,
        "title": title,
        "content": content,
        "author_contact_id": author,
        "published_at": published,
        "observed_at": now(),
        "version": version,
        "withdrawn": False,
        "withdrawn_at": None,
        "index_state": "INDEXED_CURRENT",
    }
    api.store.put(db, NS, "document", sid, record)
    _reindex(db, sid, content)
    return {
        "source_type": "SIMULATED", "source_id": sid,
        "version": version, "index_state": "INDEXED_CURRENT",
        "withdrawn": False, "content_recorded_in_receipt": False,
        "business_action_authorized": False,
    }


def create(api, db, data, payload):
    return _change(api, db, data, payload, "create")


def revise(api, db, data, payload):
    return _change(api, db, data, payload, "revise")


def withdraw(api, db, data, payload):
    api._exact(payload, {"client_request_id", "source_id", "expected_version"})
    sid = _validate_source(data, payload["source_id"])
    doc = _read(db, sid)
    require(doc is not None, "来源不存在", web.HTTPNotFound)
    require(doc.get("created_by_role") == "MAINTAINER"
            and doc.get("access_scope") == data["owner_id"],
            "维护者不能撤销非本次录入的正式来源", web.HTTPForbidden)
    require(not doc.get("withdrawn") and doc["version"] == payload["expected_version"],
            "当前版本已变化或已撤销")
    api.store.put(db, NS, "document_revision",
                  sid + ":v" + doc["version"], doc)
    doc["version"] = str(int(doc["version"]) + 1)
    doc["withdrawn"] = True
    doc["withdrawn_at"] = now()
    doc["index_state"] = "WITHDRAWN"
    api.store.put(db, NS, "document", sid, doc)
    _reindex(db, sid, None)
    return {
        "source_type": "SIMULATED", "source_id": sid,
        "version": doc["version"], "index_state": "WITHDRAWN",
        "withdrawn": True, "source_history_preserved": True,
        "content_recorded_in_receipt": False,
    }
