import asyncio
import json
import sys
from pathlib import Path
from uuid import uuid4

from nanobot.agent.tools.context import RequestContext

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "validation"))

from boss_admin_config import memory_technical_status
from boss_command_api import BossCommandAPI
from controls import ControlStore


def confirm(api, text, version):
    status, result = api.execute("BOSS", "boss.memory.confirm", {
        "client_request_id": str(uuid4()), "expected_version": version, "text": text,
    })
    assert status == 200
    return result


def revoke(api, confirmation):
    status, result = api.execute("BOSS", "boss.authorization.revoke", {
        "client_request_id": str(uuid4()), "authorization_id": confirmation["authorization_id"],
        "expected_version": "1", "reason": "本人撤销本次记忆确认",
    })
    assert status == 200
    return result


def test_revoked_confirmation_is_excluded_from_technical_eligibility(tmp_path):
    store = ControlStore(tmp_path / "memory-eligibility.sqlite")
    store.initialize("ui-check")
    with store.connect() as db:
        original = store.get(db, "ui-check", "memory", "current")["text"]
    api = BossCommandAPI(store)
    current = confirm(api, original, "1")
    assert memory_technical_status(store, "MAINTAINER")["future_context_eligible"] is True
    revoke(api, current)
    status = memory_technical_status(ControlStore(store.path), "MAINTAINER")
    assert status["memory"]["confirmation_state"] == "CONFIRMED"
    assert status["future_context_eligible"] is False
    assert original not in json.dumps(status, ensure_ascii=False)


def test_actual_owner_memory_context_stops_revoked_confirmation_and_accepts_new_confirmation(tmp_path):
    from boss_memory_runtime import OwnerMemoryContext

    store = ControlStore(tmp_path / "memory-runtime.sqlite")
    store.initialize("ui-check")
    with store.connect() as db:
        original = store.get(db, "ui-check", "memory", "current")["text"]
    api = BossCommandAPI(store)
    current = confirm(api, original, "1")
    def read():
        request = RequestContext(channel="cli", chat_id=str(uuid4()), session_key=str(uuid4()), sender_id="boss-1")
        block = asyncio.run(OwnerMemoryContext(ControlStore(store.path), "ui-check")(request))
        return json.loads(block.content), request.attributes["boss_memory_reference"]
    before, reference = read()
    assert before["memory"]["text"] == original and reference["eligible"] is True
    revoke(api, current)
    after, reference = read()
    assert after["memory"] is None and reference["eligible"] is False
    newer = confirm(api, original, current["version"])
    renewed, reference = read()
    assert renewed["memory"]["version"] == newer["version"] and reference["eligible"] is True
    assert renewed["memory"]["text"] == original
