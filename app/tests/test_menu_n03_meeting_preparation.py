import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
from uuid import uuid4

import pytest
from aiohttp import web

from test_menu_n03_preparation import preparation, selection, create_task, module_api
from test_menu_n03_overview import scope, snapshot
from boss_meetings import MeetingAPI


def confirm_materials(store, sources, key="n03-scoped-meeting"):
    service = MeetingAPI(store)
    current = service.read("BOSS")
    meeting = current["meeting"]
    with store.connect() as db:
        initial = store.get(db, "ui-check", "initial", "snapshot")
    calendar = initial["private_calendar"]
    saved = service.execute("BOSS", "draft.save", {"client_request_id": key + "-draft", "meeting_id": meeting["meeting_id"],
        "meeting_version": meeting["version"], "expected_version": current["draft"]["version"] if current["draft"] else "0",
        "purpose": "核查已选择经营范围中的当前材料", "starts_at": calendar["starts_at"], "ends_at": calendar["ends_at"],
        "timezone": calendar["timezone"], "preparation_due_at": None, "participant_ids": meeting["participant_ids"],
        "source_refs": [{"source_id": identifier, "version": version} for identifier, version in sources]})
    return service.execute("BOSS", "confirm", {"client_request_id": key + "-confirm", "meeting_id": meeting["meeting_id"],
        "meeting_version": meeting["version"], "draft_version": saved["version"], "review_sha256": saved["review_sha256"],
        "acknowledge_conflict": True})


@pytest.fixture
def ready_meeting(preparation):
    store, api, bridge = preparation
    ref = create_task(store, "n03-scoped-meeting-task")
    confirmed = confirm_materials(store, [("finance-note", "1")])
    request = selection(api, ref, {"page_id": "F14", "use": None}, "MEETING_PREPARATION")
    return store, api, bridge, ref, confirmed, request


def test_formal_scoped_meeting_materials_are_callable_repeated_and_reopened_readonly(ready_meeting):
    store, api, bridge, ref, confirmed, request = ready_meeting
    before = snapshot(store)
    view = bridge.read("BOSS", request)
    assert view["state"] == "READY_FOR_REVIEW" and view["current_use_verified"], view["missing_conditions"]
    assert view["missing_conditions"] == [] and view["meeting_context"]["source_scope_current"]
    assert view["handoff"] == {"page_id": "F04", "operation": "boss.business.meeting.prepare",
        "parameters": {"selection": request}, "required_inputs": ["context_sha256"]}
    result = bridge.meeting("BOSS", {"selection": request, "context_sha256": view["context_sha256"]})
    prepared = result["preparation"]
    assert prepared == view["meeting_preparation"]
    assert prepared["meeting"]["meeting_id"] == "meeting-1" and prepared["meeting"]["version"] == confirmed["version"]
    assert prepared["task"]["task_id"] == ref["id"] and prepared["task"]["version"] == ref["version"]
    assert prepared["applied_scope"] == request["applied_scope"] and prepared["topic_reference"] == request["topic_reference"]
    assert [row["source_reference"]["id"] for row in prepared["materials"]] == ["finance-note"]
    with store.connect() as db:
        document = store.get(db, "ui-check", "document", "finance-note")
    assert prepared["materials"][0]["content"] == document["content"]
    assert prepared["materials"][0]["author_contact_id"] == document["author_contact_id"]
    assert prepared["metrics"] == api.read("BOSS", scope())["metrics"]
    assert {row["contact_id"] for row in prepared["participants"]} == {"coordinator-1", "finance-1"}
    assert all(row["state"] == "CURRENT" for row in prepared["participants"])
    assert all(prepared[field] is False for field in ("business_authorization_granted", "business_mutation_performed",
        "invitation_sent", "message_sent", "task_completed", "meeting_occurred"))
    assert bridge.verify("BOSS", request, view["context_sha256"])["meeting_preparation"] == prepared
    reopened = module_api(store.path).preparation()
    assert reopened.meeting("BOSS", {"selection": request, "context_sha256": view["context_sha256"]})["preparation"] == prepared
    with ThreadPoolExecutor(max_workers=2) as executor:
        values = list(executor.map(lambda _: bridge.meeting("BOSS", {"selection": request, "context_sha256": view["context_sha256"]}), range(2)))
    assert all(value["preparation"] == prepared for value in values)
    assert snapshot(store) == before


def test_regional_and_period_selections_produce_actual_scoped_meeting_metrics(ready_meeting):
    store, api, bridge, ref, confirmed, request = ready_meeting
    regional = selection(api, ref, {"page_id": "F14", "use": None}, "MEETING_PREPARATION", scope("region-1"))
    view = bridge.read("BOSS", regional)
    assert view["state"] == "READY_FOR_REVIEW"
    assert view["meeting_preparation"]["metrics"] == api.read("BOSS", scope("region-1"))["metrics"]
    previous = {**scope("region-1"), "period_start": "2026-09-01", "period_end": "2026-09-10"}
    base = bridge.read("BOSS", selection(api, ref, action="MEETING_PREPARATION", selected_scope=previous))
    assert base["state"] == "READY_FOR_REVIEW"
    assert base["meeting_preparation"]["metrics"] == api.read("BOSS", previous)["metrics"]
    assert next(row["value"] for row in base["meeting_preparation"]["metrics"] if row["metric_id"] == "revenue") != next(
        row["value"] for row in view["meeting_preparation"]["metrics"] if row["metric_id"] == "revenue")


@pytest.mark.parametrize("change", ["SOURCE", "CANCELED", "MATERIALS", "TOPIC", "TASK"])
def test_current_changes_reject_old_meeting_preparation_and_preserve_its_result(ready_meeting, change):
    from test_menu_n03_preparation import BossCommandAPI, send_input
    store, api, bridge, ref, confirmed, request = ready_meeting
    current = bridge.read("BOSS", request)
    prepared = current["meeting_preparation"]
    if change == "SOURCE":
        store.control("ui-check", "withdraw", {"source_id": "finance-note", "version": "1"})
    elif change == "CANCELED":
        MeetingAPI(store).execute("BOSS", "cancel", {"client_request_id": "n03-scoped-meeting-cancel", "meeting_id": "meeting-1",
            "expected_version": confirmed["version"], "reason": "取消当前明确关联会议"})
    elif change == "MATERIALS":
        confirm_materials(store, [("finance-note", "1"), ("meeting-minutes", "1")], "n03-expanded-materials")
    elif change == "TOPIC":
        request = {**request, "topic_reference": None}
    else:
        assert BossCommandAPI(store).execute("BOSS", "boss.assignment.send", send_input(
            {"task_id": ref["id"], "version": ref["version"]}, "n03-scoped-meeting-task-send"))[0] == 200
    before = snapshot(store)
    with pytest.raises(web.HTTPConflict):
        bridge.meeting("BOSS", {"selection": request, "context_sha256": current["context_sha256"]})
    assert prepared["meeting"]["version"] == confirmed["version"] and prepared["materials"][0]["content"]
    assert snapshot(store) == before


def test_missing_relationship_and_outside_materials_still_wait(preparation):
    store, api, bridge = preparation
    ref = create_task(store)
    request = selection(api, ref, action="MEETING_PREPARATION")
    current = bridge.read("BOSS", request)
    assert current["state"] == "WAITING_INPUT" and current["meeting_preparation"] is None and current["handoff"] is None
    assert "MEETING_MATERIALS_OUTSIDE_SELECTED_SCOPE" in current["missing_conditions"]
    with pytest.raises(web.HTTPConflict):
        bridge.meeting("BOSS", {"selection": request, "context_sha256": current["context_sha256"]})


def test_expired_formal_participant_requires_current_identity_before_materials(ready_meeting):
    store, api, bridge, ref, confirmed, request = ready_meeting
    store.control("ui-check", "clock", {"at": "2027-01-02T09:00:00+08:00"})
    current_request = selection(api, ref, {"page_id": "F14", "use": None}, "MEETING_PREPARATION")
    before = snapshot(store)
    current = bridge.read("BOSS", current_request)
    assert current["state"] == "WAITING_INPUT" and current["meeting_preparation"] is None and current["handoff"] is None
    assert current["missing_conditions"] == ["CURRENT_MEETING_PARTICIPANTS_REQUIRED"]
    assert snapshot(store) == before


def test_meeting_read_input_rejects_roles_injected_identity_and_other_action(ready_meeting):
    store, api, bridge, ref, confirmed, request = ready_meeting
    current = bridge.read("BOSS", request)
    payload = {"selection": request, "context_sha256": current["context_sha256"]}
    before = snapshot(store)
    for role, error in ((None, web.HTTPUnauthorized), ("MAINTAINER", web.HTTPForbidden)):
        with pytest.raises(error):
            bridge.meeting(role, payload)
    for field in ("owner_id", "namespace", "confirmed", "meeting_id", "source_refs"):
        with pytest.raises(web.HTTPBadRequest):
            bridge.meeting("BOSS", {**payload, field: "injected"})
    with pytest.raises(web.HTTPBadRequest):
        bridge.meeting("BOSS", {**payload, "selection": {**request, "action": "ASSIGNMENT_REVIEW"}})
    assert snapshot(store) == before


def test_trusted_tool_rechecks_current_selection_and_authentication(ready_meeting):
    from boss_business_meeting_preparation import BusinessMeetingPreparationReadTool, MeetingPreparationContext
    store, api, bridge, ref, confirmed, request = ready_meeting
    current = bridge.read("BOSS", request)
    state = {"active": True, "selection": request, "sha256": current["context_sha256"]}
    tool = BusinessMeetingPreparationReadTool(bridge, lambda: MeetingPreparationContext("BOSS", state["selection"], state["sha256"], lambda: state["active"]))
    result = json.loads(asyncio.run(tool.execute()))
    assert result["preparation"] == current["meeting_preparation"]
    for role, error in ((None, web.HTTPUnauthorized), ("MAINTAINER", web.HTTPForbidden)):
        rejected = BusinessMeetingPreparationReadTool(bridge, lambda: MeetingPreparationContext(role, request, current["context_sha256"], lambda: True))
        with pytest.raises(error):
            asyncio.run(rejected.execute())
    state["active"] = False
    with pytest.raises(web.HTTPUnauthorized):
        asyncio.run(tool.execute())
    state["active"] = True
    state["selection"] = {**request, "topic_reference": None}
    with pytest.raises(web.HTTPConflict):
        asyncio.run(tool.execute())
    state["selection"] = request
    store.control("ui-check", "withdraw", {"source_id": "finance-note", "version": "1"})
    before = snapshot(store)
    with pytest.raises(web.HTTPConflict):
        asyncio.run(tool.execute())
    assert snapshot(store) == before


@pytest.mark.parametrize("change", ["AUTHENTICATION", "SELECTION", "SOURCE", "CANCELED"])
def test_inflight_tool_stops_after_current_proof_changes_without_writes(ready_meeting, change):
    from boss_business_meeting_preparation import BusinessMeetingPreparationReadTool, MeetingPreparationContext
    store, api, bridge, ref, confirmed, request = ready_meeting
    current = bridge.read("BOSS", request)
    state = {"active": True, "selection": request}
    tool = BusinessMeetingPreparationReadTool(bridge, lambda: MeetingPreparationContext("BOSS", state["selection"], current["context_sha256"], lambda: state["active"]))
    async def execute():
        pending = asyncio.create_task(tool.execute())
        await asyncio.sleep(0)
        if change == "AUTHENTICATION":
            state["active"] = False
        elif change == "SELECTION":
            state["selection"] = {**request, "topic_reference": None}
        elif change == "SOURCE":
            store.control("ui-check", "withdraw", {"source_id": "finance-note", "version": "1"})
        else:
            pending.cancel()
        before = snapshot(store)
        error = asyncio.CancelledError if change == "CANCELED" else web.HTTPUnauthorized if change == "AUTHENTICATION" else web.HTTPConflict
        with pytest.raises(error):
            await pending
        assert snapshot(store) == before
    asyncio.run(execute())


def test_actual_sdk_reads_only_current_scoped_meeting_result_without_business_writes(ready_meeting, tmp_path):
    from nanobot import Nanobot
    from nanobot.agent.loop import AgentLoop
    from nanobot.agent.tools.registry import ToolRegistry
    from nanobot.config.loader import save_config
    from nanobot.config.schema import Config
    from nanobot.providers.base import LLMResponse, ToolCallRequest
    from nanobot.session.manager import SessionManager
    from boss_business_meeting_preparation import BusinessMeetingPreparationReadTool, MeetingPreparationContext
    from test_menu_n03_preparation import BossCommandAPI
    from boss_runtime_records import runtime_records
    from connection import settings
    from product_fc01 import ProductFc01
    from product_runtime import ProductRuntime
    from sop_write_tools.fc01 import Fc01Tool, TOOLS
    from sop_write_tools.fc01.runtime import Fc01RuntimeRecorder, Fc01SimulatedProvider
    settings()
    store, api, bridge, ref, confirmed, request = ready_meeting
    current = bridge.read("BOSS", request)
    tool = BusinessMeetingPreparationReadTool(bridge, lambda: MeetingPreparationContext("BOSS", request, current["context_sha256"], lambda: True))
    async def source_events(messages, tools):
        bridge.verify("BOSS", request, current["context_sha256"])
        start = max(index for index, message in enumerate(messages) if message["role"] == "user")
        outputs = [message["content"] for message in messages[start + 1:] if message["role"] == "tool"]
        if not outputs:
            return LLMResponse(content=None, tool_calls=[ToolCallRequest(id=str(uuid4()), name=tool.name, arguments={})], usage=None)
        return LLMResponse(content=outputs[-1], usage=None)
    config = Config.model_validate({"agents": {"defaults": {"workspace": str(tmp_path / "workspace"), "provider": "deepseek",
        "model": "deepseek-flash", "maxToolIterations": 6, "maxTokens": 2000, "maxToolResultChars": 200000,
        "dream": {"enabled": False}, "idleCompactAfterMinutes": 0}},
        "providers": {"deepseek": {"apiKey": "${DEEPSEEK_API_KEY}", "apiBase": "https://api.deepseek.com"}}})
    path = tmp_path / "config.json"
    save_config(config, path)
    registry = ToolRegistry()
    provider = Fc01SimulatedProvider(source_events)
    recorder = Fc01RuntimeRecorder(store, "ui-check", registry, lambda: runtime.snapshot())
    sessions = SessionManager(tmp_path / "workspace", sessions_root=tmp_path / "native-sessions")
    loop = AgentLoop.from_config(config, provider=provider, tool_registry=registry, hook_factories=[recorder.hook_factory], session_manager=sessions)
    service = ProductFc01(store)
    available = [Fc01Tool(store, service.context_provider, name) for name in sorted(TOOLS)] + [tool]
    runtime = ProductRuntime(store, path, loop, registry, available, provider)
    service.runtime = runtime
    commands = BossCommandAPI(store, runtime)
    state = runtime.read()
    code, draft = commands.execute("MAINTAINER", "boss.runtime.save", {"client_request_id": "n03-meeting-sdk-save",
        "expected_version": state["draft"]["version"] if state["draft"] else "0", "values": {"max_tool_rounds": 6,
        "max_output_tokens": 2000, "tool_scope": [tool.name]}})
    assert code == 200, draft
    code, checked = commands.execute("MAINTAINER", "boss.runtime.validate", {"client_request_id": "n03-meeting-sdk-check",
        "expected_version": draft["version"], "expected_content_sha256": draft["content_sha256"]})
    assert code == 200, checked
    code, active = commands.execute("MAINTAINER", "boss.runtime.activate", {"client_request_id": "n03-meeting-sdk-enable",
        "expected_version": checked["version"], "expected_content_sha256": checked["content_sha256"], "expected_active_version": state["current"]["version"]})
    assert code == 200, active
    _, _, error = registry.prepare_call(tool.name, {"scope": request["applied_scope"]})
    assert error
    with store.connect() as db:
        before = db.execute("SELECT namespace,kind,id,body FROM objects WHERE kind<>'runtime_run' ORDER BY namespace,kind,id").fetchall()
        audit_before = db.execute("SELECT * FROM audit ORDER BY rowid").fetchall()
        idempotency_before = db.execute("SELECT * FROM idempotency ORDER BY rowid").fetchall()
    async def execute():
        async with Nanobot(loop, config=config) as bot:
            bot.runtime.add_context_provider(runtime.context)
            bot.runtime.add_context_provider(recorder.context)
            return await bot.run("读取当前已应用经营范围的会议准备材料", sender_id="boss-1", session_key="n03-meeting-sdk", ephemeral=True)
    result = asyncio.run(execute())
    assert not result.error
    assert json.loads(result.content)["preparation"] == current["meeting_preparation"]
    bridge.verify("BOSS", request, current["context_sha256"])
    run = next(row for row in runtime_records(store, "MAINTAINER")["runs"] if row["session_id"] == "n03-meeting-sdk")
    assert run["status"] == "SUCCEEDED" and [row["tool_id"] for row in run["tool_results"]] == [tool.name]
    assert run["tool_results"][0]["preparation_sha256"] == current["meeting_preparation"]["preparation_sha256"]
    assert current["meeting_preparation"]["materials"][0]["content"] not in json.dumps(run, ensure_ascii=False)
    with store.connect() as db:
        assert db.execute("SELECT namespace,kind,id,body FROM objects WHERE kind<>'runtime_run' ORDER BY namespace,kind,id").fetchall() == before
        assert db.execute("SELECT * FROM audit ORDER BY rowid").fetchall() == audit_before
        assert db.execute("SELECT * FROM idempotency ORDER BY rowid").fetchall() == idempotency_before
