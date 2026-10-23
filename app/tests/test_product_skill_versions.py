import sys
import json
import asyncio
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
import yaml
from aiohttp import web
from jsonschema import Draft202012Validator
from nanobot.agent.tools.context import RequestContext

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "validation"))

from boss_command_api import BossCommandAPI
from boss_page_api import BossPageAPI
from controls import ControlStore
from product_skills import ProductSkills
from test_product_runtime_configuration import product


@pytest.mark.parametrize("role,status", [(None, 401), ("BOSS", 403), ("MAINTAINER", 503)])
def test_public_method_editor_requires_maintainer_and_runtime(tmp_path, role, status):
    store = ControlStore(tmp_path / "versions.sqlite")
    store.initialize("ui-check")
    assert BossPageAPI(store).serve(role, "/api/boss/ui/admin/sop-method", "sop_id=SOP03")[0] == status


@pytest.mark.parametrize("action", ["save", "validate", "activate", "enable", "disable", "restore", "recover", "cancel"])
def test_public_method_commands_require_connected_runtime(tmp_path, action):
    store = ControlStore(tmp_path / "versions.sqlite")
    store.initialize("ui-check")
    assert BossCommandAPI(store).execute("MAINTAINER", "boss.sop." + action, {})[0] == 503


@pytest.fixture
def methods(product):
    runtime, _, _ = product
    skills = ProductSkills(runtime)
    return skills, BossCommandAPI(runtime.store, runtime, skills), BossPageAPI(runtime.store, runtime_control=runtime, skills=skills)


def validate(kind, result):
    schema = yaml.safe_load((ROOT / "specs/product-skills.openapi.yaml").read_text())
    Draft202012Validator({**schema, "$ref": "#/components/schemas/" + kind}).validate(result)


def view(methods, sop="SOP03"):
    code, result = methods[2].serve("MAINTAINER", "/api/boss/ui/admin/sop-method", "sop_id=" + sop)
    assert code == 200
    validate("MethodEditor", result)
    return result


def saved(methods, version="0.1.1", key="public-method-save"):
    current = view(methods)
    payload = {"client_request_id": key, "sop_id": "SOP03", "expected_draft_version": current["draft"]["draft_version"] if current["draft"] else "0",
        "expected_active_sha256": current["active"]["content_sha256"], "method_version": version,
        "description": current["active"]["description"], "body": current["active"]["body"], "change_note": current["active"]["description"]}
    code, result = methods[1].execute("MAINTAINER", "boss.sop.save", payload)
    assert code == 200
    validate("SaveResult", result)
    return payload, result


def checked(methods, key="public-method-validate"):
    current = view(methods)
    code, result = methods[1].execute("MAINTAINER", "boss.sop.validate", {
        "client_request_id": key, "sop_id": "SOP03", "expected_draft_version": current["draft"]["draft_version"],
        "expected_content_sha256": current["draft"]["content_sha256"]})
    assert code == 200
    validate("ValidationResult", result)
    return view(methods)


def activation(current, key):
    return {"client_request_id": key, "sop_id": "SOP03", "expected_draft_version": current["draft"]["draft_version"],
            "expected_content_sha256": current["draft"]["content_sha256"], "expected_active_sha256": current["active"]["content_sha256"]}


def test_public_lifecycle_schema_original_receipts_and_history(methods):
    skills, api, pages = methods
    original = view(methods)
    payload, result = saved(methods)
    assert view(methods)["active"] == original["active"]
    assert api.execute("MAINTAINER", "boss.sop.save", payload) == (200, result)
    current = checked(methods)
    activate = activation(current, "public-method-activate")
    code, result = api.execute("MAINTAINER", "boss.sop.activate", activate)
    assert code == 200
    validate("ActivationResult", result)
    assert view(methods)["active"]["version"] == "0.1.1"
    saved(methods, "0.1.2", "public-method-save-next")
    assert api.execute("MAINTAINER", "boss.sop.activate", activate) == (200, result)
    receipt = pages.serve("MAINTAINER", "/api/boss/ui/admin/sop-operation-status", "action=activate&client_request_id=public-method-activate")[1]
    validate("OperationStatus", receipt)
    assert receipt["outcome"] == "RECORDED" and receipt["result"] == result
    history = next(item for item in view(methods)["history"] if item["method_version"] == "0.1.0")
    from urllib.parse import urlencode
    code, body = pages.serve("MAINTAINER", "/api/boss/ui/admin/sop-history", urlencode({"sop_id": "SOP03", "history_id": history["history_id"]}))
    assert code == 200
    validate("HistoryBody", body)
    assert body["body"] == original["active"]["body"]
    assert skills.runtime.read()["admission_ready"] is True
    assert not skills.runtime.provider.requests


@pytest.mark.parametrize("operation,state,version", [("recover", "ACTIVE", "0.1.1"), ("cancel", "CANCELED", "0.1.0")])
def test_public_prepared_recovery_blocks_every_new_context_and_catalog_update(methods, operation, state, version):
    skills, api, pages = methods
    saved(methods)
    current = checked(methods)
    prepared = activation(current, "public-prepared-method")
    skills.drafts.execute("MAINTAINER", "prepare", prepared)
    other = view(methods, "SOP01")
    assert other["pending_activations"] == [] and other["global_pending_activations"][0]["sop_id"] == "SOP03"
    assert skills.runtime.read()["admission_ready"] is False
    catalog = skills.read("MAINTAINER")
    validate("Projection", catalog)
    assert not any(item["context_eligible"] for item in catalog["items"])
    request = RequestContext(channel="direct", chat_id="prepared-sop", session_key="prepared-sop", sender_id="boss-1",
        original_user_text=current["active"]["description"], runtime=skills.runtime.loop.llm_runtime())
    for context in (skills.context, skills.runtime.context):
        with pytest.raises(web.HTTPConflict):
            asyncio.run(context(request))
    with pytest.raises(web.HTTPConflict):
        skills.update("MAINTAINER", {"name": current["active"]["name"], "enabled": False, "expected_content_sha256": current["active"]["content_sha256"]})
    code, result = api.execute("MAINTAINER", "boss.sop." + operation, {
        "client_request_id": "public-" + operation, "sop_id": "SOP03", "activation_request_id": prepared["client_request_id"]})
    assert code == 200 and result["state"] == state
    validate("ActivationResult", result)
    assert view(methods)["active"]["version"] == version and view(methods)["global_pending_activations"] == []
    assert skills.runtime.read()["admission_ready"] is True
    assert not skills.runtime.provider.requests


@pytest.mark.parametrize("query", ["", "sop_id=", "sop_id=SOP03&sop_id=SOP01", "sop_id=SOP03&namespace=ui-check"])
def test_public_method_query_is_exact(methods, query):
    assert methods[2].serve("MAINTAINER", "/api/boss/ui/admin/sop-method", query)[0] == 400


@pytest.mark.parametrize("query", ["action=activate&client_request_id=not%20permitted", "action=save&client_request_id=received%3A1"])
def test_public_original_receipt_query_matches_current_identifier_schema(methods, query):
    assert methods[2].serve("MAINTAINER", "/api/boss/ui/admin/sop-operation-status", query)[0] == 400


def test_public_technical_inputs_and_internal_prepare_are_rejected(methods):
    skills, api, pages = methods
    payload, _ = saved(methods)
    with skills.runtime.store.connect() as db:
        before = tuple(db.iterdump())
    assert api.execute("BOSS", "boss.sop.save", payload)[0] == 403
    assert api.execute("MAINTAINER", "boss.sop.prepare", payload)[0] == 404
    assert api.execute("MAINTAINER", "boss.sop.save", {**payload, "namespace": "ui-check"})[0] == 400
    assert api.execute("MAINTAINER", "boss.sop.activate", {"sop_id": "SOP03"})[0] == 400
    with skills.runtime.store.connect() as db:
        assert tuple(db.iterdump()) == before


def test_current_model_and_method_drafts_use_same_native_configuration_lock(methods):
    skills, api, pages = methods
    current = view(methods)
    method = {"client_request_id": "concurrent-method-save", "sop_id": "SOP03", "expected_draft_version": "0",
        "expected_active_sha256": current["active"]["content_sha256"], "method_version": "0.1.1",
        "description": current["active"]["description"], "body": current["active"]["body"], "change_note": current["active"]["description"]}
    model = {"client_request_id": "concurrent-model-save", "expected_version": "0", "values": {
        "max_tool_rounds": 4, "max_output_tokens": 700, "tool_scope": skills.runtime.registry.tool_names}}
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(api.execute, "MAINTAINER", action, payload) for action, payload in
                   [("boss.sop.save", method), ("boss.runtime.save", model)]]
        assert [future.result(timeout=15)[0] for future in futures] == [200, 200]
    assert view(methods)["draft"]["draft_version"] == "1"
    assert skills.runtime.read()["draft"]["version"] == "1"
    assert view(methods)["active"] == current["active"]
    assert not skills.runtime.provider.requests


def adopt_runtime(methods, request_id, tools):
    runtime, api = methods[0].runtime, methods[1]
    current = runtime.read()
    code, draft = api.execute("MAINTAINER", "boss.runtime.save", {
        "client_request_id": request_id + "-save", "expected_version": current["draft"]["version"] if current["draft"] else "0",
        "values": {"max_tool_rounds": 4, "max_output_tokens": 700, "tool_scope": tools}})
    assert code == 200
    code, checked = api.execute("MAINTAINER", "boss.runtime.validate", {
        "client_request_id": request_id + "-validate", "expected_version": draft["version"],
        "expected_content_sha256": draft["content_sha256"]})
    assert code == 200
    payload = {"client_request_id": request_id + "-activate", "expected_version": checked["version"],
        "expected_content_sha256": checked["content_sha256"], "expected_active_version": current["current"]["version"]}
    code, result = api.execute("MAINTAINER", "boss.runtime.activate", payload)
    assert code == 200
    return payload, result


def test_method_validation_requires_current_actual_registered_tools(methods):
    skills, api, _ = methods
    saved(methods)
    current = checked(methods)
    adopt_runtime(methods, "method-tools", list(skills.runtime.available))
    before = view(methods)["active"]
    assert api.execute("MAINTAINER", "boss.sop.activate", activation(current, "method-stale-tools"))[0] == 409
    assert view(methods)["active"] == before
    current = checked(methods, "method-current-tools")
    assert api.execute("MAINTAINER", "boss.sop.activate", activation(current, "method-adopt-current-tools"))[0] == 200
    assert not skills.runtime.provider.requests


def test_pending_method_keeps_existing_runtime_activation_receipt(methods):
    skills, api, _ = methods
    payload, original = adopt_runtime(methods, "method-runtime-receipt", list(skills.runtime.available))
    saved(methods)
    current = checked(methods)
    skills.drafts.execute("MAINTAINER", "prepare", activation(current, "pending-method-receipt"))
    assert skills.runtime.read()["admission_ready"] is False
    assert api.execute("MAINTAINER", "boss.runtime.activate", payload) == (200, original)
    assert skills.runtime.read()["admission_ready"] is False
    assert not skills.runtime.provider.requests
