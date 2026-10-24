import pytest
from aiohttp import web

from business import checksum
from boss_command_api import BossCommandAPI
from boss_conversation import ConversationAPI
from test_native import CHAT, execute, native, read, query_artifact


def withdraw(native):
    native[0].control("ui-check", "withdraw", {"source_id": "finance-note", "version": "1"})


def test_independent_input_uses_only_current_required_sources_after_withdrawal(native):
    execute(native, ["读取 finance-note"])
    original_run, original_intent = read(native, "runtime_run")[0], read(native, "conversation_intent")[0]
    withdraw(native)
    results, _ = execute(native, ["查看当前任务", "读取 meeting-minutes"])
    runs = read(native, "runtime_run")
    assert [row["status"] for row in runs] == ["SUCCEEDED"] * 3
    assert runs[1]["conversation_context"]["references"] == []
    assert read(native, "conversation_intent")[1]["last_source_ref"] == ["document", "finance-note", "1"]
    assert runs[2]["conversation_context"]["references"] == [{"kind": "document", "id": "meeting-minutes", "version": "1"}]
    assert runs[1]["tool_results"][0]["tool_id"] == "bossTasksRead"
    assert runs[2]["tool_results"][0]["parameters_sha256"] == checksum({"source": "meeting-minutes"})
    assert "当前任务" in results[0].content and "来源：meeting-minutes" in results[1].content
    assert read(native, "runtime_run")[0] == original_run
    assert read(native, "conversation_intent")[0] == original_intent
    view = ConversationAPI(native[0]).read("BOSS", {"session_id": "websocket:" + CHAT, "chat_id": CHAT})
    assert len(view["runs"]) == 3
    assert not read(native, "authorization") and not read(native, "task")


def test_explicitly_continued_withdrawn_source_stops_without_switching_selection(native):
    execute(native, ["读取 finance-note"])
    original = read(native, "runtime_run")[0]
    withdraw(native)
    with pytest.raises(web.HTTPGone):
        execute(native, ["继续核查这份资料的版本"])
    assert read(native, "runtime_run") == [original]
    assert read(native, "conversation_intent")[-1]["status"] == "FAILED"
    execute(native, ["查看当前任务"])
    with pytest.raises(web.HTTPGone):
        execute(native, ["继续核查这份资料"])
    results, _ = execute(native, ["读取 meeting-minutes", "继续核查这份资料的版本"])
    assert all("来源：meeting-minutes" in result.content for result in results)
    assert read(native, "runtime_run")[-1]["conversation_context"]["references"] == [
        {"kind": "document", "id": "meeting-minutes", "version": "1"}]


def test_withdrawn_artifact_does_not_block_independent_input_but_its_followup_stops(native, tmp_path):
    query = query_artifact(native, tmp_path / "query-reference")
    execute(native, ["查看产物 " + query["query_id"]])
    original = read(native, "runtime_run")[-1]
    withdraw(native)
    execute(native, ["查看当前任务", "读取 meeting-minutes"])
    assert len(read(native, "runtime_run")) == 4
    for question in ("继续查看产物 " + query["query_id"], "继续只看 product-1"):
        with pytest.raises(web.HTTPException):
            execute(native, [question])
    assert len(read(native, "runtime_run")) == 4 and len(read(native, "query")) == 1
    assert read(native, "runtime_run")[1] == original


def test_selected_artifact_keeps_its_recorded_digest_after_formal_owner_change(native):
    store = native[0]
    commands = BossCommandAPI(store)
    with store.connect() as db:
        finance = store.get(db, "ui-check", "document", "finance-note")
        meeting = store.get(db, "ui-check", "document", "meeting-minutes")
    def save(key, document, draft_id, expected_version):
        status, result = commands.execute("BOSS", "boss.message.draft.save", {"client_request_id": key,
            "draft_id": draft_id, "expected_version": expected_version, "recipient_id": "coordinator-1", "related_task_id": None,
            "body": document["content"], "attachment_refs": [{"source_id": document["source_id"], "version": document["version"]}],
            "visibility": "RECIPIENT_ONLY"})
        assert status == 200
        return result
    draft = save("n02-reference-draft", finance, None, "0")
    execute(native, ["查看草稿 " + draft["draft_id"], "查看产物 " + draft["draft_id"]])
    pinned = read(native, "runtime_run")[-1]
    original_intent = read(native, "conversation_intent")[-1]
    assert original_intent["artifact_checks"]
    updated = save("n02-reference-draft-next", meeting, draft["draft_id"], draft["version"])
    assert updated["version"] != draft["version"]
    execute(native, ["查看当前任务"])
    with pytest.raises(web.HTTPConflict):
        execute(native, ["继续查看产物 " + draft["draft_id"]])
    assert len(read(native, "runtime_run")) == 3
    assert read(native, "runtime_run")[1] == pinned
    assert read(native, "conversation_intent")[1] == original_intent
    assert len(read(native, "message_draft")) == 1 and not read(native, "authorization")


def test_legacy_intent_uses_actual_recorded_source_version_for_later_followup(native):
    execute(native, ["读取 finance-note"])
    original_run = read(native, "runtime_run")[0]
    original = read(native, "conversation_intent")[0]
    original.pop("last_source_ref")
    with native[0].connect() as db:
        native[0].put(db, "ui-check", "conversation_intent", original["client_request_id"], original)
    execute(native, ["查看当前任务", "继续核查这份资料的版本"])
    assert read(native, "conversation_intent")[1]["last_source_ref"] == ["document", "finance-note", "1"]
    assert read(native, "runtime_run")[-1]["conversation_context"]["references"] == [
        {"kind": "document", "id": "finance-note", "version": "1"}]
    assert read(native, "runtime_run")[0] == original_run
    assert read(native, "conversation_intent")[0] == original
