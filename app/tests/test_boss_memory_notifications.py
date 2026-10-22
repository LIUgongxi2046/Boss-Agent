"""Real SQLite business mutations for FR-02/FR-13/FR-25.

No live model or personal secrets. All data are the project's fixed simulated
selection dataset. Every action is role-bound, explicitly confirmed, atomic,
versioned and idempotent.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "validation"))
from boss_command_api import BossCommandAPI  # noqa: E402
from boss_page_api import BossPageAPI  # noqa: E402
from controls import ControlStore  # noqa: E402

PRIVATE = "合成的仅老板本人可见的长期要求"


@pytest.fixture
def services(tmp_path):
    store = ControlStore(tmp_path / "real.sqlite")
    store.initialize("ui-check")
    return BossCommandAPI(store), BossPageAPI(store)


def call(api, role, action, key, **params):
    return api.execute(role, action, {"client_request_id": key, **params})


def test_confirm_memory_advances_version_once_and_enters_runtime_context(services):
    api, projection = services
    result = call(api, "BOSS", "boss.memory.confirm", "owner-memory-001",
                  expected_version="1", text=PRIVATE)
    assert result[0] == 200
    assert result[1]["version"] == "2"
    assert result[1]["confirmation_state"] == "CONFIRMED"
    assert call(api, "BOSS", "boss.memory.confirm", "owner-memory-001",
                expected_version="1", text=PRIVATE) == result
    assert call(api, "MAINTAINER", "boss.memory.confirm", "role-denied-001",
                expected_version="2", text=PRIVATE)[0] == 403
    status, data = projection.serve("BOSS", "/api/boss/ui/workspace/memory")
    assert status == 200 and data["memory"]["text"] == PRIVATE
    assert api.store.context("ui-check")["memory"]["text"] == PRIVATE
    with api.store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind='authorization'").fetchone()[0] == 1


def test_memory_text_never_enters_audit_or_authorization_payload(services):
    api, _ = services
    call(api, "BOSS", "boss.memory.confirm", "private-text-001",
         expected_version="1", text=PRIVATE)
    with api.store.connect() as db:
        for kind in ("authorization",):
            rows = db.execute("SELECT body FROM objects WHERE kind=?", (kind,)).fetchall()
            assert all(PRIVATE not in row[0] for row in rows)
        audit = db.execute("SELECT input,output FROM audit").fetchall()
        assert all(PRIVATE not in str(item) for item in audit)
        receipt = db.execute("SELECT result FROM idempotency").fetchall()
        assert all(PRIVATE not in item[0] for item in receipt)


def test_memory_delete_prevents_future_adoption_without_claiming_disk_erasure(services):
    api, projection = services
    call(api, "BOSS", "boss.memory.confirm", "memory-confirm-002",
         expected_version="1", text=PRIVATE)
    status, data = call(api, "BOSS", "boss.memory.delete", "memory-delete-002",
                        expected_version="2")
    assert status == 200
    assert data["confirmation_state"] == "DELETED"
    assert data["physical_secure_erasure_verified"] is False
    assert api.store.context("ui-check")["memory"] is None
    _, read = projection.serve("BOSS", "/api/boss/ui/workspace/memory")
    assert read["memory"]["text"] == ""
    assert not read["effective"]
    assert call(api, "BOSS", "boss.memory.delete", "memory-delete-002",
                expected_version="2") == (status, data)


def test_old_memory_version_and_key_conflicts_do_not_mutate(services):
    api, projection = services
    assert call(api, "BOSS", "boss.memory.confirm", "memory-old-version",
                expected_version="0", text=PRIVATE)[0] == 409
    assert call(api, "BOSS", "boss.memory.delete", "memory-old-delete",
                expected_version="0")[0] == 409
    good = call(api, "BOSS", "boss.memory.confirm", "memory-digest-key",
                expected_version="1", text=PRIVATE)
    assert good[0] == 200
    assert call(api, "BOSS", "boss.memory.confirm", "memory-digest-key",
                expected_version="1", text="changed text")[0] == 409
    _, read = projection.serve("BOSS", "/api/boss/ui/workspace/memory")
    assert read["memory"]["version"] == "2"


def test_simulation_event_is_seeded_from_current_dataset_not_fabricated(services):
    api, projection = services
    assert call(api, "BOSS", "boss.simulation.event.seed", "event-boss-denied",
                event_id="event-1")[0] == 403
    assert call(api, "MAINTAINER", "boss.simulation.event.seed", "event-unknown-001",
                event_id="other-event")[0] == 400
    status, result = call(api, "MAINTAINER", "boss.simulation.event.seed", "event-seed-001",
                          event_id="event-1")
    assert status == 200
    assert result["event_id"] == "event-1" and result["rules_installed"]
    assert call(api, "MAINTAINER", "boss.simulation.event.seed", "event-seed-001",
                event_id="event-1") == (status, result)
    assert call(api, "MAINTAINER", "boss.simulation.event.seed", "event-seed-002",
                event_id="event-1")[0] == 409
    status, notifications = projection.serve("BOSS", "/api/boss/ui/workspace/notifications")
    assert status == 200 and len(notifications["events"]) == 1
    assert notifications["events"][0]["event_id"] == "event-1"
    assert notifications["notifications"] == []  # Not delivered until Cron checks.


def test_time_advancement_is_monotonic_versioned_and_no_delivery_claim(services):
    api, projection = services
    call(api, "MAINTAINER", "boss.simulation.event.seed", "seed-before-clock",
         event_id="event-1")
    assert call(api, "BOSS", "boss.simulation.clock.advance", "clock-boss-denied",
                at="2026-10-23T09:00:00+08:00")[0] == 403
    assert call(api, "MAINTAINER", "boss.simulation.clock.advance", "clock-backward",
                at="2026-10-20T09:00:00+08:00")[0] == 400
    status, result = call(api, "MAINTAINER", "boss.simulation.clock.advance",
                          "clock-after-seed", at="2026-10-25T09:00:00+08:00")
    assert status == 200 and result["version"] == "2"
    assert result["notification_delivery_claimed"] is False
    assert api.store.dispatch_due("ui-check")[0]["state"] in ("DELIVERED", "SUPPRESSED")
    _, notifications = projection.serve("BOSS", "/api/boss/ui/workspace/notifications")
    assert notifications["events"][0]["event_id"] == "event-1"


def test_owner_snooze_uses_sim_clock_and_cas(services):
    api, projection = services
    call(api, "MAINTAINER", "boss.simulation.event.seed", "seed-for-snooze",
         event_id="event-1")
    result = call(api, "BOSS", "boss.reminder.snooze", "snooze-owner-001",
                  event_id="event-1", event_version="1",
                  reminder_version="0", until="2026-10-23T10:00:00+08:00")
    assert result[0] == 200
    assert result[1]["state"] == "SNOOZED"
    assert result[1]["version"] == "1"
    assert call(api, "BOSS", "boss.reminder.snooze", "snooze-owner-001",
                event_id="event-1", event_version="1",
                reminder_version="0", until="2026-10-23T10:00:00+08:00") == result
    assert call(api, "BOSS", "boss.reminder.close", "old-reminder-cas",
                event_id="event-1", event_version="1",
                reminder_version="0")[0] == 409
    _, payload = projection.serve("BOSS", "/api/boss/ui/workspace/notifications")
    assert payload["reminders"][0]["state"] == "SNOOZED"


def test_close_cannot_be_reopened_by_ack_and_maintainer_cannot_close(services):
    api, _ = services
    call(api, "MAINTAINER", "boss.simulation.event.seed", "seed-for-close",
         event_id="event-1")
    assert call(api, "MAINTAINER", "boss.reminder.close", "maintainer-close",
                event_id="event-1", event_version="1", reminder_version="0")[0] == 403
    status, result = call(api, "BOSS", "boss.reminder.close", "owner-close-001",
                          event_id="event-1", event_version="1", reminder_version="0")
    assert status == 200 and result["state"] == "CLOSED"
    assert call(api, "BOSS", "boss.reminder.ack", "owner-reopen",
                event_id="event-1", event_version="1", reminder_version="1")[0] == 409


def test_invalid_reminder_time_or_event_rejected_without_auth(services):
    api, _ = services
    call(api, "MAINTAINER", "boss.simulation.event.seed", "seed-for-invalid",
         event_id="event-1")
    assert call(api, "BOSS", "boss.reminder.snooze", "invalid-quiet-until",
                event_id="event-1", event_version="1", reminder_version="0",
                until="2026-10-20T09:00:00+08:00")[0] == 400
    assert call(api, "BOSS", "boss.reminder.ack", "invalid-event",
                event_id="missing", event_version="1", reminder_version="0")[0] == 404
    with api.store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM objects WHERE kind='reminder'").fetchone()[0] == 0
