import asyncio
from copy import deepcopy
import json

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from conftest import DOMAIN, ROOT
from controls import ControlStore
from test_cancel_deadline import arguments, run_for
from test_native import native
from test_observable_failure import session
from test_task_entry_consumer import CHAT, bind_task, create_task, pinned


SCHEMA_PATH = ROOT / "specs/runtime-records.schema.json"


def current_validator():
    schema = json.loads(SCHEMA_PATH.read_text())
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator({**schema, "$ref": "#/$defs/CurrentRuntimeRun"}, format_checker=FormatChecker())


@pytest.fixture
def bound_runtime(native):
    task = create_task(native, "n02-schema-actual-task")
    _, bound = bind_task(native, task, key="n02-schema-actual-entry")
    async def check():
        async with session(native) as (bot, _):
            result = await bot.run("查看当前任务", **arguments(CHAT))
            assert not result.error and task["task_id"] in result.content
    asyncio.run(check())
    run = run_for(native, CHAT)
    assert run["status"] == "SUCCEEDED" and run["conversation_context"]["task_entry"] == pinned(bound)
    with ControlStore(native[0].path).connect() as db:
        saved = native[0].get(db, "ui-check", "runtime_run", run["run_id"])
    assert saved == run
    return saved


def test_actual_saved_bound_task_runtime_validates_without_projection_or_field_removal(bound_runtime):
    original = deepcopy(bound_runtime)
    current_validator().validate(bound_runtime)
    assert bound_runtime == original
    assert bound_runtime["source_type"] == "SIMULATED" and bound_runtime["external_model_invoked"] is False
    entry = bound_runtime["conversation_context"]["task_entry"]
    assert set(entry) == {"preparation_id", "client_request_id", "preparation_sha256", "task_reference", "source_references", "return_reference"}


def test_restricted_task_entry_inputs_are_rejected_against_actual_saved_runtime(bound_runtime, record_property):
    validator = current_validator()
    validator.validate(bound_runtime)
    cases = []
    entry_path = ("conversation_context", "task_entry")
    for path in (entry_path, (*entry_path, "task_reference"), (*entry_path, "source_references", 0), (*entry_path, "return_reference")):
        for field in ("question", "body", "path", "business_authorization_granted", "confirmed", "role"):
            cases.append(((*path, field), "EXTRA", True))
    for field in bound_runtime["conversation_context"]["task_entry"]:
        cases.append(((*entry_path, field), "REMOVE", None))
    for field, values in (("task_reference", ("kind", "id", "version")),
                          ("source_references", ("kind", "id", "version", "content_sha256")),
                          ("return_reference", ("page_id", "task_id", "task_version"))):
        path = (*entry_path, field, 0) if field == "source_references" else (*entry_path, field)
        for name in values:
            cases.append(((*path, name), "REMOVE", None))
    for path, value in (
        (entry_path, None), (entry_path, []),
        ((*entry_path, "task_reference", "kind"), "document"),
        ((*entry_path, "source_references", 0, "kind"), "task"),
        ((*entry_path, "return_reference", "page_id"), "N02"),
        ((*entry_path, "preparation_sha256"), "invalid-sha256"),
        ((*entry_path, "source_references", 0, "content_sha256"), "invalid-sha256"),
        ((*entry_path, "preparation_id"), ""), ((*entry_path, "preparation_id"), "x" * 201),
        ((*entry_path, "client_request_id"), "short"), ((*entry_path, "client_request_id"), "x" * 129),
        ((*entry_path, "client_request_id"), "invalid request id"),
        ((*entry_path, "task_reference", "id"), ""), ((*entry_path, "task_reference", "version"), None),
        ((*entry_path, "source_references", 0, "version"), ""),
        ((*entry_path, "return_reference", "task_id"), None),
        ((*entry_path, "return_reference", "task_version"), ""),
        ((*entry_path, "source_references"), []),
    ):
        cases.append((path, "REPLACE", value))
    original = deepcopy(bound_runtime)
    for path, operation, value in cases:
        candidate = deepcopy(bound_runtime)
        target = candidate
        for field in path[:-1]:
            target = target[field]
        if operation == "REMOVE":
            del target[path[-1]]
        else:
            target[path[-1]] = value
        assert list(validator.iter_errors(candidate)), (path, operation)
    assert bound_runtime == original
    record_property("rejected_task_entry_input_count", len(cases))


def test_actual_unbound_runtime_keeps_optional_task_entry_absent(native):
    chat = "n02-schema-unbound"
    async def check():
        async with session(native) as (bot, _):
            assert not (await bot.run("读取 meeting-minutes", **arguments(chat))).error
    asyncio.run(check())
    run = run_for(native, chat)
    assert "task_entry" not in run["conversation_context"]
    current_validator().validate(run)


def test_runtime_schema_preserves_exact_product_112_baseline():
    base = json.loads((DOMAIN / "specs/runtime-records.schema.json").read_text())
    assert base["$id"] == "urn:boss-agent:runtime-records:1.12.0"
    schema = json.loads(SCHEMA_PATH.read_text())
    assert schema["$id"] == "urn:boss-agent:runtime-records:1.13.0"
    schema["$id"] = base["$id"]
    del schema["$defs"]["ConversationContext"]["properties"]["task_entry"]
    del schema["$defs"]["ConversationTaskEntry"]
    del schema["$defs"]["TaskEntryIdentifier"]
    assert schema == base
