import json
import sys
from pathlib import Path

import pytest
from aiohttp import web

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "validation"))

from boss_command_api import BossCommandAPI
from controls import ControlStore


def test_memory_technical_projection_and_deletion_after_reopen(tmp_path):
    from boss_admin_config import memory_technical_status

    store = ControlStore(tmp_path / "admin.sqlite")
    store.initialize("ui-check")
    before = memory_technical_status(store, "MAINTAINER")
    assert before["memory"]["confirmation_state"] == "CONFIRMED"
    assert before["future_context_eligible"] is True
    assert before["model_adoption_verified"] is False
    with store.connect() as db:
        body = store.get(db, "ui-check", "memory", "current")["text"]
    assert body not in json.dumps(before, ensure_ascii=False)
    status, result = BossCommandAPI(store).execute("BOSS", "boss.memory.delete", {
        "client_request_id": "w2-delete-memory", "expected_version": "1",
    })
    assert status == 200
    reopened = ControlStore(store.path)
    after = memory_technical_status(reopened, "MAINTAINER")
    assert after["memory"]["version"] == result["version"]
    assert after["future_context_eligible"] is False
    assert after["deletion_propagation"] == "CURRENT_CONTEXT_CLEARED"
    assert reopened.context("ui-check")["memory"] is None
    assert after["physical_secure_erasure_verified"] is False
    assert body not in json.dumps(after, ensure_ascii=False)


@pytest.mark.parametrize("role", [None, "BOSS", "finance-1"])
def test_memory_technical_projection_rejects_other_roles(tmp_path, role):
    from boss_admin_config import memory_technical_status

    store = ControlStore(tmp_path / "roles.sqlite")
    store.initialize("ui-check")
    with pytest.raises(web.HTTPUnauthorized if role is None else web.HTTPForbidden):
        memory_technical_status(store, role)


def test_memory_technical_projection_rejects_inactive_space(tmp_path):
    from boss_admin_config import memory_technical_status

    store = ControlStore(tmp_path / "reset.sqlite")
    store.initialize("ui-check")
    store.control("ui-check", "reset", {"namespace": "next-execution"})
    with pytest.raises(web.HTTPConflict):
        memory_technical_status(store, "MAINTAINER")
