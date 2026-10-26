import base64
import hashlib
from datetime import date
from io import BytesIO
from pathlib import PurePath
from urllib.parse import parse_qs
from zipfile import ZipFile

from aiohttp import web
from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph
from pypdf import PdfReader

from business import now, require
from boss_knowledge_ingestion import create, revise, withdraw, _validate_publication
from boss_source_policy import source_validity
from boss_v7_store import NAMESPACE, optional, rows, text

MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_TEXT_CHARS = 2_000_000
VISIBILITY = "OWNER_APPROVED_SIMULATED"


def _editable(document, snapshot):
    return (document.get("created_by_role") == "MAINTAINER"
            and document.get("source_type") == "SIMULATED"
            and document.get("access_scope") == snapshot["owner_id"])


def read_knowledge(store, db, snapshot):
    sources = []
    for document in rows(db, "document"):
        permitted = _editable(document, snapshot)
        upload = optional(db, "knowledge_upload", document["source_id"] + ":v" + document["version"]) if permitted else None
        sources.append({
            "id": document["source_id"], "title": document.get("title", document["source_id"]),
            "author_id": document.get("author_contact_id", ""),
            "observed_at": document.get("observed_date", document.get("observed_at", "")[:10]),
            "published_at": document.get("published_at", "")[:10],
            "valid_until": document.get("valid_until"), "visibility": VISIBILITY,
            "version": document["version"], "index_state": document.get("index_state", "NOT_RECORDED"),
            "withdrawn": document.get("withdrawn", False),
            "editable": permitted and not document.get("withdrawn"),
            "source_type": document["source_type"], "file_name": upload["name"] if upload else "",
            "content_sha256": hashlib.sha256(document["content"].encode()).hexdigest() if permitted else "",
            "original_available": permitted, "error": None,
        })
    return {"sources": sources, "authors": [{"id": row["contact_id"], "label": row["name"]} for row in snapshot["contacts"]],
            "visibility_options": [{"id": VISIBILITY, "label": "本人获准模拟资料"}]}


def _docx_blocks(container, depth=0):
    require(depth <= 8, "DOCX表格嵌套超过允许范围", web.HTTPBadRequest)
    for block in container.iter_inner_content():
        if isinstance(block, Paragraph):
            yield block.text
        elif isinstance(block, Table):
            for row in block.rows:
                yield "\t".join("\n".join(_docx_blocks(cell, depth + 1)) for cell in row.cells)


def _extract(upload):
    require(isinstance(upload, dict) and set(upload) == {"name", "mime_type", "size", "content_base64"},
            "上传文件字段无效", web.HTTPBadRequest)
    name = text(upload["name"], "文件名称", 255)
    require(PurePath(name).name == name and "\\" not in name, "文件名称不能包含目录", web.HTTPBadRequest)
    require(type(upload["size"]) is int and 0 < upload["size"] <= MAX_FILE_BYTES,
            "文件大小需要在20 MB以内", web.HTTPBadRequest)
    encoded = text(upload["content_base64"], "文件编码", (MAX_FILE_BYTES + 2) // 3 * 4)
    raw = base64.b64decode(encoded, validate=True)
    require(len(raw) == upload["size"], "文件大小与上传记录不符", web.HTTPBadRequest)
    extension = PurePath(name).suffix.lower()
    require(extension in {".txt", ".md", ".pdf", ".docx"}, "文件类型未获准", web.HTTPBadRequest)
    if extension in {".txt", ".md"}:
        content = raw.decode("utf-8-sig")
    elif extension == ".pdf":
        reader = PdfReader(BytesIO(raw), strict=True)
        require(not reader.is_encrypted, "需要提供可直接读取的PDF", web.HTTPBadRequest)
        require(len(reader.pages) <= 1000, "PDF页数超过1000页", web.HTTPBadRequest)
        content = "\n\n".join(page.extract_text() for page in reader.pages)
    else:
        with ZipFile(BytesIO(raw)) as archive:
            entries = archive.infolist()
            require(len(entries) <= 5000 and sum(entry.file_size for entry in entries) <= 100 * 1024 * 1024,
                    "DOCX展开内容超过允许范围", web.HTTPBadRequest)
        content = "\n".join(_docx_blocks(Document(BytesIO(raw))))
    require(30 <= len(content.strip()) <= MAX_TEXT_CHARS, "文件可读正文需要包含30至2000000个字符", web.HTTPBadRequest)
    return content.strip(), {**upload, "sha256": hashlib.sha256(raw).hexdigest()}


def mutate_knowledge(api, db, snapshot, payload, action):
    api._exact(payload, {"client_request_id", "source_id", "expected_version", "values", "upload", "text", "confirmation"})
    require(payload["confirmation"] is True, "需要确认来源操作", web.HTTPBadRequest)
    if action == "withdraw":
        return withdraw(api, db, snapshot, {key: payload[key] for key in ("client_request_id", "source_id", "expected_version")})
    values = payload["values"]
    require(isinstance(values, dict), "来源字段无效", web.HTTPBadRequest)
    api._exact(values, {"source_id", "title", "author_id", "observed_at", "published_at", "valid_until", "visibility", "change_note"})
    require(payload["source_id"] == values["source_id"], "来源标识不一致", web.HTTPBadRequest)
    require(values["visibility"] == VISIBILITY, "来源范围未获准", web.HTTPForbidden)
    observed = _validate_publication(values["observed_at"])
    published = _validate_publication(values["published_at"])
    expires = _validate_publication(values["valid_until"]) if values["valid_until"] else None
    require(expires is None or date.fromisoformat(expires) > date.fromisoformat(published), "有效期限必须晚于发布日期", web.HTTPBadRequest)
    change_note = text(values["change_note"], "变更说明", 2000)
    upload = None
    if payload["upload"] is not None:
        require(payload["text"] == "", "文件和直接文本只能选择其中一项", web.HTTPBadRequest)
        content, upload = _extract(payload["upload"])
    else:
        content = text(payload["text"], "来源正文", MAX_TEXT_CHARS)
    adapted = {"client_request_id": payload["client_request_id"], "source_id": payload["source_id"],
               "title": values["title"], "author_contact_id": values["author_id"], "published_at": published, "content": content}
    if action == "revise":
        adapted["expected_version"] = payload["expected_version"]
        result = revise(api, db, snapshot, adapted)
    else:
        require(action == "ingest" and payload["expected_version"] == "0", "新增来源版本无效", web.HTTPBadRequest)
        result = create(api, db, snapshot, adapted)
    record = api.store.get(db, NAMESPACE, "document", result["source_id"])
    record.update(observed_date=observed, valid_until=expires, change_note=change_note,
                  content_sha256=hashlib.sha256(content.encode()).hexdigest(), received_at=now())
    api.store.put(db, NAMESPACE, "document", record["source_id"], record)
    if upload is not None:
        api.store.put(db, NAMESPACE, "knowledge_upload", record["source_id"] + ":v" + record["version"], upload)
    return result


def search_knowledge(store, db, snapshot, query_string):
    params = parse_qs(query_string, keep_blank_values=True, strict_parsing=True)
    require(set(params) == {"query"} and len(params["query"]) == 1, "检索参数无效", web.HTTPBadRequest)
    query = text(params["query"][0], "检索内容", 500)
    pattern = "%" + query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    matches = db.execute("SELECT source_id,content FROM knowledge_text WHERE namespace=? AND content LIKE ? ESCAPE '\\' ORDER BY source_id", (NAMESPACE, pattern)).fetchall()
    clock = store.get(db, NAMESPACE, "clock", "current")["at"]
    hits = []
    for source_id, indexed in matches:
        document = store.get(db, NAMESPACE, "document", source_id)
        if not _editable(document, snapshot) or source_validity(document, clock) != "VALID":
            continue
        content = document["content"]
        require(indexed == content, "来源索引与当前版本不一致")
        position = content.casefold().find(query.casefold())
        start = max(0, position - 80)
        end = min(len(content), start + 400)
        hits.append({"source_id": source_id, "version": document["version"], "title": document["title"],
                     "excerpt": content[start:end], "start": start, "end": end, "index_state": document["index_state"]})
        if len(hits) == 50:
            break
    return {"projection": "knowledge-search", "hits": hits, "read_at": now()}
