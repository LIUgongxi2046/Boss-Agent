import hashlib
import mimetypes
from pathlib import Path

from aiohttp import web
from nanobot.webui.attachment_ingress import extract_data_url_mime

from business import checksum, require
from boss_conversation import owner_role, validate


class ConversationAttachments:
    def __init__(self, sessions, media_root):
        self.sessions = sessions
        self.media_root = Path(media_root).resolve()

    def record_upload(self, role, query, accepted_media, accepted_paths):
        owner_role(role)
        validate("Context", query)
        require(isinstance(query["chat_id"], str) and query["session_id"] == "websocket:" + query["chat_id"], "原生附件会话归属不符", web.HTTPForbidden)
        require(isinstance(accepted_media, list) and isinstance(accepted_paths, list) and len(accepted_media) == len(accepted_paths), "原生上传结果与选择记录不符", web.HTTPBadRequest)
        prepared = {}
        for media, filename in zip(accepted_media, accepted_paths):
            require(isinstance(media, dict) and isinstance(filename, str), "原生上传元信息无效", web.HTTPBadRequest)
            path = Path(filename).resolve()
            require(path.is_relative_to(self.media_root) and path.is_file(), "上传文件不属于当前获准媒体目录", web.HTTPForbidden)
            name = media.get("name")
            require(name is None or isinstance(name, str) and name and Path(name).name == name and "\x00" not in name, "原上传文件名无效", web.HTTPBadRequest)
            mime = extract_data_url_mime(media.get("data_url"))
            require(mime is not None, "上传类型缺少原生有效记录", web.HTTPBadRequest)
            identifier = "attachment-" + checksum({"session_id": query["session_id"], "path": str(path)})
            prepared[identifier] = {"original_name": name, "mime_type": mime, "content_sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "size_bytes": path.stat().st_size}
        # 仅由原生入口在实际上传成功后调用；该元信息不提供业务授权。
        session = self.sessions.get_or_create(query["session_id"])
        current = session.metadata.get("boss_attachment_metadata", {})
        require(all(identifier not in current or current[identifier] == value for identifier, value in prepared.items()), "上传附件的已保存元信息发生变化")
        session.metadata["boss_attachment_metadata"] = {**current, **prepared}
        self.sessions.save(session)
        return validate("UploadMetadataResult", {"session_id": session.key, "attachment_ids": list(prepared), "metadata_saved": True, "business_authorization_granted": False})

    def read(self, role, query):
        owner_role(role)
        validate("Context", query)
        require(isinstance(query["chat_id"], str) and query["session_id"] == "websocket:" + query["chat_id"], "原生附件会话归属不符", web.HTTPForbidden)
        session = self.sessions.read_session_snapshot(query["session_id"])
        attachments = []
        if session is not None:
            require(session.key == query["session_id"], "原生会话标识不符", web.HTTPForbidden)
            for index, message in enumerate(session.messages):
                if message["role"] != "user":
                    continue
                for filename in message.get("media", []):
                    path = Path(filename).resolve()
                    require(path.is_relative_to(self.media_root), "附件不属于当前获准媒体目录", web.HTTPForbidden)
                    present = path.is_file()
                    before = path.stat() if present else None
                    digest = hashlib.sha256(path.read_bytes()).hexdigest() if present else None
                    require(not present or (path.stat().st_size, path.stat().st_mtime_ns) == (before.st_size, before.st_mtime_ns), "读取期间附件发生变化")
                    identifier = "attachment-" + checksum({"session_id": session.key, "path": str(path)})
                    metadata = session.metadata.get("boss_attachment_metadata", {}).get(identifier)
                    require(not present or metadata is None or metadata["content_sha256"] == digest and metadata["size_bytes"] == before.st_size, "附件内容与实际上传版本不符")
                    attachments.append({"attachment_id": identifier,
                        "stored_name": path.name, "original_name": metadata["original_name"] if metadata else None,
                        "mime_type": metadata["mime_type"] if metadata else mimetypes.guess_type(path.name)[0], "size_bytes": before.st_size if present else None,
                        "content_sha256": digest, "processing_state": "STORED" if present else "MISSING", "user_message_index": index})
        return validate("Attachments", {"source_type": "RUNTIME_RECORD", **query, "session_state": "SAVED" if session else "NO_SAVED_SESSION",
            "attachments": attachments, "business_authorization_granted": False})
