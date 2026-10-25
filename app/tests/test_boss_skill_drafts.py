import hashlib
import json
import shutil
import sys
from pathlib import Path

import pytest
from aiohttp import web
from nanobot.agent.skills import SkillsLoader
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.config.loader import load_config, save_config
from nanobot.config.schema import Config

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "validation"))

from boss_native_skills import BossSkillCatalog
from controls import ControlStore
from model_probe import BusinessTool


@pytest.fixture
def methods(tmp_path):
    workspace = tmp_path / "workspace"
    shutil.copytree(ROOT / "agent/skills", workspace / "skills")
    config_path = tmp_path / "config.json"
    config = Config()
    config.agents.defaults.workspace = str(workspace)
    save_config(config, config_path)
    store = ControlStore(tmp_path / "methods.sqlite")
    store.initialize("ui-check")
    registry = ToolRegistry()
    envelope = {"request_id": "w2-sop-drafts", "owner_id": "boss-1", "execution_namespace": "ui-check",
                "dataset_id": "selection", "dataset_version": "1", "session_id": "w2-sop-drafts"}
    assets = json.loads((ROOT / "specs/agent-assets.json").read_text())
    for item in assets["tools"]:
        registry.register(BusinessTool(item["tool_id"], store, envelope, {}, []))
    return store, BossSkillCatalog(SkillsLoader(workspace), registry), config_path


def service(methods):
    from boss_skill_drafts import BossSkillDrafts
    return BossSkillDrafts(*methods)


def save_current(api, *, key="save-method", version="0.1.1", expected="0", body=None):
    view = api.read("MAINTAINER", "SOP03")
    active = view["active"]
    return api.execute("MAINTAINER", "save", {
        "client_request_id": key, "sop_id": "SOP03", "expected_draft_version": expected,
        "expected_active_sha256": active["content_sha256"], "method_version": version,
        "description": active["description"], "body": body or active["body"],
        "change_note": "核查当前经营方法的版本保存与读取",
    })


def test_saved_draft_keeps_native_current_context(methods):
    api = service(methods)
    _, before = methods[1].context("BOSS", ["SOP03"])
    save_current(api)
    _, after = methods[1].context("BOSS", ["SOP03"])
    assert after == before and after[0]["version"] == "0.1.0"


def test_save_reopen_validate_publish_and_native_context(methods):
    api = service(methods)
    before = api.read("MAINTAINER", "SOP03")["active"]
    saved = save_current(api)
    assert saved["draft_version"] == "1" and saved["state"] == "DRAFT"
    assert api.read("MAINTAINER", "SOP03")["active"] == before
    assert save_current(api) == saved
    reopened = service(methods)
    draft = reopened.read("MAINTAINER", "SOP03")["draft"]
    checked = reopened.execute("MAINTAINER", "validate", {
        "client_request_id": "validate-method", "sop_id": "SOP03", "expected_draft_version": "1",
        "expected_content_sha256": draft["content_sha256"],
    })
    assert checked["validation_status"] == "VALIDATED_STATIC_ONLY"
    published = reopened.execute("MAINTAINER", "activate", {
        "client_request_id": "activate-method", "sop_id": "SOP03", "expected_draft_version": "1",
        "expected_content_sha256": draft["content_sha256"], "expected_active_sha256": before["content_sha256"],
    })
    assert published["state"] == "ACTIVE" and published["method_version"] == "0.1.1"
    final = service(methods).read("MAINTAINER", "SOP03")
    assert final["active"]["version"] == "0.1.1" and final["draft"]["state"] == "ACTIVE"
    assert {row["method_version"] for row in final["history"]} == {"0.1.0", "0.1.1"}
    block, references = methods[1].context("BOSS", ["SOP03"])
    assert references[0]["version"] == "0.1.1" and "query_metrics" in block.content
    assert references[0]["content_sha256"] == hashlib.sha256((methods[1].loader.workspace / "skills/boss-sop03/SKILL.md").read_bytes()).hexdigest()
    assert load_config(methods[2]).agents.defaults.disabled_skills == []


def checked_payload(api, key="activate-method"):
    view = api.read("MAINTAINER", "SOP03")
    draft = view["draft"]
    api.execute("MAINTAINER", "validate", {
        "client_request_id": "validate-" + key, "sop_id": "SOP03", "expected_draft_version": draft["draft_version"],
        "expected_content_sha256": draft["content_sha256"],
    })
    return {"client_request_id": key, "sop_id": "SOP03", "expected_draft_version": draft["draft_version"],
            "expected_content_sha256": draft["content_sha256"], "expected_active_sha256": view["active"]["content_sha256"]}


def test_history_restore_creates_new_draft_and_preserves_current_native_method(methods):
    api = service(methods)
    save_current(api)
    api.execute("MAINTAINER", "activate", checked_payload(api))
    view = api.read("MAINTAINER", "SOP03")
    historical = next(item for item in view["history"] if item["method_version"] == "0.1.0")
    body = api.read_history("MAINTAINER", "SOP03", historical["history_id"])
    restored = api.execute("MAINTAINER", "restore", {
        "client_request_id": "restore-method", "sop_id": "SOP03", "expected_draft_version": "1",
        "expected_active_sha256": view["active"]["content_sha256"], "method_version": "0.1.2",
        "history_id": historical["history_id"], "change_note": "恢复获准历史方法为新的待确认草稿",
    })
    after = service(methods).read("MAINTAINER", "SOP03")
    assert restored["state"] == "DRAFT" and restored["draft_version"] == "2"
    assert after["active"] == view["active"]
    assert after["draft"]["body"] == body["body"]
    assert after["draft"]["restored_from"] == historical["history_id"]
    assert any(item["origin"] == "DRAFT_REVISION" for item in after["history"])


@pytest.mark.parametrize("mode,version", [("recover", "0.1.1"), ("cancel", "0.1.0")])
def test_prepared_activation_survives_reopen_and_requires_explicit_recovery(methods, mode, version):
    api = service(methods)
    save_current(api)
    payload = checked_payload(api)
    prepared = api.execute("MAINTAINER", "prepare", payload)
    assert prepared["state"] == "PREPARED"
    reopened = service(methods)
    assert len(reopened.read("MAINTAINER", "SOP03")["pending_activations"]) == 1
    assert reopened.operation_status("MAINTAINER", "activate", payload["client_request_id"])["outcome"] == "PREPARED"
    with pytest.raises(web.HTTPConflict):
        methods[1].context("BOSS", ["SOP03"])
    result = reopened.execute("MAINTAINER", mode, {
        "client_request_id": mode + "-method", "sop_id": "SOP03", "activation_request_id": payload["client_request_id"],
    })
    assert result["state"] == ("ACTIVE" if mode == "recover" else "CANCELED")
    assert reopened.read("MAINTAINER", "SOP03")["pending_activations"] == []
    _, references = methods[1].context("BOSS", ["SOP03"])
    assert references[0]["version"] == version
    receipt = reopened.operation_status("MAINTAINER", "activate", payload["client_request_id"])
    assert receipt["outcome"] == "RECORDED" and receipt["result"] == result
    assert reopened.operation_status("MAINTAINER", mode, mode + "-method")["result"] == result
    with methods[0].connect() as db:
        recorded = tuple(db.iterdump())
    assert reopened.execute("MAINTAINER", mode, {
        "client_request_id": mode + "-method", "sop_id": "SOP03", "activation_request_id": payload["client_request_id"],
    }) == result
    with methods[0].connect() as db:
        assert tuple(db.iterdump()) == recorded


def test_invalid_reference_is_persisted_as_invalid_and_cannot_activate(methods):
    api = service(methods)
    before = api.read("MAINTAINER", "SOP03")["active"]
    body = before["body"].replace("[read_evidence](tool:read_evidence)", "[read_evidence](tool:unknown_operation)")
    save_current(api, body=body)
    view = api.read("MAINTAINER", "SOP03")
    payload = checked_payload(api)
    checked = api.read("MAINTAINER", "SOP03")["draft"]
    assert checked["validation_status"] == "INVALID"
    assert checked["errors"][0]["unknown"] == ["unknown_operation"]
    with pytest.raises(web.HTTPConflict):
        api.execute("MAINTAINER", "activate", payload)
    assert api.read("MAINTAINER", "SOP03")["active"] == before


def test_same_request_with_different_body_and_stale_draft_are_rejected(methods):
    api = service(methods)
    save_current(api)
    with pytest.raises(web.HTTPConflict):
        save_current(api, body=api.read("MAINTAINER", "SOP03")["active"]["body"] + "\n新增当前来源核查要求。")
    with pytest.raises(web.HTTPConflict):
        save_current(api, key="another-save", expected="0")
    assert api.read("MAINTAINER", "SOP03")["draft"]["draft_version"] == "1"


@pytest.mark.parametrize("role,status", [(None, 401), ("BOSS", 403), ("CONTACT", 403)])
def test_draft_service_rejects_other_identities_and_does_not_change_database(methods, role, status):
    api = service(methods)
    with methods[0].connect() as db:
        before = tuple(db.iterdump())
    for call in (lambda: api.read(role, "SOP03"), lambda: api.execute(role, "save", {}),
                 lambda: api.operation_status(role, "save", "unknown"), lambda: api.read_history(role, "SOP03", "unknown")):
        with pytest.raises(web.HTTPException) as failure:
            call()
        assert failure.value.status == status
    with methods[0].connect() as db:
        assert tuple(db.iterdump()) == before


def test_activation_receipt_replay_does_not_publish_again(methods):
    api = service(methods)
    save_current(api)
    payload = checked_payload(api)
    first = api.execute("MAINTAINER", "activate", payload)
    with methods[0].connect() as db:
        before = tuple(db.iterdump())
    assert api.execute("MAINTAINER", "activate", payload) == first
    with methods[0].connect() as db:
        assert tuple(db.iterdump()) == before


def test_inactive_space_rejects_prepared_completion_before_native_changes(methods):
    api = service(methods)
    save_current(api)
    payload = checked_payload(api)
    api.execute("MAINTAINER", "prepare", payload)
    path = methods[1].loader.workspace / "skills/boss-sop03/SKILL.md"
    original, config = path.read_bytes(), methods[2].read_bytes()
    methods[0].control("ui-check", "reset", {"namespace": "w2-next-execution"})
    with pytest.raises(web.HTTPConflict):
        api.execute("MAINTAINER", "recover", {"client_request_id": "recover-inactive", "sop_id": "SOP03", "activation_request_id": payload["client_request_id"]})
    assert path.read_bytes() == original and methods[2].read_bytes() == config


def test_catalog_enable_is_blocked_while_activation_needs_recovery(methods):
    api = service(methods)
    save_current(api)
    payload = checked_payload(api)
    api.execute("MAINTAINER", "prepare", payload)
    with pytest.raises(web.HTTPConflict):
        methods[1].set_enabled("MAINTAINER", "SOP03", enabled=False, expected_content_sha256=payload["expected_active_sha256"], config_path=methods[2])


def test_current_native_method_can_be_disabled_and_enabled_without_new_draft(methods):
    api = service(methods)
    active = api.read("MAINTAINER", "SOP03")["active"]
    for action in ("disable", "enable"):
        result = api.execute("MAINTAINER", action, {"client_request_id": action + "-native-method", "sop_id": "SOP03", "expected_active_sha256": active["content_sha256"]})
        assert result["enabled"] == (action == "enable")
        view = api.read("MAINTAINER", "SOP03")
        assert view["draft"] is None and view["active"]["content_sha256"] == active["content_sha256"]


@pytest.mark.parametrize("field,value", [("namespace", "another-space"), ("owner_id", "boss-1"), ("expected_active_sha256", [])])
def test_method_command_rejects_scope_injection_and_invalid_field_types(methods, field, value):
    api = service(methods)
    active = api.read("MAINTAINER", "SOP03")["active"]
    payload = {"client_request_id": "invalid-native-method", "sop_id": "SOP03", "expected_active_sha256": active["content_sha256"], field: value}
    with pytest.raises(web.HTTPBadRequest):
        api.execute("MAINTAINER", "disable", payload)
    assert api.read("MAINTAINER", "SOP03")["active"] == active
