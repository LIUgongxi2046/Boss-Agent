import asyncio
import json
import sys
from pathlib import Path
from uuid import uuid4

import pytest
from nanobot.agent.tools.context import RequestContext
from nanobot.agent.tools.registry import ToolRegistry

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "validation"))

from boss_admin_config import memory_technical_status
from boss_command_api import BossCommandAPI
from boss_memory_runtime import OwnerMemoryContext
from boss_runtime_records import RuntimeRecorder
from business import checksum
from controls import ControlStore


def record_current_context(store):
    with store.connect() as db:
        configuration = store.get(db, "ui-check", "configuration", "current")
    recorder = RuntimeRecorder(store, "ui-check", ToolRegistry(), lambda: {
        "provider": configuration["provider"], "model_id": configuration["model_id"],
        "api_type": configuration["api_type"], "max_tool_rounds": configuration["max_tool_rounds"],
        "max_output_tokens": 700, "timeout": configuration["timeout"], "config_sha256": checksum(configuration),
    })
    request = RequestContext(channel="cli", chat_id=str(uuid4()), session_key=str(uuid4()), sender_id="boss-1")
    asyncio.run(OwnerMemoryContext(store)(request))
    asyncio.run(recorder.context(request))


def test_technical_scope_and_unknown_observation_are_read_only(tmp_path):
    store = ControlStore(tmp_path / "memory-scope.sqlite")
    store.initialize("ui-check")
    with store.connect() as db:
        initial = store.get(db, "ui-check", "initial", "snapshot")
        before = db.execute("SELECT COUNT(*) FROM audit").fetchone()[0]
    result = memory_technical_status(store, "MAINTAINER")
    assert result["source_type"] == "RUNTIME_RECORD"
    assert result["owner_scope"] == {key: initial[key] for key in ("owner_id", "dataset_id", "dataset_version")}
    assert result["memory_source_type"] == initial["source_type"]
    assert result["confirmation_authority_checked"] is True
    assert result["next_context_memory_version"] == "1"
    assert result["latest_context_selection"] is None
    assert result["context_selection_count"] == 0
    assert result["model_adoption_verified"] is False
    assert initial["memory"]["text"] not in json.dumps(result, ensure_ascii=False)
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM audit").fetchone()[0] == before


def test_revoked_confirmation_and_actual_context_selection_remain_distinct(tmp_path):
    store = ControlStore(tmp_path / "memory-confirmation.sqlite")
    store.initialize("ui-check")
    api = BossCommandAPI(store)
    with store.connect() as db:
        original = store.get(db, "ui-check", "memory", "current")["text"]
    status, confirmed = api.execute("BOSS", "boss.memory.confirm", {
        "client_request_id": str(uuid4()), "expected_version": "1", "text": original,
    })
    assert status == 200
    record_current_context(store)
    before = memory_technical_status(store, "MAINTAINER")
    assert before["latest_context_selection"]["memory_version"] == "2"
    assert before["latest_context_selection"]["eligible"] is True
    assert before["latest_context_selection"]["run_status"] == "QUEUED"
    assert before["model_adoption_verified"] is False
    status, _ = api.execute("BOSS", "boss.authorization.revoke", {
        "client_request_id": str(uuid4()), "authorization_id": confirmed["authorization_id"],
        "expected_version": "1", "reason": "本人停止当前记忆采用",
    })
    assert status == 200
    revoked = memory_technical_status(ControlStore(store.path), "MAINTAINER")
    assert revoked["memory"]["confirmation_state"] == "CONFIRMED"
    assert revoked["future_context_eligible"] is False
    assert revoked["next_context_memory_version"] is None
    assert revoked["latest_context_selection"]["eligible"] is True
    record_current_context(store)
    excluded = memory_technical_status(store, "MAINTAINER")
    assert excluded["context_selection_count"] == 2
    assert excluded["latest_context_selection"]["eligible"] is False
    assert excluded["latest_context_selection"]["matches_current_memory_version"] is True


def test_deleted_memory_current_content_and_historical_scope_are_separate(tmp_path):
    store = ControlStore(tmp_path / "memory-delete.sqlite")
    store.initialize("ui-check")
    record_current_context(store)
    status, receipt = BossCommandAPI(store).execute("BOSS", "boss.memory.delete", {
        "client_request_id": str(uuid4()), "expected_version": "1",
    })
    assert status == 200
    reopened = ControlStore(store.path)
    result = memory_technical_status(reopened, "MAINTAINER")
    assert result["memory"]["version"] == receipt["version"] == "2"
    assert result["next_context_memory_version"] is None
    assert result["latest_context_selection"]["memory_version"] == "1"
    assert result["latest_context_selection"]["matches_current_memory_version"] is False
    assert result["deletion_scopes"]["current_memory_content"] == "CLEARED"
    assert result["deletion_scopes"]["initial_approved_source"] == "RETAINED"
    assert result["deletion_scopes"]["loaded_sessions"] == "NOT_VERIFIED"
    assert result["deletion_scopes"]["backups"] == "NOT_VERIFIED"
    assert result["deletion_scopes"]["physical_erasure"] == "NOT_VERIFIED"
    assert result["derived_memory_index"] == "NOT_USED"
    assert result["physical_secure_erasure_verified"] is False
    assert result["owner_content_mutation_allowed"] is False


@pytest.mark.parametrize("action", ["boss.memory.confirm", "boss.memory.delete"])
def test_maintainer_cannot_change_memory_content(tmp_path, action):
    store = ControlStore(tmp_path / "memory-read-only.sqlite")
    store.initialize("ui-check")
    with store.connect() as db:
        current = store.get(db, "ui-check", "memory", "current")
    payload = {"client_request_id": str(uuid4()), "expected_version": current["version"]}
    if action == "boss.memory.confirm":
        payload["text"] = current["text"]
    status, _ = BossCommandAPI(store).execute("MAINTAINER", action, payload)
    assert status == 403
    with store.connect() as db:
        assert store.get(db, "ui-check", "memory", "current") == current
        assert db.execute("SELECT COUNT(*) FROM audit").fetchone()[0] == 0
