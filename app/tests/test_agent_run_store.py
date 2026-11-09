import multiprocessing
import sqlite3
import time
import json
from concurrent.futures import ProcessPoolExecutor

import pytest

from agent_run_store import RunStore
from agent_run_broker import RunBroker
from agent_run_requirements import RunRequirements
from controls import ControlStore
from hermes_source_invalidation import begin_source_cleanup


def test_run_connection_closes_after_commit_and_rollback(tmp_path):
    store = RunStore(tmp_path / "runs.sqlite")
    with store.connect() as db:
        db.execute("CREATE TABLE connection_check (value INTEGER)")
        db.execute("INSERT INTO connection_check VALUES (1)")
    with pytest.raises(sqlite3.ProgrammingError):
        db.execute("SELECT 1")
    with pytest.raises(ValueError):
        with store.connect() as failed:
            failed.execute("INSERT INTO connection_check VALUES (2)")
            raise ValueError("transaction failure")
    with pytest.raises(sqlite3.ProgrammingError):
        failed.execute("SELECT 1")
    with store.connect() as check:
        assert check.execute("SELECT value FROM connection_check").fetchall() == [(1,)]
        with check:
            assert check.execute("SELECT value FROM connection_check").fetchall() == [(1,)]
        assert check.execute("SELECT 1").fetchone() == (1,)
    with pytest.raises(sqlite3.ProgrammingError):
        check.execute("SELECT 1")


def test_child_creation_shares_authorization_transaction(tmp_path):
    store = RunStore(tmp_path / "runs.sqlite")
    parent = store.create_run("boss-1", "space-1", "parent-request", "parent-digest")
    lease = store.acquire_lease(parent, 0, "worker", 60)
    store.transition(parent, lease["revision"], "RUNNING", "worker", lease["epoch"])
    with pytest.raises(ValueError, match="撤销事务"):
        with store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            child = store.create_child_run_in_transaction(db, parent, "worker", lease["epoch"], "child-request", "child-digest")
            assert store.create_child_run_in_transaction(db, parent, "worker", lease["epoch"], "child-request", "child-digest") == child
            raise ValueError("撤销事务")
    with store.connect() as db:
        assert db.execute("SELECT count(*) FROM agent_runs WHERE parent_run_id=?", (parent,)).fetchone() == (0,)
        assert db.execute("SELECT count(*) FROM agent_request_keys WHERE request_key=?", ("child-request",)).fetchone() == (0,)
        with pytest.raises(ValueError, match="当前数据库事务"):
            store.create_child_run_in_transaction(db, parent, "worker", lease["epoch"], "child-request", "child-digest")
    child = store.create_child_run(parent, "worker", lease["epoch"], "child-request", "child-digest")
    assert store.create_child_run(parent, "worker", lease["epoch"], "child-request", "child-digest") == child


def create_in_process(path):
    return RunStore(path).create_run("boss-1", "space-1", "request-1", "digest-1")


def acquire_in_process(path, run, owner):
    return RunStore(path).acquire_lease(run, 0, owner, 60)


def add_in_process(path, run, key):
    return RunStore(path).add_input(run, 1, key, "会议关注事项")


def acquire_after_interrupt_in_process(path, run, revision, start, output):
    store = RunStore(path, allow_migration=False)
    start.wait()
    try:
        result = store.acquire_lease(run, revision, "worker-acquire", 60)
    except ValueError as error:
        output.put(("acquire", "error", str(error)))
    else:
        output.put(("acquire", "ok", result["epoch"]))


def cancel_after_interrupt_in_process(path, run, revision, start, output):
    store = RunStore(path, allow_migration=False)
    start.wait()
    try:
        result = store.cancel(run, revision, request_key="concurrent-cancel")
    except ValueError as error:
        output.put(("cancel", "error", str(error)))
    else:
        output.put(("cancel", "ok", result["status"]))


def test_source_cleanup_keeps_unrelated_run_available(tmp_path):
    business = ControlStore(tmp_path / "business.sqlite")
    business.initialize("ui-check")
    runs = RunStore(business.path)
    run_id = runs.create_run("boss-1", "ui-check", "unrelated-run", "unrelated-digest")
    assert begin_source_cleanup(business, "ui-check", "finance-note", "1") is True
    lease = runs.acquire_lease(run_id, 0, "worker", 60)
    runs.renew_lease(run_id, "worker", lease["epoch"], 60)
    with business.connect() as db:
        assert business.get(db, "ui-check", "hermes_source_cleanup", "finance-note")["state"] == "PENDING"


def test_source_cleanup_blocks_lease_and_preserves_revision(tmp_path):
    business = ControlStore(tmp_path / "business.sqlite")
    business.initialize("ui-check")
    runs = RunStore(business.path)
    active = runs.create_run("technical-owner", "ui-check", "active-source", "active-digest")
    queued = runs.create_run("technical-owner", "ui-check", "queued-source", "queued-digest")
    with runs.connect() as db:
        db.execute("UPDATE agent_runs SET selected_refs=? WHERE run_id IN (?,?)", (json.dumps(["finance-note"]), active, queued))
    lease = runs.acquire_lease(active, 0, "worker", 60)
    runs.transition(active, lease["revision"], "RUNNING", "worker", lease["epoch"])
    child = runs.create_child_run(active, "worker", lease["epoch"], "child-source", "child-digest")
    child_lease = runs.acquire_lease(child, 0, "child-worker", 60)
    before = runs.read_run(active)
    assert begin_source_cleanup(business, "ui-check", "finance-note", "1") is True
    with pytest.raises(ValueError, match="来源清理尚未完成"):
        runs.renew_lease(active, "worker", lease["epoch"], 60)
    with pytest.raises(ValueError, match="来源清理尚未完成"):
        runs.renew_lease(child, "child-worker", child_lease["epoch"], 60)
    with pytest.raises(ValueError, match="来源清理尚未完成"):
        runs.transition(active, before["revision"], "WAITING_INPUT", "worker", lease["epoch"])
    with pytest.raises(ValueError, match="来源清理尚未完成"):
        runs.acquire_lease(queued, 0, "worker", 60)
    assert runs.read_run(active)["revision"] == before["revision"]
    assert runs.read_run(queued)["lease_epoch"] == 0
    runs.transition(active, before["revision"], "FAILED", "worker", lease["epoch"])
    assert runs.read_run(active)["status"] == "FAILED"
    business.control("ui-check", "withdraw", {"source_id": "finance-note", "version": "1"})
    with pytest.raises(ValueError, match="来源已经撤销"):
        runs.acquire_lease(queued, 0, "worker", 60)


def test_request_replay_and_conflict(tmp_path):
    store = RunStore(tmp_path / "runs.sqlite")
    first = store.create_run("boss-1", "space-1", "request-1", "digest-1")
    assert store.create_run("boss-1", "space-1", "request-1", "digest-1") == first
    with pytest.raises(ValueError, match="请求键"):
        store.create_run("boss-1", "space-1", "request-1", "digest-2")
    with sqlite3.connect(store.path) as db:
        assert db.execute("SELECT count(*) FROM agent_runs").fetchone()[0] == 1


def test_waiting_input_selection_requires_explicit_resume(tmp_path):
    runs = RunStore(tmp_path / "runs.sqlite")
    RunRequirements(runs, allow_migration=True)
    run_id = runs.create_run("technical-owner", "technical-space", "waiting-request", "waiting-digest")
    lease = runs.acquire_queued_for_execution(run_id, 0, "worker", 60)
    before = runs.read_run(run_id)
    runs.transition(run_id, before["revision"], "WAITING_INPUT", "worker", lease["epoch"])
    waiting = runs.read_run(run_id)
    assert RunBroker.allowed_actions(waiting) == ["READ_EVENTS", "ADD_INPUT", "CANCEL"]
    with runs.connect() as db:
        db.execute("BEGIN")
        assert RunRequirements.read_in_transaction(db, run_id, 1)["state"] == "PENDING_CONFIRMATION"
    saved = runs.add_input(run_id, 1, "technical-input", "补充成果要求")
    assert runs.add_input(run_id, 1, "technical-input", "补充成果要求") == saved
    with runs.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        RunRequirements.save_in_transaction(db, run_id, 2, "technical-input", ["TEXT"])
    applied = runs.apply_input(run_id, 1, "worker", lease["epoch"])
    assert runs.apply_input(run_id, 1, "worker", lease["epoch"]) == applied
    waiting = runs.read_run(run_id)
    assert waiting["status"] == "WAITING_INPUT" and waiting["goal_revision"] == waiting["applied_goal_revision"] == 2
    runs.transition(run_id, waiting["revision"], "RUNNING", "worker", lease["epoch"])
    assert runs.read_run(run_id)["status"] == "RUNNING"
    assert [event["type"] for event in runs.events(run_id, 0)] == ["STATUS_CHANGED", "STATUS_CHANGED", "INPUT_RECEIVED", "INPUT_APPLIED", "STATUS_CHANGED"]


def test_parallel_request_and_lease(tmp_path):
    path = tmp_path / "runs.sqlite"
    store = RunStore(path)
    with ProcessPoolExecutor(max_workers=4) as pool:
        runs = list(pool.map(create_in_process, [path] * 8))
    assert len(set(runs)) == 1
    lease = store.acquire_lease(runs[0], 0, "worker-1", 60)
    with pytest.raises(ValueError, match="租约"):
        store.acquire_lease(runs[0], 1, "worker-2", 60)
    assert lease["epoch"] == 1


def test_events_replay_and_fencing(tmp_path):
    store = RunStore(tmp_path / "runs.sqlite")
    run = store.create_run("boss-1", "space-1", "request-1", "digest-1")
    lease = store.acquire_lease(run, 0, "worker-1", 60)
    with pytest.raises(ValueError, match="成果服务"):
        store.append_event(run, "worker-1", lease["epoch"], "artifact-event", "ARTIFACT_CANDIDATE", {})
    first = store.append_event(run, "worker-1", lease["epoch"], "event-1", "RUN_STARTED", {"status": "started"})
    assert store.append_event(run, "worker-1", lease["epoch"], "event-1", "RUN_STARTED", {"status": "started"}) == first
    with pytest.raises(ValueError, match="事件"):
        store.append_event(run, "worker-1", lease["epoch"], "event-1", "RUN_STARTED", {"status": "changed"})
    with pytest.raises(ValueError, match="租约"):
        store.append_event(run, "worker-2", lease["epoch"], "event-2", "RUN_FAILED", {})
    with pytest.raises(ValueError, match="事件类型或版本"):
        store.append_event(run, "worker-1", lease["epoch"], "event-2", "UNKNOWN_EVENT", {})
    with pytest.raises(ValueError, match="事件类型或版本"):
        store.append_event(run, "worker-1", lease["epoch"], "event-2", "RUN_FAILED", {}, payload_version=2)
    assert RunStore(store.path).events(run, 0) == [first]
    assert first["trace_id"] and first["occurred_at"] and first["payload_version"] == 1
    assert store.events(run, first["seq"]) == []


def test_release_fences_prior_owner(tmp_path):
    store = RunStore(tmp_path / "runs.sqlite")
    run = store.create_run("boss-1", "space-1", "request-1", "digest-1")
    old = store.acquire_lease(run, 0, "worker-1", 60)
    store.renew_lease(run, "worker-1", old["epoch"], 60)
    store.release_lease(run, "worker-1", old["epoch"])
    new = store.acquire_lease(run, 3, "worker-2", 60)
    assert new["epoch"] == old["epoch"] + 1
    with pytest.raises(ValueError, match="租约"):
        store.append_event(run, "worker-1", old["epoch"], "event-1", "RUN_STARTED", {})


def test_expired_lease_cannot_write_or_renew(tmp_path):
    store = RunStore(tmp_path / "runs.sqlite")
    run = store.create_run("boss-1", "space-1", "request-1", "digest-1")
    old = store.acquire_lease(run, 0, "worker-1", 0.05)
    time.sleep(0.1)
    with pytest.raises(ValueError, match="租约"):
        store.renew_lease(run, "worker-1", old["epoch"], 60)
    new = store.acquire_lease(run, 1, "worker-2", 60)
    with pytest.raises(ValueError, match="租约"):
        store.append_event(run, "worker-1", old["epoch"], "event-1", "RUN_STARTED", {})
    assert new["epoch"] == 2


def test_concurrent_processes_have_one_lease(tmp_path):
    path = tmp_path / "runs.sqlite"
    store = RunStore(path)
    run = store.create_run("boss-1", "space-1", "request-1", "digest-1")
    with ProcessPoolExecutor(max_workers=2) as pool:
        attempts = [pool.submit(acquire_in_process, path, run, owner) for owner in ("worker-1", "worker-2")]
    assert sum(future.exception() is None for future in attempts) == 1
    assert sum(isinstance(future.exception(), ValueError) for future in attempts) == 1


def test_inputs_are_ordered_and_cancel_is_durable(tmp_path):
    store = RunStore(tmp_path / "runs.sqlite")
    run = store.create_run("boss-1", "space-1", "request-1", "digest-1")
    lease = store.acquire_lease(run, 0, "worker-1", 60)
    store.transition(run, 1, "RUNNING", "worker-1", lease["epoch"])
    first = store.add_input(run, 1, "input-1", "资料范围")
    assert store.add_input(run, 1, "input-1", "资料范围") == first
    with pytest.raises(ValueError):
        store.add_input(run, 1, "input-2", "关注事项")
    second = store.add_input(run, 2, "input-2", "关注事项")
    with pytest.raises(ValueError):
        store.apply_input(run, 2, "worker-1", lease["epoch"])
    store.apply_input(run, 1, "worker-1", lease["epoch"])
    store.apply_input(run, 2, "worker-1", lease["epoch"])
    current = store.read_run(run)
    assert (first["input_seq"], second["input_seq"], current["applied_goal_revision"]) == (1, 2, 3)
    store.cancel(run, current["revision"])
    current = RunStore(store.path).read_run(run)
    assert current["status"] == "CANCEL_REQUESTED" and current["cancel_requested_at"]
    with pytest.raises(ValueError):
        store.add_input(run, 3, "input-3", "后续输入")
    with pytest.raises(ValueError):
        store.append_event(run, "worker-1", lease["epoch"], "event-2", "TOOL_STARTED", {})
    assert [event["seq"] for event in store.events(run, 0)] == list(range(1, len(store.events(run, 0)) + 1))


def test_transition_guards_and_migration_repeat(tmp_path):
    path = tmp_path / "runs.sqlite"
    store = RunStore(path)
    run = store.create_run("boss-1", "space-1", "request-1", "digest-1")
    with pytest.raises(ValueError):
        store.transition(run, 0, "SUCCEEDED", "worker-1", 1)
    lease = store.acquire_lease(run, 0, "worker-1", 60)
    store.transition(run, 1, "RUNNING", "worker-1", lease["epoch"])
    with pytest.raises(ValueError):
        store.transition(run, 2, "SUCCEEDED", "worker-1", lease["epoch"])
    store.transition(run, 2, "FAILED", "worker-1", lease["epoch"])
    with pytest.raises(ValueError):
        store.transition(run, 3, "RUNNING", "worker-1", lease["epoch"])
    reopened = RunStore(path)
    assert reopened.read_run(run)["status"] == "FAILED"
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT count(*) FROM agent_schema_migrations").fetchone()[0] == 1


def test_expired_running_lease_is_interrupted_and_recovered(tmp_path):
    store = RunStore(tmp_path / "runs.sqlite")
    run = store.create_run("boss-1", "space-1", "request-1", "digest-1")
    old = store.acquire_lease(run, 0, "worker-1", 0.1)
    store.transition(run, 1, "RUNNING", "worker-1", old["epoch"])
    time.sleep(0.15)
    store.interrupt_expired(run)
    assert store.read_run(run)["status"] == "INTERRUPTED"
    new = store.acquire_lease(run, 3, "worker-2", 60)
    assert new["epoch"] == old["epoch"] + 1
    with pytest.raises(ValueError):
        store.append_event(run, "worker-1", old["epoch"], "event-1", "TOOL_STARTED", {})


def test_canceled_run_cannot_reacquire_lease_after_interruption(tmp_path):
    store = RunStore(tmp_path / "runs.sqlite")
    run = store.create_run("boss-1", "space-1", "request-1", "digest-1")
    lease = store.acquire_lease(run, 0, "worker-1", 0.05)
    store.transition(run, 1, "RUNNING", "worker-1", lease["epoch"])
    receipt = store.cancel(run, 2, request_key="cancel-before-expiry")
    assert receipt["status"] == "CANCEL_REQUESTED"
    time.sleep(0.1)
    store.interrupt_expired(run)
    current = store.read_run(run)
    assert current["status"] == "INTERRUPTED" and current["cancel_requested_at"] is not None
    with pytest.raises(ValueError, match="租约不可取得"):
        store.acquire_lease(run, current["revision"], "worker-2", 60)
    assert store.cancel(run, 2, request_key="cancel-before-expiry") == receipt


def interrupted_run(tmp_path):
    store = RunStore(tmp_path / "runs.sqlite")
    run = store.create_run("boss-1", "space-1", "request-1", "digest-1")
    lease = store.acquire_lease(run, 0, "worker-1", 0.5)
    store.transition(run, 1, "RUNNING", "worker-1", lease["epoch"])
    time.sleep(0.6)
    store.interrupt_expired(run)
    current = store.read_run(run)
    assert current["status"] == "INTERRUPTED" and current["cancel_requested_at"] is None
    return store, run, current["revision"]


def test_cancel_commit_before_lease_acquisition_blocks_acquire(tmp_path):
    store, run, revision = interrupted_run(tmp_path)
    receipt = store.cancel(run, revision, request_key="cancel-before-lease")
    assert receipt["status"] == "INTERRUPTED"
    current = store.read_run(run)
    assert current["cancel_requested_at"] is not None and current["lease_owner"] is None
    with pytest.raises(ValueError, match="租约不可取得"):
        store.acquire_lease(run, current["revision"], "worker-2", 60)
    reopened = RunStore(store.path, allow_migration=False).read_run(run)
    assert reopened["cancel_requested_at"] == current["cancel_requested_at"]
    assert reopened["status"] == "INTERRUPTED"


def test_lease_acquisition_before_cancel_keeps_cancel_flag_and_blocks_tools(tmp_path):
    store, run, revision = interrupted_run(tmp_path)
    lease = store.acquire_lease(run, revision, "worker-2", 60)
    current = store.read_run(run)
    assert current["lease_owner"] == "worker-2" and current["cancel_requested_at"] is None
    receipt = store.cancel(run, current["revision"], request_key="cancel-after-lease")
    assert receipt["status"] == "INTERRUPTED"
    after = store.read_run(run)
    assert after["cancel_requested_at"] is not None and after["lease_owner"] == "worker-2"
    with pytest.raises(ValueError, match="禁止事件"):
        store.append_event(run, "worker-2", lease["epoch"], "late-tool", "TOOL_STARTED", {})
    with pytest.raises(ValueError, match="租约不可取得"):
        store.acquire_lease(run, after["revision"], "worker-3", 60)
    reopened = RunStore(store.path, allow_migration=False).read_run(run)
    assert reopened["cancel_requested_at"] == after["cancel_requested_at"]
    assert reopened["lease_owner"] == "worker-2"


def test_concurrent_cancel_and_lease_acquisition_has_one_winner(tmp_path):
    store, run, revision = interrupted_run(tmp_path)
    context = multiprocessing.get_context("spawn")
    start, output = context.Event(), context.Queue()
    processes = [context.Process(target=acquire_after_interrupt_in_process, args=(store.path, run, revision, start, output)),
                 context.Process(target=cancel_after_interrupt_in_process, args=(store.path, run, revision, start, output))]
    for process in processes:
        process.start()
    start.set()
    for process in processes:
        process.join(60)
        assert process.exitcode == 0
    outcomes = [output.get(timeout=5) for _ in processes]
    assert sorted(item[1] for item in outcomes) == ["error", "ok"]
    winner = next(item for item in outcomes if item[1] == "ok")
    reopened = RunStore(store.path, allow_migration=False)
    current = reopened.read_run(run)
    if winner[0] == "acquire":
        assert current["cancel_requested_at"] is None and current["lease_owner"] is not None
        receipt = reopened.cancel(run, current["revision"], request_key="concurrent-cancel-retry")
        assert receipt["status"] == "INTERRUPTED"
        current = reopened.read_run(run)
    else:
        assert current["lease_owner"] is None
    assert current["cancel_requested_at"] is not None
    assert current["status"] == "INTERRUPTED"
    with pytest.raises(ValueError, match="租约不可取得"):
        reopened.acquire_lease(run, current["revision"], "worker-after-race", 60)
    if current["lease_owner"] is not None:
        with pytest.raises(ValueError, match="禁止事件"):
            reopened.append_event(run, current["lease_owner"], current["lease_epoch"], "race-tool", "TOOL_STARTED", {})


def test_cancel_retry_returns_original_receipt(tmp_path):
    store = RunStore(tmp_path / "runs.sqlite")
    run = store.create_run("boss-1", "space-1", "request-1", "digest-1")
    lease = store.acquire_lease(run, 0, "worker-1", 60)
    store.transition(run, 1, "RUNNING", "worker-1", lease["epoch"])
    receipt = store.cancel(run, 2, request_key="cancel-1")
    assert store.cancel(run, 2, request_key="cancel-1") == receipt
    with pytest.raises(ValueError):
        store.cancel(run, 3, request_key="cancel-1")


def test_parallel_migration_and_version_mismatch(tmp_path):
    path = tmp_path / "runs.sqlite"
    with ProcessPoolExecutor(max_workers=4) as pool:
        runs = list(pool.map(create_in_process, [path] * 4))
    assert len(set(runs)) == 1
    with sqlite3.connect(path) as db:
        db.execute("UPDATE agent_schema_migrations SET sha256=? WHERE version=?", ("invalid", "upgrade2_001"))
    with pytest.raises(ValueError, match="迁移版本"):
        RunStore(path)


def test_parallel_inputs_and_atomic_event_failure(tmp_path):
    path = tmp_path / "runs.sqlite"
    store = RunStore(path)
    run = store.create_run("boss-1", "space-1", "request-1", "digest-1")
    with ProcessPoolExecutor(max_workers=2) as pool:
        attempts = [pool.submit(add_in_process, path, run, key) for key in ("input-1", "input-2")]
    assert sum(future.exception() is None for future in attempts) == 1
    assert sum(isinstance(future.exception(), ValueError) for future in attempts) == 1
    before = store.read_run(run)
    with sqlite3.connect(path) as db:
        db.execute("CREATE TRIGGER reject_events BEFORE INSERT ON agent_run_events BEGIN SELECT RAISE(ABORT, 'event rejected'); END")
    with pytest.raises(sqlite3.IntegrityError):
        store.cancel(run, before["revision"], request_key="cancel-1")
    assert store.read_run(run) == before
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT count(*) FROM agent_run_operations").fetchone()[0] == 0
