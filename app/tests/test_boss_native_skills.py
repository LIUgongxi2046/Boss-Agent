import hashlib
import json
import shutil
import sys
from pathlib import Path

import pytest
from nanobot.agent.skills import SkillsLoader, parse_skill_metadata, valid_skill_metadata
from nanobot.agent.tools.registry import ToolRegistry
from aiohttp import web
from nanobot.config.loader import load_config, save_config
from nanobot.config.schema import Config
from nanobot.webui.skills_api import set_webui_skill_enabled

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "validation"))
ASSETS = json.loads((ROOT / "specs/agent-assets.json").read_text())
SKILLS = ROOT / "agent/skills"


def test_thirteen_current_sops_have_native_method_documents(tmp_path):
    loader = SkillsLoader(tmp_path, builtin_skills_dir=SKILLS)
    expected = {"boss-" + item["sop_id"].lower() for item in ASSETS["sops"]}
    assert {entry["name"] for entry in loader.list_skills()} == expected
    for item in ASSETS["sops"]:
        name = "boss-" + item["sop_id"].lower()
        content = loader.load_skill(name)
        metadata = parse_skill_metadata(content)
        assert valid_skill_metadata(metadata, name)
        assert metadata["metadata"]["boss"] == {
            "sop_id": item["sop_id"], "version": item["version"],
            "requirement_id": item["requirement_id"],
        }
        binding = next(binding for binding in ASSETS["sop_backend_bindings"] if binding["sop_id"] == item["sop_id"])
        assert all(operation in content for operation in binding["read_operations"] + binding["command_operations"])
        assert all(label in content for label in ("触发", "输入", "步骤", "授权", "输出", "结束条件"))
        block = loader.build_explicit_skill_runtime_context("$" + name)
        assert block is not None and block.source == "explicit_skills"
        assert "### Skill: " + name in block.content


def test_native_disable_persists_and_excludes_next_context(tmp_path):
    shutil.copytree(SKILLS, tmp_path / "skills")
    config_path = tmp_path / "config.json"
    config = Config()
    config.agents.defaults.workspace = str(tmp_path)
    save_config(config, config_path)
    disabled = set()
    original = (tmp_path / "skills/boss-sop03/SKILL.md").read_bytes()
    result = set_webui_skill_enabled(tmp_path, "boss-sop03", enabled=False, disabled_skills=disabled, config_path=config_path)
    assert result == {"name": "boss-sop03", "enabled": False, "deleted": False}
    restarted = load_config(config_path)
    loader = SkillsLoader(tmp_path, disabled_skills=set(restarted.agents.defaults.disabled_skills))
    assert loader.build_explicit_skill_runtime_context("$boss-sop03") is None
    set_webui_skill_enabled(tmp_path, "boss-sop03", enabled=True, disabled_skills=disabled, config_path=config_path)
    reopened = load_config(config_path)
    loader = SkillsLoader(tmp_path, disabled_skills=set(reopened.agents.defaults.disabled_skills))
    assert loader.build_explicit_skill_runtime_context("$boss-sop03") is not None
    assert (tmp_path / "skills/boss-sop03/SKILL.md").read_bytes() == original


@pytest.fixture
def native_catalog(tmp_path):
    from boss_native_skills import BossSkillCatalog
    from model_probe import BusinessTool
    from business import Store

    registry = ToolRegistry()
    store = Store(tmp_path / "skills.sqlite")
    namespace = "w2-native-skills"
    store.initialize(namespace)
    envelope = {"request_id": "w2-native-skills", "owner_id": "boss-1", "execution_namespace": namespace,
                "dataset_id": "selection", "dataset_version": "1", "session_id": "w2-native-skills"}
    for tool in ASSETS["tools"]:
        registry.register(BusinessTool(tool["tool_id"], store, envelope, {}, []))
    return BossSkillCatalog(SkillsLoader(tmp_path, builtin_skills_dir=SKILLS), registry)


def test_catalog_uses_actual_registered_tools_and_safe_version_projection(native_catalog):
    status = native_catalog.technical_status("MAINTAINER")
    assert len(status["items"]) == 13
    eligible = [item for item in status["items"] if item["context_eligible"]]
    assert [item["sop_id"] for item in eligible] == ["SOP03"]
    assert not status["private_body_available_here"]
    for item in status["items"]:
        original = (SKILLS / item["name"] / "SKILL.md").read_bytes()
        assert item["content_sha256"] == hashlib.sha256(original).hexdigest()
        assert original.decode() not in json.dumps(status, ensure_ascii=False)
    with pytest.raises(web.HTTPConflict):
        native_catalog.context("BOSS", ["SOP01"])
    native_catalog.registry.unregister("read_evidence")
    with pytest.raises(web.HTTPConflict):
        native_catalog.context("BOSS", ["SOP03"])


def test_context_contains_native_body_and_exact_current_version(native_catalog):
    block, references = native_catalog.context("BOSS", ["SOP03"])
    assert block.source == "explicit_skills"
    assert "调用 query_metrics" in block.content
    assert "原因贡献材料缺少时明确说明未知" in block.content
    assert references == [{
        "sop_id": "SOP03", "name": "boss-sop03", "version": "0.1.0",
        "content_sha256": hashlib.sha256((SKILLS / "boss-sop03/SKILL.md").read_bytes()).hexdigest(),
    }]
    native_catalog.loader.disabled_skills.add("boss-sop03")
    with pytest.raises(web.HTTPConflict):
        native_catalog.context("BOSS", ["SOP03"])


@pytest.mark.parametrize("role,status", [(None, 401), ("MAINTAINER", 403), ("CONTACT", 403)])
def test_context_rejects_non_owner(native_catalog, role, status):
    with pytest.raises(web.HTTPException) as failure:
        native_catalog.context(role, ["SOP03"])
    assert failure.value.status == status


@pytest.mark.parametrize("role,status", [(None, 401), ("BOSS", 403), ("CONTACT", 403)])
def test_technical_status_rejects_other_identities(native_catalog, role, status):
    with pytest.raises(web.HTTPException) as failure:
        native_catalog.technical_status(role)
    assert failure.value.status == status


@pytest.mark.parametrize("sop_ids", [[], ["SOP99"], ["SOP03", "SOP03"], [None], "SOP03"])
def test_context_rejects_ambiguous_method_selection(native_catalog, sop_ids):
    with pytest.raises(web.HTTPBadRequest):
        native_catalog.context("BOSS", sop_ids)


def test_catalog_enable_uses_same_native_configuration_and_reopen(native_catalog, tmp_path):
    from boss_native_skills import BossSkillCatalog

    shutil.copytree(SKILLS, tmp_path / "skills")
    config_path = tmp_path / "config.json"
    save_config(Config(), config_path)
    item = next(item for item in native_catalog.technical_status("MAINTAINER")["items"] if item["sop_id"] == "SOP03")
    original = (tmp_path / "skills/boss-sop03/SKILL.md").read_bytes()
    disabled = native_catalog.set_enabled("MAINTAINER", "SOP03", enabled=False,
                                         expected_content_sha256=item["content_sha256"], config_path=config_path)
    assert disabled["activation_policy"] == "NEXT_CONTEXT_LOAD" and disabled["enabled"] is False
    reopened = BossSkillCatalog(SkillsLoader(tmp_path, disabled_skills=set(load_config(config_path).agents.defaults.disabled_skills)), native_catalog.registry)
    with pytest.raises(web.HTTPConflict):
        reopened.context("BOSS", ["SOP03"])
    reopened.set_enabled("MAINTAINER", "SOP03", enabled=True,
                         expected_content_sha256=item["content_sha256"], config_path=config_path)
    restarted = BossSkillCatalog(SkillsLoader(tmp_path, disabled_skills=set(load_config(config_path).agents.defaults.disabled_skills)), native_catalog.registry)
    block, references = restarted.context("BOSS", ["SOP03"])
    assert block is not None and references[0]["content_sha256"] == item["content_sha256"]
    assert (tmp_path / "skills/boss-sop03/SKILL.md").read_bytes() == original


def test_catalog_rejects_unregistered_enable_stale_hash_and_missing_config(native_catalog, tmp_path):
    shutil.copytree(SKILLS, tmp_path / "skills")
    config_path = tmp_path / "config.json"
    save_config(Config(), config_path)
    original = config_path.read_bytes()
    items = {item["sop_id"]: item for item in native_catalog.technical_status("MAINTAINER")["items"]}
    with pytest.raises(web.HTTPConflict):
        native_catalog.set_enabled("MAINTAINER", "SOP01", enabled=True,
                                   expected_content_sha256=items["SOP01"]["content_sha256"], config_path=config_path)
    with pytest.raises(web.HTTPConflict):
        native_catalog.set_enabled("MAINTAINER", "SOP03", enabled=False,
                                   expected_content_sha256=items["SOP01"]["content_sha256"], config_path=config_path)
    with pytest.raises(web.HTTPConflict):
        native_catalog.set_enabled("MAINTAINER", "SOP03", enabled=False,
                                   expected_content_sha256=items["SOP03"]["content_sha256"], config_path=tmp_path / "missing.json")
    assert config_path.read_bytes() == original


@pytest.mark.parametrize("role,status", [(None, 401), ("BOSS", 403), ("CONTACT", 403)])
def test_method_enable_rejects_other_identities_before_reading_configuration(native_catalog, tmp_path, role, status):
    with pytest.raises(web.HTTPException) as failure:
        native_catalog.set_enabled(role, "SOP03", enabled=False, expected_content_sha256="", config_path=tmp_path / "config.json")
    assert failure.value.status == status
    assert not (tmp_path / "config.json").exists()
