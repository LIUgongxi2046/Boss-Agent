from concurrent.futures import ProcessPoolExecutor
import multiprocessing
import os
import time

import pytest

from agent_run_store import RunStore


def submit_input(path, run_id, request_key):
    return RunStore(path, allow_migration=False).add_input(run_id, 1, request_key, "模拟会议关注")


def start_and_exit(path, run_id):
    RunStore(path, allow_migration=False).acquire_queued_for_execution(run_id, 0, "technical-worker", 0.2)
    os._exit(21)


def read_page(store, run_id, cursor):
    with store.connect() as db:
        db.execute("BEGIN")
        return store.event_page_in_transaction(db, run_id, cursor)


def test_input_competition_and_event_pages_survive_reopen(tmp_path):
    path = tmp_path / "runs.sqlite"
    store = RunStore(path)
    run_id = store.create_run("technical-owner", "technical-space", "create", "digest")
    with ProcessPoolExecutor(max_workers=2) as pool:
        attempts = [pool.submit(submit_input, path, run_id, key) for key in ("input-a", "input-b")]
        errors = [item.exception() for item in attempts]
    assert sum(error is None for error in errors) == 1
    assert sum(isinstance(error, ValueError) for error in errors) == 1
    for revision in range(2, 106):
        store.add_input(run_id, revision, "input-" + str(revision), "模拟会议关注")
    first = read_page(store, run_id, 0)
    assert len(first["events"]) == 100 and first["has_more"] and first["next_seq"] == 100
    reopened = RunStore(path, allow_migration=False)
    second = read_page(reopened, run_id, first["next_seq"])
    combined = first["events"] + second["events"]
    assert [event["seq"] for event in combined] == list(range(1, 106))
    assert second["next_seq"] == 105 and not second["has_more"]
    assert read_page(reopened, run_id, 105) == {"events": [], "next_seq": 105, "has_more": False}
    current = reopened.read_run(run_id)
    receipt = reopened.cancel(run_id, current["revision"], request_key="cancel")
    assert reopened.cancel(run_id, current["revision"], request_key="cancel") == receipt
    assert read_page(RunStore(path, allow_migration=False), run_id, 105)["events"][0]["payload"]["to"] == "CANCELED"


def test_missing_event_is_rejected(tmp_path):
    store = RunStore(tmp_path / "runs.sqlite")
    run_id = store.create_run("technical-owner", "technical-space", "create", "digest")
    store.add_input(run_id, 1, "first", "模拟会议关注")
    store.add_input(run_id, 2, "second", "模拟会议关注")
    with store.connect() as db:
        db.execute("DELETE FROM agent_run_events WHERE run_id=? AND seq=1", (run_id,))
    with pytest.raises(ValueError, match="事件序号不可核查"):
        read_page(store, run_id, 0)


def test_expired_process_recovery_appears_in_event_page(tmp_path):
    path = tmp_path / "runs.sqlite"
    store = RunStore(path)
    run_id = store.create_run("technical-owner", "technical-space", "create", "digest")
    process = multiprocessing.get_context("spawn").Process(target=start_and_exit, args=(path, run_id))
    process.start()
    process.join(20)
    assert process.exitcode == 21
    first = read_page(store, run_id, 0)
    assert first["events"][0]["payload"]["to"] == "RUNNING"
    time.sleep(0.25)
    RunStore(path, allow_migration=False).interrupt_expired(run_id)
    page = read_page(RunStore(path, allow_migration=False), run_id, first["next_seq"])
    assert [event["payload"]["to"] for event in page["events"]] == ["INTERRUPTED"]
