import asyncio
import hashlib
import io
import os
import signal
from dataclasses import dataclass
from datetime import datetime
import math
from pathlib import Path
import subprocess
import tarfile
from time import monotonic
from urllib.parse import urlsplit

from agent_run_store import TRANSITIONS, utc_now
from boss_simulation_api import SimulationAPI, _context


class RequestBudgetBoundaryUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class ReadScope:
    actor_id: str
    space_id: str
    dataset_id: str
    dataset_version: str


@dataclass(frozen=True)
class EngineRunConfig:
    run_id: str
    lease_epoch: int
    engine_commit: str
    provider_url: str
    request_limit: int

    def validate(self):
        if not isinstance(self.run_id, str) or not self.run_id:
            raise ValueError("运行编号无效")
        if type(self.lease_epoch) is not int or self.lease_epoch <= 0:
            raise ValueError("租约版本无效")
        if self.engine_commit != "903230b1e23e0c496b28e5d2e8c4f2639cd506b6":
            raise ValueError("引擎版本不匹配")
        endpoint = urlsplit(self.provider_url)
        if endpoint.scheme != "http" or endpoint.hostname != "127.0.0.1" or not endpoint.port or endpoint.username or endpoint.password or endpoint.path not in ("", "/") or endpoint.query or endpoint.fragment:
            raise ValueError("Provider 入口必须是本机地址")
        if type(self.request_limit) is not int or self.request_limit <= 0:
            raise ValueError("模型请求额度无效")


@dataclass(frozen=True)
class EngineProcessConfig:
    run: EngineRunConfig
    engine_dir: Path
    source_archive: Path
    runtime_dir: Path
    python_executable: Path
    workspace_root: Path
    workspace: Path
    isolation_profile: Path
    max_rounds: int
    max_tools: int
    max_seconds: int
    max_concurrency: int
    max_context_tokens: int
    max_files: int
    max_file_bytes: int
    max_open_files: int
    max_cpu_seconds: int

    def validate_resource_limits(self):
        if type(self.max_file_bytes) is not int or self.max_file_bytes <= 0 or type(self.max_open_files) is not int or self.max_open_files < 16 or type(self.max_cpu_seconds) is not int or self.max_cpu_seconds <= 0:
            raise ValueError("进程资源预算无效")

    def validate(self):
        if not isinstance(self.run, EngineRunConfig):
            raise ValueError("缺少运行配置")
        self.run.validate()
        limits = (self.max_rounds, self.max_tools, self.max_seconds, self.max_concurrency,
                  self.max_context_tokens, self.max_files, self.max_file_bytes)
        if any(type(value) is not int or value <= 0 for value in limits):
            raise ValueError("运行预算必须包含有限正整数")
        self.validate_resource_limits()
        engine = Path(self.engine_dir).resolve(strict=True)
        runtime = Path(self.runtime_dir).resolve(strict=True)
        executable = Path(self.python_executable).resolve(strict=True)
        root = Path(self.workspace_root).resolve(strict=True)
        workspace = Path(self.workspace).resolve(strict=True)
        profile = Path(self.isolation_profile).resolve(strict=True)
        archive_path = Path(self.source_archive).resolve(strict=True)
        if not engine.is_dir() or not runtime.is_dir() or not root.is_dir() or not workspace.is_dir() or not profile.is_file() or not archive_path.is_file():
            raise ValueError("运行目录或隔离配置无效")
        if not executable.is_file() or not executable.is_relative_to(runtime) or not os.access(executable, os.X_OK):
            raise ValueError("Python 执行文件不在允许的运行目录")
        if workspace == root or not workspace.is_relative_to(root) or workspace.is_relative_to(engine) or workspace.is_relative_to(runtime) or engine.is_relative_to(workspace) or runtime.is_relative_to(workspace):
            raise ValueError("运行工作目录不在允许范围")
        with archive_path.open("rb") as archive_file:
            expected_files, expected_dirs = verify_engine_archive(archive_file, engine,
                "2902bae7c50d1a93b10cc7a42042dc0c54a40f8b665de91b54e88553f20cff7b")
        validate_engine_inventory(engine, expected_files, expected_dirs)
        from hermes_runtime_binding import require_editable_runtime_binding
        require_editable_runtime_binding(self.python_executable, engine)


_MAX_ENGINE_ARCHIVE_BYTES = 128 * 1024 * 1024


def _snapshot_engine_archive(archive_file, expected_digest):
    snapshot = archive_file.read(_MAX_ENGINE_ARCHIVE_BYTES + 1)
    if len(snapshot) > _MAX_ENGINE_ARCHIVE_BYTES:
        raise ValueError("Hermes 源码归档超出大小限制")
    if hashlib.sha256(snapshot).hexdigest() != expected_digest:
        raise ValueError("Hermes 源码归档摘要不符")
    return snapshot


def verify_engine_archive(archive_file, engine, expected_digest):
    return _verify_engine_archive_snapshot(_snapshot_engine_archive(archive_file, expected_digest), engine)


def _verify_engine_archive_snapshot(snapshot, engine):
    expected_files = set()
    expected_dirs = {Path(".")}
    with tarfile.open(fileobj=io.BytesIO(snapshot), mode="r|gz") as archive:
        for member in archive:
            parts = Path(member.name).parts
            if not parts or any(part in ("..", ".") for part in parts) or Path(member.name).is_absolute():
                raise ValueError("源码归档路径无效")
            if len(parts) == 1 and member.isdir():
                continue
            if len(parts) < 2 or not (member.isfile() or member.isdir()):
                raise ValueError("源码归档包含不支持的文件类型")
            relative = Path(*parts[1:])
            expected_dirs.update(relative.parents)
            if member.isdir():
                expected_dirs.add(relative)
                continue
            if relative in expected_files:
                raise ValueError("源码归档包含重复文件")
            expected_files.add(relative)
            target = engine.joinpath(*parts[1:]).resolve(strict=True)
            if not target.is_relative_to(engine) or not target.is_file():
                raise ValueError("源码文件路径无效")
            source = archive.extractfile(member)
            if source is None:
                raise ValueError("源码归档内容无效")
            with source, target.open("rb") as actual:
                if hashlib.file_digest(source, "sha256").digest() != hashlib.file_digest(actual, "sha256").digest():
                    raise ValueError("Hermes 源码内容与归档不符")
    return expected_files, expected_dirs


def validate_engine_inventory(engine, expected_files, expected_dirs):
    for current, directories, files in os.walk(engine, followlinks=False):
        directory = Path(current)
        for name in directories:
            path = directory / name
            if path.is_symlink() or path.relative_to(engine) not in expected_dirs:
                raise ValueError("Hermes 源码目录包含未核查目录或符号链接")
        for name in files:
            path = directory / name
            if path.is_symlink() or not path.is_file() or path.relative_to(engine) not in expected_files:
                raise ValueError("Hermes 源码目录包含未核查文件或符号链接")
            if path.stat().st_nlink != 1:
                raise ValueError("Hermes 源码文件存在其他硬链接")


ENGINE_EVENT_FIELDS = {"RUN_STARTED": {"engine_commit"}, "TOOL_STARTED": {"tool_id", "call_id"}, "TOOL_FINISHED": {"tool_id", "call_id", "outcome"}, "USAGE_RECORDED": {"requests_used", "total_tokens"}, "RUN_FINISHED": {"outcome"}, "RUN_FAILED": {"error_code"}}
USAGE_EVENT_FIELDS = frozenset({"requests_used", "total_tokens", "root_run_id", "usage_kind", "snapshot_revision", "snapshot_final", "lease_epoch", "request_limit", "known_requests", "usage_state", "known_total_tokens", "cost", "cost_state", "currency"})


class EngineEventSink:
    def __init__(self, store, config: EngineRunConfig, lease_owner: str):
        config.validate()
        if not isinstance(lease_owner, str) or not lease_owner:
            raise ValueError("租约持有者无效")
        self.store, self.config, self.lease_owner = store, config, lease_owner

    def is_cancelled(self):
        with self.store.connect() as db:
            db.execute("BEGIN")
            self.store._require_lease(db, self.config.run_id, self.lease_owner, self.config.lease_epoch)
            row = db.execute("SELECT status,cancel_requested_at FROM agent_runs WHERE run_id=?", (self.config.run_id,)).fetchone()
            return row[1] is not None or row[0] in {"CANCEL_REQUESTED", "CANCELED", "FAILED", "SUCCEEDED", "INTERRUPTED"}

    def require_tool_access(self, actor_id, space_id):
        with self.store.connect() as db:
            db.execute("BEGIN")
            from hermes_source_invalidation import require_source_cleanup_complete
            require_source_cleanup_complete(db, self.config.run_id)
            self.store._require_lease(db, self.config.run_id, self.lease_owner, self.config.lease_epoch)
            row = db.execute("SELECT actor_id,space_id,status,cancel_requested_at FROM agent_runs WHERE run_id=?", (self.config.run_id,)).fetchone()
            if row is None or (row[0], row[1]) != (actor_id, space_id) or row[2] != "RUNNING" or row[3] is not None:
                raise ValueError("运行身份、状态或取消检查未通过")
            self.store.require_active_lineage(db, self.config.run_id)

    def emit(self, origin_event_id, event_type, payload):
        if event_type not in ENGINE_EVENT_FIELDS or not isinstance(payload, dict):
            raise ValueError("引擎事件不受支持")
        if event_type == "USAGE_RECORDED":
            if not set(payload).issubset(USAGE_EVENT_FIELDS) or not {"requests_used", "total_tokens"}.issubset(payload):
                raise ValueError("引擎事件字段无效")
        elif set(payload) != ENGINE_EVENT_FIELDS[event_type]:
            raise ValueError("引擎事件字段无效")
        if event_type == "RUN_STARTED" and payload["engine_commit"] != self.config.engine_commit:
            raise ValueError("引擎事件版本不匹配")
        return self.store.append_event(self.config.run_id, self.lease_owner, self.config.lease_epoch, origin_event_id, event_type, payload)


class EngineProcessSupervisor:
    def __init__(self, sink: EngineEventSink, process: subprocess.Popen, *, cancel_grace=5, lease_ttl=None, max_seconds=None, process_group=False, process_evidence=None, request_key=None, authority=None, usage_report=None):
        if not isinstance(sink, EngineEventSink) or not isinstance(process, subprocess.Popen):
            raise ValueError("需要引擎事件入口和实际进程")
        if isinstance(cancel_grace, bool) or not isinstance(cancel_grace, (int, float)) or not math.isfinite(cancel_grace) or cancel_grace <= 0:
            raise ValueError("取消等待时间无效")
        if lease_ttl is not None and (isinstance(lease_ttl, bool) or not isinstance(lease_ttl, (int, float)) or not math.isfinite(lease_ttl) or lease_ttl <= 0):
            raise ValueError("租约续期时间无效")
        if max_seconds is not None and (isinstance(max_seconds, bool) or not isinstance(max_seconds, (int, float)) or not math.isfinite(max_seconds) or max_seconds <= 0):
            raise ValueError("运行时限无效")
        if type(process_group) is not bool:
            raise ValueError("进程组配置无效")
        if process_group and (process.poll() is not None or os.getpgid(process.pid) != process.pid or os.getsid(process.pid) != process.pid):
            raise ValueError("受管进程必须处于独立会话及进程组")
        if process_evidence is not None:
            from hermes_process_evidence import HermesProcessEvidence
            if not isinstance(process_evidence, HermesProcessEvidence) or process_evidence.store.path.resolve() != sink.store.path.resolve() or process_evidence.processes.get((sink.config.run_id, request_key)) is not process:
                raise ValueError("进程与持久记录不匹配")
        elif request_key is not None:
            raise ValueError("进程记录缺少服务")
        if authority is not None:
            from hermes_run_authority import HermesRunAuthority
            if not isinstance(authority, HermesRunAuthority) or authority.sink is not sink:
                raise ValueError("进程监督与运行授权不匹配")
        if usage_report is not None and not callable(usage_report):
            raise ValueError("usage 报告入口无效")
        self.authority = authority
        self.sink, self.process = sink, process
        self.cancel_grace = cancel_grace
        self.lease_ttl = lease_ttl
        self.cancel_sent_at = None
        self.deadline = monotonic() + max_seconds if max_seconds is not None else None
        self.time_limit_reached = False
        self.requirements_stop_sent = False
        self.intent_stop_sent = False
        self.authority_stop_sent = False
        self.process_group = process_group
        self.process_evidence = process_evidence
        self.request_key = request_key
        self.usage_report = usage_report
        self.usage_recorded = False

    def _signal(self, sig):
        if self.process_group:
            if self.process.poll() is not None or os.getpgid(self.process.pid) != self.process.pid or os.getsid(self.process.pid) != self.process.pid:
                raise ValueError("受管进程组已经失效")
            os.killpg(self.process.pid, sig)
        else:
            self.process.send_signal(sig)

    def step(self):
        if self.process.poll() is not None:
            if self.deadline is not None and monotonic() >= self.deadline:
                self.time_limit_reached = True
            return self.observe_exit()
        store, config = self.sink.store, self.sink.config
        with store.connect() as db:
            waiting = db.execute("SELECT 1 FROM agent_runs r JOIN agent_run_events e ON e.run_id=r.run_id WHERE r.run_id=? AND r.status='WAITING_INPUT' AND r.cancel_requested_at IS NULL AND e.lease_epoch=? AND e.type='STATUS_CHANGED' AND json_extract(e.payload,'$.to')='WAITING_INPUT' AND (json_extract(e.payload,'$.reason')='OUTPUT_REQUIREMENTS_UNCONFIRMED' OR (json_extract(e.payload,'$.reason')='INPUT_REQUIRED' AND EXISTS (SELECT 1 FROM agent_run_events q WHERE q.event_id=json_extract(e.payload,'$.input_required_event_id') AND q.run_id=r.run_id AND q.lease_epoch=e.lease_epoch AND q.type='INPUT_REQUIRED' AND json_extract(q.payload,'$.goal_revision')=json_extract(e.payload,'$.goal_revision'))))", (config.run_id, config.lease_epoch)).fetchone()
            intent_waiting = db.execute("SELECT 1 FROM agent_runs r JOIN agent_run_events e ON e.run_id=r.run_id JOIN agent_intents i ON i.run_id=r.run_id AND i.intent_id=json_extract(e.payload,'$.intent_id') WHERE r.run_id=? AND r.status='WAITING_CONFIRMATION' AND r.cancel_requested_at IS NULL AND e.lease_epoch=? AND e.type='INTENT_PREPARED' AND i.status IN ('WAITING_CONFIRMATION','SUCCEEDED','REJECTED')", (config.run_id, config.lease_epoch)).fetchone() if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='agent_intents'").fetchone() else None
        if waiting is not None:
            if not self.requirements_stop_sent:
                self._signal(signal.SIGKILL)
                self.requirements_stop_sent = True
                return "REQUIREMENTS_STOP_SENT"
            return "REQUIREMENTS_STOP_WAITING"
        if intent_waiting is not None:
            if not self.intent_stop_sent:
                self._signal(signal.SIGKILL)
                self.intent_stop_sent = True
                return "INTENT_STOP_SENT"
            return "INTENT_STOP_WAITING"
        with store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT lease_owner,lease_epoch,lease_expires_at,status,cancel_requested_at FROM agent_runs WHERE run_id=?", (config.run_id,)).fetchone()
            canceling = row is not None and row[4] is not None and row[3] in {"CANCEL_REQUESTED", "RECONCILING"}
            if self.authority is not None and not canceling:
                valid = False
                try:
                    self.authority.require_in_transaction(db)
                    valid = True
                finally:
                    if not valid:
                        self._signal(signal.SIGKILL)
                        self.authority_stop_sent = True
            if row is not None and row[4] is None and row[3] in {"RUNNING", "WAITING_INPUT", "WAITING_CONFIRMATION"}:
                lineage_valid = False
                try:
                    from hermes_source_invalidation import require_source_cleanup_complete
                    require_source_cleanup_complete(db, config.run_id)
                    store.require_active_lineage(db, config.run_id)
                    lineage_valid = True
                finally:
                    if not lineage_valid:
                        self._signal(signal.SIGKILL)
                        self.authority_stop_sent = True
        if row is None or row[0] != self.sink.lease_owner or row[1] != config.lease_epoch or row[2] is None or datetime.fromisoformat(row[2]) <= utc_now():
            self._signal(signal.SIGKILL)
            raise ValueError("引擎租约已经失效")
        if row[4] is None and row[3] in {"RUNNING", "WAITING_INPUT", "WAITING_CONFIRMATION"}:
            if self.deadline is not None and monotonic() >= self.deadline:
                self.time_limit_reached = True
                if self.cancel_sent_at is None:
                    self._signal(signal.SIGKILL if self.process_group else signal.SIGTERM)
                    self.cancel_sent_at = monotonic()
                    return "TIME_LIMIT_SIGNAL_SENT"
                if self.process_group:
                    return "TIME_LIMIT_WAITING"
                if monotonic() - self.cancel_sent_at >= self.cancel_grace:
                    self._signal(signal.SIGKILL)
                    return "TIME_LIMIT_STOP_SENT"
                return "TIME_LIMIT_WAITING"
            if self.lease_ttl is not None and (datetime.fromisoformat(row[2]) - utc_now()).total_seconds() <= self.lease_ttl / 2:
                store.renew_lease(config.run_id, self.sink.lease_owner, config.lease_epoch, self.lease_ttl)
            return "RUNNING"
        if self.cancel_sent_at is None:
            self._signal(signal.SIGKILL if self.process_group else signal.SIGTERM)
            self.cancel_sent_at = monotonic()
            return "CANCEL_SIGNAL_SENT"
        if self.process_group:
            return "CANCEL_WAITING"
        if monotonic() - self.cancel_sent_at >= self.cancel_grace:
            self._signal(signal.SIGKILL)
            return "CANCEL_STOP_SENT"
        return "CANCEL_WAITING"

    async def monitor(self, *, interval=0.1):
        if isinstance(interval, bool) or not isinstance(interval, (int, float)) or not math.isfinite(interval) or interval <= 0:
            raise ValueError("进程检查间隔无效")
        if self.lease_ttl is not None and interval >= self.lease_ttl / 2:
            raise ValueError("进程检查间隔超过租约续期范围")
        try:
            while True:
                state = self.step()
                if state in {"ENGINE_EXITED", "FAILED", "RECONCILING", "SUCCEEDED", "CANCELED", "INTERRUPTED", "WAITING_INPUT", "WAITING_CONFIRMATION"}:
                    return state
                await asyncio.sleep(interval)
        finally:
            if self.process.poll() is None:
                stopped = self.authority_stop_sent or self.process_group and (self.cancel_sent_at is not None or self.requirements_stop_sent or self.intent_stop_sent)
                if not stopped:
                    self._signal(signal.SIGKILL)
                self.process.wait(timeout=10)
            if self.process_evidence is not None:
                self.process_evidence.observe_exit(self.sink.config.run_id, self.request_key)
            self._record_usage()

    def _record_usage(self):
        if self.usage_report is None or self.usage_recorded:
            return
        with self.sink.store.connect() as db:
            db.execute("BEGIN")
            lease = db.execute("SELECT lease_owner,lease_epoch,lease_expires_at,status FROM agent_runs WHERE run_id=?",
                               (self.sink.config.run_id,)).fetchone()
        if lease is None or lease[0] != self.sink.lease_owner or lease[1] != self.sink.config.lease_epoch or lease[2] is None or datetime.fromisoformat(lease[2]) <= utc_now() or lease[3] in {"FAILED", "CANCELED", "SUCCEEDED", "INTERRUPTED"}:
            return
        budget = getattr(self.usage_report, "__self__", None)
        if hasattr(budget, "record_usage_snapshot"):
            budget.record_usage_snapshot()
            self.usage_recorded = True
            return
        report = self.usage_report()
        if not isinstance(report, dict):
            raise ValueError("usage 报告无效")
        requests_used, total_tokens = report.get("requests_used"), report.get("total_tokens")
        if type(requests_used) is not int or requests_used < 0 or total_tokens is not None and (type(total_tokens) is not int or total_tokens < 0):
            raise ValueError("usage 报告字段无效")
        if "snapshot_revision" in report and "root_run_id" in report:
            payload = {"root_run_id": report["root_run_id"], "usage_kind": "CUMULATIVE_SNAPSHOT",
                       "snapshot_revision": report["snapshot_revision"], "lease_epoch": self.sink.config.lease_epoch,
                       "request_limit": report["request_limit"], "requests_used": requests_used,
                       "known_requests": report["known_requests"], "usage_state": report["usage_state"],
                       "known_total_tokens": report["known_total_tokens"], "total_tokens": total_tokens,
                       "cost": report["cost"], "cost_state": report["cost_state"], "currency": report["currency"]}
        else:
            payload = {"requests_used": requests_used, "total_tokens": total_tokens}
        self.sink.emit("usage-recorded:" + self.sink.config.run_id + ":" + str(self.sink.config.lease_epoch), "USAGE_RECORDED", payload)
        self.usage_recorded = True

    def observe_exit(self):
        exit_code = self.process.poll()
        if exit_code is None:
            raise ValueError("引擎进程仍在运行")
        if self.process_evidence is not None:
            self.process_evidence.observe_exit(self.sink.config.run_id, self.request_key)
        self._record_usage()
        store, config = self.sink.store, self.sink.config
        with store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            store._require_lease_identity(db, config.run_id, self.sink.lease_owner, config.lease_epoch)
            run = db.execute("SELECT status,cancel_requested_at FROM agent_runs WHERE run_id=?", (config.run_id,)).fetchone()
            if run[0] in {"FAILED", "CANCELED", "SUCCEEDED", "INTERRUPTED"}:
                return run[0]
            if run == ("WAITING_INPUT", None) and (exit_code == 0 or self.requirements_stop_sent):
                event = db.execute("SELECT 1 FROM agent_run_events e WHERE e.run_id=? AND e.lease_epoch=? AND e.type='STATUS_CHANGED' AND json_extract(e.payload,'$.to')='WAITING_INPUT' AND (json_extract(e.payload,'$.reason')='OUTPUT_REQUIREMENTS_UNCONFIRMED' OR (json_extract(e.payload,'$.reason')='INPUT_REQUIRED' AND EXISTS (SELECT 1 FROM agent_run_events q WHERE q.event_id=json_extract(e.payload,'$.input_required_event_id') AND q.run_id=e.run_id AND q.lease_epoch=e.lease_epoch AND q.type='INPUT_REQUIRED' AND json_extract(q.payload,'$.goal_revision')=json_extract(e.payload,'$.goal_revision'))))", (config.run_id, config.lease_epoch)).fetchone()
                if event is not None:
                    return "WAITING_INPUT"
            if run == ("WAITING_CONFIRMATION", None) and (exit_code == 0 or self.intent_stop_sent):
                present = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='agent_intents'").fetchone()
                if present is not None:
                    event = db.execute("SELECT 1 FROM agent_run_events e JOIN agent_intents i ON i.run_id=e.run_id AND i.intent_id=json_extract(e.payload,'$.intent_id') WHERE e.run_id=? AND e.lease_epoch=? AND e.type='INTENT_PREPARED' AND i.status IN ('WAITING_CONFIRMATION','SUCCEEDED','REJECTED')", (config.run_id, config.lease_epoch)).fetchone()
                    if event is not None:
                        return "WAITING_CONFIRMATION"
            if run[1] is not None:
                if run[0] == "RECONCILING":
                    return "RECONCILING"
                if run[0] != "CANCEL_REQUESTED":
                    raise ValueError("取消后的运行状态不可核查")
                db.execute("UPDATE agent_runs SET status='RECONCILING',revision=revision+1 WHERE run_id=?", (config.run_id,))
                store._record_event(db, config.run_id, "STATUS_CHANGED", {"from": run[0], "to": "RECONCILING"}, config.lease_epoch)
                return "RECONCILING"
            group_unverified = self.process_group and self.cancel_sent_at is None
            if exit_code != 0 or self.time_limit_reached or group_unverified:
                if "FAILED" not in TRANSITIONS.get(run[0], set()):
                    raise ValueError("引擎退出后的运行状态无效")
                error_code = "ENGINE_TIME_LIMIT" if self.time_limit_reached else "ENGINE_GROUP_UNVERIFIED" if group_unverified else "ENGINE_PROCESS_EXIT"
                existing_failure = db.execute("SELECT 1 FROM agent_run_events WHERE run_id=? AND lease_epoch=? AND type='RUN_FAILED' LIMIT 1", (config.run_id, config.lease_epoch)).fetchone()
                if existing_failure is None:
                    store._record_event(db, config.run_id, "RUN_FAILED", {"error_code": error_code}, config.lease_epoch, "engine-process-exit")
                db.execute("UPDATE agent_runs SET status='FAILED',revision=revision+1 WHERE run_id=?", (config.run_id,))
                store._record_event(db, config.run_id, "STATUS_CHANGED", {"from": run[0], "to": "FAILED"}, config.lease_epoch)
                return "FAILED"
            return "ENGINE_EXITED"


def recover_expired_run(store, run_id):
    store.interrupt_expired(run_id)
    return store.read_run(run_id)


class HermesBridge:
    def __init__(self, store):
        self._store = store
        self._simulation = SimulationAPI(store)

    def start(self, *, run_id, lease_epoch, budget, process_config=None, run_sink=None, actor_id=None, space_id=None):
        if any(value is not None for value in (run_sink, actor_id, space_id)) and (run_sink is None or actor_id is None or space_id is None or process_config is None):
            raise ValueError("进程启动需要完整的运行入口和身份范围")
        if process_config is not None:
            if not isinstance(process_config, EngineProcessConfig) or process_config.run.run_id != run_id or process_config.run.lease_epoch != lease_epoch:
                raise ValueError("进程配置与运行不匹配")
            expected_budget = {"model_requests": process_config.run.request_limit, "rounds": process_config.max_rounds,
                               "tools": process_config.max_tools, "seconds": process_config.max_seconds,
                               "concurrency": process_config.max_concurrency, "context_tokens": process_config.max_context_tokens,
                               "files": process_config.max_files, "file_bytes": process_config.max_file_bytes,
                               "open_files": process_config.max_open_files, "cpu_seconds": process_config.max_cpu_seconds}
            if not isinstance(budget, dict) or budget != expected_budget or any(type(value) is not int for value in budget.values()):
                raise ValueError("进程预算与运行预算不匹配")
            if run_sink is not None:
                from hermes_process_manager import HermesProcessManager
                return HermesProcessManager(run_sink, process_config).start(actor_id=actor_id, space_id=space_id)
            process_config.validate()
        raise RequestBudgetBoundaryUnavailable(
            "Hermes 运行身份、进程隔离和模型请求预算边界尚未完成验证，引擎运行不可启动"
        )

    def read_documents(self, *, scope: ReadScope, source_ids: list[str]):
        with self._store.connect() as db:
            db.execute("BEGIN")
            return self.read_documents_in_transaction(db, scope=scope, source_ids=source_ids)

    def read_documents_in_transaction(self, db, *, scope: ReadScope, source_ids: list[str]):
        main = db.execute("PRAGMA database_list").fetchone()
        if not db.in_transaction or main is None or main[1] != "main" or Path(main[2]).resolve() != self._store.path.resolve():
            raise ValueError("来源读取需要当前业务数据库事务")
        if not isinstance(scope, ReadScope):
            raise ValueError("需要服务端提供读取范围")
        if not all(isinstance(value, str) and value for value in (
            scope.actor_id, scope.space_id, scope.dataset_id, scope.dataset_version
        )):
            raise ValueError("读取范围不完整")
        if not isinstance(source_ids, list) or not source_ids or any(
            not isinstance(value, str) or not value for value in source_ids
        ):
            raise ValueError("需要明确的来源编号")
        current = _context(db)
        if (current["owner_id"], current["namespace"], current["dataset_id"], current["dataset_version"]) != (
            scope.actor_id, scope.space_id, scope.dataset_id, scope.dataset_version
        ):
            raise ValueError("当前主体或资料范围不匹配")
        result = self._simulation.project_in_transaction("BOSS", db, {
            "interface_id": "SI13", "object_ids": source_ids, "filters": {},
        })
        records = result["records"]
        if any(record["entity_type"] != "document" for record in records):
            raise ValueError("读取结果包含非文档对象")
        if {record["object_id"] for record in records} != set(source_ids):
            raise ValueError("来源不存在或不可读取")
        if any(not record["source_refs"] or any(ref["status"] != "VALID" for ref in record["source_refs"]) for record in records):
            raise ValueError("来源版本无效")
        return result
