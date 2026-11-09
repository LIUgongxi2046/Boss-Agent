import asyncio
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from nanobot.cron.service import CronService

from agent_run_store import RunStore
from agent_schedule_inspection import AgentScheduleInspectionLease, inspect_legacy_cron
from controls import ControlStore


def test_real_cron_object_stop_is_only_local_observation(tmp_path):
    async def exercise():
        cron = CronService(tmp_path / "cron" / "jobs.json")
        assert inspect_legacy_cron(cron) == {"local_state": "STOPPED", "other_instances": "UNVERIFIED"}
        await cron.start()
        assert inspect_legacy_cron(cron)["local_state"] == "ACTIVE_OR_DRAINING"
        cron.stop()
        assert inspect_legacy_cron(cron) == {"local_state": "STOPPED", "other_instances": "UNVERIFIED"}

    asyncio.run(exercise())


def test_inspection_lease_contends_expires_and_fences_old_owner(tmp_path):
    store = ControlStore(tmp_path / "business.sqlite")
    store.initialize("ui-check")
    RunStore(store.path)
    leases = AgentScheduleInspectionLease(store, allow_migration=True)
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(leases.acquire, owner, 1) for owner in ("inspector-a", "inspector-b")]
    errors = [item.exception() for item in futures]
    assert sum(error is None for error in errors) == 1
    assert [str(error) for error in errors if error is not None] == ["调度核查租约已被占用"]
    winner = futures[errors.index(None)].result()
    assert winner["purpose"] == "INSPECTION_ONLY"
    assert leases.acquire(winner["owner"], 1) == winner
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        assert leases.require_current_in_transaction(db, winner["owner"], winner["epoch"]) == "INSPECTION_ONLY"
    time.sleep(1.1)
    reopened = AgentScheduleInspectionLease(ControlStore(store.path))
    new_owner = "inspector-b" if winner["owner"] == "inspector-a" else "inspector-a"
    newer = reopened.acquire(new_owner, 60)
    assert newer["epoch"] == winner["epoch"] + 1
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        with pytest.raises(ValueError, match="已经失效"):
            reopened.require_current_in_transaction(db, winner["owner"], winner["epoch"])
        assert reopened.require_current_in_transaction(db, new_owner, newer["epoch"]) == "INSPECTION_ONLY"
