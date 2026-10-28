import sys
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator
from nanobot.session.manager import SessionManager

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "validation"))

from boss_conversation_attachments import ConversationAttachments
from fc03_agent.formal import FormalMorningTool, FORMAL_TOOLS
from product_conversation import ProductConversation
from product_morning import ProductMorning
from product_review_runtime import configure_review_runtime
from runtime_sop_read_tools import BossWorkspaceReadTool, SOP_WORKSPACE_PROJECTIONS
from sop_write_tools.fc01 import Fc01Tool, TOOLS
from product_fc01 import ProductFc01
from test_product_runtime_configuration import product


def test_review_initialization_activates_complete_catalog_and_preserves_changes(product, tmp_path):
    runtime, api, pages = product
    morning = ProductMorning(runtime.store)
    fc01 = ProductFc01(runtime.store)
    sessions = SessionManager(tmp_path / "workspace", sessions_root=tmp_path / "sessions")
    conversation = ProductConversation(runtime.store, runtime.registry, runtime.snapshot,
        ConversationAttachments(sessions, tmp_path / "media"))
    for name in TOOLS - runtime.available.keys():
        runtime.available[name] = Fc01Tool(runtime.store, fc01.context_provider, name)
    for name in FORMAL_TOOLS:
        runtime.available[name] = FormalMorningTool(runtime.store, morning.context_provider, name)
    runtime.available["conversationRead"] = next(tool for tool in conversation.delegates if tool.name == "conversationRead")
    for tool in conversation.business_tools():
        runtime.available[tool.name] = tool
    assert len(runtime.available) == 24
    configure_review_runtime(runtime)
    state = runtime.read()
    assert state["admission_ready"]
    assert set(state["current"]["tool_scope"]) == set(runtime.available)
    assert isinstance(runtime.registry.get("bossWorkspaceRead"), BossWorkspaceReadTool)
    assert runtime.registry.get("bossWorkspaceRead").allowed_projections == SOP_WORKSPACE_PROJECTIONS
    schema = yaml.safe_load((ROOT / "specs/product-runtime.openapi.yaml").read_text())
    Draft202012Validator({**schema, "$ref": "#/components/schemas/Values"}).validate(state["draft"]["values"])
    with runtime.store.connect() as db:
        before = db.execute("SELECT kind,id,body FROM objects ORDER BY kind,id").fetchall()
    configure_review_runtime(runtime)
    with runtime.store.connect() as db:
        assert db.execute("SELECT kind,id,body FROM objects ORDER BY kind,id").fetchall() == before
    assert not runtime.provider.requests
    assert state["current"]["version"] == "2"
