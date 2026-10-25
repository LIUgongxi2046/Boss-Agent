import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "validation"))

from boss_command_api import BossCommandAPI
from boss_page_api import BossPageAPI
from business import initial_materials
from controls import ControlStore


def test_public_memory_revocation_preserves_history_and_stops_future_adoption(tmp_path):
    store = ControlStore(tmp_path / "memory-public.sqlite")
    store.initialize("ui-check")
    commands = BossCommandAPI(store)
    text = initial_materials()["memory"]["text"]
    status, saved = commands.execute("BOSS", "boss.memory.confirm", {
        "client_request_id": "public-memory-confirm", "expected_version": "1", "text": text,
    })
    assert status == 200
    with store.connect() as db:
        current = store.get(db, "ui-check", "memory", "current")
        assert current["authorization_id"] == saved["authorization_id"]
    reads = BossPageAPI(store)
    status, before = reads.serve("BOSS", "/api/boss/ui/workspace/memory")
    assert status == 200 and before["effective"] is True
    status, revoked = commands.execute("BOSS", "boss.authorization.revoke", {
        "client_request_id": "public-memory-revoke", "authorization_id": saved["authorization_id"],
        "expected_version": "1", "reason": text,
    })
    assert status == 200 and revoked["revoked"] is True
    reopened = ControlStore(store.path)
    status, after = BossPageAPI(reopened).serve("BOSS", "/api/boss/ui/workspace/memory")
    assert status == 200 and after["effective"] is False
    assert after["memory"]["text"] == text
    assert after["memory"]["confirmation_state"] == "CONFIRMED"
    assert after["future_turn_policy"] == "CURRENT_NON_REVOKED_CONFIRMATION_ONLY"
    assert reopened.context("ui-check")["memory"] is None
    assert reads.serve("MAINTAINER", "/api/boss/ui/workspace/memory")[0] == 403


def test_each_new_public_memory_confirmation_links_its_own_authorization(tmp_path):
    store = ControlStore(tmp_path / "memory-confirmations.sqlite")
    store.initialize("ui-check")
    commands = BossCommandAPI(store)
    version = "1"
    identifiers = []
    for index in range(2):
        status, saved = commands.execute("BOSS", "boss.memory.confirm", {
            "client_request_id": "public-memory-confirm-" + str(index), "expected_version": version,
            "text": initial_materials()["memory"]["text"],
        })
        assert status == 200
        version = saved["version"]
        identifiers.append(saved["authorization_id"])
        assert store.context("ui-check")["memory"]["authorization_id"] == identifiers[-1]
    assert len(set(identifiers)) == 2
