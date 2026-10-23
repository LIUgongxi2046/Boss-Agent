import sys
import asyncio
import json
import yaml
from pathlib import Path

import pytest
from aiohttp import web
from nanobot.agent.tools.context import RequestContext
from nanobot.config.loader import load_config
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "validation"))

from boss_page_api import BossPageAPI
from controls import ControlStore
from product_skills import ProductSkills
from test_product_runtime_configuration import product


def validate(kind, value):
    document = yaml.safe_load((ROOT / "specs/product-skills.openapi.yaml").read_text())
    Draft202012Validator({**document, "$ref": "#/components/schemas/" + kind}).validate(value)


@pytest.mark.parametrize("role,status", [(None, 401), ("BOSS", 403), ("MAINTAINER", 503)])
def test_public_native_skill_read_requires_maintainer_and_live_service(tmp_path, role, status):
    store = ControlStore(tmp_path / "skills-public.sqlite")
    store.initialize("ui-check")
    pages = BossPageAPI(store)
    assert pages.serve(role, "/api/boss/ui/admin/skills")[0] == status


@pytest.fixture
def skills(product):
    runtime, api, pages = product
    service = ProductSkills(runtime)
    return service, BossPageAPI(runtime.store, runtime_control=runtime, skills=service)


def request(service):
    return RequestContext(channel="direct", chat_id="public-skill-check", session_key="public-skill-check",
        sender_id="boss-1", original_user_text="$boss-sop03", runtime=service.runtime.loop.llm_runtime())


def test_public_catalog_uses_live_loader_registry_and_native_current_files(skills):
    service, pages = skills
    code, result = pages.serve("MAINTAINER", "/api/boss/ui/admin/skills")
    assert code == 200 and len(result["items"]) == 13
    validate("Projection", result)
    assert service.catalog.loader is service.runtime.loop.context.skills
    assert service.catalog.registry is service.runtime.registry
    assert result["runtime_admission_ready"] is True
    assert result["private_body_available_here"] is False
    assert [item["sop_id"] for item in result["items"] if item["context_eligible"]] == ["SOP03"]
    assert pages.serve("MAINTAINER", "/api/boss/ui/admin/skills", "namespace=ui-check")[0] == 400
    with service.runtime.store.connect() as db:
        before = tuple(db.iterdump())
    current = request(service)
    blocks = asyncio.run(service.context(current))
    native = service.runtime.loop.context.skills.build_explicit_skill_runtime_context(current.original_user_text)
    assert blocks[0] == native
    assert json.loads(blocks[1].content)["sops"] == current.attributes["boss_sop_reference"]
    unsubscribe = service.runtime.loop.register_runtime_context_provider(service.context)
    resolved = asyncio.run(service.runtime.loop._resolve_runtime_context_for_request(request(service), service.runtime.registry))
    assert resolved.count(native) == 1
    assert len([block for block in resolved if block.source == "boss-sop-versions"]) == 1
    unsubscribe()
    with service.runtime.store.connect() as db:
        assert tuple(db.iterdump()) == before
    assert not service.runtime.provider.requests


def change(service, enabled):
    item = next(item for item in service.read("MAINTAINER")["items"] if item["sop_id"] == "SOP03")
    payload = {"name": item["name"], "enabled": enabled, "expected_content_sha256": item["content_sha256"]}
    validate("Update", payload)
    result = service.update("MAINTAINER", payload)
    validate("Result", result)
    return result


def test_native_skill_change_applies_next_context_without_changing_model_settings(skills):
    service, pages = skills
    runtime = service.runtime
    original = runtime.snapshot()
    assert change(service, False)["enabled"] is False
    assert "boss-sop03" in load_config(runtime.config.path).agents.defaults.disabled_skills
    assert service.read("MAINTAINER")["runtime_admission_ready"] is True
    assert {key: value for key, value in runtime.snapshot().items() if key != "config_sha256"} == {
        key: value for key, value in original.items() if key != "config_sha256"}
    assert runtime.snapshot()["config_sha256"] != original["config_sha256"]
    asyncio.run(runtime.context(request(service)))
    with pytest.raises(web.HTTPConflict):
        asyncio.run(service.context(request(service)))
    assert change(service, True)["enabled"] is True
    assert "boss-sop03" not in load_config(runtime.config.path).agents.defaults.disabled_skills
    assert asyncio.run(service.context(request(service)))[0].source == "explicit_skills"
    assert not runtime.provider.requests


@pytest.mark.parametrize("role,status", [(None, 401), ("BOSS", 403), ("CONTACT", 403)])
def test_native_skill_change_rejects_other_roles_without_writes(skills, role, status):
    service, _ = skills
    before = service.runtime.config.path.read_bytes()
    with pytest.raises(web.HTTPException) as failure:
        service.update(role, {})
    assert failure.value.status == status
    assert service.runtime.config.path.read_bytes() == before


def test_native_skill_change_cannot_adopt_unapproved_model_configuration(skills):
    service, _ = skills
    service.runtime.config.update(lambda config: setattr(config.agents.defaults, "max_tool_iterations", 8))
    before = service.runtime.config.path.read_bytes()
    with pytest.raises(web.HTTPConflict):
        change(service, False)
    assert service.runtime.config.path.read_bytes() == before
    assert "boss-sop03" not in load_config(service.runtime.config.path).agents.defaults.disabled_skills
