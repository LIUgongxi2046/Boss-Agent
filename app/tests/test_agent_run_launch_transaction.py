import multiprocessing
import os

import pytest

from agent_run_launch_transaction import RunLaunchTransaction
from agent_run_store import RunStore


def cancel_in_process(path, run_id, started, done):
    store = RunStore(path, allow_migration=False)
    started.set()
    store.cancel(run_id, 1)
    done.set()


def interrupted_transaction(path, run_id, ready):
    store = RunStore(path, allow_migration=False)
    with RunLaunchTransaction(store).hold(run_id, "technical-worker", 1) as db:
        db.execute("UPDATE agent_runs SET goal='temporary change' WHERE run_id=?", (run_id,))
        ready.set()
        os._exit(27)


def create_run(path):
    store = RunStore(path)
    run_id = store.create_run("technical-owner", "technical-space", "request", "digest")
    lease = store.acquire_queued_for_execution(run_id, 0, "technical-worker", 60)
    return store, run_id, lease


def test_cancellation_waits_for_launch_transaction(tmp_path):
    store, run_id, lease = create_run(tmp_path / "runs.sqlite")
    context = multiprocessing.get_context("spawn")
    started, done = context.Event(), context.Event()
    with RunLaunchTransaction(store).hold(run_id, "technical-worker", lease["epoch"]) as db:
        process = context.Process(target=cancel_in_process, args=(store.path, run_id, started, done))
        process.start()
        assert started.wait(10)
        assert not done.wait(0.4)
        assert db.execute("SELECT status,cancel_requested_at FROM agent_runs WHERE run_id=?", (run_id,)).fetchone() == ("RUNNING", None)
    process.join(15)
    assert process.exitcode == 0 and done.is_set()
    assert store.read_run(run_id)["status"] == "CANCEL_REQUESTED"
    with pytest.raises(ValueError):
        with RunLaunchTransaction(store).hold(run_id, "technical-worker", lease["epoch"]):
            pass


def test_process_exit_aborts_transaction_and_releases_database(tmp_path):
    store, run_id, lease = create_run(tmp_path / "runs.sqlite")
    context = multiprocessing.get_context("spawn")
    ready = context.Event()
    process = context.Process(target=interrupted_transaction, args=(store.path, run_id, ready))
    process.start()
    assert ready.wait(10)
    process.join(15)
    assert process.exitcode == 27
    with RunLaunchTransaction(store).hold(run_id, "technical-worker", lease["epoch"]) as db:
        assert db.execute("SELECT goal FROM agent_runs WHERE run_id=?", (run_id,)).fetchone() == (None,)
