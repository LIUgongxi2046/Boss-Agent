import sys
import asyncio
import sqlite3
import signal
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from agent_run_concurrency import RunConcurrencyBudget
from agent_run_store import RunStore
from hermes_anchor_evidence import HermesAnchorEvidence, reclaim_uncertain_anchor, require_lease_window
from hermes_anchor_supervisor import AnchorRunStateStore, AnchorSupervisor, GuardedEngineSupervisor
from hermes_bridge import EngineEventSink, EngineRunConfig
from hermes_process_anchor import AnchorProcessGroup, GuardianBootstrapError
from hermes_process_evidence import HermesProcessEvidence
from hermes_run_recovery import inspect_recovery
from agent_simulation_migration_install import install_simulation_migrations


ENGINE = Path(__file__).with_name("hermes_anchor_engine_probe.py").resolve()
ENV = {"PATH": "/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE": "1"}


def test_lease_window_rejects_expired_or_insufficient_time():
    now = datetime.now(timezone.utc)
    require_lease_window((now + timedelta(seconds=60)).isoformat(), 10)
    with pytest.raises(ValueError, match="剩余时间不足"):
        require_lease_window((now - timedelta(seconds=1)).isoformat(), 10)
    with pytest.raises(ValueError, match="剩余时间不足"):
        require_lease_window((now + timedelta(seconds=1)).isoformat(), 10)
    with pytest.raises(ValueError, match="到期时间无效"):
        require_lease_window(datetime.now().isoformat(), 10)
    with pytest.raises(ValueError, match="时限无效"):
        require_lease_window((now + timedelta(seconds=60)).isoformat(), float("nan"))


def test_uncertain_anchor_reclaims_real_process_group(tmp_path):
    anchor = AnchorProcessGroup.start([sys.executable, str(ENGINE), "sleep"], cwd=tmp_path, env=ENV, deferred=True)
    reclaim_uncertain_anchor(anchor)
    assert anchor.process.returncode == -signal.SIGKILL
    assert anchor.control_write is None


def test_anchor_migration_and_missing_run_rejection(tmp_path):
    store = RunStore(tmp_path / "runs.sqlite")
    RunConcurrencyBudget(store, allow_migration=True)
    HermesProcessEvidence(store, allow_migration=True)
    evidence = HermesAnchorEvidence(store, allow_migration=True)
    HermesAnchorEvidence(store)
    anchor = AnchorProcessGroup.start([sys.executable, str(ENGINE), "sleep"], cwd=tmp_path, env=ENV)
    try:
        with pytest.raises(ValueError):
            evidence.record("missing-run", "missing-request", "missing-owner", 1, anchor)
        with store.connect() as db:
            assert db.execute("SELECT count(*) FROM hermes_anchor_evidence").fetchone() == (0,)
            assert db.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        if anchor.process.poll() is None:
            anchor.reclaim()


def test_anchor_migration_requires_process_evidence(tmp_path):
    store = RunStore(tmp_path / "runs.sqlite")
    with pytest.raises(ValueError, match="迁移条件不足"):
        HermesAnchorEvidence(store, allow_migration=True)
    with store.connect() as db:
        assert db.execute("SELECT 1 FROM sqlite_master WHERE name='hermes_anchor_evidence'").fetchone() is None


def test_missing_run_rejects_release_before_engine_execution(tmp_path):
    store = RunStore(tmp_path / "runs.sqlite")
    RunConcurrencyBudget(store, allow_migration=True)
    HermesProcessEvidence(store, allow_migration=True)
    evidence = HermesAnchorEvidence(store, allow_migration=True)
    output = tmp_path / "started"
    command = [sys.executable, "-c", "import pathlib,sys; pathlib.Path(sys.argv[1]).write_text('started')", str(output)]
    anchor = AnchorProcessGroup.start(command, cwd=tmp_path, env=ENV, deferred=True)
    try:
        with pytest.raises(ValueError):
            evidence.release("missing-run", "missing-request", "missing-owner", 1, anchor)
        assert not output.exists()
    finally:
        if anchor.process.poll() is None:
            anchor.reclaim()


@pytest.mark.parametrize("scenario", ["current", "lease_removed", "race"])
def test_anchor_exit_marks_process_and_reservation_unknown_atomically(tmp_path, scenario):
    store = RunStore(tmp_path / "runs.sqlite")
    budget = RunConcurrencyBudget(store, allow_migration=True)
    process_evidence = HermesProcessEvidence(store, allow_migration=True)
    evidence = HermesAnchorEvidence(store, allow_migration=True)
    run_id = store.create_run("technical-actor", "technical-space", "technical-request", "technical-digest")
    lease = store.acquire_lease(run_id, 0, "technical-worker", 60)
    epoch = lease["epoch"]
    store.transition(run_id, lease["revision"], "RUNNING", "technical-worker", epoch)
    budget.configure(run_id, "technical-worker", epoch, 1)
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        budget.reserve_in_transaction(db, run_id, "technical-worker", epoch, "slot", "digest")
        ticket = process_evidence.record_start_in_transaction(db, run_id, "slot", "digest", "technical-worker", epoch,
                                                              "technical-actor", "technical-space")
    anchor = AnchorProcessGroup.start([sys.executable, str(ENGINE), "sleep"], cwd=tmp_path, env=ENV,
                                      deferred=True, guarded=True)
    try:
        if scenario == "race":
            barrier = threading.Barrier(2)

            def bind():
                barrier.wait()
                return process_evidence.bind_prepared_anchor(ticket, anchor)

            with ThreadPoolExecutor(max_workers=2) as executor:
                attempts = [executor.submit(bind) for _ in range(2)]
                results = [attempt.result(timeout=10) for attempt in attempts if attempt.exception(timeout=10) is None]
                errors = [attempt.exception(timeout=10) for attempt in attempts if attempt.exception(timeout=10) is not None]
            assert results == [{"run_id": run_id, "request_key": "slot"}]
            assert len(errors) == 1 and str(errors[0]) == "进程启动登记不可使用"
        else:
            assert process_evidence.bind_prepared_anchor(ticket, anchor) == {"run_id": run_id, "request_key": "slot"}
        with pytest.raises(ValueError, match="登记不可使用"):
            process_evidence.bind_prepared_anchor(ticket, anchor)
        supervisor = AnchorSupervisor(anchor, AnchorRunStateStore(store.path), run_id, "technical-worker", epoch, 30)
        os.kill(anchor.guardian_pid, signal.SIGKILL)
        anchor.process.wait(timeout=5)
        result = supervisor.step()
        assert result.state == "ANCHOR_EXIT"
        assert result.cleanup == "UNVERIFIED"
        assert result.descendants == "NOT_VERIFIED"
        if scenario == "race":
            barrier = threading.Barrier(2)

            def mark():
                barrier.wait()
                return supervisor.record_uncertain(evidence, "slot")

            def release():
                barrier.wait()
                return store.release_lease(run_id, "technical-worker", epoch)

            with ThreadPoolExecutor(max_workers=2) as executor:
                marked = executor.submit(mark)
                released = executor.submit(release)
                assert released.result(timeout=10) is None
                error = marked.exception(timeout=10)
            assert error is None or isinstance(error, ValueError)
            with store.connect() as db:
                process_state = db.execute("SELECT state FROM hermes_process_evidence WHERE run_id=?", (run_id,)).fetchone()[0]
                reservation_state = db.execute("SELECT state FROM agent_concurrency_reservations WHERE run_id=?", (run_id,)).fetchone()[0]
                assert (process_state, reservation_state) == (("UNKNOWN", "UNKNOWN") if error is None else ("STARTING", "ACTIVE"))
            return
        if scenario == "lease_removed":
            store.release_lease(run_id, "technical-worker", epoch)
        with pytest.raises(ValueError, match="代次不一致"):
            evidence.mark_uncertain(run_id, "slot", "technical-worker", epoch + 1, anchor)
        with store.connect() as db:
            assert db.execute("SELECT state FROM hermes_process_evidence WHERE run_id=?", (run_id,)).fetchone() == ("STARTING",)
            assert db.execute("SELECT state FROM agent_concurrency_reservations WHERE run_id=?", (run_id,)).fetchone() == ("ACTIVE",)
        if scenario == "lease_removed":
            with pytest.raises(ValueError, match="代次不一致"):
                evidence.mark_uncertain(run_id, "slot", "technical-worker", epoch, anchor)
            expected = {"process_state": "UNKNOWN", "reservation_state": "UNKNOWN", "run_state": "INTERRUPTED"}
            assert evidence.mark_uncertain(run_id, "slot", "technical-worker", epoch, anchor, allow_released=True) == expected
            assert evidence.mark_uncertain(run_id, "slot", "technical-worker", epoch, anchor, allow_released=True) == expected
            inspection = inspect_recovery(store, run_id, "technical-actor", "technical-space")
            assert inspection["unknown_reservations"] == 1
            assert inspection["duplicate_execution_allowed"] is False
            with pytest.raises(ValueError):
                store.acquire_lease(run_id, store.read_run(run_id)["revision"], "next-worker", 60)
            with store.connect() as db:
                assert db.execute("SELECT count(*) FROM agent_run_events WHERE run_id=? AND type='STATUS_CHANGED' AND json_extract(payload,'$.to')='INTERRUPTED'", (run_id,)).fetchone() == (1,)
            return
        expected = {"process_state": "UNKNOWN", "reservation_state": "UNKNOWN", "run_state": "INTERRUPTED"}
        assert supervisor.record_uncertain(evidence, "slot") == expected
        assert supervisor.record_uncertain(evidence, "slot") == expected
        with store.connect() as db:
            assert db.execute("SELECT state FROM hermes_process_evidence WHERE run_id=?", (run_id,)).fetchone() == ("UNKNOWN",)
            assert db.execute("SELECT state FROM agent_concurrency_reservations WHERE run_id=?", (run_id,)).fetchone() == ("UNKNOWN",)
            assert db.execute("SELECT status FROM agent_runs WHERE run_id=?", (run_id,)).fetchone() == ("INTERRUPTED",)
            assert db.execute("SELECT count(*) FROM agent_run_events WHERE run_id=? AND type='STATUS_CHANGED' AND json_extract(payload,'$.to')='INTERRUPTED'", (run_id,)).fetchone() == (1,)
        with pytest.raises(ValueError, match="原租约仍然有效"):
            inspect_recovery(store, run_id, "technical-actor", "technical-space")
        store.release_lease(run_id, "technical-worker", epoch)
        inspection = inspect_recovery(store, run_id, "technical-actor", "technical-space")
        assert inspection["status"] == "INTERRUPTED"
        assert inspection["unknown_reservations"] == 1
        assert inspection["process_evidence"][0]["state"] == "UNKNOWN"
        assert inspection["duplicate_execution_allowed"] is False
        assert inspection["automatic_requeue"] is False
        with store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            assert budget.recover_in_transaction(db, run_id, "slot")["state"] == "UNKNOWN"
        with pytest.raises(ValueError):
            store.acquire_lease(run_id, store.read_run(run_id)["revision"], "next-worker", 60)
        with store.connect() as db:
            assert db.execute("SELECT state FROM agent_concurrency_reservations WHERE run_id=?", (run_id,)).fetchone() == ("UNKNOWN",)
    finally:
        if anchor.process.poll() is None:
            anchor.reclaim()
        anchor.close_control()


@pytest.mark.parametrize("order", ["cancel_first", "mark_first", "concurrent"])
def test_anchor_unknown_and_cancel_preserve_accepted_request(tmp_path, order):
    store = RunStore(tmp_path / "runs.sqlite")
    budget = RunConcurrencyBudget(store, allow_migration=True)
    process_evidence = HermesProcessEvidence(store, allow_migration=True)
    evidence = HermesAnchorEvidence(store, allow_migration=True)
    run_id = store.create_run("technical-actor", "technical-space", "technical-request", "technical-digest")
    lease = store.acquire_lease(run_id, 0, "technical-worker", 60)
    epoch = lease["epoch"]
    store.transition(run_id, lease["revision"], "RUNNING", "technical-worker", epoch)
    budget.configure(run_id, "technical-worker", epoch, 1)
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        budget.reserve_in_transaction(db, run_id, "technical-worker", epoch, "slot", "digest")
        process_evidence.record_start_in_transaction(db, run_id, "slot", "digest", "technical-worker", epoch,
                                                     "technical-actor", "technical-space")
    anchor = AnchorProcessGroup.start([sys.executable, str(ENGINE), "sleep"], cwd=tmp_path, env=ENV,
                                      deferred=True, guarded=True)
    try:
        evidence.record(run_id, "slot", "technical-worker", epoch, anchor)
        supervisor = AnchorSupervisor(anchor, AnchorRunStateStore(store.path), run_id, "technical-worker", epoch, 30)
        os.kill(anchor.guardian_pid, signal.SIGKILL)
        anchor.process.wait(timeout=5)
        assert supervisor.step().state == "ANCHOR_EXIT"
        original_revision = store.read_run(run_id)["revision"]
        if order == "cancel_first":
            receipt = store.cancel(run_id, original_revision, request_key="cancel-request")
            accepted_at = store.read_run(run_id)["cancel_requested_at"]
            supervisor.record_uncertain(evidence, "slot")
        elif order == "mark_first":
            supervisor.record_uncertain(evidence, "slot")
            receipt = store.cancel(run_id, store.read_run(run_id)["revision"], request_key="cancel-request")
            accepted_at = store.read_run(run_id)["cancel_requested_at"]
        else:
            barrier = threading.Barrier(2)

            def mark():
                barrier.wait()
                return supervisor.record_uncertain(evidence, "slot")

            def cancel():
                barrier.wait()
                return store.cancel(run_id, original_revision, request_key="cancel-request")

            with ThreadPoolExecutor(max_workers=2) as executor:
                marked = executor.submit(mark)
                canceled = executor.submit(cancel)
                assert marked.result(timeout=10)["run_state"] == "INTERRUPTED"
                error = canceled.exception(timeout=10)
            assert error is None or isinstance(error, ValueError)
            if error is None:
                receipt = canceled.result()
            else:
                assert str(error) == "运行不能取消"
                assert store.read_run(run_id)["cancel_requested_at"] is None
                receipt = store.cancel(run_id, store.read_run(run_id)["revision"], request_key="cancel-request")
            accepted_at = store.read_run(run_id)["cancel_requested_at"]
        current = store.read_run(run_id)
        assert current["status"] == "INTERRUPTED"
        assert accepted_at is not None and current["cancel_requested_at"] == accepted_at
        assert current["lease_owner"] == "technical-worker"
        assert current["lease_epoch"] == epoch
        with store.connect() as db:
            assert db.execute("SELECT state FROM hermes_process_evidence WHERE run_id=?", (run_id,)).fetchone() == ("UNKNOWN",)
            assert db.execute("SELECT state FROM agent_concurrency_reservations WHERE run_id=?", (run_id,)).fetchone() == ("UNKNOWN",)
            assert db.execute("SELECT count(*) FROM agent_run_operations WHERE run_id=? AND request_key='cancel-request'", (run_id,)).fetchone() == (1,)
        assert store.cancel(run_id, receipt["revision"] - 1, request_key="cancel-request") == receipt
    finally:
        if anchor.process.poll() is None:
            anchor.reclaim()
        anchor.close_control()


def test_anchor_migration_failure_keeps_version_unregistered(tmp_path):
    store = RunStore(tmp_path / "runs.sqlite")
    RunConcurrencyBudget(store, allow_migration=True)
    HermesProcessEvidence(store, allow_migration=True)
    with store.connect() as db:
        db.execute("CREATE TABLE hermes_anchor_evidence (existing INTEGER)")
    with pytest.raises(sqlite3.OperationalError):
        HermesAnchorEvidence(store, allow_migration=True)
    with store.connect() as db:
        assert db.execute("SELECT 1 FROM agent_schema_migrations WHERE version='hermes_anchor_evidence_001'").fetchone() is None
        assert db.execute("PRAGMA table_info(hermes_anchor_evidence)").fetchone()[1] == "existing"


def test_prepared_anchor_rejects_changed_lease(tmp_path):
    store = RunStore(tmp_path / "runs.sqlite")
    budget = RunConcurrencyBudget(store, allow_migration=True)
    process_evidence = HermesProcessEvidence(store, allow_migration=True)
    HermesAnchorEvidence(store, allow_migration=True)
    run_id = store.create_run("technical-actor", "technical-space", "technical-request", "technical-digest")
    lease = store.acquire_lease(run_id, 0, "technical-worker", 60)
    epoch = lease["epoch"]
    store.transition(run_id, lease["revision"], "RUNNING", "technical-worker", epoch)
    budget.configure(run_id, "technical-worker", epoch, 1)
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        budget.reserve_in_transaction(db, run_id, "technical-worker", epoch, "slot", "digest")
        ticket = process_evidence.record_start_in_transaction(db, run_id, "slot", "digest", "technical-worker", epoch,
                                                              "technical-actor", "technical-space")
    anchor = AnchorProcessGroup.start([sys.executable, str(ENGINE), "sleep"], cwd=tmp_path, env=ENV,
                                      deferred=True, guarded=True)
    try:
        store.release_lease(run_id, "technical-worker", epoch)
        with pytest.raises(ValueError):
            process_evidence.bind_prepared_anchor(ticket, anchor)
        assert anchor.process.poll() is not None
        assert anchor.control_write is None
        with pytest.raises(ValueError, match="登记不可使用"):
            process_evidence.bind_prepared_anchor(ticket, anchor)
        with store.connect() as db:
            assert db.execute("SELECT count(*) FROM hermes_anchor_evidence").fetchone() == (0,)
            assert db.execute("SELECT state FROM hermes_process_evidence WHERE run_id=?", (run_id,)).fetchone() == ("STARTING",)
            assert db.execute("SELECT state FROM agent_concurrency_reservations WHERE run_id=?", (run_id,)).fetchone() == ("ACTIVE",)
    finally:
        if anchor.process.poll() is None:
            anchor.reclaim()
        anchor.close_control()


def test_two_anchors_compete_for_one_ticket(tmp_path):
    store = RunStore(tmp_path / "runs.sqlite")
    budget = RunConcurrencyBudget(store, allow_migration=True)
    process_evidence = HermesProcessEvidence(store, allow_migration=True)
    HermesAnchorEvidence(store, allow_migration=True)
    run_id = store.create_run("technical-actor", "technical-space", "technical-request", "technical-digest")
    lease = store.acquire_lease(run_id, 0, "technical-worker", 60)
    epoch = lease["epoch"]
    store.transition(run_id, lease["revision"], "RUNNING", "technical-worker", epoch)
    budget.configure(run_id, "technical-worker", epoch, 1)
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        budget.reserve_in_transaction(db, run_id, "technical-worker", epoch, "slot", "digest")
        ticket = process_evidence.record_start_in_transaction(db, run_id, "slot", "digest", "technical-worker", epoch,
                                                              "technical-actor", "technical-space")
    anchors = []
    try:
        for _ in range(2):
            anchors.append(AnchorProcessGroup.start([sys.executable, str(ENGINE), "sleep"], cwd=tmp_path, env=ENV,
                                                    deferred=True, guarded=True))
        barrier = threading.Barrier(2)

        def bind(anchor):
            barrier.wait()
            return process_evidence.bind_prepared_anchor(ticket, anchor)

        with ThreadPoolExecutor(max_workers=2) as executor:
            attempts = [executor.submit(bind, anchor) for anchor in anchors]
            errors = [attempt.exception(timeout=10) for attempt in attempts]
        assert sum(error is None for error in errors) == 1
        assert sum(isinstance(error, ValueError) and str(error) == "进程启动登记不可使用" for error in errors) == 1
        winner = anchors[errors.index(None)]
        loser = anchors[1 - errors.index(None)]
        assert winner.process.poll() is None and loser.process.poll() is None
        with store.connect() as db:
            assert db.execute("SELECT anchor_pid,engine_pid FROM hermes_anchor_evidence").fetchall() == [(winner.anchor_pid, winner.engine_pid)]
        loser.reclaim()
        assert loser.process.poll() is not None and winner.process.poll() is None
    finally:
        for anchor in anchors:
            if anchor.process.poll() is None:
                anchor.reclaim()
            anchor.close_control()


@pytest.mark.parametrize("scenario", ["guardian_exit", "lease_released", "engine_success", "engine_failure", "bootstrap_timeout", "bootstrap_error", "bootstrap_error_lease_released"])
def test_guarded_supervisor_records_uncertain_anchor_exit(tmp_path, scenario):
    store = RunStore(tmp_path / "runs.sqlite")
    budget = RunConcurrencyBudget(store, allow_migration=True)
    process_evidence = HermesProcessEvidence(store, allow_migration=True)
    evidence = HermesAnchorEvidence(store, allow_migration=True)
    run_id = store.create_run("technical-actor", "technical-space", "technical-request", "technical-digest")
    lease = store.acquire_lease(run_id, 0, "technical-worker", 60)
    epoch = lease["epoch"]
    store.transition(run_id, lease["revision"], "RUNNING", "technical-worker", epoch)
    budget.configure(run_id, "technical-worker", epoch, 1)
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        budget.reserve_in_transaction(db, run_id, "technical-worker", epoch, "slot", "digest")
        ticket = process_evidence.record_start_in_transaction(db, run_id, "slot", "digest", "technical-worker", epoch,
                                                              "technical-actor", "technical-space")
    command = [sys.executable, "-c", "raise SystemExit(0)" if scenario == "engine_success" else "raise SystemExit(7)"] if scenario in {"engine_success", "engine_failure"} else [sys.executable, "-c", "import time; time.sleep(0.2)"] if scenario in {"bootstrap_error", "bootstrap_error_lease_released"} else [sys.executable, str(ENGINE), "no_read" if scenario == "bootstrap_timeout" else "sleep"]
    anchor = AnchorProcessGroup.start(command, cwd=tmp_path, env=ENV,
                                      deferred=True, guarded=True, bootstrap=b"x" * (1024 * 1024) if scenario in {"bootstrap_timeout", "bootstrap_error", "bootstrap_error_lease_released"} else b"")
    try:
        process_evidence.bind_prepared_anchor(ticket, anchor)
        config = EngineRunConfig(run_id, epoch, "903230b1e23e0c496b28e5d2e8c4f2639cd506b6", "http://127.0.0.1:49152", 1)
        supervisor = GuardedEngineSupervisor(EngineEventSink(store, config, "technical-worker"), anchor, evidence, "slot", max_seconds=0.2 if scenario == "bootstrap_timeout" else 30)
        assert supervisor.step() == "RUNNING"
        if scenario == "lease_released":
            async def exercise():
                task = asyncio.create_task(supervisor.monitor(interval=0.01))
                await asyncio.sleep(0.05)
                store.release_lease(run_id, "technical-worker", epoch)
                with pytest.raises(ValueError, match="租约无效"):
                    await task
            asyncio.run(exercise())
            assert anchor.process.poll() is not None
            assert anchor.control_write is None
            return
        if scenario in {"bootstrap_error", "bootstrap_error_lease_released"}:
            evidence.release(run_id, "slot", "technical-worker", epoch, anchor)
            with pytest.raises(GuardianBootstrapError, match="引擎启动信息传输失败"):
                asyncio.run(asyncio.wait_for(supervisor.monitor(interval=0.01), 10))
            if scenario == "bootstrap_error_lease_released":
                store.release_lease(run_id, "technical-worker", epoch)
                with pytest.raises(ValueError):
                    store.acquire_lease(run_id, store.read_run(run_id)["revision"], "next-worker", 60)
            evidence.mark_uncertain(run_id, "slot", "technical-worker", epoch, anchor, allow_released=scenario == "bootstrap_error_lease_released")
            assert not any(event["type"] in {"RUN_STARTED", "RUN_FINISHED", "RUN_FAILED"} for event in store.events(run_id, 0))
        elif scenario == "bootstrap_timeout":
            evidence.release(run_id, "slot", "technical-worker", epoch, anchor)
            assert asyncio.run(asyncio.wait_for(supervisor.monitor(interval=0.01), 10)) == "INTERRUPTED"
            assert supervisor.time_limit_reached and supervisor.engine_exit is None
        elif scenario in {"engine_success", "engine_failure"}:
            evidence.release(run_id, "slot", "technical-worker", epoch, anchor)
            assert asyncio.run(asyncio.wait_for(supervisor.monitor(interval=0.01), 10)) == "INTERRUPTED"
            assert supervisor.engine_exit == (0 if scenario == "engine_success" else 7)
        else:
            os.kill(anchor.guardian_pid, signal.SIGKILL)
            anchor.process.wait(timeout=5)
            assert supervisor.step() == "INTERRUPTED"
        with store.connect() as db:
            assert db.execute("SELECT state FROM hermes_process_evidence WHERE run_id=?", (run_id,)).fetchone() == ("UNKNOWN",)
            assert db.execute("SELECT state FROM agent_concurrency_reservations WHERE run_id=?", (run_id,)).fetchone() == ("UNKNOWN",)
            assert db.execute("SELECT status FROM agent_runs WHERE run_id=?", (run_id,)).fetchone() == ("INTERRUPTED",)
    finally:
        if anchor.process.poll() is None:
            anchor.reclaim()
        anchor.close_control()


def test_anchor_migration_installs_in_simulation_catalog(tmp_path):
    path = tmp_path / "business.sqlite"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE objects (id TEXT)")
    result = install_simulation_migrations(path)
    assert "hermes_anchor_evidence_001" in result["installed"]
    assert install_simulation_migrations(path)["installed"] == []
