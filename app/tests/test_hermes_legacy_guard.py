import threading
import select
import subprocess
import sys
import time
from datetime import timedelta
from pathlib import Path

import pytest
from aiohttp import web

from agent_run_store import RunStore, utc_now
from hermes_legacy_routes import guard_legacy_adoption_in_transaction
from test_hermes_legacy_routes import recorded_link


def active_link(tmp_path):
    store, sessions, scope, inventory, proof, run_id = recorded_link(tmp_path)
    runs = RunStore(store.path, allow_migration=False)
    lease = runs.acquire_lease(run_id, 0, "worker", 60)
    runs.transition(run_id, lease["revision"], "RUNNING", "worker", lease["epoch"])
    return store, sessions, scope, inventory, proof, run_id, runs, lease["epoch"]


def test_session_save_waits_until_guard_finishes_and_retry_detects_change(tmp_path):
    store, sessions, scope, inventory, proof, run_id, runs, epoch = active_link(tmp_path)
    session = sessions.get_or_create(proof.session_id)
    session.add_message("user", "继续核查会议资料")
    entered = threading.Event()
    finished = threading.Event()

    def save_session():
        entered.set()
        sessions.save(session, fsync=True)
        finished.set()

    with runs.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        with guard_legacy_adoption_in_transaction(db, inventory, scope, runs, run_id, "worker", epoch) as (link, snapshot):
            assert link["session_id"] == proof.session_id
            assert len(snapshot.messages) == 1
            thread = threading.Thread(target=save_session)
            thread.start()
            assert entered.wait(5) and not finished.wait(0.2)
    thread.join(10)
    assert not thread.is_alive() and finished.is_set()
    with runs.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        with pytest.raises(ValueError, match="当前范围已经变化"):
            with guard_legacy_adoption_in_transaction(db, inventory, scope, runs, run_id, "worker", epoch):
                pass


def test_session_delete_waits_and_retry_rejects_missing_session(tmp_path):
    _, sessions, scope, inventory, proof, run_id, runs, epoch = active_link(tmp_path)
    entered = threading.Event()
    finished = threading.Event()

    def delete_session():
        entered.set()
        assert sessions.delete_session(proof.session_id)
        finished.set()

    with runs.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        with guard_legacy_adoption_in_transaction(db, inventory, scope, runs, run_id, "worker", epoch) as (_, snapshot):
            assert snapshot.key == proof.session_id
            thread = threading.Thread(target=delete_session)
            thread.start()
            assert entered.wait(5) and not finished.wait(0.2)
    thread.join(10)
    assert not thread.is_alive() and finished.is_set()
    with runs.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        with pytest.raises(web.HTTPNotFound):
            with guard_legacy_adoption_in_transaction(db, inventory, scope, runs, run_id, "worker", epoch):
                pass


def test_guard_rejects_invalid_lease_without_reading_history(tmp_path):
    _, _, scope, inventory, _, run_id, runs, epoch = active_link(tmp_path)
    with runs.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        with pytest.raises(ValueError, match="租约无效"):
            with guard_legacy_adoption_in_transaction(db, inventory, scope, runs, run_id, "other-worker", epoch):
                pass


def test_guard_rechecks_lease_after_read(tmp_path):
    _, _, scope, inventory, _, run_id, runs, epoch = active_link(tmp_path)
    with runs.connect() as db:
        db.execute("UPDATE agent_runs SET lease_expires_at=? WHERE run_id=?", ((utc_now() + timedelta(seconds=0.8)).isoformat(), run_id))
    with runs.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        with pytest.raises(ValueError, match="租约无效"):
            with guard_legacy_adoption_in_transaction(db, inventory, scope, runs, run_id, "worker", epoch):
                time.sleep(0.9)


def test_guard_detects_external_file_deletion_at_exit(tmp_path):
    _, sessions, scope, inventory, proof, run_id, runs, epoch = active_link(tmp_path)
    with runs.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        with pytest.raises(web.HTTPNotFound):
            with guard_legacy_adoption_in_transaction(db, inventory, scope, runs, run_id, "worker", epoch):
                sessions._get_session_path(proof.session_id).unlink()


def test_memory_change_waits_until_guard_finishes(tmp_path):
    store, _, scope, inventory, proof, run_id, runs, epoch = active_link(tmp_path)
    entered = threading.Event()
    finished = threading.Event()

    def delete_memory():
        entered.set()
        with store.connect() as db:
            db.execute("DELETE FROM objects WHERE namespace=? AND kind='memory' AND id='current'", ("ui-check",))
        finished.set()

    with runs.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        with guard_legacy_adoption_in_transaction(db, inventory, scope, runs, run_id, "worker", epoch) as (_, snapshot):
            assert snapshot.key == proof.session_id
            thread = threading.Thread(target=delete_memory)
            thread.start()
            assert entered.wait(5) and not finished.wait(0.2)
    thread.join(10)
    assert not thread.is_alive() and finished.is_set()
    with runs.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        with pytest.raises(ValueError, match="当前范围已经变化"):
            with guard_legacy_adoption_in_transaction(db, inventory, scope, runs, run_id, "worker", epoch):
                pass


def test_cross_process_save_waits_and_retry_detects_change(tmp_path):
    _, _, scope, inventory, _, run_id, runs, epoch = active_link(tmp_path)
    script = Path(__file__).with_name("hermes_legacy_session_writer.py")
    process = subprocess.Popen([sys.executable, str(script), str(tmp_path)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1)
    try:
        assert process.stdout.readline().strip() == "ready"
        with runs.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            with guard_legacy_adoption_in_transaction(db, inventory, scope, runs, run_id, "worker", epoch) as (_, snapshot):
                assert len(snapshot.messages) == 1
                process.stdin.write("save\n")
                process.stdin.flush()
                assert process.stdout.readline().strip() == "writing"
                assert not select.select([process.stdout], [], [], 0.2)[0]
        assert process.stdout.readline().strip() == "saved"
        assert process.wait(timeout=10) == 0
        with runs.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            with pytest.raises(ValueError, match="当前范围已经变化"):
                with guard_legacy_adoption_in_transaction(db, inventory, scope, runs, run_id, "worker", epoch):
                    pass
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=10)
        process.stdin.close()
        process.stdout.close()
