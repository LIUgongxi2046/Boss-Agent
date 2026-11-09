import asyncio
import os
import sys
from pathlib import Path

import pytest
from aiohttp import web
from nanobot.agent.loop import AgentLoop
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.config.loader import save_config
from nanobot.config.schema import Config
from nanobot.session.manager import SessionManager

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "validation"))

from boss_page_api import BossPageAPI
from business import OPERATIONS
from controls import ControlStore
from model_probe import BusinessTool
from product_bi import FeatureProvider
from product_fc01 import ProductFc01
from product_read_tools import product_read_tools
from product_runtime import ProductRuntime


def test_simulated_runtime_without_external_credential(tmp_path):
    assert "DEEPSEEK_API_KEY" not in os.environ
    config = Config()
    config.agents.defaults.workspace = str(tmp_path / "workspace")
    config.agents.defaults.provider = "deepseek"
    config.agents.defaults.model = "deepseek-flash"
    config.agents.defaults.dream.enabled = False
    config.providers.deepseek.api_key = "${DEEPSEEK_API_KEY}"
    config.providers.deepseek.api_base = "https://api.deepseek.com"
    filename = tmp_path / "config.json"
    save_config(config, filename)
    store = ControlStore(tmp_path / "business.sqlite")
    store.initialize("ui-check")
    registry = ToolRegistry()
    envelope = {"request_id": "configuration-check", "owner_id": "boss-1", "execution_namespace": "ui-check",
                "dataset_id": "selection", "dataset_version": "1", "session_id": "configuration-check"}
    available = [BusinessTool(name, store, envelope, {}, []) for name in OPERATIONS]
    pages = BossPageAPI(store)
    available.extend(product_read_tools(store, pages))
    fc01 = ProductFc01(store)
    provider = FeatureProvider(fc01, None)
    config.providers.deepseek.api_key = ""
    sessions = SessionManager(config.workspace_path, sessions_root=tmp_path / "sessions")
    loop = AgentLoop.from_config(config, provider=provider, tool_registry=registry, session_manager=sessions)
    runtime = ProductRuntime(store, filename, loop, registry, available, provider, workspace_api=pages)
    assert runtime.provider.external_provider is None
    assert runtime._native().providers.deepseek.api_key == ""
    response = asyncio.run(fc01.events([], []))
    assert response.content.startswith("SIMULATED：")
    with pytest.raises(web.HTTPServiceUnavailable):
        runtime._native({"values": {"credential_reference": "DEEPSEEK_API_KEY"}})
