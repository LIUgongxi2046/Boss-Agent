import asyncio
import multiprocessing
import os
import sqlite3

import pytest
from nanobot.cron.service import CronService
from nanobot.cron.types import CronJob, CronPayload, CronSchedule

from agent_run_store import RunStore
from agent_schedule_occurrence_gate import AgentScheduleOccurrenceGate
from controls import ControlStore


INSTANT = "2026-10-30T01:00:00+00:00"


def create_store(path):
    store = ControlStore(path)
    store.initialize("ui-check")
    RunStore(store.path)
    gate = AgentScheduleOccurrenceGate(store, allow_migration=True)
    with store.connect() as db:
        initial = store.get(db, "ui-check", "initial", "snapshot")
        store.put(db, "ui-check", "owner_plan", "technical-plan", {"plan_id": "technical-plan", "version": "1", "owner_id": initial["owner_id"], "source_type": "SIMULATED", "state": "PAUSED"})
        db.execute("CREATE TABLE technical_effects (occurrence_id TEXT PRIMARY KEY)")
    return store, gate


def compete(path, start, output):
    store = ControlStore(path)
    gate = AgentScheduleOccurrenceGate(store)
    start.wait()
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        result = gate.claim_in_transaction(db, "technical-plan", "1", INSTANT)
        if result["claimed"]:
            db.execute("INSERT INTO technical_effects VALUES (?)", (result["occurrence_id"],))
    output.put(result)


def interrupted(path, commit):
    store = ControlStore(path)
    gate = AgentScheduleOccurrenceGate(store)
    db = store.connect()
    db.execute("BEGIN IMMEDIATE")
    result = gate.claim_in_transaction(db, "technical-plan", "1", INSTANT)
    db.execute("INSERT INTO technical_effects VALUES (?)", (result["occurrence_id"],))
    if commit:
        db.commit()
    os._exit(17)


def test_process_competition_and_immutable_record(tmp_path):
    store, gate = create_store(tmp_path / "business.sqlite")
    context = multiprocessing.get_context("spawn")
    start, output = context.Event(), context.Queue()
    processes = [context.Process(target=compete, args=(store.path, start, output)) for _ in range(2)]
    for process in processes:
        process.start()
    start.set()
    for process in processes:
        process.join(60)
        assert process.exitcode == 0
    results = [output.get(timeout=5) for _ in processes]
    assert sorted(result["claimed"] for result in results) == [False, True]
    assert results[0]["occurrence_id"] == results[1]["occurrence_id"]
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        same = gate.claim_in_transaction(db, "technical-plan", "1", "2026-10-30T09:00:00+08:00")
        assert not same["claimed"]
        assert db.execute("SELECT count(*) FROM technical_effects").fetchone() == (1,)
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("DELETE FROM agent_schedule_occurrence_gate")


@pytest.mark.parametrize("commit", [False, True])
def test_process_interruption_recovery(tmp_path, commit):
    store, gate = create_store(tmp_path / "business.sqlite")
    process = multiprocessing.get_context("spawn").Process(target=interrupted, args=(store.path, commit))
    process.start()
    process.join(60)
    assert process.exitcode == 17
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        result = gate.claim_in_transaction(db, "technical-plan", "1", INSTANT)
        assert result["claimed"] is not commit
        assert db.execute("SELECT count(*) FROM technical_effects").fetchone() == (int(commit),)
        if result["claimed"]:
            db.execute("INSERT INTO technical_effects VALUES (?)", (result["occurrence_id"],))
    with store.connect() as db:
        assert db.execute("SELECT count(*) FROM technical_effects").fetchone() == (1,)


def test_real_cron_uses_same_transactional_gate(tmp_path):
    store, gate = create_store(tmp_path / "business.sqlite")

    async def exercise():
        async def on_job(job):
            with store.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                result = gate.claim_in_transaction(db, "technical-plan", "1", INSTANT)
                if result["claimed"]:
                    db.execute("INSERT INTO technical_effects VALUES (?)", (result["occurrence_id"],))

        cron = CronService(tmp_path / "cron" / "jobs.json", on_job=on_job)
        cron.register_system_job(CronJob(id="technical", name="technical", schedule=CronSchedule(kind="every", every_ms=60000), payload=CronPayload(kind="system_event", message="technical")))
        assert await cron.run_job("technical", force=True)
        assert await cron.run_job("technical", force=True)

    asyncio.run(exercise())
    with store.connect() as db:
        assert db.execute("SELECT count(*) FROM technical_effects").fetchone() == (1,)


def test_wrong_version_and_database_are_rejected(tmp_path):
    store, gate = create_store(tmp_path / "business.sqlite")
    other, _ = create_store(tmp_path / "other.sqlite")
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        with pytest.raises(ValueError, match="身份或版本"):
            gate.claim_in_transaction(db, "technical-plan", "2", INSTANT)
    with other.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        with pytest.raises(ValueError, match="同一数据库"):
            gate.claim_in_transaction(db, "technical-plan", "1", INSTANT)
