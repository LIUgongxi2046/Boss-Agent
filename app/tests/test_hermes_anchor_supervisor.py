import asyncio
import json
import os
import signal
import sqlite3
import sys
import time
from pathlib import Path

import pytest

from agent_run_store import RunStore
from hermes_anchor_supervisor import AnchorExitObserver, AnchorRunStateStore, AnchorSupervisor
from hermes_process_anchor import AnchorProcessGroup


ENGINE = Path(__file__).with_name("hermes_anchor_engine_probe.py").resolve()
ENV = {"PATH": "/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE": "1"}


def read_pid(path, timeout=10):
    deadline = time.monotonic() + timeout
    content = path.read_text(encoding="utf-8").strip() if path.exists() else ""
    while not content.isdigit() and time.monotonic() < deadline:
        time.sleep(0.02)
        content = path.read_text(encoding="utf-8").strip() if path.exists() else ""
    if not content.isdigit():
        raise AssertionError("进程编号文件未写入")
    return int(content)


def make_run(tmp_path, ttl=60):
    runs = RunStore(tmp_path / "runs.sqlite")
    run_id = runs.create_run("owner", "space", "request", "digest")
    row = runs.read_run(run_id)
    lease = runs.acquire_queued_for_execution(run_id, row["revision"], "owner", ttl)
    return runs, run_id, lease["epoch"]


def apply_intent_migration(runs):
    script = Path(__file__).resolve().parents[2] / "validation" / "migrations" / "upgrade2_intents_001.sql"
    with runs.connect() as db:
        db.executescript(script.read_text(encoding="utf-8"))


def insert_event(runs, run_id, epoch, payload, event_type="STATUS_CHANGED"):
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    with runs.connect() as db:
        seq = db.execute("SELECT coalesce(max(seq),0)+1 FROM agent_run_events WHERE run_id=?", (run_id,)).fetchone()[0]
        db.execute("INSERT INTO agent_run_events VALUES (?,?,?,?,?,?,?,?,?,?)",
                   ("event-" + str(seq), run_id, seq, "origin-" + str(seq), epoch, event_type,
                    "2026-11-01T00:00:00+00:00", "trace-" + str(seq), 1, encoded))


def stop_anchor(anchor):
    if anchor.process.poll() is None:
        anchor.reclaim()
    anchor.close_control()


def test_guarded_supervisor_reclaims_when_run_is_missing(tmp_path):
    output = tmp_path / "started"
    command = [sys.executable, "-c", "import pathlib,sys; pathlib.Path(sys.argv[1]).write_text('started')", str(output)]
    anchor = AnchorProcessGroup.start(command, cwd=tmp_path, env=ENV, deferred=True, guarded=True)
    observer = AnchorExitObserver(anchor)
    try:
        runs = RunStore(tmp_path / "runs.sqlite")
        result = AnchorSupervisor(anchor, AnchorRunStateStore(runs.path), "missing-run", "missing-worker", 1, 30).step()
        assert result.state == "LEASE_LOST"
        assert result.cleanup == "RECLAIMED"
        assert result.descendants == "NOT_VERIFIED"
        observed = observer.poll(timeout=5)
        if anchor.engine_pid not in observed:
            observed.update(observer.poll(timeout=5))
        assert anchor.engine_pid in observed
        assert not output.exists()
    finally:
        observer.close()
        stop_anchor(anchor)


def test_guarded_supervisor_marks_anchor_exit_unverified(tmp_path):
    ready = tmp_path / "engine.pid"
    anchor = AnchorProcessGroup.start([sys.executable, str(ENGINE), "ready_sleep", str(ready)],
                                      cwd=tmp_path, env=ENV, guarded=True)
    observer = AnchorExitObserver(anchor)
    try:
        assert read_pid(ready) == anchor.engine_pid
        runs = RunStore(tmp_path / "runs.sqlite")
        supervisor = AnchorSupervisor(anchor, AnchorRunStateStore(runs.path), "missing-run", "missing-worker", 1, 30)
        os.kill(anchor.anchor_pid, signal.SIGKILL)
        anchor.process.wait(timeout=5)
        result = supervisor.step()
        assert result.state == "LEASE_LOST"
        assert result.cleanup == "UNVERIFIED"
        assert result.descendants == "NOT_VERIFIED"
        observed = observer.poll(timeout=5)
        if anchor.engine_pid not in observed:
            observed.update(observer.poll(timeout=5))
        assert anchor.engine_pid in observed
    finally:
        observer.close()
        if anchor.process.poll() is None:
            anchor.reclaim()
        anchor.close_control()


def test_guardian_exit_preserves_supervisor_uncertainty(tmp_path):
    ready = tmp_path / "engine.pid"
    anchor = AnchorProcessGroup.start([sys.executable, str(ENGINE), "ready_sleep", str(ready)],
                                      cwd=tmp_path, env=ENV, guarded=True)
    observer = AnchorExitObserver(anchor)
    try:
        assert read_pid(ready) == anchor.engine_pid
        runs = RunStore(tmp_path / "runs.sqlite")
        supervisor = AnchorSupervisor(anchor, AnchorRunStateStore(runs.path), "missing-run", "missing-worker", 1, 30)
        os.kill(anchor.guardian_pid, signal.SIGKILL)
        anchor.process.wait(timeout=5)
        result = supervisor.step()
        assert result.state == "LEASE_LOST"
        assert result.cleanup == "UNVERIFIED"
        assert result.descendants == "NOT_VERIFIED"
        observed = observer.poll(timeout=5)
        if anchor.engine_pid not in observed:
            observed.update(observer.poll(timeout=5))
        assert anchor.engine_pid in observed
    finally:
        observer.close()
        if anchor.process.poll() is None:
            anchor.reclaim()
        anchor.close_control()


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_supervisor_rejects_nonfinite_time_values(tmp_path, value):
    anchor = AnchorProcessGroup.start([sys.executable, str(ENGINE), "sleep"], cwd=tmp_path, env=ENV)
    try:
        runs = RunStore(tmp_path / "runs.sqlite")
        state = AnchorRunStateStore(runs.path)
        with pytest.raises(ValueError, match="时限无效"):
            AnchorSupervisor(anchor, state, "run", "worker", 1, value)
        supervisor = AnchorSupervisor(anchor, state, "run", "worker", 1, 1)
        with pytest.raises(ValueError, match="检查间隔无效"):
            asyncio.run(supervisor.monitor(interval=value))
    finally:
        stop_anchor(anchor)


def test_supervisor_cancel_reclaims_anchor_group(tmp_path):
    child_path = tmp_path / "child.pid"
    anchor = AnchorProcessGroup.start([sys.executable, str(ENGINE), "sleep_child", str(child_path)],
                                      cwd=tmp_path, env=ENV)
    child_pid = read_pid(child_path)
    try:
        runs, run_id, epoch = make_run(tmp_path)
        runs.cancel(run_id, runs.read_run(run_id)["revision"])
        result = AnchorSupervisor(anchor, AnchorRunStateStore(runs.path), run_id, "owner", epoch, 30).step()
        assert result.state == "RECONCILING"
        assert result.cleanup == "RECLAIMED"
        assert result.descendants == "NOT_VERIFIED"
        time.sleep(0.2)
        with pytest.raises(ProcessLookupError):
            os.kill(child_pid, 0)
    finally:
        stop_anchor(anchor)
        try:
            os.kill(child_pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def test_supervisor_timeout_reclaims_anchor_group(tmp_path):
    child_path = tmp_path / "child.pid"
    anchor = AnchorProcessGroup.start([sys.executable, str(ENGINE), "sleep_child", str(child_path)],
                                      cwd=tmp_path, env=ENV)
    child_pid = read_pid(child_path)
    try:
        runs, run_id, epoch = make_run(tmp_path)
        supervisor = AnchorSupervisor(anchor, AnchorRunStateStore(runs.path), run_id, "owner", epoch, 0.1)
        time.sleep(0.2)
        result = supervisor.step()
        assert result.state == "TIME_LIMIT"
        assert result.cleanup == "RECLAIMED"
        time.sleep(0.2)
        with pytest.raises(ProcessLookupError):
            os.kill(child_pid, 0)
    finally:
        stop_anchor(anchor)
        try:
            os.kill(child_pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def test_supervisor_rejects_expired_lease(tmp_path):
    anchor = AnchorProcessGroup.start([sys.executable, "-c", "import time; time.sleep(30)"],
                                      cwd=tmp_path, env=ENV)
    try:
        runs, run_id, epoch = make_run(tmp_path, ttl=0.05)
        time.sleep(0.1)
        result = AnchorSupervisor(anchor, AnchorRunStateStore(runs.path), run_id, "owner", epoch, 30).step()
        assert result.state == "LEASE_LOST"
        assert result.cleanup == "RECLAIMED"
    finally:
        stop_anchor(anchor)


def test_supervisor_marks_terminal_state_without_engine_success(tmp_path):
    anchor = AnchorProcessGroup.start([sys.executable, "-c", "import time; time.sleep(30)"],
                                      cwd=tmp_path, env=ENV)
    try:
        runs, run_id, epoch = make_run(tmp_path)
        row = runs.read_run(run_id)
        runs.transition(run_id, row["revision"], "FAILED", "owner", epoch)
        result = AnchorSupervisor(anchor, AnchorRunStateStore(runs.path), run_id, "owner", epoch, 30).step()
        assert result.state == "FAILED"
        assert result.engine_exit is None
        assert result.cleanup == "RECLAIMED"
        assert result.authorization == "NOT_VERIFIED"
        assert result.lease_renewal == "NOT_AVAILABLE"
        assert result.consistency == "SNAPSHOT_ONLY"
    finally:
        stop_anchor(anchor)


def test_supervisor_detects_engine_exit_and_reclaims(tmp_path):
    anchor = AnchorProcessGroup.start([sys.executable, "-c", "pass"], cwd=tmp_path, env=ENV)
    try:
        runs, run_id, epoch = make_run(tmp_path)
        supervisor = AnchorSupervisor(anchor, AnchorRunStateStore(runs.path), run_id, "owner", epoch, 30)
        deadline = time.monotonic() + 10
        while supervisor.result is None and time.monotonic() < deadline:
            supervisor.step()
            time.sleep(0.02)
        assert supervisor.result is not None
        assert supervisor.result.state == "ENGINE_EXITED"
        assert supervisor.result.engine_exit == 0
        assert supervisor.result.cleanup == "RECLAIMED"
    finally:
        stop_anchor(anchor)


def test_supervisor_maps_nonzero_engine_exit_to_failed(tmp_path):
    anchor = AnchorProcessGroup.start([sys.executable, "-c", "raise SystemExit(3)"], cwd=tmp_path, env=ENV)
    try:
        runs, run_id, epoch = make_run(tmp_path)
        supervisor = AnchorSupervisor(anchor, AnchorRunStateStore(runs.path), run_id, "owner", epoch, 30)
        deadline = time.monotonic() + 10
        while supervisor.result is None and time.monotonic() < deadline:
            supervisor.step()
            time.sleep(0.02)
        assert supervisor.result.state == "FAILED"
        assert supervisor.result.engine_exit == 3
        assert supervisor.result.cleanup == "RECLAIMED"
    finally:
        stop_anchor(anchor)


def test_supervisor_requires_waiting_event_before_stopping(tmp_path):
    child_path = tmp_path / "child.pid"
    anchor = AnchorProcessGroup.start([sys.executable, str(ENGINE), "sleep_child", str(child_path)],
                                      cwd=tmp_path, env=ENV)
    child_pid = read_pid(child_path)
    try:
        runs, run_id, epoch = make_run(tmp_path)
        runs.transition(run_id, runs.read_run(run_id)["revision"], "WAITING_INPUT", "owner", epoch)
        supervisor = AnchorSupervisor(anchor, AnchorRunStateStore(runs.path), run_id, "owner", epoch, 30)
        assert supervisor.step() is None
        assert supervisor.result is None
        assert os.kill(child_pid, 0) is None
    finally:
        stop_anchor(anchor)
        try:
            os.kill(child_pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def test_supervisor_stops_on_recorded_waiting_event(tmp_path):
    child_path = tmp_path / "child.pid"
    anchor = AnchorProcessGroup.start([sys.executable, str(ENGINE), "sleep_child", str(child_path)],
                                      cwd=tmp_path, env=ENV)
    child_pid = read_pid(child_path)
    try:
        runs, run_id, epoch = make_run(tmp_path)
        runs.transition(run_id, runs.read_run(run_id)["revision"], "WAITING_INPUT", "owner", epoch)
        runs.append_event(run_id, "owner", epoch, "waiting-input-1", "STATUS_CHANGED",
                          {"to": "WAITING_INPUT", "reason": "OUTPUT_REQUIREMENTS_UNCONFIRMED", "goal_revision": 1})
        supervisor = AnchorSupervisor(anchor, AnchorRunStateStore(runs.path), run_id, "owner", epoch, 30)
        result = supervisor.step()
        assert result.state == "WAITING_INPUT"
        assert result.cleanup == "RECLAIMED"
        time.sleep(0.2)
        with pytest.raises(ProcessLookupError):
            os.kill(child_pid, 0)
    finally:
        stop_anchor(anchor)
        try:
            os.kill(child_pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def test_supervisor_stops_on_recorded_confirmation_event(tmp_path):
    child_path = tmp_path / "child.pid"
    anchor = AnchorProcessGroup.start([sys.executable, str(ENGINE), "sleep_child", str(child_path)],
                                      cwd=tmp_path, env=ENV)
    child_pid = read_pid(child_path)
    try:
        runs, run_id, epoch = make_run(tmp_path)
        apply_intent_migration(runs)
        intent_id = "intent-1"
        with runs.connect() as db:
            db.execute("INSERT INTO agent_intents VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       (intent_id, run_id, "owner", "space", "intent-request", "digest", "test-action",
                        "object-1", "1", "1", "payload", "intent-client", "{}", "WAITING_CONFIRMATION",
                        None, None, "2026-11-01T00:00:00+00:00", 0))
        runs.transition(run_id, runs.read_run(run_id)["revision"], "WAITING_CONFIRMATION", "owner", epoch)
        runs.append_event(run_id, "owner", epoch, "intent-prepared-1", "INTENT_PREPARED", {"intent_id": intent_id})
        supervisor = AnchorSupervisor(anchor, AnchorRunStateStore(runs.path), run_id, "owner", epoch, 30)
        result = supervisor.step()
        assert result.state == "WAITING_CONFIRMATION"
        assert result.cleanup == "RECLAIMED"
        time.sleep(0.2)
        with pytest.raises(ProcessLookupError):
            os.kill(child_pid, 0)
    finally:
        stop_anchor(anchor)
        try:
            os.kill(child_pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def test_supervisor_ignores_waiting_event_from_old_epoch(tmp_path):
    anchor = AnchorProcessGroup.start([sys.executable, "-c", "import time; time.sleep(30)"],
                                      cwd=tmp_path, env=ENV)
    try:
        runs, run_id, epoch = make_run(tmp_path)
        runs.transition(run_id, runs.read_run(run_id)["revision"], "WAITING_INPUT", "owner", epoch)
        insert_event(runs, run_id, 0, {"to": "WAITING_INPUT", "reason": "OUTPUT_REQUIREMENTS_UNCONFIRMED", "goal_revision": 1})
        supervisor = AnchorSupervisor(anchor, AnchorRunStateStore(runs.path), run_id, "owner", epoch, 30)
        assert supervisor.step() is None
        assert supervisor.result is None
    finally:
        stop_anchor(anchor)


def test_supervisor_ignores_waiting_event_after_goal_change(tmp_path):
    anchor = AnchorProcessGroup.start([sys.executable, "-c", "import time; time.sleep(30)"],
                                      cwd=tmp_path, env=ENV)
    try:
        runs, run_id, epoch = make_run(tmp_path)
        runs.transition(run_id, runs.read_run(run_id)["revision"], "WAITING_INPUT", "owner", epoch)
        runs.append_event(run_id, "owner", epoch, "waiting-input-goal-1", "STATUS_CHANGED",
                          {"to": "WAITING_INPUT", "reason": "OUTPUT_REQUIREMENTS_UNCONFIRMED", "goal_revision": 1})
        runs.add_input(run_id, 1, "input-after-goal", "新目标输入")
        supervisor = AnchorSupervisor(anchor, AnchorRunStateStore(runs.path), run_id, "owner", epoch, 30)
        assert supervisor.step() is None
        assert supervisor.result is None
    finally:
        stop_anchor(anchor)


def test_supervisor_rejects_lease_change_before_step(tmp_path):
    anchor = AnchorProcessGroup.start([sys.executable, "-c", "import time; time.sleep(30)"],
                                      cwd=tmp_path, env=ENV)
    try:
        runs, run_id, epoch = make_run(tmp_path)
        with runs.connect() as db:
            db.execute("UPDATE agent_runs SET lease_owner='other-owner',lease_epoch=? WHERE run_id=?", (epoch + 1, run_id))
        result = AnchorSupervisor(anchor, AnchorRunStateStore(runs.path), run_id, "owner", epoch, 30).step()
        assert result.state == "LEASE_CHANGED"
        assert result.consistency == "SNAPSHOT_ONLY"
    finally:
        stop_anchor(anchor)


def test_supervisor_rejects_queued_state(tmp_path):
    anchor = AnchorProcessGroup.start([sys.executable, "-c", "import time; time.sleep(30)"],
                                      cwd=tmp_path, env=ENV)
    try:
        runs, run_id, epoch = make_run(tmp_path)
        with runs.connect() as db:
            db.execute("UPDATE agent_runs SET status='QUEUED' WHERE run_id=?", (run_id,))
        result = AnchorSupervisor(anchor, AnchorRunStateStore(runs.path), run_id, "owner", epoch, 30).step()
        assert result.state == "NOT_SUPERVISABLE"
        assert result.cleanup == "RECLAIMED"
    finally:
        stop_anchor(anchor)


def test_supervisor_cleans_up_after_state_read_exception(tmp_path):
    anchor = AnchorProcessGroup.start([sys.executable, "-c", "import time; time.sleep(30)"],
                                      cwd=tmp_path, env=ENV)
    empty = tmp_path / "not-a-run-store.sqlite"
    with sqlite3.connect(empty):
        pass
    try:
        supervisor = AnchorSupervisor(anchor, AnchorRunStateStore(empty), "run-1", "owner", 1, 30)
        with pytest.raises(sqlite3.OperationalError):
            asyncio.run(supervisor.monitor(interval=0.01))
        assert supervisor.result.cleanup == "RECLAIMED"
        assert supervisor.result.descendants == "NOT_VERIFIED"
    finally:
        stop_anchor(anchor)


def test_supervisor_marks_anchor_exit_unverified(tmp_path):
    child_path = tmp_path / "child.pid"
    anchor = AnchorProcessGroup.start([sys.executable, str(ENGINE), "sleep_child", str(child_path)],
                                      cwd=tmp_path, env=ENV)
    child_pid = read_pid(child_path)
    try:
        runs, run_id, epoch = make_run(tmp_path)
        supervisor = AnchorSupervisor(anchor, AnchorRunStateStore(runs.path), run_id, "owner", epoch, 30)
        os.kill(anchor.anchor_pid, signal.SIGKILL)
        anchor.process.wait(timeout=10)
        supervisor.abort("ANCHOR_EXIT")
        assert supervisor.result.cleanup == "UNVERIFIED"
        assert supervisor.result.descendants == "NOT_VERIFIED"
        os.kill(child_pid, 0)
    finally:
        stop_anchor(anchor)
        try:
            os.kill(anchor.engine_pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        try:
            os.kill(child_pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def test_supervisor_does_not_claim_detached_descendant_cleanup(tmp_path):
    child_path = tmp_path / "detached.pid"
    anchor = AnchorProcessGroup.start([sys.executable, str(ENGINE), "detached", str(child_path)],
                                      cwd=tmp_path, env=ENV)
    child_pid = None
    try:
        child_pid = read_pid(child_path)
        runs, run_id, epoch = make_run(tmp_path)
        supervisor = AnchorSupervisor(anchor, AnchorRunStateStore(runs.path), run_id, "owner", epoch, 30)
        deadline = time.monotonic() + 10
        while supervisor.result is None and time.monotonic() < deadline:
            supervisor.step()
            time.sleep(0.02)
        assert supervisor.result.state == "ENGINE_EXITED"
        assert supervisor.result.descendants == "NOT_VERIFIED"
    finally:
        stop_anchor(anchor)
        if child_pid is not None:
            try:
                os.kill(child_pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
