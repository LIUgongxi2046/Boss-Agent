from concurrent.futures import ThreadPoolExecutor
import json

import pytest
from aiohttp import web

from test_menu_n02_context_references import (
    ROOT, BossCommandAPI, ControlStore, ConversationAPI, SessionManager, actual_conversation, source,
)
from test_boss_command_api import create_input, send_input


CHAT = "n02-task-entry"
CONTEXT = {"session_id": "websocket:" + CHAT, "chat_id": CHAT}


def all_objects(store):
    with store.connect() as db:
        return db.execute("SELECT namespace,kind,id,body FROM objects ORDER BY namespace,kind,id").fetchall()


def business_snapshot(store):
    with store.connect() as db:
        return ([row for row in all_objects(store) if row[1] not in
            {"conversation_task_preparation", "conversation_task_binding", "conversation_intent", "runtime_run"}],
            db.execute("SELECT * FROM audit ORDER BY rowid").fetchall(),
            db.execute("SELECT * FROM idempotency ORDER BY rowid").fetchall())


@pytest.fixture
def task_entry(tmp_path):
    store = ControlStore(tmp_path / "entry.sqlite")
    store.initialize("ui-check")
    commands = BossCommandAPI(store)
    code, task = commands.execute("BOSS", "boss.assignment.create", create_input("n02-entry-create"))
    assert code == 200, task
    with store.connect() as db:
        configuration = store.get(db, "ui-check", "configuration", "current")
        configuration["tool_scope"] = ["bossEvidenceRead"]
        store.put(db, "ui-check", "configuration", "current", configuration)
    sessions = SessionManager(tmp_path / "workspace", sessions_root=tmp_path / "native-sessions")
    sessions.save(sessions.get_or_create(CONTEXT["session_id"]))
    entry = ConversationAPI(store).task_entry(sessions)
    request = {"client_request_id": "n02-entry-request", "task_id": task["task_id"], "task_version": task["version"]}
    return store, commands, task, sessions, entry, request


def bind_request(prepared, chat=CHAT):
    return {key: prepared[key] for key in ("client_request_id", "preparation_id", "preparation_sha256")} | {"chat_id": chat}


def test_current_task_entry_persists_exact_selection_and_actual_native_session(task_entry, tmp_path):
    store, commands, task, sessions, entry, request = task_entry
    before = business_snapshot(store)
    prepared = entry.prepare("BOSS", request)
    assert prepared["binding_state"] == "PREPARED" and prepared["context"] is None
    assert prepared["task_reference"] == {"kind": "task", "id": task["task_id"], "version": task["version"]}
    assert prepared["return_reference"] == {"page_id": "F06", "task_id": task["task_id"], "task_version": task["version"]}
    assert prepared["source_references"][0]["id"] == "finance-note"
    assert len(prepared["source_references"][0]["content_sha256"]) == 64
    assert entry.prepare("BOSS", request) == prepared
    bound = entry.bind("BOSS", bind_request(prepared))
    assert bound["context"] == CONTEXT and bound["binding_state"] == "BOUND"
    assert bound["preparation_sha256"] == prepared["preparation_sha256"]
    current = entry.read("BOSS", CONTEXT)
    assert current["current_use_verified"] and current["entry"] == bound
    assert current["references"] == [bound["task_reference"],
        *[{key: row[key] for key in ("kind", "id", "version")} for row in bound["source_references"]]]
    assert business_snapshot(store) == before
    reopened_sessions = SessionManager(tmp_path / "workspace", sessions_root=tmp_path / "native-sessions")
    reopened = ConversationAPI(ControlStore(store.path)).task_entry(reopened_sessions)
    assert reopened.read("BOSS", CONTEXT) == current
    receipt = reopened.receipt("BOSS", {"client_request_id": request["client_request_id"]})
    assert receipt["outcome"] == "RECORDED" and receipt["entry"]["current_use_verified"] is False
    assert receipt["entry"]["task_reference"] == prepared["task_reference"]
    run, _, question = actual_conversation(store, tmp_path, source(store), chat_id=CHAT,
        references=tuple((ref["kind"], ref["id"], ref["version"]) for ref in current["references"]))
    assert run["conversation_context"]["references"] == current["references"]
    assert any(message["role"] == "user" for message in reopened_sessions.read_session_snapshot(CONTEXT["session_id"]).messages)
    assert reopened.bind("BOSS", bind_request(prepared)) == bound
    assert business_snapshot(store) == before
    assert question not in json.dumps(current, ensure_ascii=False) and str(tmp_path) not in json.dumps(current)
    assert not current["business_authorization_granted"] and not current["business_mutation_performed"]


@pytest.mark.parametrize("stage", ["PREPARED", "BOUND"])
def test_task_version_change_stops_old_preparation_without_automatic_replacement(task_entry, stage):
    store, commands, task, sessions, entry, request = task_entry
    prepared = entry.prepare("BOSS", request)
    if stage == "BOUND":
        entry.bind("BOSS", bind_request(prepared))
    code, sent = commands.execute("BOSS", "boss.assignment.send", send_input(task, "n02-entry-version-send"))
    assert code == 200, sent
    before = all_objects(store)
    for operation in (lambda: entry.prepare("BOSS", request), lambda: entry.bind("BOSS", bind_request(prepared))):
        with pytest.raises(web.HTTPConflict):
            operation()
    if stage == "BOUND":
        with pytest.raises(web.HTTPConflict):
            entry.read("BOSS", CONTEXT)
    assert all_objects(store) == before
    receipt = entry.receipt("BOSS", {"client_request_id": request["client_request_id"]})
    assert receipt["entry"]["task_reference"]["version"] == task["version"]
    assert receipt["entry"]["binding_state"] == stage
    selected = entry.prepare("BOSS", {**request, "client_request_id": "n02-entry-new-selection", "task_version": sent["task_version"]})
    assert selected["task_reference"]["version"] == sent["task_version"]


@pytest.mark.parametrize("stage", ["PREPARED", "BOUND"])
def test_source_withdrawal_stops_binding_and_current_use_but_preserves_receipt(task_entry, stage):
    store, commands, task, sessions, entry, request = task_entry
    prepared = entry.prepare("BOSS", request)
    if stage == "BOUND":
        entry.bind("BOSS", bind_request(prepared))
    store.control("ui-check", "withdraw", {"source_id": "finance-note", "version": "1"})
    before = all_objects(store)
    with pytest.raises(web.HTTPGone):
        entry.bind("BOSS", bind_request(prepared))
    if stage == "BOUND":
        with pytest.raises(web.HTTPGone):
            entry.read("BOSS", CONTEXT)
    assert all_objects(store) == before
    saved = entry.receipt("BOSS", {"client_request_id": request["client_request_id"]})["entry"]
    assert saved["source_references"] == prepared["source_references"] and saved["binding_state"] == stage
    assert saved["current_use_verified"] is False


def test_idempotency_and_cross_session_selection_do_not_replace_binding(task_entry):
    store, commands, task, sessions, entry, request = task_entry
    prepared = entry.prepare("BOSS", request)
    with pytest.raises(web.HTTPConflict):
        entry.prepare("BOSS", {**request, "task_version": "2"})
    bound = entry.bind("BOSS", bind_request(prepared))
    other_context = {"session_id": "websocket:n02-entry-other", "chat_id": "n02-entry-other"}
    sessions.save(sessions.get_or_create(other_context["session_id"]))
    with pytest.raises(web.HTTPConflict):
        entry.bind("BOSS", bind_request(prepared, other_context["chat_id"]))
    other = entry.read("BOSS", other_context)
    assert other["binding_state"] == "UNBOUND" and other["entry"] is None and other["references"] == []
    code, second_task = commands.execute("BOSS", "boss.assignment.create", create_input("n02-entry-second-task"))
    assert code == 200, second_task
    second = entry.prepare("BOSS", {**request, "client_request_id": "n02-entry-second-selection", "task_id": second_task["task_id"]})
    with pytest.raises(web.HTTPConflict):
        entry.bind("BOSS", {**bind_request(prepared), "preparation_sha256": second["preparation_sha256"]})
    with pytest.raises(web.HTTPConflict):
        entry.bind("BOSS", bind_request(second))
    assert entry.read("BOSS", CONTEXT)["entry"] == bound
    assert entry.bind("BOSS", bind_request(second, other_context["chat_id"]))["task_reference"]["id"] == second_task["task_id"]


def test_identity_context_and_extra_fields_are_rejected_without_records(task_entry):
    store, commands, task, sessions, entry, request = task_entry
    prepared = entry.prepare("BOSS", request)
    before = all_objects(store)
    for role, error in ((None, web.HTTPUnauthorized), ("MAINTAINER", web.HTTPForbidden)):
        for operation in (lambda: entry.prepare(role, request), lambda: entry.bind(role, bind_request(prepared)), lambda: entry.read(role, CONTEXT),
                          lambda: entry.receipt(role, {"client_request_id": request["client_request_id"]})):
            with pytest.raises(error):
                operation()
    for field in ("owner_id", "namespace", "dataset_id", "source_references", "confirmed"):
        with pytest.raises(web.HTTPBadRequest):
            entry.prepare("BOSS", {**request, field: "injected"})
    with pytest.raises(web.HTTPForbidden):
        entry.read("BOSS", {**CONTEXT, "session_id": "websocket:n02-other"})
    assert all_objects(store) == before
    for field in ("owner_id", "namespace", "session_id", "task_id"):
        with pytest.raises(web.HTTPBadRequest):
            entry.bind("BOSS", {**bind_request(prepared), field: "injected"})
    with pytest.raises(web.HTTPConflict):
        entry.bind("BOSS", {**bind_request(prepared), "client_request_id": "n02-entry-wrong-request"})
    assert all_objects(store) == before


def test_binding_requires_actual_unused_native_session(task_entry, tmp_path):
    store, commands, task, sessions, entry, request = task_entry
    prepared = entry.prepare("BOSS", request)
    with pytest.raises(web.HTTPNotFound):
        entry.bind("BOSS", bind_request(prepared, "n02-entry-missing"))
    actual_conversation(store, tmp_path, source(store), chat_id=CHAT)
    with pytest.raises(web.HTTPConflict):
        entry.bind("BOSS", bind_request(prepared))
    assert entry.read("BOSS", CONTEXT)["binding_state"] == "UNBOUND"


def test_concurrent_binding_keeps_one_preparation_per_native_session(task_entry):
    store, commands, task, sessions, entry, request = task_entry
    first = entry.prepare("BOSS", request)
    second = entry.prepare("BOSS", {**request, "client_request_id": "n02-entry-concurrent-second"})
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(entry.bind, "BOSS", bind_request(prepared)) for prepared in (first, second)]
    assert sum(future.exception() is None for future in futures) == 1
    assert sum(isinstance(future.exception(), web.HTTPConflict) for future in futures) == 1
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind='conversation_task_binding'").fetchone()[0] == 1


def test_concurrent_prepare_reuses_original_record_and_unknown_receipt_stays_unknown(task_entry):
    store, commands, task, sessions, entry, request = task_entry
    assert entry.receipt("BOSS", {"client_request_id": request["client_request_id"]})["outcome"] == "NOT_FOUND_IN_CURRENT_STORE"
    with ThreadPoolExecutor(max_workers=2) as executor:
        first, second = [future.result() for future in [executor.submit(entry.prepare, "BOSS", request) for _ in range(2)]]
    assert first == second
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind='conversation_task_preparation'").fetchone()[0] == 1


@pytest.mark.parametrize("change", ["EXPIRED", "CHANGED"])
def test_fixed_source_expiry_or_revision_stops_bound_context_without_replacement(tmp_path, change):
    from boss_supply_quality import IMPORT_ACTION, COORDINATE_ACTION, SupplyQualityAPI
    from test_boss_supply_quality import coordination_payload, definition
    store = ControlStore(tmp_path / "entry-sources.sqlite")
    store.initialize("ui-check")
    service = SupplyQualityAPI(store)
    manifest = definition()["initial_request"]
    assert service.execute("MAINTAINER", IMPORT_ACTION, manifest)["state"] == "SUCCESS"
    task = service.execute("BOSS", COORDINATE_ACTION, coordination_payload(service, "n02-entry-source-coordinate"))
    sessions = SessionManager(tmp_path / "workspace", sessions_root=tmp_path / "native-sessions")
    sessions.save(sessions.get_or_create(CONTEXT["session_id"]))
    entry = ConversationAPI(store).task_entry(sessions)
    request = {"client_request_id": "n02-entry-source-request", "task_id": task["task_id"], "task_version": task["version"]}
    prepared = entry.prepare("BOSS", request)
    entry.bind("BOSS", bind_request(prepared))
    if change == "EXPIRED":
        with store.connect() as db:
            document = store.get(db, "ui-check", "document", prepared["source_references"][0]["id"])
        store.control("ui-check", "clock", {"at": document["valid_until"]})
    else:
        link = task["coordination_link"]
        record = next(row for row in manifest["records"] if row["entity_type"] == link["origin_entity_type"]
            and row["data"]["event_id"] == link["origin_record_id"])
        assert service.execute("MAINTAINER", IMPORT_ACTION, {**manifest, "client_request_id": "n02-entry-source-revision",
            "records": [{**record, "expected_version": link["origin_version"]}]})["state"] == "SUCCESS"
    before = all_objects(store)
    for operation in (lambda: entry.read("BOSS", CONTEXT), lambda: entry.prepare("BOSS", request)):
        with pytest.raises(web.HTTPGone if change == "EXPIRED" else web.HTTPConflict):
            operation()
    assert all_objects(store) == before
    receipt = entry.receipt("BOSS", {"client_request_id": request["client_request_id"]})
    assert receipt["entry"]["task_reference"] == prepared["task_reference"]
    assert receipt["entry"]["source_references"] == prepared["source_references"]
    assert receipt["entry"]["current_use_verified"] is False


def test_existing_morning_entry_cannot_be_taken_over_by_task_entry(task_entry):
    from product_morning import ProductMorning
    store, commands, task, sessions, entry, request = task_entry
    morning = ProductMorning(store)
    morning.native.bind("BOSS", "n02-entry-morning-original", {"chat_id": CHAT, "date": "2026-10-24", "timezone": "Asia/Shanghai"},
        attached=lambda chat: chat == CHAT, active=lambda: True)
    prepared = entry.prepare("BOSS", request)
    before = all_objects(store)
    with pytest.raises(web.HTTPConflict):
        entry.bind("BOSS", bind_request(prepared))
    assert all_objects(store) == before


def test_native_session_deletion_or_recreation_does_not_reuse_old_task_binding(task_entry):
    store, commands, task, sessions, entry, request = task_entry
    prepared = entry.prepare("BOSS", request)
    entry.bind("BOSS", bind_request(prepared))
    assert sessions.delete_session(CONTEXT["session_id"])
    for operation in (lambda: entry.read("BOSS", CONTEXT), lambda: entry.prepare("BOSS", request)):
        with pytest.raises(web.HTTPNotFound):
            operation()
    sessions.save(sessions.get_or_create(CONTEXT["session_id"]))
    for operation in (lambda: entry.read("BOSS", CONTEXT), lambda: entry.bind("BOSS", bind_request(prepared))):
        with pytest.raises(web.HTTPConflict):
            operation()
    receipt = entry.receipt("BOSS", {"client_request_id": request["client_request_id"]})
    assert receipt["entry"]["task_reference"] == prepared["task_reference"] and not receipt["entry"]["current_use_verified"]
