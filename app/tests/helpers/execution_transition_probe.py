import asyncio
import base64
import hashlib
import json
import os
import sys
from pathlib import Path
from uuid import uuid4
from urllib.parse import urlencode

from nanobot import Nanobot
from nanobot.agent.loop import AgentLoop
from nanobot.agent.tools.context import RequestContext
from nanobot.config.loader import load_config, save_config
from nanobot.config.schema import Config
from nanobot.runtime_context import RUNTIME_CONTEXT_HISTORY_META, append_runtime_context
from nanobot.webui.media_gateway import WebUIMediaGateway
from loguru import logger

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "validation"))

from boss_command_api import BossCommandAPI
from boss_dataset_generator import GENERATOR_VERSION, RELATIONSHIP_VERSION
from boss_execution_scope import NAMESPACE
from boss_execution_transition import ExecutionTransition, CATALOG, TRANSITION_KIND, restart_execution
from boss_page_api import BossPageAPI
from boss_memory_runtime import OwnerMemoryContext
from boss_memory_sessions import MemorySessionManager, MemoryAutoCompact
from boss_conversation_attachments import ConversationAttachments
from controls import ControlStore
from connection import settings
from product_bi import BI_TOOLS, FeatureBusinessTool, FeatureProvider, FeatureRecorder, FeatureToolRegistry, ProductBI
from product_fc01 import ProductFc01
from product_runtime import ProductRuntime
from sop_write_tools.fc01 import Fc01Tool, TOOLS


def native_runtime(store, path):
    settings()
    if not path.exists():
        config = Config.model_validate({"agents": {"defaults": {"workspace": str(path.parent / "workspace"),
            "provider": "deepseek", "model": "deepseek-flash", "maxToolIterations": 12, "maxTokens": 700,
            "maxToolResultChars": 200000, "dream": {"enabled": False}, "idleCompactAfterMinutes": 0}},
            "providers": {"deepseek": {"apiKey": "${DEEPSEEK_API_KEY}", "apiBase": "https://api.deepseek.com"}}})
        save_config(config, path)
    config = load_config(path)
    fc01, bi = ProductFc01(store), ProductBI(store)
    provider, registry = FeatureProvider(fc01, bi), FeatureToolRegistry()
    recorder = FeatureRecorder(store, registry, lambda: runtime.snapshot(), bi)
    sessions = MemorySessionManager(config.workspace_path, business_store=store, sessions_root=path.parent / "sessions")
    loop = AgentLoop.from_config(config, provider=provider, tool_registry=registry, hook_factories=[recorder.hook_factory],
                                 session_manager=sessions)
    loop.auto_compact = MemoryAutoCompact(sessions, loop.consolidator)
    sessions.invalidate_context = loop.auto_compact.invalidate_memory_context
    tools = [FeatureBusinessTool(store, fc01, bi, name) if name in BI_TOOLS else Fc01Tool(store, fc01.context_provider, name)
             for name in sorted(TOOLS)]
    runtime = ProductRuntime(store, path, loop, registry, tools, provider)
    runtime.conversation_attachments = ConversationAttachments(loop.sessions, path.parent / "media" / "websocket")
    runtime.conversation_attachments.media_root.mkdir(parents=True, exist_ok=True)
    fc01.runtime = bi.runtime = runtime
    return runtime, bi, recorder, config


def query_payload(initial):
    return {"client_request_id": str(uuid4()), "question": "核查当前空间的经营事实和依据", "scope": {
        "metric_ids": ["sales_quantity", "revenue", "gross_profit"], "region_id": "region-1", "product_ids": ["product-1"],
        "legal_entity_id": "entity-1", "period_start": initial["periods"]["CURRENT"][0], "period_end": initial["periods"]["CURRENT"][1],
        "comparison_start": initial["periods"]["BASE"][0], "comparison_end": initial["periods"]["BASE"][1],
        "currency": "CNY", "quantity_unit": "tonne", "trade_scope": "EXTERNAL_SALES", "definition_version": "1",
        "business_basis": "SELECTION_REPORTED", "settlement_state": "SETTLED"}}


async def prepare(work):
    assert NAMESPACE == "ui-check"
    store = ControlStore(work / "business.sqlite")
    store.initialize(NAMESPACE)
    runtime, bi, recorder, config = native_runtime(store, work / "config.json")
    event = asyncio.Event()
    transition = ExecutionTransition(store, runtime, work, event)
    runtime.execution_transition = transition
    transition.mark_adopted()
    commands = BossCommandAPI(store, runtime)
    for expected_version, action, values in (
        ("1", "confirm", {"text": "检查期间采用本人确认的简报要求。", "source_note": "本人确认后检查删除传播", "visibility": "BOSS_ONLY", "valid_until": None}),
        ("2", "delete", None),
        ("3", "confirm", {"text": "归档后仅供本人查询，不参与新空间采用。", "source_note": "本人重新确认的新内容", "visibility": "BOSS_ONLY", "valid_until": None}),
    ):
        status, memory = commands.execute("BOSS", "boss.owner_workspace.personal-memory." + action, {
            "client_request_id": str(uuid4()), "expected_version": expected_version, "expected_candidate_version": "0",
            "confirmation": True, **({"values": values} if values is not None else {})})
        assert status == 200, memory
        if action == "delete":
            status, cleanup = commands.execute("BOSS", "boss.owner_workspace.personal-memory.reconcile", {
                "client_request_id": str(uuid4()), "expected_version": memory["result"]["version"]})
            assert status == 200 and cleanup["result"]["state"] == "PROPAGATION_REQUESTED", cleanup
    status, application = commands.execute("MAINTAINER", "boss.simulation.application.seed", {
        "client_request_id": str(uuid4()), "application_id": "application-1", "applicant_contact_id": "finance-1",
        "amount_cny": "3000.00", "title": "模拟资料归档检查", "description": "用于检查本人决定与原附件版本的读取",
        "attachment_text": "SIMULATED：本人审阅当前模拟资料，相关决定只记录在所属执行空间。"})
    assert status == 200, application
    status, decision = commands.execute("BOSS", "boss.approval.decide", {
        "client_request_id": str(uuid4()), "application_id": "application-1", "expected_version": "1",
        "source_id": "application-1-attachment", "source_version": "1", "amount": "3000.00", "currency": "CNY",
        "decision": "REJECT", "comment": "本人拒绝当前模拟申请，保留原附件供历史查询。"})
    assert status == 200, decision
    store.control(NAMESPACE, "withdraw", {"source_id": "application-1-attachment", "version": "1"})
    status, generated = commands.execute("MAINTAINER", "boss.technical.datasets.generate", {"client_request_id": str(uuid4()),
        "seed": 260101, "scale": "SMALL", "period_start": "2026-09", "period_end": "2026-10",
        "generator_version": GENERATOR_VERSION, "relationship_version": RELATIONSHIP_VERSION})
    assert status == 200, generated
    session = runtime.loop.sessions.get_or_create("websocket:owner-history")
    context = await OwnerMemoryContext(store)(RequestContext(channel="websocket", chat_id="owner-history",
                                                            session_key=session.key, sender_id="boss-1"))
    content, marker = append_runtime_context("保留此次经营核查的原会话。", [context])
    session.add_message("user", content, **{RUNTIME_CONTEXT_HISTORY_META: marker})
    for index in range(1, 32):
        session.add_message("user", "历史会话分页核查，第" + str(index) + "条本人输入。")
    runtime.loop.sessions.save(session, fsync=True)
    document = (ROOT / "specs/morning-coverage.json").read_bytes()
    selected_media = [{"name": "morning-coverage.json", "data_url": "data:application/json;base64," + base64.b64encode(document).decode("ascii")}]
    gateway = WebUIMediaGateway(workspace_path=config.workspace_path, logger=logger,
                               media_dir=lambda channel: runtime.conversation_attachments.media_root)
    paths, failure = gateway.store_inbound_attachments(selected_media)
    assert failure is None and len(paths) == 1
    runtime.conversation_attachments.record_upload("BOSS", {"session_id": session.key, "chat_id": "owner-history"}, selected_media, paths)
    session.add_message("user", "", media=paths)
    runtime.loop.sessions.save(session, fsync=True)
    for action, values in (
        ("boss.simulation.event.seed", {"event_id": "event-1"}),
        ("boss.simulation.clock.advance", {"at": "2026-10-24T17:00:00+08:00"}),
    ):
        status, event_result = commands.execute("MAINTAINER", action, {"client_request_id": str(uuid4()), **values})
        assert status == 200, event_result
    assert store.dispatch_due(NAMESPACE)[0]["state"] == "DELIVERED"
    store.control(NAMESPACE, "event", {"event_id": "event-1", "version": "2", "state": "CANCELED",
                                      "impact": "NORMAL", "due_at": "2026-10-24T17:00:00+08:00"})
    with store.connect() as db:
        initial = store.get(db, NAMESPACE, "initial", "snapshot")
    async with Nanobot(runtime.loop, config=config) as bot:
        bi.bot = bot
        for context in (runtime.context, bi.scope_context, recorder.context):
            bot.runtime.add_context_provider(context)
        query = asyncio.create_task(bi.execute("BOSS", query_payload(initial), False, lambda: True))
        while True:
            with store.connect() as db:
                count = db.execute("SELECT count(*) FROM objects WHERE namespace=? AND kind='query'", (NAMESPACE,)).fetchone()[0]
            if count:
                break
            assert not query.done()
            await asyncio.sleep(0)
        status, inspection = commands.execute("MAINTAINER", "boss.technical.datasets.inspect-reset", {
            "client_request_id": str(uuid4()), "expected_namespace": NAMESPACE})
        assert status == 200 and inspection["result"]["active_runs"] == 1, inspection
        payload = {"client_request_id": str(uuid4()), "dataset_id": generated["result"]["dataset_id"],
            "expected_dataset_version": "1", "expected_namespace": NAMESPACE, "impact_version": inspection["result"]["version"], "confirmed": True}
        status, receipt = commands.execute("MAINTAINER", "boss.technical.datasets.load", payload)
        assert status == 200 and receipt["result"]["state"] == "REQUESTED", receipt
        assert commands.execute("BOSS", "boss.memory.delete", {"client_request_id": str(uuid4()), "expected_version": "1"})[0] == 409
        await event.wait()
        await runtime.stop_runs()
        await asyncio.wait([query])
        assert query.cancelled()
    await runtime.close()
    transition.runtime_stopped = True
    namespace = transition.finish_stopped_runtime()
    with store.connect() as db:
        assert db.execute("SELECT namespace FROM spaces WHERE active=1").fetchall() == [(namespace,)]
        old_runs = [json.loads(body) for body, in db.execute("SELECT body FROM objects WHERE namespace=? AND kind='runtime_run'", (NAMESPACE,))]
        assert len(old_runs) == 1 and old_runs[0]["status"] == "CANCELED" and old_runs[0]["finished_at"]
        assert store.get(db, namespace, "schedule", "current")["enabled"] is False
        assert db.execute("SELECT count(*) FROM objects WHERE namespace=? AND kind IN ('memory','task','outbox','owner_plan','runtime_run')", (namespace,)).fetchone()[0] == 0
    return {"namespace": namespace, "request_id": payload["client_request_id"], "payload": payload}


async def adopt(work, request_id):
    store = ControlStore(work / "business.sqlite")
    runtime, bi, recorder, config = native_runtime(store, work / "spaces" / NAMESPACE / "config.json")
    transition = ExecutionTransition(store, runtime, work, asyncio.Event())
    runtime.execution_transition = transition
    transition.mark_adopted()
    assert runtime.loop.sessions.list_sessions() == []
    pages, commands = BossPageAPI(store, runtime_control=runtime), BossCommandAPI(store, runtime)
    status, receipt = pages.serve("MAINTAINER", "/api/boss/ui/admin/technical/datasets/requests/" + request_id)
    assert status == 200 and receipt["transition"]["state"] == "ADOPTED", receipt
    with store.connect() as db:
        record = store.get(db, CATALOG, TRANSITION_KIND, request_id)
        assert record["request_pid"] == os.getpid()
        assert store.get(db, NAMESPACE, "execution_space", "current")["runtime_adopted_at"]
        initial = store.get(db, NAMESPACE, "initial", "snapshot")
    replay = {"client_request_id": request_id, "dataset_id": record["dataset_id"], "expected_dataset_version": record["dataset_version"],
        "expected_namespace": record["previous_namespace"], "impact_version": record["impact_version"], "confirmed": True}
    assert commands.execute("MAINTAINER", "boss.technical.datasets." + record["action"], replay) == (200, {key: value for key, value in receipt.items() if key != "transition"})
    assert not transition.stop_event.is_set()
    status, history = pages.serve("MAINTAINER", "/api/boss/ui/admin/technical/datasets/history/" + record["previous_namespace"])
    assert status == 200 and history["state"] == "READ_ONLY", history
    assert history["counts"]["runtime_run"] == 1
    if record["previous_namespace"] == "ui-check":
        assert history["counts"]["sessions"] == 2 and history["counts"]["memory"] == 1
        assert history["runtime"]["runs"][0]["status"] == "CANCELED"
    else:
        assert history["counts"]["memory"] == 0 and history["runtime"]["runs"][0]["status"] == "SUCCEEDED"
        with store.connect() as db:
            assert store.get(db, NAMESPACE, "initial", "snapshot") == store.get(db, record["previous_namespace"], "initial", "snapshot")
    assert history["current_evidence_eligible"] is False
    assert "保留此次经营核查" not in json.dumps(history, ensure_ascii=False)
    assert pages.serve("BOSS", "/api/boss/ui/admin/technical/datasets/history/" + record["previous_namespace"])[0] == 403
    before = store.path.read_bytes()
    status, memories = pages.serve("BOSS", "/api/boss/ui/owner/personal-memory")
    assert status == 200 and memories["current"] is None and memories["candidate"] is None, memories
    archived = [row for row in memories["archived_history"] if row["namespace"] == "ui-check"]
    assert len(archived) == 4
    assert archived[0]["version"] == "4" and archived[0]["text"] == "归档后仅供本人查询，不参与新空间采用。"
    assert all(row["state"] == "DELETED" and not row["text"] and not row["source_note"] for row in archived[1:])
    assert all(row["current_evidence_eligible"] is False for row in archived)
    status, decisions = pages.serve("BOSS", "/api/boss/ui/owner/decisions")
    assert status == 200, decisions
    original = next(row for row in decisions["records"] if row["target_id"] == "application-1")
    assert original["namespace"] == "ui-check" and original["historical"] is True
    assert original["effective_state"] == "READ_ONLY_HISTORY" and not original["can_continue"] and not original["can_revoke"]
    assert original["request_id"] is None and original["current_target_id"] is None
    assert original["original_records"][0]["decision"] == "REJECT"
    assert original["original_records"][0]["content"] == "本人拒绝当前模拟申请，保留原附件供历史查询。"
    assert original["sources"][0]["state"] == "WITHDRAWN" and original["sources"][0]["version"] == "1"
    assert original["sources"][0]["content"].startswith("SIMULATED：")
    assert pages.serve("BOSS", "/api/boss/ui/owner/authorizations")[1]["records"] == []
    for domain in ("personal-memory", "decisions", "notification-history"):
        assert pages.serve("MAINTAINER", "/api/boss/ui/owner/" + domain)[0] == 403
    assert commands.execute("BOSS", "boss.owner_workspace.authorizations.revoke", {
        "client_request_id": str(uuid4()), "authorization_id": original["authorization_id"], "expected_version": "1",
        "reason": "检查跨空间操作拒绝"})[0] == 404
    assert store.path.read_bytes() == before
    status, notifications = pages.serve("BOSS", "/api/boss/ui/owner/notification-history")
    assert status == 200, notifications
    notice = next(row for row in notifications["records"] if row["namespace"] == "ui-check" and row["target_id"] == "event-1")
    assert notice["version"] == "1" and notice["historical"] is True and not notice["can_continue"]
    assert json.loads(notice["original_records"][0]["content"])["state"] == "OPEN"
    query = urlencode({"execution_namespace": "ui-check", "event_id": "event-1", "event_version": "1"})
    status, target = pages.serve("BOSS", "/api/boss/ui/notification-target", query)
    assert status == 200 and target["page_id"] == "D09" and target["record_id"] == notice["id"], target
    assert target["execution_namespace"] == "ui-check"
    endpoint = "/api/boss/ui/owner/session-history"
    status, catalog = pages.serve("BOSS", endpoint)
    assert status == 200 and any(row["namespace"] == "ui-check" and row["session_count"] == 1 for row in catalog["spaces"]), catalog
    assert not any(row["namespace"].startswith("dataset-candidate:") for row in catalog["spaces"])
    status, sessions = pages.serve("BOSS", endpoint, urlencode({"namespace": "ui-check"}))
    assert status == 200 and [row["key"] for row in sessions["sessions"]] == ["websocket:owner-history"], sessions
    with store.connect() as db:
        archive = store.get(db, CATALOG, "execution_archive", "ui-check")
    files = list(Path(archive["sessions_directory"]).iterdir())
    digests = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in files if path.is_file()}
    for page, expected in ((1, 30), (2, 3)):
        status, messages = pages.serve("BOSS", endpoint, urlencode({"namespace": "ui-check", "session_key": "websocket:owner-history", "page": page}))
        assert status == 200 and messages["total"] == 33 and len(messages["messages"]) == expected, messages
        assert messages["current_evidence_eligible"] is False and messages["historical_namespace"] == "ui-check"
        assert all(row["role"] == "user" for row in messages["messages"])
        assert "归档后仅供本人查询" not in json.dumps(messages, ensure_ascii=False)
        if page == 1:
            assert messages["messages"][0]["content"] == "保留此次经营核查的原会话。"
        else:
            assert messages["messages"][-1]["content"] == ""
    assert pages.serve("MAINTAINER", endpoint, urlencode({"namespace": "ui-check", "session_key": "websocket:owner-history"}))[0] == 403
    assert pages.serve("BOSS", endpoint, urlencode({"namespace": NAMESPACE}))[0] == 404
    assert pages.serve("BOSS", endpoint, urlencode({"namespace": "ui-check", "session_key": "sdk:owner-history"}))[0] == 404
    assert pages.serve("BOSS", endpoint, "namespace=ui-check&page=0")[0] == 400
    status, attachment_view = pages.serve("BOSS", endpoint, urlencode({"namespace": "ui-check", "session_key": "websocket:owner-history"}))
    assert status == 200 and len(attachment_view["attachments"]) == 1, attachment_view
    attachment = attachment_view["attachments"][0]
    assert attachment["original_name"] == "morning-coverage.json" and attachment["processing_state"] == "STORED" and attachment["download_available"]
    assert attachment["user_message_index"] == 32
    assert "relative_path" not in json.dumps(attachment_view) and "media_directory" not in json.dumps(attachment_view)
    download_query = urlencode({"namespace": "ui-check", "session_key": "websocket:owner-history", "attachment_id": attachment["attachment_id"]})
    status, download = pages.serve("BOSS", endpoint, download_query)
    original_file = (ROOT / "specs/morning-coverage.json").read_bytes()
    assert status == 200 and base64.b64decode(download["download"]["content"]) == original_file, download
    assert download["download"]["content_sha256"] == hashlib.sha256(original_file).hexdigest()
    assert pages.serve("MAINTAINER", endpoint, download_query)[0] == 403
    assert pages.serve("BOSS", endpoint, download_query + "&page=1")[0] == 400
    assert pages.serve("BOSS", endpoint, urlencode({"namespace": "ui-check", "session_key": "websocket:owner-history", "attachment_id": "attachment-unknown"}))[0] == 404
    assert {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in files if path.is_file()} == digests
    assert store.path.read_bytes() == before
    if sys.argv[1] == "verify-reset":
        path = Path(archive["media_directory"]) / attachment["stored_name"]
        assert path.read_bytes() == original_file
        path.write_bytes((ROOT / "specs/conversation.schema.json").read_bytes())
        status, changed = pages.serve("BOSS", endpoint, urlencode({"namespace": "ui-check", "session_key": "websocket:owner-history"}))
        assert status == 200 and changed["attachments"][0]["processing_state"] == "CHANGED"
        assert changed["attachments"][0]["download_available"] is False
        assert pages.serve("BOSS", endpoint, download_query)[0] == 409
        path.unlink()
        status, missing = pages.serve("BOSS", endpoint, urlencode({"namespace": "ui-check", "session_key": "websocket:owner-history"}))
        assert status == 200 and missing["attachments"][0]["processing_state"] == "MISSING"
        assert pages.serve("BOSS", endpoint, download_query)[0] == 409
    async with Nanobot(runtime.loop, config=config) as bot:
        bi.bot = bot
        for context in (runtime.context, bi.scope_context, recorder.context):
            bot.runtime.add_context_provider(context)
        result = await bi.execute("BOSS", query_payload(initial), False, lambda: True)
        assert result["request_state"] == "SUCCEEDED"
        assert result["receipt"]["query"]["result"]["envelope"]["execution_namespace"] == NAMESPACE
        reset_receipt = None
        if sys.argv[1] == "adopt":
            status, impact = commands.execute("MAINTAINER", "boss.technical.datasets.inspect-reset", {
                "client_request_id": str(uuid4()), "expected_namespace": NAMESPACE})
            assert status == 200, impact
            status, reset_receipt = commands.execute("MAINTAINER", "boss.technical.datasets.reset", {
                "client_request_id": str(uuid4()), "dataset_id": initial["dataset_id"], "expected_dataset_version": initial["dataset_version"],
                "expected_namespace": NAMESPACE, "impact_version": impact["result"]["version"], "confirmed": True})
            assert status == 200, reset_receipt
            await transition.stop_event.wait()
    await runtime.close()
    if reset_receipt is not None:
        transition.runtime_stopped = True
        namespace = transition.finish_stopped_runtime()
        return {"next_namespace": namespace, "request_id": reset_receipt["request_id"]}
    return {"namespace": NAMESPACE, "transition_state": receipt["transition"]["state"], "run_id": result["run_id"]}


if __name__ == "__main__":
    work = Path(sys.argv[2])
    result = asyncio.run(prepare(work) if sys.argv[1] == "prepare" else adopt(work, sys.argv[3]))
    if sys.argv[1] == "prepare":
        restart_execution(result["namespace"], __file__, "adopt", str(work), result["request_id"])
    if "next_namespace" in result:
        restart_execution(result["next_namespace"], __file__, "verify-reset", str(work), result["request_id"])
    print(json.dumps(result))
