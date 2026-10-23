import sys
import asyncio
import json
from pathlib import Path

import pytest
import yaml
from aiohttp import web
from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012
from nanobot.agent.loop import AgentLoop
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.agent.tools.context import RequestContext
from nanobot.config.loader import load_config, resolve_config_env_vars, save_config
from nanobot.config.schema import Config

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "validation"))

from boss_agent_read_tools import BossResearchSourcesTool
from boss_command_api import BossCommandAPI
from boss_page_api import BossPageAPI
from business import OPERATIONS
from connection import RecordedProvider, settings
from controls import ControlStore
from model_probe import BusinessTool
from product_runtime import ProductRuntime
from boss_runtime_records import RuntimeRecorder


@pytest.fixture
def product(tmp_path):
    connection = settings()
    config = Config()
    config.agents.defaults.workspace = str(tmp_path / "workspace")
    config.agents.defaults.provider = "deepseek"
    config.agents.defaults.model = "deepseek-flash"
    config.agents.defaults.max_tool_iterations = 12
    config.agents.defaults.max_tokens = 4096
    config.agents.defaults.dream.enabled = False
    config.providers.deepseek.api_key = "${DEEPSEEK_API_KEY}"
    config.providers.deepseek.api_base = "https://api.deepseek.com"
    filename = tmp_path / "config.json"
    save_config(config, filename)
    config = resolve_config_env_vars(load_config(filename), config_path=filename)
    store = ControlStore(tmp_path / "business.sqlite")
    store.initialize("ui-check")
    registry = ToolRegistry()
    envelope = {"request_id": "config-check", "owner_id": "boss-1", "execution_namespace": "ui-check",
                "dataset_id": "selection", "dataset_version": "1", "session_id": "config-check"}
    tools = [BusinessTool(name, store, envelope, {}, []) for name in OPERATIONS]
    tools.append(BossResearchSourcesTool(store, "BOSS"))
    provider = RecordedProvider(connection, tmp_path / "transport.json", redact_payload=True)
    loop = AgentLoop.from_config(config, provider=provider, tool_registry=registry)
    runtime = ProductRuntime(store, filename, loop, registry, tools, provider)
    return runtime, BossCommandAPI(store, runtime), BossPageAPI(store, runtime_control=runtime)


def command(api, action, **values):
    return api.execute("MAINTAINER", "boss.runtime." + action,
                       {"client_request_id": "runtime-config-" + action, **values})


def saved(product, rounds=4, tools=None):
    runtime, api, _ = product
    return command(api, "save", expected_version="0", values={"max_tool_rounds": rounds,
                   "max_output_tokens": 700, "tool_scope": tools or list(runtime.available)})


def validated(product):
    runtime, api, _ = product
    code, draft = saved(product)
    assert code == 200
    code, checked = command(api, "validate", expected_version=draft["version"], expected_content_sha256=draft["content_sha256"])
    assert code == 200
    return checked


def test_scope_is_explicit_and_current_configuration_is_not_expanded(product):
    runtime, api, pages = product
    initial = runtime.read()
    assert initial["admission_ready"] is True
    assert "bossWorkspaceRead" in initial["available_tools"]
    assert "bossWorkspaceRead" not in initial["current"]["tool_scope"]
    assert set(runtime.registry.tool_names) == set(OPERATIONS)
    checked = validated(product)
    assert runtime.read()["current"] == initial["current"]
    code, result = command(api, "activate", expected_version=checked["version"],
                           expected_content_sha256=checked["content_sha256"], expected_active_version="1")
    assert code == 200 and result["runtime_applied"] is True
    assert runtime.read()["admission_ready"] is True
    assert runtime.read()["draft"]["validation_status"] == "ACTIVATED"
    assert runtime.loop.max_iterations == 4
    assert runtime.loop.llm_runtime().generation.max_tokens == 700
    assert set(runtime.registry.tool_names) == set(runtime.available)
    native = load_config(runtime.config.path)
    assert native.agents.defaults.max_tool_iterations == 4
    assert native.agents.defaults.max_tokens == 700
    with runtime.store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind IN ('authorization','task','outbox','runtime_run')").fetchone()[0] == 0
    assert not runtime.provider.requests


def test_version_conflict_and_repeated_activation_preserve_receipt(product):
    runtime, api, _ = product
    checked = validated(product)
    arguments = {"expected_version": checked["version"], "expected_content_sha256": checked["content_sha256"], "expected_active_version": "1"}
    before = runtime.config.path.read_bytes()
    assert command(api, "activate", **{**arguments, "expected_active_version": "2"})[0] == 409
    assert runtime.config.path.read_bytes() == before
    first = command(api, "activate", **arguments)
    second = command(api, "activate", **arguments)
    assert first == second and first[0] == 200
    assert runtime.read()["current"]["version"] == "2"


def test_saved_native_change_requires_explicit_revalidation(product):
    runtime, api, _ = product
    checked = validated(product)
    runtime.config.update(lambda config: setattr(config.agents.defaults, "max_tool_iterations", 8))
    assert runtime.read()["admission_ready"] is False
    with pytest.raises(web.HTTPConflict):
        runtime.snapshot()
    assert command(api, "activate", expected_version=checked["version"],
                   expected_content_sha256=checked["content_sha256"], expected_active_version="1")[0] == 409
    assert runtime.loop.max_iterations == 12


def test_roles_cannot_change_runtime_or_read_configuration(product):
    runtime, api, pages = product
    for role, status in [(None, 401), ("BOSS", 403), ("finance-1", 401)]:
        assert api.execute(role, "boss.runtime.save", {"client_request_id": "runtime-role-denied"})[0] == status
        assert pages.serve(role, "/api/boss/ui/admin/runtime-configuration")[0] == status
    assert pages.serve("MAINTAINER", "/api/boss/ui/admin/runtime-configuration", "namespace=outside")[0] == 400
    assert pages.serve("MAINTAINER", "/api/boss/ui/admin/runtime-configuration")[0] == 200


@pytest.mark.parametrize("values", [
    {"max_tool_rounds": 0, "max_output_tokens": 700, "tool_scope": ["query_metrics"]},
    {"max_tool_rounds": 4, "max_output_tokens": 700, "tool_scope": ["exec"]},
    {"max_tool_rounds": 4, "max_output_tokens": 700, "tool_scope": ["query_metrics", "query_metrics"]},
    {"max_tool_rounds": 4, "max_output_tokens": 700, "tool_scope": ["query_metrics"], "owner_id": "boss-1"},
])
def test_unapproved_or_invalid_configuration_has_no_write(product, values):
    runtime, api, _ = product
    before = runtime.read()
    assert command(api, "save", expected_version="0", values=values)[0] == 400
    assert runtime.read() == before


def test_disable_keeps_business_and_tool_state_and_blocks_next_admission(product):
    runtime, api, _ = product
    before = runtime.registry.get_definitions()
    assert command(api, "deactivate", expected_active_version="1")[0] == 200
    assert runtime.read()["admission_ready"] is False
    assert runtime.registry.get_definitions() == before
    assert runtime.read()["current"]["enabled"] is False
    with runtime.store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind IN ('authorization','task','outbox','runtime_run')").fetchone()[0] == 0
    assert not runtime.provider.requests


def test_admitted_request_keeps_snapshot_after_native_save_and_disable(product):
    runtime, api, _ = product
    request = RequestContext(channel="direct", chat_id="configuration-check", session_key="configuration-check",
                             sender_id="boss-1", runtime=runtime.loop.llm_runtime())
    asyncio.run(runtime.context(request))
    recorder = RuntimeRecorder(runtime.store, "ui-check", runtime.registry, runtime.snapshot)
    asyncio.run(recorder.context(request))
    original = request.runtime
    runtime.config.update(lambda config: setattr(config.agents.defaults, "max_tool_iterations", 8))
    assert command(api, "deactivate", expected_active_version="1")[0] == 200
    asyncio.run(runtime.context(request))
    assert request.runtime is original and runtime.loop.max_iterations == 12
    next_request = RequestContext(channel="direct", chat_id="next-configuration-check", session_key="next-configuration-check",
                                  sender_id="boss-1", runtime=runtime.loop.llm_runtime())
    with pytest.raises(web.HTTPConflict):
        asyncio.run(runtime.context(next_request))
    assert not runtime.provider.requests


def test_actual_configuration_lifecycle_matches_its_review_schema(product):
    runtime, api, pages = product
    extension_path = ROOT / "specs/product-runtime.openapi.yaml"
    extension = yaml.safe_load(extension_path.read_text())
    record_path = ROOT / "specs/runtime-records.schema.json"
    record_schema = json.loads(record_path.read_text())
    registry = Registry().with_resources([
        (extension_path.as_uri(), Resource.from_contents(extension, default_specification=DRAFT202012)),
        (record_path.as_uri(), Resource.from_contents(record_schema)),
    ])
    def validate(name, result):
        schema = {"$id": extension_path.as_uri(), **extension, "$ref": "#/components/schemas/" + name}
        Draft202012Validator(schema, registry=registry, format_checker=FormatChecker()).validate(result)
    code, initial = pages.serve("MAINTAINER", "/api/boss/ui/admin/runtime-configuration")
    assert code == 200
    validate("RuntimeConfiguration", initial)
    code, draft = saved(product)
    assert code == 200
    validate("Draft", draft)
    code, checked = command(api, "validate", expected_version=draft["version"], expected_content_sha256=draft["content_sha256"])
    assert code == 200
    validate("Draft", checked)
    code, activated = command(api, "activate", expected_version=checked["version"],
                              expected_content_sha256=checked["content_sha256"], expected_active_version="1")
    assert code == 200
    validate("Receipt", activated)
    validate("RuntimeConfiguration", runtime.read())
    code, disabled = command(api, "deactivate", expected_active_version="2")
    assert code == 200
    validate("Receipt", disabled)
    assert all(api.ACTION_ROLES[operation["action"]] == operation["role"] for operation in extension["x-websocket-operations"])
