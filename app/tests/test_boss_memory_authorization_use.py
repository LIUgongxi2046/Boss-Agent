import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "validation"))

from boss_command_api import BossCommandAPI
from business import initial_materials
from controls import ControlStore


def confirmed(api, version, key):
    status, result = api.execute("BOSS", "boss.memory.confirm", {"client_request_id": key, "expected_version": version,
        "text": initial_materials()["memory"]["text"]})
    assert status == 200
    return result


def revoked(api, identifier, key):
    status, result = api.execute("BOSS", "boss.authorization.revoke", {"client_request_id": key, "authorization_id": identifier,
        "expected_version": "1", "reason": initial_materials()["memory"]["text"]})
    assert status == 200
    return result


def test_revoked_memory_confirmation_stops_new_context_after_database_reopen(tmp_path):
    store = ControlStore(tmp_path / "memory-use.sqlite")
    store.initialize("ui-check")
    api = BossCommandAPI(store)
    current = confirmed(api, "1", "memory-use-confirm")
    assert store.context("ui-check")["memory"]["text"] == initial_materials()["memory"]["text"]
    revoked(api, current["authorization_id"], "memory-use-revoke")
    reopened = ControlStore(store.path)
    assert reopened.context("ui-check")["memory"] is None
    with reopened.connect() as db:
        historical = reopened.get(db, "ui-check", "memory", "current")
        assert historical["confirmation_state"] == "CONFIRMED"
        assert historical["version"] == current["version"]
        assert historical["text"] == initial_materials()["memory"]["text"]


def test_revoking_previous_confirmation_does_not_block_new_owner_confirmation(tmp_path):
    store = ControlStore(tmp_path / "memory-newer-use.sqlite")
    store.initialize("ui-check")
    api = BossCommandAPI(store)
    previous = confirmed(api, "1", "memory-previous-confirm")
    newer = confirmed(api, previous["version"], "memory-newer-confirm")
    revoked(api, previous["authorization_id"], "memory-previous-revoke")
    assert store.context("ui-check")["memory"]["version"] == newer["version"]
    revoked(api, newer["authorization_id"], "memory-newer-revoke")
    assert ControlStore(store.path).context("ui-check")["memory"] is None


def test_new_owner_confirmation_after_revocation_is_a_distinct_version(tmp_path):
    store = ControlStore(tmp_path / "memory-reconfirmed.sqlite")
    store.initialize("ui-check")
    api = BossCommandAPI(store)
    previous = confirmed(api, "1", "memory-original-confirm")
    revoked(api, previous["authorization_id"], "memory-original-revoke")
    assert store.context("ui-check")["memory"] is None
    newer = confirmed(api, previous["version"], "memory-explicit-reconfirm")
    assert newer["authorization_id"] != previous["authorization_id"]
    assert store.context("ui-check")["memory"]["version"] == newer["version"]
