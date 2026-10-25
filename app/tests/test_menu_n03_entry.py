from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
import inspect
import json

import pytest
from aiohttp import web
from jsonschema import Draft202012Validator

from test_menu_n02_context_references import ConversationAPI, SessionManager, ROOT
from test_menu_n02_task_entry import all_objects, bind_request
from test_menu_n03_overview import BusinessOverviewAPI, ControlStore, scope


CHAT = "n03-business-entry"
CONTEXT = {"session_id": "websocket:" + CHAT, "chat_id": CHAT}
TECHNICAL = {"conversation_business_store", "conversation_business_preparation", "conversation_business_binding"}


def business_snapshot(store):
    with store.connect() as db:
        return ([row for row in all_objects(store) if row[1] not in TECHNICAL],
            db.execute("SELECT * FROM audit ORDER BY rowid").fetchall(),
            db.execute("SELECT * FROM idempotency ORDER BY rowid").fetchall())


@pytest.fixture
def selection(tmp_path):
    store = ControlStore(tmp_path / "entry.sqlite")
    store.initialize("ui-check")
    sessions = SessionManager(tmp_path / "workspace", sessions_root=tmp_path / "native-sessions")
    sessions.save(sessions.get_or_create(CONTEXT["session_id"]))
    getter = getattr(ConversationAPI(store), "business_entry", None)
    assert callable(getter), "ConversationAPI需要独立经营范围入口"
    entry = getter(sessions)
    assert inspect.getfile(type(entry)) == str(ROOT / "validation/boss_business_overview_entry.py")
    view = BusinessOverviewAPI(store).read("BOSS", scope())
    request = {"client_request_id": "n03-business-request", "applied_scope": scope(),
        "snapshot_sha256": view["snapshot_sha256"], "topic_reference": {"page_id": "F14", "use": None}}
    return store, sessions, entry, request


def test_actual_session_scope_sources_and_safe_return_survive_same_store_reopen(selection, tmp_path):
    store, sessions, entry, request = selection
    before = business_snapshot(store)
    prepared = entry.prepare("BOSS", request)
    assert prepared["applied_scope"] == request["applied_scope"]
    assert prepared["topic_reference"] == request["topic_reference"]
    assert prepared["snapshot_sha256"] == request["snapshot_sha256"]
    assert prepared["binding_state"] == "PREPARED" and prepared["context"] is None
    assert prepared["return_reference"] == {"page_id": "N03", "applied_scope": scope(),
        "topic_reference": request["topic_reference"], "snapshot_sha256": request["snapshot_sha256"]}
    assert prepared["source_references"][0]["id"] == "finance-note"
    assert prepared["source_references"][0]["status"] == "VALID"
    assert entry.prepare("BOSS", request) == prepared
    bound = entry.bind("BOSS", bind_request(prepared, CHAT))
    assert bound["context"] == {**CONTEXT, "native_session_created_at": sessions.read_session_snapshot(CONTEXT["session_id"]).created_at.isoformat()}
    current = entry.read("BOSS", CONTEXT)
    assert current["entry"] == bound and current["current_use_verified"]
    assert current["overview"]["snapshot_sha256"] == request["snapshot_sha256"]
    assert current["references"] == [{"kind": "document", "id": "finance-note", "version": "1"}]
    assert business_snapshot(store) == before
    reopened_sessions = SessionManager(tmp_path / "workspace", sessions_root=tmp_path / "native-sessions")
    reopened = ConversationAPI(ControlStore(store.path)).business_entry(reopened_sessions)
    assert reopened.read("BOSS", CONTEXT)["entry"] == bound
    assert reopened.bind("BOSS", bind_request(prepared, CHAT)) == bound
    assert reopened.receipt("BOSS", {"client_request_id": request["client_request_id"]})["entry"]["current_use_verified"] is False
    assert business_snapshot(store) == before
    encoded = json.dumps(current, ensure_ascii=False)
    for private in (str(tmp_path), "owner_id", "namespace", "content\"", "question\""):
        assert private not in encoded
    assert not current["business_authorization_granted"] and not current["business_mutation_performed"]
    from boss_business_overview_entry import SCHEMA
    assert SCHEMA["$id"] == "urn:boss-agent:business-overview:1.1.0"
    Draft202012Validator.check_schema(SCHEMA)


@pytest.mark.parametrize("topic", [None, {"page_id": "F19", "use": "EGG"}, {"page_id": "F19", "use": "MILK"}, {"page_id": "F19", "use": "BEEF"}, {"page_id": "F19", "use": "BROILER"}])
def test_optional_topic_and_four_formal_uses_remain_fixed(selection, topic):
    store, sessions, entry, request = selection
    prepared = entry.prepare("BOSS", {**request, "topic_reference": topic})
    entry.bind("BOSS", bind_request(prepared, CHAT))
    assert entry.read("BOSS", CONTEXT)["entry"]["topic_reference"] == topic
    with pytest.raises(web.HTTPConflict):
        entry.prepare("BOSS", {**request, "topic_reference": {"page_id": "F21", "use": None}})


@pytest.mark.parametrize("stage", ["PREPARED", "BOUND"])
@pytest.mark.parametrize("change", ["WITHDRAWN", "CLOCK", "ASSOCIATION"])
def test_current_projection_changes_stop_adoption_and_preserve_original_receipt(selection, stage, change):
    from test_menu_n03_overview import BossCommandAPI, create_input
    store, sessions, entry, request = selection
    prepared = entry.prepare("BOSS", request)
    if stage == "BOUND":
        entry.bind("BOSS", bind_request(prepared, CHAT))
    if change == "WITHDRAWN":
        store.control("ui-check", "withdraw", {"source_id": "finance-note", "version": "1"})
    elif change == "CLOCK":
        with store.connect() as db:
            clock = store.get(db, "ui-check", "clock", "current")["at"]
        store.control("ui-check", "clock", {"at": (datetime.fromisoformat(clock) + timedelta(seconds=1)).isoformat()})
    else:
        assert BossCommandAPI(store).execute("BOSS", "boss.assignment.create", create_input("n03-entry-associated"))[0] == 200
    before = all_objects(store)
    for operation in (lambda: entry.prepare("BOSS", request), lambda: entry.bind("BOSS", bind_request(prepared, CHAT))):
        with pytest.raises(web.HTTPConflict):
            operation()
    if stage == "BOUND":
        with pytest.raises(web.HTTPConflict):
            entry.read("BOSS", CONTEXT)
    saved = entry.receipt("BOSS", {"client_request_id": request["client_request_id"]})["entry"]
    assert saved["snapshot_sha256"] == prepared["snapshot_sha256"] and saved["binding_state"] == stage
    assert saved["source_references"] == prepared["source_references"] and not saved["current_use_verified"]
    assert all_objects(store) == before


def test_roles_strict_fields_changed_scope_and_untrusted_hash_are_rejected(selection):
    store, sessions, entry, request = selection
    prepared = entry.prepare("BOSS", request)
    before = all_objects(store)
    for role, error in ((None, web.HTTPUnauthorized), ("MAINTAINER", web.HTTPForbidden)):
        for operation in (lambda: entry.prepare(role, request), lambda: entry.bind(role, bind_request(prepared, CHAT)),
                          lambda: entry.read(role, CONTEXT), lambda: entry.receipt(role, {"client_request_id": request["client_request_id"]})):
            with pytest.raises(error):
                operation()
    for field in ("owner_id", "namespace", "dataset_id", "store_reference", "source_references", "confirmed"):
        with pytest.raises(web.HTTPBadRequest):
            entry.prepare("BOSS", {**request, field: "injected"})
    for selection_scope in ({**scope(), "attention": "SOURCE_REVIEW"}, scope("region-1")):
        with pytest.raises(web.HTTPConflict):
            entry.prepare("BOSS", {**request, "client_request_id": "n03-other-selection", "applied_scope": selection_scope})
    with pytest.raises(web.HTTPConflict):
        entry.prepare("BOSS", {**request, "client_request_id": "n03-self-signed", "snapshot_sha256": "0" * 64})
    with pytest.raises(web.HTTPBadRequest):
        entry.prepare("BOSS", {**request, "client_request_id": "n03-invalid-topic-use", "topic_reference": {"page_id": "F14", "use": "EGG"}})
    with pytest.raises(web.HTTPForbidden):
        entry.read("BOSS", {**CONTEXT, "session_id": "websocket:other-context"})
    with pytest.raises(web.HTTPBadRequest):
        entry.bind("BOSS", {**bind_request(prepared, CHAT), "owner_id": "other"})
    assert all_objects(store) == before


def test_unknown_original_number_and_independent_store_never_restore_binding(selection, tmp_path):
    store, sessions, entry, request = selection
    before = all_objects(store)
    assert entry.receipt("BOSS", {"client_request_id": request["client_request_id"]})["outcome"] == "NOT_FOUND_IN_CURRENT_STORE"
    assert entry.read("BOSS", CONTEXT)["binding_state"] == "UNBOUND"
    assert all_objects(store) == before
    prepared = entry.prepare("BOSS", request)
    other_store = ControlStore(tmp_path / "independent.sqlite")
    other_store.initialize("ui-check")
    other = ConversationAPI(other_store).business_entry(sessions)
    assert other.receipt("BOSS", {"client_request_id": request["client_request_id"]})["entry"] is None
    independently_prepared = other.prepare("BOSS", request)
    assert independently_prepared["store_reference"] != prepared["store_reference"]
    with pytest.raises(web.HTTPConflict):
        other.bind("BOSS", bind_request(prepared, CHAT))
    assert other.read("BOSS", CONTEXT)["entry"] is None


def test_concurrent_prepare_bind_and_original_session_are_exclusive(selection):
    store, sessions, entry, request = selection
    with ThreadPoolExecutor(max_workers=2) as executor:
        values = [future.result() for future in [executor.submit(entry.prepare, "BOSS", request) for _ in range(2)]]
    assert values[0] == values[1]
    second = entry.prepare("BOSS", {**request, "client_request_id": "n03-second-prepare"})
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(entry.bind, "BOSS", bind_request(value, CHAT)) for value in (values[0], second)]
    assert sum(future.exception() is None for future in futures) == 1
    assert sum(isinstance(future.exception(), web.HTTPConflict) for future in futures) == 1
    current = entry.read("BOSS", CONTEXT)["entry"]
    sessions.save(sessions.get_or_create("websocket:n03-other-session"))
    with pytest.raises(web.HTTPConflict):
        entry.bind("BOSS", bind_request(current, "n03-other-session"))


def test_session_missing_deleted_recreated_or_used_is_rejected(selection):
    store, sessions, entry, request = selection
    prepared = entry.prepare("BOSS", request)
    with pytest.raises(web.HTTPNotFound):
        entry.bind("BOSS", bind_request(prepared, "n03-missing-session"))
    entry.bind("BOSS", bind_request(prepared, CHAT))
    assert sessions.delete_session(CONTEXT["session_id"])
    with pytest.raises(web.HTTPNotFound):
        entry.read("BOSS", CONTEXT)
    sessions.save(sessions.get_or_create(CONTEXT["session_id"]))
    with pytest.raises(web.HTTPConflict):
        entry.read("BOSS", CONTEXT)
    assert not entry.receipt("BOSS", {"client_request_id": request["client_request_id"]})["entry"]["current_use_verified"]


def test_real_morning_task_and_existing_message_entries_cannot_be_taken_over(selection, tmp_path):
    from product_morning import ProductMorning
    from test_menu_n03_overview import BossCommandAPI, create_input
    from test_menu_n02_context_references import actual_conversation, source
    store, sessions, entry, request = selection
    morning_chat = "n03-original-morning"
    sessions.save(sessions.get_or_create("websocket:" + morning_chat))
    ProductMorning(store).native.bind("BOSS", "n03-morning-original", {"chat_id": morning_chat, "date": "2026-10-24", "timezone": "Asia/Shanghai"},
        attached=lambda chat: chat == morning_chat, active=lambda: True)
    prepared = entry.prepare("BOSS", request)
    with pytest.raises(web.HTTPConflict):
        entry.bind("BOSS", bind_request(prepared, morning_chat))
    code, task = BossCommandAPI(store).execute("BOSS", "boss.assignment.create", create_input("n03-original-task"))
    assert code == 200
    task_entry = ConversationAPI(store).task_entry(sessions)
    task_prepared = task_entry.prepare("BOSS", {"client_request_id": "n03-task-original", "task_id": task["task_id"], "task_version": task["version"]})
    task_entry.bind("BOSS", bind_request(task_prepared, CHAT))
    # 任务改变总览快照后，采用服务重新读取的明确选择。
    request = {**request, "client_request_id": "n03-after-task", "snapshot_sha256": BusinessOverviewAPI(store).read("BOSS", scope())["snapshot_sha256"]}
    current = entry.prepare("BOSS", request)
    with pytest.raises(web.HTTPConflict):
        entry.bind("BOSS", bind_request(current, CHAT))
    other_chat = "n03-actual-messages"
    actual_conversation(store, tmp_path, source(store), chat_id=other_chat)
    with pytest.raises(web.HTTPConflict):
        entry.bind("BOSS", bind_request(current, other_chat))
    free_chat = "n03-business-only"
    sessions.save(sessions.get_or_create("websocket:" + free_chat))
    entry.bind("BOSS", bind_request(current, free_chat))
    fresh_task = task_entry.prepare("BOSS", {"client_request_id": "n03-task-second-selection", "task_id": task["task_id"], "task_version": task["version"]})
    with pytest.raises(web.HTTPConflict):
        task_entry.bind("BOSS", bind_request(fresh_task, free_chat))
    with store.connect() as db:
        with pytest.raises(web.HTTPConflict):
            entry.require_available_in_transaction(db, {"chat_id": free_chat, "session_id": "websocket:" + free_chat})


def test_actual_sdk_messages_and_saved_results_preserve_bound_native_identity(selection, tmp_path):
    from test_menu_n02_context_references import actual_conversation, source
    store, sessions, entry, request = selection
    prepared = entry.prepare("BOSS", request)
    bound = entry.bind("BOSS", bind_request(prepared, CHAT))
    current = entry.read("BOSS", CONTEXT)
    run, _, question = actual_conversation(store, tmp_path, source(store), chat_id=CHAT,
        references=tuple((ref["kind"], ref["id"], ref["version"]) for ref in current["references"]))
    assert run["conversation_context"]["references"] == current["references"]
    assert any(message["role"] == "user" and message["content"].startswith(question + "\n\n")
        for message in sessions.read_session_snapshot(CONTEXT["session_id"]).messages)
    assert entry.read("BOSS", CONTEXT)["entry"] == bound
    assert entry.bind("BOSS", bind_request(prepared, CHAT)) == bound
    store.control("ui-check", "withdraw", {"source_id": "finance-note", "version": "1"})
    with pytest.raises(web.HTTPConflict):
        entry.read("BOSS", CONTEXT)
    assert ConversationAPI(store).read("BOSS", CONTEXT)["runs"][0]["run_id"] == run["run_id"]
    assert not entry.receipt("BOSS", {"client_request_id": request["client_request_id"]})["entry"]["current_use_verified"]


def test_other_entry_claim_after_binding_stops_current_use_without_restoring_proof(selection):
    from product_morning import ProductMorning
    store, sessions, entry, request = selection
    prepared = entry.prepare("BOSS", request)
    entry.bind("BOSS", bind_request(prepared, CHAT))
    ProductMorning(store).native.bind("BOSS", "n03-morning-conflict", {"chat_id": CHAT, "date": "2026-10-24", "timezone": "Asia/Shanghai"},
        attached=lambda chat: chat == CHAT, active=lambda: True)
    before = all_objects(store)
    with pytest.raises(web.HTTPConflict):
        entry.read("BOSS", CONTEXT)
    assert not entry.receipt("BOSS", {"client_request_id": request["client_request_id"]})["entry"]["current_use_verified"]
    assert all_objects(store) == before


@pytest.mark.parametrize("change", ["REVISION", "EXPIRED", "DEPENDENCY_WITHDRAWN"])
def test_formal_supply_source_revision_expiry_and_dependency_stop_original_binding(selection, change):
    from boss_supply_quality import IMPORT_ACTION
    from test_boss_supply_quality import imported, definition
    from test_menu_n02_context_references import imported_source
    store, sessions, entry, request = selection
    service, _ = imported(store)
    document, adoption = imported_source(store)
    view = BusinessOverviewAPI(store).read("BOSS", scope())
    request = {**request, "snapshot_sha256": view["snapshot_sha256"]}
    prepared = entry.prepare("BOSS", request)
    entry.bind("BOSS", bind_request(prepared, CHAT))
    if change == "REVISION":
        manifest = definition()["initial_request"]
        assert service.execute("MAINTAINER", IMPORT_ACTION, {**manifest, "client_request_id": "n03-formal-source-revision",
            "records": [{**record, "expected_version": "1"} for record in manifest["records"]]})["state"] == "SUCCESS"
    elif change == "EXPIRED":
        store.control("ui-check", "clock", {"at": document["valid_until"]})
    else:
        dependency = next(row for row in adoption["dependencies"] if row["source_id"] != document["source_id"])
        store.control("ui-check", "withdraw", {"source_id": dependency["source_id"], "version": dependency["version"]})
    before = all_objects(store)
    with pytest.raises(web.HTTPConflict):
        entry.read("BOSS", CONTEXT)
    saved = entry.receipt("BOSS", {"client_request_id": request["client_request_id"]})["entry"]
    assert saved["source_references"] == prepared["source_references"] and not saved["current_use_verified"]
    assert all_objects(store) == before
