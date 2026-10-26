import os
import base64
import stat
from pathlib import Path
from urllib.parse import parse_qs

import jsonlines
from aiohttp import web
from nanobot.runtime_context import public_history_message
from nanobot.session.history_visibility import is_hidden_history_message
from nanobot.session.manager import JsonlSessionStore, Session
from nanobot.utils.helpers import strip_think

from business import require
from boss_owner_history import owner_spaces
from boss_conversation_attachments import ConversationAttachments
from boss_conversation import validate

PAGE_SIZE = 30


def session_history(db, snapshot, query):
    parameters = parse_qs(query, keep_blank_values=True)
    require(set(parameters) <= {"namespace", "session_key", "page", "attachment_id"}
            and all(len(values) == 1 and values[0] for values in parameters.values()),
            "历史会话查询参数无效", web.HTTPBadRequest)
    namespace = parameters.get("namespace", [None])[0]
    key = parameters.get("session_key", [None])[0]
    attachment_id = parameters.get("attachment_id", [None])[0]
    require(attachment_id is None or key is not None and "page" not in parameters,
            "附件读取需要原会话编号且不接受消息页码", web.HTTPBadRequest)
    page_value = parameters.get("page", ["1"])[0]
    require(page_value.isascii() and page_value.isdigit() and 1 <= int(page_value) <= 100000,
            "历史会话页码无效", web.HTTPBadRequest)
    page = int(page_value)
    archives = [(scope, initial, archive) for scope, initial, archive in owner_spaces(db, snapshot) if archive]
    spaces = [{"namespace": scope, "dataset_id": initial["dataset_id"], "dataset_version": initial["dataset_version"],
               "archived_at": archive["archived_at"],
               "session_count": sum(item["key"].startswith("websocket:") for item in archive["sessions"])}
              for scope, initial, archive in archives]
    result = {"spaces": spaces, "historical_namespace": namespace, "session_key": key,
              "state": "READ_ONLY_HISTORY", "current_evidence_eligible": False,
              "sessions": [], "messages": [], "attachments": [], "attachments_state": "NOT_SELECTED",
              "page": page, "page_size": PAGE_SIZE, "total": 0}
    if namespace is None:
        require(key is None and page == 1, "需要选择原执行空间", web.HTTPBadRequest)
        return result
    match = [(initial, archive) for scope, initial, archive in archives if scope == namespace]
    require(len(match) == 1, "没有获准的归档执行空间", web.HTTPNotFound)
    initial, archive = match[0]
    result.update(dataset_id=initial["dataset_id"], dataset_version=initial["dataset_version"], archived_at=archive["archived_at"])
    sessions = sorted([item for item in archive["sessions"] if item["key"].startswith("websocket:")],
                      key=lambda item: (item["updated_at"], item["key"]), reverse=True)
    if key is None:
        result.update(sessions=sessions[(page - 1) * PAGE_SIZE:page * PAGE_SIZE], total=len(sessions))
        return result
    require(len(key) <= 256 and any(item["key"] == key for item in sessions), "原会话不存在或没有读取权限", web.HTTPNotFound)
    directory = Path(archive["sessions_directory"])
    require(directory.is_absolute() and directory.resolve() == directory and directory.is_dir(),
            "原会话目录无法核查", web.HTTPConflict)
    path = directory / (JsonlSessionStore.storage_key(key) + ".jsonl")
    require(path.is_file() and not path.is_symlink(), "原会话文件不存在或无法读取", web.HTTPGone)
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor, "rb") as source:
        before = os.fstat(source.fileno())
        require(stat.S_ISREG(before.st_mode), "原会话文件类型无效", web.HTTPConflict)
        with jsonlines.Reader(source) as reader:
            metadata = reader.read(type=dict)
            require(metadata.get("_type") == "metadata" and metadata.get("key") == key,
                    "原会话文件与编号不一致", web.HTTPConflict)
            total = 0
            selected = []
            persisted_messages = []
            for item in reader.iter(type=dict):
                if item.get("_type") == "provider_state":
                    continue
                require("_type" not in item, "原会话包含无法识别的记录", web.HTTPConflict)
                persisted_messages.append(item)
                if item.get("role") not in {"user", "assistant"} or is_hidden_history_message(item):
                    continue
                public = public_history_message(item)
                content = public.get("content")
                if isinstance(content, list):
                    content = "\n".join(block["text"] for block in content
                                        if isinstance(block, dict) and block.get("type") == "text" and isinstance(block.get("text"), str))
                require(content is None or isinstance(content, str), "原会话消息内容格式无效", web.HTTPConflict)
                content = strip_think(content) if content and item["role"] == "assistant" else content
                if not content and not item.get("media"):
                    continue
                if (page - 1) * PAGE_SIZE <= total < page * PAGE_SIZE:
                    selected.append({"index": total, "role": item["role"], "content": content if content is not None else "",
                                     "timestamp": item.get("timestamp")})
                total += 1
        after = os.fstat(source.fileno())
        require((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
                == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns),
                "原会话文件已经变化，需要重新读取", web.HTTPConflict)
    result.update(messages=selected, total=total, created_at=metadata.get("created_at"), updated_at=metadata.get("updated_at"))
    saved_metadata = metadata.get("metadata", {})
    require(isinstance(saved_metadata, dict), "原会话元信息格式无效", web.HTTPConflict)
    session = Session(key=key, messages=persisted_messages, metadata=saved_metadata)
    stored = saved_metadata.get("boss_attachment_metadata", {})
    require(isinstance(stored, dict), "原附件保存记录格式无效", web.HTTPConflict)
    for identifier, value in stored.items():
        validate("Id", identifier)
        validate("StoredAttachment", value)
    media_directory = archive.get("media_directory")
    if media_directory is None:
        require(attachment_id is None, "原媒体目录没有归档记录，无法读取附件", web.HTTPConflict)
        result.update(attachments_state="MEDIA_DIRECTORY_UNRECORDED", attachments=[{
            "attachment_id": identifier, "original_name": value["original_name"], "stored_name": None,
            "mime_type": value["mime_type"], "recorded_size_bytes": value["size_bytes"],
            "recorded_content_sha256": value["content_sha256"], "processing_state": "REFERENCE_UNAVAILABLE",
            "download_available": False, "user_message_index": None,
        } for identifier, value in stored.items()])
        return result
    media_root = Path(media_directory)
    require(media_root.is_absolute() and media_root.resolve() == media_root,
            "原媒体目录引用无法核查", web.HTTPConflict)
    attachments = ConversationAttachments(None, media_root)
    context = {"session_id": key, "chat_id": key.removeprefix("websocket:")}
    if attachment_id is not None:
        validate("Id", attachment_id)
        item, content = attachments.read_content("BOSS", context, session, attachment_id)
        result.update(messages=[], total=0, attachments_state="VERIFIED", download={
            "attachment_id": attachment_id, "filename": item["original_name"] or item["stored_name"],
            "mime_type": item["mime_type"], "content_sha256": item["recorded_content_sha256"],
            "size_bytes": len(content), "encoding": "base64", "content": base64.b64encode(content).decode("ascii"),
        })
        return result
    view = attachments.read_snapshot("BOSS", context, session)
    result.update(attachments_state="READ", attachments=[{
        **item, "download_available": item["processing_state"] == "STORED" and item["recorded_content_sha256"] is not None,
    } for item in view["attachments"]])
    return result
