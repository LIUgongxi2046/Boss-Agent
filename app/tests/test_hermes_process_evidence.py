import json
import os
import signal
import sqlite3
import subprocess
import sys
from datetime import timedelta
from pathlib import Path

import pytest

from agent_run_concurrency import RunConcurrencyBudget
from agent_run_launch_transaction import RunLaunchTransaction
from agent_run_store import RunStore, utc_now
from hermes_process_evidence import HermesProcessEvidence
from hermes_bridge import EngineEventSink, EngineProcessSupervisor, EngineRunConfig
from hermes_budget_gateway import RunBoundBudgetStore


PROBE = Path(__file__).with_name("hermes_lifecycle_probe.py").resolve()
ANCHOR_ENGINE = Path(__file__).with_name("hermes_anchor_engine_probe.py").resolve()


def expire_lease(store, run_id):
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute("UPDATE agent_runs SET lease_expires_at=? WHERE run_id=?", ((utc_now() - timedelta(seconds=1)).isoformat(), run_id))


def running_process_store(tmp_path, ttl=60):
    store = RunStore(tmp_path / "runs.sqlite")
    budget = RunConcurrencyBudget(store, allow_migration=True)
    evidence = HermesProcessEvidence(store, allow_migration=True)
    run_id = store.create_run("boss-1", "ui-check", "request", "request-digest")
    lease = store.acquire_lease(run_id, 0, "worker", ttl)
    store.transition(run_id, lease["revision"], "RUNNING", "worker", lease["epoch"])
    budget.configure(run_id, "worker", lease["epoch"], 1)
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        budget.reserve_in_transaction(db, run_id, "worker", lease["epoch"], "slot", "digest")
    return store, budget, evidence, run_id, lease["epoch"]


def start(evidence, run_id, epoch, seconds):
    return evidence.start(run_id, "slot", "digest", "worker", epoch, "boss-1", "ui-check",
                          [sys.executable, str(PROBE), "child", str(seconds)], cwd=PROBE.parent)


def test_start_rejects_identity_and_reservation_mismatch(tmp_path):
    store, budget, evidence, run_id, epoch = running_process_store(tmp_path)
    command = [sys.executable, str(PROBE), "child", "1"]
    with pytest.raises(ValueError, match="运行身份或并发预留不可核查"):
        evidence.start(run_id, "slot", "digest", "worker", epoch, "other", "ui-check", command, cwd=PROBE.parent)
    with pytest.raises(ValueError, match="运行身份或并发预留不可核查"):
        evidence.start(run_id, "slot", "other-digest", "worker", epoch, "boss-1", "ui-check", command, cwd=PROBE.parent)
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        assert budget.release_in_transaction(db, run_id, "worker", epoch, "slot", "digest") == "RELEASED"
    with pytest.raises(ValueError, match="运行身份或并发预留不可核查"):
        start(evidence, run_id, epoch, 1)
    with store.connect() as db:
        assert db.execute("SELECT count(*) FROM hermes_process_evidence").fetchone()[0] == 0


def test_start_record_uses_shared_transaction_and_rolls_back(tmp_path):
    store, _, evidence, run_id, epoch = running_process_store(tmp_path)
    with RunLaunchTransaction(store).hold(run_id, "worker", epoch) as db:
        ticket = evidence.record_start_in_transaction(db, run_id, "slot", "digest", "worker", epoch, "boss-1", "ui-check")
        assert db.execute("SELECT state,pid FROM hermes_process_evidence WHERE run_id=?", (run_id,)).fetchone() == ("STARTING", None)
        with pytest.raises(ValueError, match="事务尚未结束"):
            evidence.start_prepared(ticket, [sys.executable, str(PROBE), "child", "1"], cwd=PROBE.parent)
        db.rollback()
    with pytest.raises(ValueError, match="启动状态不可核查"):
        evidence.start_prepared(ticket, [sys.executable, str(PROBE), "child", "1"], cwd=PROBE.parent)
    with store.connect() as db:
        assert db.execute("SELECT count(*) FROM hermes_process_evidence").fetchone() == (0,)
    pid = start(evidence, run_id, epoch, 0.2)
    process = evidence.processes[(run_id, "slot")]
    assert process.pid == pid
    process.wait(timeout=10)
    assert evidence.observe_exit(run_id, "slot")["exit_scope"] == "LEADER_ONLY"


def test_committed_start_record_can_launch_only_once(tmp_path):
    store, _, evidence, run_id, epoch = running_process_store(tmp_path)
    with RunLaunchTransaction(store).hold(run_id, "worker", epoch) as db:
        ticket = evidence.record_start_in_transaction(db, run_id, "slot", "digest", "worker", epoch, "boss-1", "ui-check")
    pid = evidence.start_prepared(ticket, [sys.executable, str(PROBE), "child", "1"], cwd=PROBE.parent)
    with pytest.raises(ValueError, match="登记不可使用"):
        evidence.start_prepared(ticket, [sys.executable, str(PROBE), "child", "1"], cwd=PROBE.parent)
    assert evidence.processes[(run_id, "slot")].pid == pid
    store.cancel(run_id, store.read_run(run_id)["revision"])
    evidence.cancel(run_id, "slot")
    evidence.processes[(run_id, "slot")].wait(timeout=10)
    assert evidence.observe_exit(run_id, "slot")["exit_scope"] == "LEADER_ONLY"


def test_cancel_after_registration_prevents_process_creation(tmp_path):
    store, budget, evidence, run_id, epoch = running_process_store(tmp_path)
    with RunLaunchTransaction(store).hold(run_id, "worker", epoch) as db:
        ticket = evidence.record_start_in_transaction(db, run_id, "slot", "digest", "worker", epoch, "boss-1", "ui-check")
    store.cancel(run_id, store.read_run(run_id)["revision"])
    with pytest.raises(ValueError):
        evidence.start_prepared(ticket, [sys.executable, str(PROBE), "child", "1"], cwd=PROBE.parent)
    assert (run_id, "slot") not in evidence.processes
    assert evidence.read(run_id, "slot")["state"] == "UNKNOWN"
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        assert budget.recover_in_transaction(db, run_id, "slot")["state"] == "UNKNOWN"


def test_failed_process_creation_keeps_unknown_evidence_and_reservation(tmp_path):
    store, budget, evidence, run_id, epoch = running_process_store(tmp_path)
    with pytest.raises(FileNotFoundError):
        evidence.start(run_id, "slot", "digest", "worker", epoch, "boss-1", "ui-check",
                       [str(tmp_path / "missing-executable")], cwd=tmp_path)
    assert evidence.read(run_id, "slot")["state"] == "UNKNOWN"
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        assert budget.recover_in_transaction(db, run_id, "slot")["state"] == "UNKNOWN"
        with pytest.raises(ValueError, match="需要核查原执行"):
            budget.release_in_transaction(db, run_id, "worker", epoch, "slot", "digest")


def test_invalid_bootstrap_is_rejected_before_process_record(tmp_path):
    store, _, evidence, run_id, epoch = running_process_store(tmp_path)
    bootstrap = {"endpoint": "http://127.0.0.1:1234", "capability": "short", "run_id": run_id,
                 "engine_commit": "903230b1e23e0c496b28e5d2e8c4f2639cd506b6"}
    with pytest.raises(ValueError, match="凭据无效"):
        evidence.start(run_id, "slot", "digest", "worker", epoch, "boss-1", "ui-check", [sys.executable, str(PROBE), "child", "1"], cwd=tmp_path, bootstrap=bootstrap)
    with store.connect() as db:
        assert db.execute("SELECT count(*) FROM hermes_process_evidence").fetchone() == (0,)


def test_exit_record_is_bound_to_actual_child_and_reservation(tmp_path):
    store, _, evidence, run_id, epoch = running_process_store(tmp_path)
    pid = start(evidence, run_id, epoch, 0.2)
    assert evidence.read(run_id, "slot")["pid"] == pid
    with pytest.raises(ValueError, match="运行尚未请求取消"):
        evidence.cancel(run_id, "slot")
    with pytest.raises(ValueError, match="进程仍在运行"):
        evidence.observe_exit(run_id, "slot")
    evidence.processes[(run_id, "slot")].wait(timeout=10)
    assert evidence.observe_exit(run_id, "slot") == {"state": "EXITED", "exit_code": 0, "exit_scope": "LEADER_ONLY"}
    assert HermesProcessEvidence(store).read(run_id, "slot")["state"] == "EXITED"
    assert evidence.observe_exit(run_id, "slot")["exit_code"] == 0
    with store.connect() as db:
        assert db.execute("SELECT state FROM agent_concurrency_reservations WHERE run_id=?", (run_id,)).fetchone() == ("ACTIVE",)


def test_cancel_records_actual_signal_exit(tmp_path):
    store, _, evidence, run_id, epoch = running_process_store(tmp_path)
    start(evidence, run_id, epoch, 5)
    store.cancel(run_id, store.read_run(run_id)["revision"])
    evidence.cancel(run_id, "slot")
    evidence.processes[(run_id, "slot")].wait(timeout=10)
    result = evidence.observe_exit(run_id, "slot")
    assert result == {"state": "EXITED", "exit_code": -signal.SIGKILL, "exit_scope": "LEADER_ONLY"}
    assert store.read_run(run_id)["status"] == "CANCEL_REQUESTED"


def test_supervisor_records_exit_before_run_failure(tmp_path):
    store, _, evidence, run_id, epoch = running_process_store(tmp_path)
    start(evidence, run_id, epoch, 0.2)
    process = evidence.processes[(run_id, "slot")]
    config = EngineRunConfig(run_id, epoch, "903230b1e23e0c496b28e5d2e8c4f2639cd506b6", "http://127.0.0.1:1234", 1)
    supervisor = EngineProcessSupervisor(EngineEventSink(store, config, "worker"), process, process_group=True, process_evidence=evidence, request_key="slot")
    process.wait(timeout=10)
    assert supervisor.observe_exit() == "FAILED"
    assert evidence.read(run_id, "slot")["exit_scope"] == "LEADER_ONLY"
    assert store.read_run(run_id)["status"] == "FAILED"


def test_supervisor_interruption_leaves_unknown_slot_occupied(tmp_path):
    store, budget, evidence, run_id, epoch = running_process_store(tmp_path, ttl=30)
    supervisor = subprocess.run([sys.executable, str(PROBE), "supervisor", str(store.path), run_id, str(epoch)], env=os.environ.copy(), check=False)
    assert supervisor.returncode == 17
    assert evidence.read(run_id, "slot")["state"] == "RUNNING"
    with pytest.raises(ValueError, match="原租约仍然有效"):
        evidence.mark_unknown(run_id, "slot")
    expire_lease(store, run_id)
    assert HermesProcessEvidence(store).mark_unknown(run_id, "slot") == "UNKNOWN"
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        assert budget.mark_unknown_in_transaction(db, run_id, "slot") == "UNKNOWN"
    record = HermesProcessEvidence(store).read(run_id, "slot")
    assert record["state"] == "UNKNOWN" and record["exit_code"] is None and record["exit_scope"] is None


def test_interruption_after_registration_preserves_unknown_slot(tmp_path):
    store, budget, evidence, run_id, epoch = running_process_store(tmp_path, ttl=30)
    supervisor = subprocess.run([sys.executable, str(PROBE), "registered", str(store.path), run_id, str(epoch)], env=os.environ.copy(), check=False)
    assert supervisor.returncode == 17
    assert evidence.read(run_id, "slot")["state"] == "STARTING"
    with pytest.raises(ValueError, match="原租约仍然有效"):
        evidence.mark_unknown(run_id, "slot")
    expire_lease(store, run_id)
    assert HermesProcessEvidence(store).mark_unknown(run_id, "slot") == "UNKNOWN"
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        assert budget.mark_unknown_in_transaction(db, run_id, "slot") == "UNKNOWN"


def test_cancel_after_leader_exit_rejects_and_keeps_child(tmp_path):
    store, _, evidence, run_id, epoch = running_process_store(tmp_path)
    child_path = tmp_path / "lingering.pid"
    evidence.start(run_id, "slot", "digest", "worker", epoch, "boss-1", "ui-check",
                   [sys.executable, str(ANCHOR_ENGINE), "lingering", str(child_path)], cwd=tmp_path)
    process = evidence.processes[(run_id, "slot")]
    process.wait(timeout=10)
    child_pid = int(child_path.read_text(encoding="utf-8"))
    store.cancel(run_id, store.read_run(run_id)["revision"])
    try:
        with pytest.raises(ValueError, match="进程组已经失效"):
            evidence.cancel(run_id, "slot")
        os.kill(child_pid, 0)
    finally:
        os.kill(child_pid, signal.SIGKILL)


def test_observe_exit_after_leader_exit_records_leader_only_with_live_child(tmp_path):
    store, _, evidence, run_id, epoch = running_process_store(tmp_path)
    child_path = tmp_path / "observed.pid"
    evidence.start(run_id, "slot", "digest", "worker", epoch, "boss-1", "ui-check",
                   [sys.executable, str(ANCHOR_ENGINE), "lingering", str(child_path)], cwd=tmp_path)
    process = evidence.processes[(run_id, "slot")]
    process.wait(timeout=10)
    child_pid = int(child_path.read_text(encoding="utf-8"))
    try:
        observed = evidence.observe_exit(run_id, "slot")
        assert observed == {"state": "EXITED", "exit_code": 0, "exit_scope": "LEADER_ONLY"}
        assert evidence.read(run_id, "slot")["exit_scope"] == "LEADER_ONLY"
        with store.connect() as db:
            assert db.execute("SELECT state FROM agent_concurrency_reservations WHERE run_id=? AND request_key=?", (run_id, "slot")).fetchone() == ("ACTIVE",)
        os.kill(child_pid, 0)
    finally:
        os.kill(child_pid, signal.SIGKILL)


def exit_supervisor(store, evidence, run_id, epoch):
    config = EngineRunConfig(run_id, epoch, "903230b1e23e0c496b28e5d2e8c4f2639cd506b6", "http://127.0.0.1:1234", 1)
    sink = EngineEventSink(store, config, "worker")
    budget = RunBoundBudgetStore(sink, allow_migration=True)
    process = evidence.processes[(run_id, "slot")]
    return EngineProcessSupervisor(sink, process, process_evidence=evidence, request_key="slot",
                                   usage_report=budget.usage_report)


def test_supervisor_exit_record_failure_skips_usage_and_preserves_error(tmp_path):
    store, _, evidence, run_id, epoch = running_process_store(tmp_path)
    evidence.start(run_id, "slot", "digest", "worker", epoch, "boss-1", "ui-check",
                   [sys.executable, str(PROBE), "child", "0.1"], cwd=PROBE.parent)
    evidence.processes[(run_id, "slot")].wait(timeout=10)
    supervisor = exit_supervisor(store, evidence, run_id, epoch)
    os.chmod(store.path, 0o444)
    try:
        with pytest.raises(sqlite3.OperationalError):
            supervisor.observe_exit()
    finally:
        os.chmod(store.path, 0o644)
    assert not any(event["type"] == "USAGE_RECORDED" for event in store.events(run_id, 0))


def test_supervisor_usage_failure_keeps_exit_evidence_and_original_error(tmp_path):
    store, _, evidence, run_id, epoch = running_process_store(tmp_path)
    evidence.start(run_id, "slot", "digest", "worker", epoch, "boss-1", "ui-check",
                   [sys.executable, str(PROBE), "child", "0.1"], cwd=PROBE.parent)
    evidence.processes[(run_id, "slot")].wait(timeout=10)
    supervisor = exit_supervisor(store, evidence, run_id, epoch)
    with store.connect() as db:
        db.execute("INSERT INTO hermes_model_requests VALUES ('bad', ?, ?, ?, 'COMPLETED', '{bad')", (run_id, run_id, epoch))
        db.commit()
    with pytest.raises(json.JSONDecodeError):
        supervisor.observe_exit()
    assert evidence.read(run_id, "slot")["state"] == "EXITED"
    assert store.read_run(run_id)["status"] == "RUNNING"
    assert not any(event["type"] == "USAGE_RECORDED" for event in store.events(run_id, 0))


def test_supervisor_dual_failure_keeps_first_exit_error(tmp_path):
    store, _, evidence, run_id, epoch = running_process_store(tmp_path)
    evidence.start(run_id, "slot", "digest", "worker", epoch, "boss-1", "ui-check",
                   [sys.executable, str(PROBE), "child", "0.1"], cwd=PROBE.parent)
    evidence.processes[(run_id, "slot")].wait(timeout=10)
    supervisor = exit_supervisor(store, evidence, run_id, epoch)
    with store.connect() as db:
        db.execute("INSERT INTO hermes_model_requests VALUES ('bad', ?, ?, ?, 'COMPLETED', '{bad')", (run_id, run_id, epoch))
        db.commit()
    os.chmod(store.path, 0o444)
    try:
        with pytest.raises(sqlite3.OperationalError):
            supervisor.observe_exit()
    finally:
        os.chmod(store.path, 0o644)
    assert not any(event["type"] == "USAGE_RECORDED" for event in store.events(run_id, 0))
