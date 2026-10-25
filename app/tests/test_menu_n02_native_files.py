import base64
import hashlib
import inspect
import json
from pathlib import Path
import sys

import pytest
from aiohttp import web
from loguru import logger

ROOT = Path(__file__).resolve().parents[2]
from test_menu_n02_domain import actual_query_run

sys.path.insert(0, str(ROOT / "validation"))
from boss_conversation_attachments import ConversationAttachments
from controls import ControlStore


def accepted_file(directory):
    from nanobot.webui.media_gateway import WebUIMediaGateway
    media_root = directory / "media"
    media_root.mkdir()
    gateway = WebUIMediaGateway(workspace_path=directory, logger=logger, media_dir=lambda _: media_root)
    data = (ROOT / "specs/morning-coverage.json").read_bytes()
    selected = [{"name": "morning-coverage.json", "data_url": "data:application/json;base64," + base64.b64encode(data).decode()}]
    paths, failure = gateway.store_inbound_attachments(selected)
    assert failure is None and len(paths) == 1
    return media_root, data, selected, paths


@pytest.fixture
def native_document(tmp_path):
    # 按应用入口加载 SDK，随后创建独立会话服务。
    from nanobot import Nanobot
    from nanobot.agent.loop import AgentLoop
    from nanobot.config.schema import Config
    from nanobot.session.manager import SessionManager

    assert Path(inspect.getfile(ConversationAttachments)).resolve() == ROOT / "validation/boss_conversation_attachments.py"
    media_root, data, selected, paths = accepted_file(tmp_path)
    sessions = SessionManager(tmp_path / "native-workspace", sessions_root=tmp_path / "native-sessions")
    api = ConversationAttachments(sessions, media_root)
    context = {"session_id": "websocket:n02-real-file", "chat_id": "n02-real-file"}
    receipt = api.record_upload("BOSS", context, selected, paths)
    store = ControlStore(tmp_path / "business.sqlite")
    store.initialize("ui-check")
    run, output = actual_query_run(store, tmp_path / "native-workspace", session=context["session_id"], media=paths, sessions=sessions)
    assert run["status"] == "SUCCEEDED" and output["query_id"]
    saved = sessions.read_session_snapshot(context["session_id"])
    assert len(saved.metadata["boss_attachment_metadata"]) == 1
    users = [message for message in saved.messages if message["role"] == "user"]
    assert users and not any(message.get("media") for message in users)
    fresh_sessions = SessionManager(tmp_path / "native-workspace", sessions_root=tmp_path / "native-sessions")
    reopened = ConversationAttachments(fresh_sessions, media_root)
    return reopened, context, receipt, data, selected, paths


def test_saved_attachment_changes_without_creating_any_new_runtime_run(tmp_path):
    """N02 file freshness must never depend on runtime run_id or status."""
    from nanobot.session.manager import SessionManager

    media_root, data, selected, paths = accepted_file(tmp_path)
    sessions = SessionManager(tmp_path / "native-workspace",
                              sessions_root=tmp_path / "native-sessions")
    api = ConversationAttachments(sessions, media_root)
    context = {"session_id": "websocket:n02-upload-without-run",
               "chat_id": "n02-upload-without-run"}
    receipt = api.record_upload("BOSS", context, selected, paths)
    saved = api.read("BOSS", context)
    assert saved["session_state"] == "SAVED"
    assert saved["source_type"] == "RUNTIME_RECORD"
    assert saved["business_authorization_granted"] is False
    assert len(saved["attachments"]) == 1
    assert saved["attachments"][0]["processing_state"] == "STORED"
    assert saved["attachments"][0]["attachment_id"] == receipt["attachment_ids"][0]
    assert not sessions.read_session_snapshot(context["session_id"]).messages

    another = (ROOT / "specs/conversation.schema.json").read_bytes()
    Path(paths[0]).write_bytes(another)
    changed = api.read("BOSS", context)
    assert changed["attachments"][0]["processing_state"] == "CHANGED"
    assert changed["attachments"][0]["content_sha256"] == hashlib.sha256(another).hexdigest()
    assert changed["attachments"][0]["recorded_content_sha256"] == hashlib.sha256(data).hexdigest()
    Path(paths[0]).unlink()
    missing = api.read("BOSS", context)
    assert missing["attachments"][0]["processing_state"] == "MISSING"
    assert missing["attachments"][0]["size_bytes"] is None
    assert missing["attachments"][0]["attachment_id"] == receipt["attachment_ids"][0]
    assert not sessions.read_session_snapshot(context["session_id"]).messages


def test_uploaded_document_survives_actual_sdk_session_save(native_document, tmp_path):
    reopened, context, receipt, data, selected, paths = native_document
    view = reopened.read("BOSS", context)
    assert len(view["attachments"]) == 1
    attachment = view["attachments"][0]
    assert receipt["attachment_ids"] == [attachment["attachment_id"]]
    assert attachment["original_name"] == selected[0]["name"]
    assert attachment["mime_type"] == "application/json"
    assert attachment["size_bytes"] == len(data)
    assert attachment["content_sha256"] == hashlib.sha256(data).hexdigest()
    assert attachment["recorded_size_bytes"] == len(data)
    assert attachment["recorded_content_sha256"] == hashlib.sha256(data).hexdigest()
    assert attachment["processing_state"] == "STORED"
    assert attachment["user_message_index"] is None
    assert str(tmp_path) not in json.dumps(view)
    assert view["business_authorization_granted"] is False
    assert "relative_path" not in json.dumps(view)
    assert reopened.record_upload("BOSS", context, selected, paths) == receipt
    assert reopened.read("BOSS", context) == view


@pytest.mark.parametrize("state", ["MISSING", "CHANGED"])
def test_native_saved_reference_reports_current_and_recorded_file_state(native_document, state):
    reopened, context, receipt, data, selected, paths = native_document
    metadata_before = reopened.sessions.read_session_snapshot(context["session_id"]).metadata
    if state == "MISSING":
        Path(paths[0]).unlink()
        current = None
    else:
        current = (ROOT / "specs/conversation.schema.json").read_bytes()
        Path(paths[0]).write_bytes(current)
    attachment = reopened.read("BOSS", context)["attachments"][0]
    assert attachment["processing_state"] == state
    assert receipt["attachment_ids"] == [attachment["attachment_id"]]
    assert attachment["original_name"] == selected[0]["name"]
    assert attachment["mime_type"] == "application/json"
    assert attachment["recorded_size_bytes"] == len(data)
    assert attachment["recorded_content_sha256"] == hashlib.sha256(data).hexdigest()
    assert attachment["size_bytes"] == (len(current) if current else None)
    assert attachment["content_sha256"] == (hashlib.sha256(current).hexdigest() if current else None)
    assert attachment["user_message_index"] is None
    assert reopened.sessions.read_session_snapshot(context["session_id"]).metadata == metadata_before


def test_native_saved_reference_enforces_owner_context_and_media_directory(native_document):
    reopened, context, receipt, data, selected, paths = native_document
    for role, error in ((None, web.HTTPUnauthorized), ("MAINTAINER", web.HTTPForbidden)):
        with pytest.raises(error):
            reopened.read(role, context)
        with pytest.raises(error):
            reopened.record_upload(role, context, selected, paths)
    with pytest.raises(web.HTTPBadRequest):
        reopened.read("BOSS", {**context, "path": paths[0]})
    with pytest.raises(web.HTTPForbidden):
        reopened.read("BOSS", {**context, "chat_id": "n02-other"})
    assert reopened.read("BOSS", {"session_id": "websocket:n02-other", "chat_id": "n02-other"})["attachments"] == []
    Path(paths[0]).unlink()
    Path(paths[0]).symlink_to(ROOT / "specs/morning-coverage.json")
    with pytest.raises(web.HTTPForbidden):
        reopened.read("BOSS", context)
