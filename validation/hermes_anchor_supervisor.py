import asyncio
import math
import os
import select
import signal
import sqlite3
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from hermes_process_anchor import AnchorProcessGroup, _require_engine_owned_by_anchor
from hermes_anchor_evidence import HermesAnchorEvidence
from hermes_bridge import EngineEventSink, EngineProcessSupervisor


class AnchorExitObserver:
    def __init__(self, anchor):
        if not isinstance(anchor, AnchorProcessGroup) or anchor.process.poll() is not None:
            raise ValueError("锚点进程不可核查")
        _require_engine_owned_by_anchor(anchor.anchor_pid, anchor.engine_pid)
        self.anchor_pid = anchor.anchor_pid
        self.engine_pid = anchor.engine_pid
        self.queue = select.kqueue()
        ready = False
        try:
            events = [select.kevent(pid, filter=select.KQ_FILTER_PROC, flags=select.KQ_EV_ADD | select.KQ_EV_ENABLE,
                                    fflags=select.KQ_NOTE_EXIT) for pid in (self.anchor_pid, self.engine_pid)]
            self.queue.control(events, 0, 0)
            ready = True
        finally:
            if not ready:
                self.queue.close()

    def poll(self, timeout=0):
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout < 0:
            raise ValueError("进程事件等待时间无效")
        events = self.queue.control(None, 2, timeout)
        for event in events:
            if event.flags & select.KQ_EV_ERROR or event.ident not in {self.anchor_pid, self.engine_pid}:
                raise ValueError("进程退出事件不可核查")
        return {event.ident for event in events if event.fflags & select.KQ_NOTE_EXIT}

    def close(self):
        self.queue.close()


@dataclass(frozen=True)
class AnchorRunState:
    status: str
    lease_owner: str
    lease_epoch: int
    lease_expires_at: str | None
    cancel_requested_at: str | None
    goal_revision: int
    waiting_input: bool
    waiting_confirmation: bool


class AnchorRunStateStore:
    def __init__(self, path):
        if not isinstance(path, (str, Path)) or not Path(path).is_file():
            raise ValueError("锚点监督状态数据库无效")
        self.path = Path(path).resolve()

    def read(self, run_id):
        if not isinstance(run_id, str) or not run_id:
            raise ValueError("锚点监督运行编号无效")
        connection = sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True)
        try:
            connection.execute("BEGIN")
            row = connection.execute(
                "SELECT status,lease_owner,lease_epoch,lease_expires_at,cancel_requested_at,goal_revision FROM agent_runs WHERE run_id=?",
                (run_id,),
            ).fetchone()
            if row is None:
                return None
            waiting_input = False
            waiting_confirmation = False
            if row[0] == "WAITING_INPUT":
                waiting_input = connection.execute(
                    "SELECT 1 FROM agent_run_events e WHERE e.run_id=? AND e.lease_epoch=? AND e.type='STATUS_CHANGED' "
                    "AND json_extract(e.payload,'$.to')='WAITING_INPUT' AND json_extract(e.payload,'$.goal_revision')=? AND "
                    "(json_extract(e.payload,'$.reason')='OUTPUT_REQUIREMENTS_UNCONFIRMED' OR "
                    "(json_extract(e.payload,'$.reason')='INPUT_REQUIRED' AND EXISTS ("
                    "SELECT 1 FROM agent_run_events q WHERE q.event_id=json_extract(e.payload,'$.input_required_event_id') "
                    "AND q.run_id=e.run_id AND q.lease_epoch=e.lease_epoch AND q.type='INPUT_REQUIRED' "
                    "AND json_extract(q.payload,'$.goal_revision')=json_extract(e.payload,'$.goal_revision'))))",
                    (run_id, row[2], row[5]),
                ).fetchone() is not None
            if row[0] == "WAITING_CONFIRMATION":
                intents = connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='agent_intents'").fetchone()
                if intents is not None:
                    waiting_confirmation = connection.execute(
                        "SELECT 1 FROM agent_run_events e JOIN agent_intents i ON i.run_id=e.run_id "
                        "AND i.intent_id=json_extract(e.payload,'$.intent_id') "
                        "WHERE e.run_id=? AND e.lease_epoch=? AND e.type='INTENT_PREPARED' "
                        "AND i.status IN ('WAITING_CONFIRMATION','SUCCEEDED','REJECTED')",
                        (run_id, row[2]),
                    ).fetchone() is not None
        finally:
            connection.close()
        return AnchorRunState(row[0], row[1], row[2], row[3], row[4], row[5], waiting_input, waiting_confirmation)


@dataclass(frozen=True)
class AnchorSupervisionResult:
    state: str
    engine_exit: int | None
    cleanup: str
    descendants: str = "NOT_VERIFIED"
    authorization: str = "NOT_VERIFIED"
    lease_renewal: str = "NOT_AVAILABLE"
    consistency: str = "SNAPSHOT_ONLY"


class AnchorSupervisor:
    def __init__(self, anchor, state_store, run_id, lease_owner, lease_epoch, max_seconds):
        if not isinstance(anchor, AnchorProcessGroup):
            raise ValueError("锚点监督需要真实锚点进程")
        if not isinstance(state_store, AnchorRunStateStore):
            raise ValueError("锚点监督需要真实状态存储")
        if not isinstance(run_id, str) or not run_id or not isinstance(lease_owner, str) or not lease_owner:
            raise ValueError("锚点监督运行身份无效")
        if type(lease_epoch) is not int or lease_epoch <= 0:
            raise ValueError("锚点监督租约代次无效")
        if isinstance(max_seconds, bool) or not isinstance(max_seconds, (int, float)) or not math.isfinite(max_seconds) or max_seconds <= 0:
            raise ValueError("锚点监督时限无效")
        self.anchor = anchor
        self.state_store = state_store
        self.run_id = run_id
        self.lease_owner = lease_owner
        self.lease_epoch = lease_epoch
        self.deadline = time.monotonic() + max_seconds
        self.result = None

    def _expired(self, state):
        if state.lease_expires_at is None:
            return True
        expires = datetime.fromisoformat(state.lease_expires_at)
        if expires.tzinfo is None:
            raise ValueError("锚点监督租约时间缺少时区")
        return expires <= datetime.now(timezone.utc)

    def _status_reason(self, state):
        if state is None:
            return "LEASE_LOST"
        if state.lease_owner != self.lease_owner or state.lease_epoch != self.lease_epoch:
            return "LEASE_LOST"
        if self._expired(state):
            return "LEASE_LOST"
        if state.status in {"SUCCEEDED", "FAILED"}:
            return state.status
        if state.status == "CANCELED":
            return "CANCELED"
        if state.status == "INTERRUPTED":
            return "INTERRUPTED"
        if state.status in {"CANCEL_REQUESTED", "RECONCILING"} or state.cancel_requested_at is not None:
            return "RECONCILING"
        if state.status == "WAITING_INPUT" and state.waiting_input:
            return "WAITING_INPUT"
        if state.status == "WAITING_CONFIRMATION" and state.waiting_confirmation:
            return "WAITING_CONFIRMATION"
        if state.status == "QUEUED" or state.status not in {"RUNNING", "WAITING_INPUT", "WAITING_CONFIRMATION"}:
            return "NOT_SUPERVISABLE"
        return None

    def _recheck(self, reason):
        current = self.state_store.read(self.run_id)
        if current is None:
            return "LEASE_LOST"
        if current.lease_owner != self.lease_owner or current.lease_epoch != self.lease_epoch:
            return "LEASE_CHANGED"
        current_reason = self._status_reason(current)
        if current_reason is not None:
            return current_reason
        if reason in {"CANCELED", "RECONCILING", "WAITING_INPUT", "WAITING_CONFIRMATION"}:
            return None
        return reason

    def _finish(self, state, engine_exit=None):
        if self.result is not None:
            return
        try:
            rechecked = self._recheck(state)
        except (sqlite3.Error, ValueError):
            rechecked = state
        if rechecked is None:
            return
        state = rechecked
        cleanup = "NOT_ATTEMPTED"
        if self.anchor.process.poll() is None:
            try:
                exit_code = self.anchor.reclaim()
            except (ValueError, OSError, subprocess.TimeoutExpired):
                cleanup = "UNVERIFIED"
            else:
                cleanup = "RECLAIMED" if exit_code == -signal.SIGKILL else "UNVERIFIED"
        else:
            cleanup = "UNVERIFIED"
        self.result = AnchorSupervisionResult(state, engine_exit, cleanup)

    def abort(self, state="SUPERVISOR_EXIT"):
        self._finish(state)

    def record_uncertain(self, evidence, request_key):
        if not isinstance(evidence, HermesAnchorEvidence) or evidence.store.path.resolve() != self.state_store.path:
            raise ValueError("锚点监督记录数据库不匹配")
        if self.result is None or self.anchor.process.poll() is None:
            raise ValueError("锚点监督尚未结束")
        return evidence.mark_uncertain(self.run_id, request_key, self.lease_owner, self.lease_epoch, self.anchor)

    def step(self):
        if self.result is not None:
            return self.result
        if self.anchor.process.poll() is not None:
            self._finish("ANCHOR_EXIT")
            return self.result
        state = self.state_store.read(self.run_id)
        reason = self._status_reason(state)
        if reason is None and time.monotonic() >= self.deadline:
            reason = "TIME_LIMIT"
        if reason is None:
            engine_exit = self.anchor.poll_engine_exit()
            if engine_exit is not None:
                reason = "FAILED" if engine_exit != 0 else "ENGINE_EXITED"
                self._finish(reason, engine_exit)
                return self.result
        if reason is not None:
            self._finish(reason)
        return self.result

    async def monitor(self, interval=0.05):
        if isinstance(interval, bool) or not isinstance(interval, (int, float)) or not math.isfinite(interval) or interval <= 0:
            raise ValueError("锚点监督检查间隔无效")
        try:
            while self.result is None:
                if self.step() is None:
                    await asyncio.sleep(interval)
            return self.result
        finally:
            if self.result is None:
                self.abort("SUPERVISOR_EXIT")


class GuardedEngineSupervisor(EngineProcessSupervisor):
    def __init__(self, sink, anchor, evidence, request_key, *, max_seconds, authority=None, usage_report=None):
        if not isinstance(sink, EngineEventSink) or not isinstance(anchor, AnchorProcessGroup) or not isinstance(evidence, HermesAnchorEvidence):
            raise ValueError("受管引擎监督需要实际运行和锚点记录")
        if evidence.store.path.resolve() != sink.store.path.resolve() or getattr(anchor, "_prepared_binding", None) != (sink.config.run_id, request_key):
            raise ValueError("受管引擎监督记录不匹配")
        with sink.store.connect() as db:
            row = db.execute("SELECT anchor_pid,engine_pid,supervisor_pid,lease_owner,lease_epoch FROM hermes_anchor_evidence WHERE run_id=? AND request_key=?", (sink.config.run_id, request_key)).fetchone()
        if row != (anchor.anchor_pid, anchor.engine_pid, os.getpid(), sink.lease_owner, sink.config.lease_epoch):
            raise ValueError("受管引擎监督身份不可核查")
        super().__init__(sink, anchor.process, process_group=True, max_seconds=max_seconds, authority=authority, usage_report=usage_report)
        self.anchor = anchor
        self.anchor_evidence = evidence
        self.anchor_request_key = request_key
        self._termination_requested = False
        self.engine_exit = None

    def _signal(self, sig):
        if self._termination_requested:
            return
        super()._signal(sig)
        self._termination_requested = True

    def step(self):
        if self.anchor.process.poll() is None:
            engine_exit = self.anchor.poll_engine_exit()
            if engine_exit is not None:
                self.engine_exit = engine_exit
                self.anchor.reclaim()
                return self.observe_exit()
        return super().step()

    def observe_exit(self):
        if self.process.poll() is None:
            raise ValueError("锚点进程仍在运行")
        self._record_usage()
        result = self.anchor_evidence.mark_uncertain(self.sink.config.run_id, self.anchor_request_key, self.sink.lease_owner,
                                                      self.sink.config.lease_epoch, self.anchor)
        return result["run_state"]

    async def monitor(self, *, interval=0.1):
        try:
            return await super().monitor(interval=interval)
        finally:
            self.anchor.close_control()
