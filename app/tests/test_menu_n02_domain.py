import asyncio
import base64
import json
import os
from pathlib import Path
import sys
from uuid import uuid4

import pytest
from aiohttp import web

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "validation"))
if os.environ.get("MENU_N02_PRODUCT_ROOT"):
    sys.path.insert(0, str(Path(os.environ["MENU_N02_PRODUCT_ROOT"]) / "validation"))

from business import checksum, encode
from boss_command_api import BossCommandAPI
from controls import ControlStore
from test_boss_message_calendar import cmd, msg_input


def prohibit_network(event, args):
    if event == "socket.connect":
        raise PermissionError("MENU-N02领域检查禁止外部连接")


sys.addaudithook(prohibit_network)


@pytest.fixture
def store(tmp_path):
    value = ControlStore(tmp_path / "menu-n02.sqlite")
    value.initialize("ui-check")
    return value


def test_message_contact_expiry_uses_owner_iana_date_at_utc_midnight(store):
    store.control("ui-check", "clock", {"at": "2027-01-01T16:30:00+00:00"})
    code, _ = cmd(BossCommandAPI(store), "BOSS", "boss.message.draft.save", "n02-expired-contact", **msg_input(attachment_refs=[]))
    assert code == 403
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind='message_draft'").fetchone()[0] == 0


def actual_query_run(store, workspace, session="websocket:n02-current", *, media=None, sessions=None):
    from dataclasses import replace
    from nanobot import Nanobot
    from nanobot.agent.loop import AgentLoop
    from nanobot.agent.tools.registry import ToolRegistry
    from nanobot.config.schema import Config
    from nanobot.providers.base import LLMResponse, ToolCallRequest
    from nanobot.session.manager import SessionManager
    from fc02_agent import Fc02Context, bind_query, register_fc02_tools
    from fc02_agent.runtime import Fc02RuntimeRecorder, Fc02SimulatedProvider
    config = Config.model_validate({"agents": {"defaults": {"provider": "deepseek", "model": "deepseek-flash",
        "workspace": str(workspace), "maxToolIterations": 12, "maxTokens": 700, "dream": {"enabled": False}, "idleCompactAfterMinutes": 0}}})
    registry = ToolRegistry()
    snapshot = {"provider": "deepseek", "model_id": "deepseek-flash", "api_type": "chat_completions", "max_tool_rounds": 12,
        "max_output_tokens": 700, "timeout": 120, "config_sha256": checksum(config.model_dump(mode="json"))}
    params = {"region_id": "region-1", "product_ids": ["product-1", "product-2"], "metric_ids": ["gross_margin"], "definition_version": "1",
        "period_start": "2026-10-01", "period_end": "2026-10-10", "comparison_start": "2026-09-01", "comparison_end": "2026-09-10",
        "question": "查询当前获准期间的毛利率及依据", "currency": "CNY", "trade_scope": "EXTERNAL_SALES", "query_mode": "SCOPED",
        "legal_entity_id": "entity-1", "quantity_unit": "tonne", "business_basis": "SELECTION_REPORTED", "settlement_state": "SETTLED"}
    current = [Fc02Context("BOSS", "boss-1", "ui-check", "selection", "1", "n02-initial-request", session, True, (bind_query(params),), frozenset())]
    recorder = Fc02RuntimeRecorder(store, "ui-check", registry, lambda: snapshot, lambda: current[0])
    async def produce(messages, tools):
        outputs = [json.loads(row["content"]) for row in messages if row["role"] == "tool"]
        if not outputs:
            return LLMResponse(content=None, tool_calls=[ToolCallRequest(id=str(uuid4()), name="query_metrics", arguments=params)])
        return LLMResponse(content=encode(outputs[-1]))
    provider = Fc02SimulatedProvider(produce)
    provider.generation = config.resolve_preset().to_generation_settings()
    if sessions is None:
        sessions = SessionManager(workspace, sessions_root=workspace.parent / (workspace.name + "-sessions"))
    loop = AgentLoop.from_config(config, tool_registry=registry, provider=provider, hook_factories=[recorder.hook_factory], session_manager=sessions)
    for name in list(registry.tool_names):
        registry.unregister(name)
    register_fc02_tools(registry, store, lambda: current[0])
    async def execute():
        async with Nanobot(loop, config=config) as bot:
            bot.runtime.add_context_provider(recorder.context)
            async def admitted_request(request):
                binding = request.attributes["boss_runtime_binding"]
                current[0] = replace(current[0], request_id=binding.request_id, session_id=binding.session_id)
            bot.runtime.add_context_provider(admitted_request)
            return await bot.run("查询当前获准期间的毛利率及依据", session_key=session, sender_id="boss-1", media=media)
    result = asyncio.run(execute())
    assert not result.error
    with store.connect() as db:
        run = json.loads(db.execute("SELECT body FROM objects WHERE kind='runtime_run' ORDER BY rowid DESC LIMIT 1").fetchone()[0])
    return run, json.loads(result.content)


def test_current_conversation_adopts_only_actual_run_references_and_current_source(store, tmp_path):
    from boss_conversation import ConversationAPI
    run, output = actual_query_run(store, tmp_path / "runtime")
    api = ConversationAPI(store)
    scope = {"session_id": run["session_id"], "chat_id": run["chat_id"]}
    view = api.read("BOSS", scope)
    assert view["runs"][0]["run_id"] == run["run_id"]
    assert view["runs"][0]["status"] == "SUCCEEDED"
    reference = next(row for row in view["runs"][0]["artifacts"] if row["kind"] == "query")
    assert reference["id"] == output["query_id"]
    selected = {**scope, "run_id": run["run_id"], "kind": "query", "id": output["query_id"]}
    detail = api.artifact("BOSS", selected)
    assert detail["data"]["values"] == output["values"]
    assert detail["evidence"]["sources"][0]["source_id"] == "finance-note"
    assert detail["business_authorization_granted"] is False
    with store.connect() as db:
        before = db.execute("SELECT COUNT(*) FROM audit").fetchone()[0]
    restored = ConversationAPI(ControlStore(store.path)).artifact("BOSS", selected)
    assert restored["data"] == detail["data"]
    assert restored["evidence"]["original_records"] == detail["evidence"]["original_records"]
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM audit").fetchone()[0] == before
    store.control("ui-check", "withdraw", {"source_id": "finance-note", "version": "1"})
    with pytest.raises(web.HTTPGone):
        api.artifact("BOSS", selected)
    assert api.read("BOSS", scope)["runs"][0]["artifacts"][0]["id"] == output["query_id"]
    assert "values" not in json.dumps(api.read("BOSS", scope))


def test_conversation_rejects_other_chat_run_or_injected_identity(store, tmp_path):
    from boss_conversation import ConversationAPI
    run, output = actual_query_run(store, tmp_path / "runtime")
    api = ConversationAPI(store)
    scope = {"session_id": run["session_id"], "chat_id": run["chat_id"]}
    for role, error in ((None, web.HTTPUnauthorized), ("MAINTAINER", web.HTTPForbidden)):
        with pytest.raises(error):
            api.read(role, scope)
        with pytest.raises(error):
            api.messages(role)
    for field in ("owner_id", "namespace", "authorization_id", "confirmed"):
        with pytest.raises(web.HTTPBadRequest):
            api.read("BOSS", {**scope, field: "injected"})
    other = {"session_id": "websocket:n02-other", "chat_id": "n02-other"}
    assert api.read("BOSS", other)["runs"] == []
    with pytest.raises(web.HTTPForbidden):
        api.artifact("BOSS", {**other, "run_id": run["run_id"], "kind": "query", "id": output["query_id"]})
    with pytest.raises(web.HTTPForbidden):
        api.artifact("BOSS", {**scope, "run_id": run["run_id"], "kind": "task", "id": "unrelated-task"})
    another, _ = actual_query_run(store, tmp_path / "other-runtime", session="websocket:n02-other")
    assert [row["run_id"] for row in api.read("BOSS", scope)["runs"]] == [run["run_id"]]
    assert [row["run_id"] for row in api.read("BOSS", {"session_id": another["session_id"], "chat_id": another["chat_id"]})["runs"]] == [another["run_id"]]


def test_message_projection_keeps_send_delivery_reply_and_source_state_distinct(store):
    from boss_conversation import ConversationAPI
    commands, api = BossCommandAPI(store), ConversationAPI(store)
    draft = cmd(commands, "BOSS", "boss.message.draft.save", "n02-message-save", **msg_input())[1]
    view = api.messages("BOSS")
    current = view["drafts"][0]
    assert current["body"] == msg_input()["body"]
    send = {"draft_id": draft["draft_id"], "expected_version": draft["version"], "recipient_id": "coordinator-1", "expected_content_sha256": current["content_sha256"]}
    code, sent = cmd(commands, "BOSS", "boss.message.send", "n02-message-send", **send)
    assert code == 200, sent
    assert cmd(commands, "BOSS", "boss.message.send", "n02-message-send", **send) == (code, sent)
    assert cmd(commands, "MAINTAINER", "boss.simulation.message.reply", "n02-message-reply", message_id=sent["message_id"], author_contact_id="coordinator-1", text="合成反馈：正在核查当前材料")[0] == 200
    view = api.messages("BOSS")
    assert view["sent_messages"][0]["send_state"] == "SENT_SIMULATED"
    assert view["sent_messages"][0]["delivery_state"] == "NOT_VERIFIED"
    assert view["replies"][0]["reply_to"] == sent["message_id"]
    assert view["replies"][0]["task_completion_confirmed"] is False
    assert {row["contact_id"] for row in view["contacts"] if row["name"] == "陈明"} == {"coordinator-1", "contact-2"}
    store.control("ui-check", "withdraw", {"source_id": "finance-note", "version": "1"})
    stale = api.messages("BOSS")
    assert stale["sent_messages"][0]["body"] is None
    assert stale["sent_messages"][0]["adoption_state"] == "NEEDS_REVIEW"
    assert stale["sent_messages"][0]["send_state"] == "SENT_SIMULATED"


def test_native_attachment_metadata_uses_saved_session_and_actual_file(store, tmp_path):
    from boss_conversation_attachments import ConversationAttachments
    from nanobot.session.manager import SessionManager
    from nanobot.webui.media_gateway import WebUIMediaGateway
    from loguru import logger
    sessions = SessionManager(tmp_path / "sessions", sessions_root=tmp_path / "native-sessions")
    media = tmp_path / "media"
    media.mkdir()
    gateway = WebUIMediaGateway(workspace_path=tmp_path, logger=logger, media_dir=lambda _: media)
    actual = (ROOT / "specs/morning-coverage.json").read_bytes()
    selected_media = [{"name": "morning-coverage.json", "data_url": "data:application/json;base64," + base64.b64encode(actual).decode()}]
    paths, failure = gateway.store_inbound_attachments(selected_media)
    assert failure is None
    session = sessions.get_or_create("websocket:n02-files")
    session.add_message("user", "核查本人实际补充的附件", media=paths)
    sessions.save(session)
    api = ConversationAttachments(sessions, media)
    scope = {"session_id": session.key, "chat_id": "n02-files"}
    recorded = api.record_upload("BOSS", scope, selected_media, paths)
    assert recorded["metadata_saved"] and not recorded["business_authorization_granted"]
    assert api.record_upload("BOSS", scope, selected_media, paths) == recorded
    view = api.read("BOSS", scope)
    assert view["attachments"][0]["original_name"] == selected_media[0]["name"]
    assert view["attachments"][0]["mime_type"] == "application/json"
    assert view["attachments"][0]["size_bytes"] == len(actual)
    assert view["attachments"][0]["content_sha256"] == checksum_bytes(actual)
    assert view["attachments"][0]["processing_state"] == "STORED"
    assert view["attachments"][0]["user_message_index"] == 0
    assert str(tmp_path) not in json.dumps(view)
    with pytest.raises(web.HTTPForbidden):
        api.read("MAINTAINER", scope)
    with pytest.raises(web.HTTPForbidden):
        api.record_upload("MAINTAINER", scope, selected_media, paths)
    with pytest.raises(web.HTTPBadRequest):
        api.read("BOSS", {**scope, "path": paths[0]})
    assert api.read("BOSS", {"session_id": "websocket:n02-empty", "chat_id": "n02-empty"})["attachments"] == []
    reopened = ConversationAttachments(SessionManager(tmp_path / "sessions", sessions_root=tmp_path / "native-sessions"), media)
    assert reopened.read("BOSS", scope) == view
    Path(paths[0]).unlink()
    missing = reopened.read("BOSS", scope)["attachments"][0]
    assert missing["processing_state"] == "MISSING"
    assert missing["size_bytes"] is None and missing["content_sha256"] is None
    assert missing["attachment_id"] == view["attachments"][0]["attachment_id"]


def test_native_attachment_symlink_cannot_read_outside_approved_media(tmp_path):
    from boss_conversation_attachments import ConversationAttachments
    from nanobot.session.manager import SessionManager
    media = tmp_path / "media"
    media.mkdir()
    link = media / "outside.json"
    link.symlink_to(ROOT / "specs/morning-coverage.json")
    sessions = SessionManager(tmp_path / "sessions", sessions_root=tmp_path / "native-sessions")
    session = sessions.get_or_create("websocket:n02-restricted")
    session.add_message("user", "核查附件范围限制", media=[str(link)])
    sessions.save(session)
    with pytest.raises(web.HTTPForbidden):
        ConversationAttachments(sessions, media).read("BOSS", {"session_id": session.key, "chat_id": "n02-restricted"})


def test_conversation_schema_and_read_operations_grant_no_business_authority(store):
    from jsonschema import Draft202012Validator
    from boss_conversation import SCHEMA, ConversationAPI
    Draft202012Validator.check_schema(SCHEMA)
    api = ConversationAPI(store)
    with store.connect() as db:
        before = db.execute("SELECT COUNT(*) FROM objects").fetchone()[0]
        audit = db.execute("SELECT COUNT(*) FROM audit").fetchone()[0]
    view = api.read("BOSS", {"session_id": "websocket:new-owner-chat", "chat_id": "new-owner-chat"})
    assert view["coverage_state"] == "UNAVAILABLE" and view["runs"] == []
    assert not view["business_authorization_granted"] and not api.messages("BOSS")["business_mutation_performed"]
    with store.connect() as db:
        db.execute("BEGIN")
        assert api.project_in_transaction("BOSS", db, {"session_id": view["session_id"], "chat_id": view["chat_id"]}) == view
        assert db.execute("SELECT COUNT(*) FROM objects").fetchone()[0] == before
        assert db.execute("SELECT COUNT(*) FROM audit").fetchone()[0] == audit


def checksum_bytes(value):
    import hashlib
    return hashlib.sha256(value).hexdigest()
