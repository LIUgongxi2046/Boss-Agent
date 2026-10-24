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

    def _identifier(self, session_id, path):
        return "attachment-" + checksum({"session_id": session_id, "path": str(path)})

    def _approved_path(self, filename):
        path = Path(filename).resolve()
        require(path.is_relative_to(self.media_root), "附件不属于当前获准媒体目录", web.HTTPForbidden)
        require(not path.exists() or path.is_file(), "附件引用没有指向普通文件")
        return path

    def _metadata(self, session):
        metadata = session.metadata.get("boss_attachment_metadata", {})
        require(isinstance(metadata, dict), "附件保存记录无效")
        for identifier, value in metadata.items():
            validate("Id", identifier)
            validate("StoredAttachment", value)
        return metadata

    def _file_state(self, path):
        if not path.is_file():
            return None, None
        before = path.stat()
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        after = path.stat()
        require((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) ==
                (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns), "读取期间附件发生变化")
        return before.st_size, digest

    def record_upload(self, role, query, accepted_media, accepted_paths):
        owner_role(role)
        validate("Context", query)
        require(isinstance(query["chat_id"], str) and query["session_id"] == "websocket:" + query["chat_id"], "原生附件会话归属不符", web.HTTPForbidden)
        require(isinstance(accepted_media, list) and isinstance(accepted_paths, list) and len(accepted_media) == len(accepted_paths), "原生上传结果与选择记录不符", web.HTTPBadRequest)
        prepared = {}
        for media, filename in zip(accepted_media, accepted_paths):
            require(isinstance(media, dict) and isinstance(filename, str), "原生上传元信息无效", web.HTTPBadRequest)
            path = self._approved_path(filename)
            require(path.is_file(), "上传文件不属于当前获准媒体目录", web.HTTPForbidden)
            name = media.get("name")
            require(name is None or isinstance(name, str) and name and Path(name).name == name and "\x00" not in name, "原上传文件名无效", web.HTTPBadRequest)
            mime = extract_data_url_mime(media.get("data_url"))
            require(mime is not None, "上传类型缺少原生有效记录", web.HTTPBadRequest)
            identifier = self._identifier(query["session_id"], path)
            size, digest = self._file_state(path)
            require(size is not None, "上传文件已经缺失")
            prepared[identifier] = validate("StoredAttachment", {"original_name": name, "mime_type": mime,
                "content_sha256": digest, "size_bytes": size, "relative_path": path.relative_to(self.media_root).as_posix()})
        # 仅由原生入口在实际上传成功后调用；该元信息不提供业务授权。
        session = self.sessions.get_or_create(query["session_id"])
        current = self._metadata(session)
        require(all(identifier not in current or all(value[key] == old for key, old in current[identifier].items())
                    for identifier, value in prepared.items()), "上传附件的已保存元信息发生变化")
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
            metadata = self._metadata(session)
            paths = {}
            positions = {}
            for index, message in enumerate(session.messages):
                if message["role"] != "user":
                    continue
                for filename in message.get("media", []):
                    path = self._approved_path(filename)
                    identifier = self._identifier(session.key, path)
                    paths[identifier] = path
                    positions.setdefault(identifier, set()).add(index)
            unresolved = set()
            for identifier, value in metadata.items():
                if "relative_path" in value:
                    path = self._approved_path(self.media_root / value["relative_path"])
                    require(self._identifier(session.key, path) == identifier, "附件保存引用与编号不符", web.HTTPForbidden)
                    paths[identifier] = path
                elif identifier not in paths:
                    unresolved.add(identifier)
            # 历史记录仅按既有完整编号匹配获准目录内的文件，不解析正文或推断消息位置。
            if unresolved:
                for candidate in self.media_root.rglob("*"):
                    path = candidate.resolve()
                    if path.is_relative_to(self.media_root):
                        identifier = self._identifier(session.key, path)
                        if identifier in unresolved and path.is_file():
                            paths[identifier] = path
            for identifier in dict.fromkeys([*metadata, *paths]):
                path = paths.get(identifier)
                value = metadata.get(identifier)
                size, digest = self._file_state(path) if path is not None else (None, None)
                state = "REFERENCE_UNAVAILABLE" if path is None else "MISSING" if size is None else "STORED"
                if size is not None and value and (value["size_bytes"], value["content_sha256"]) != (size, digest):
                    state = "CHANGED"
                indices = positions.get(identifier, set())
                attachments.append({"attachment_id": identifier,
                    "stored_name": path.name if path else None, "original_name": value["original_name"] if value else None,
                    "mime_type": value["mime_type"] if value else mimetypes.guess_type(path.name)[0],
                    "size_bytes": size, "content_sha256": digest,
                    "recorded_size_bytes": value["size_bytes"] if value else None,
                    "recorded_content_sha256": value["content_sha256"] if value else None,
                    "processing_state": state, "user_message_index": next(iter(indices)) if len(indices) == 1 else None})
        return validate("Attachments", {"source_type": "RUNTIME_RECORD", **query, "session_state": "SAVED" if session else "NO_SAVED_SESSION",
            "attachments": attachments, "business_authorization_granted": False})
