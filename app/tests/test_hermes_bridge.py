import asyncio
import hashlib
import os
import select
import signal
import sqlite3
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "validation"))

from boss_comprehensive_simulation import populate
from controls import ControlStore
from hermes_bridge import HermesBridge, ReadScope, RequestBudgetBoundaryUnavailable, EngineRunConfig, EngineProcessConfig, EngineEventSink, EngineProcessSupervisor, recover_expired_run, validate_engine_inventory, _snapshot_engine_archive, _verify_engine_archive_snapshot, _MAX_ENGINE_ARCHIVE_BYTES
from hermes_process_manager import HermesProcessManager
from agent_run_store import RunStore


def test_archive_verification_keeps_open_file_across_path_replacement(tmp_path):
    engine = tmp_path / "engine"
    engine.mkdir()
    original = engine / "version.txt"
    original.write_text("独立技术资料", encoding="utf-8")
    other = tmp_path / "other.txt"
    other.write_text("其他技术资料", encoding="utf-8")
    archive = tmp_path / "source.tar.gz"
    replacement = tmp_path / "replacement.tar.gz"
    with tarfile.open(archive, "w:gz") as output:
        output.add(original, arcname="source/version.txt")
    with tarfile.open(replacement, "w:gz") as output:
        output.add(other, arcname="source/version.txt")
    original_link = tmp_path / "original.tar.gz"
    os.link(archive, original_link)
    with archive.open("rb") as opened:
        digest = hashlib.file_digest(opened, "sha256").hexdigest()
        opened.seek(0)
        subprocess.run([sys.executable, "-c", "import os,sys; os.replace(sys.argv[1],sys.argv[2])",
                        str(replacement), str(archive)], check=True, timeout=10)
        snapshot = _snapshot_engine_archive(opened, digest)
        with archive.open("rb") as current:
            assert hashlib.file_digest(current, "sha256").hexdigest() != digest
        subprocess.run([sys.executable, "-c", "import sys; open(sys.argv[1],'r+b').write(b'changed')",
                        str(original_link)], check=True, timeout=10)
        opened.seek(0)
        assert hashlib.file_digest(opened, "sha256").hexdigest() != digest
        opened.seek(0)
        with pytest.raises(ValueError, match="摘要不符"):
            _snapshot_engine_archive(opened, digest)
        files, directories = _verify_engine_archive_snapshot(snapshot, engine)
        assert files == {Path("version.txt")} and directories == {Path(".")}


def test_archive_snapshot_rejects_oversized_file(tmp_path):
    archive = tmp_path / "oversized.tar.gz"
    with archive.open("wb") as output:
        output.truncate(_MAX_ENGINE_ARCHIVE_BYTES + 1)
    with archive.open("rb") as opened, pytest.raises(ValueError, match="超出大小限制"):
        _snapshot_engine_archive(opened, "0" * 64)


def test_engine_inventory_rejects_extra_files_directories_and_symlinks(tmp_path):
    engine = tmp_path / "engine"
    engine.mkdir()
    directory = engine / "source"
    directory.mkdir()
    present = directory / "version.txt"
    present.write_text("技术核查", encoding="utf-8")
    files = {Path("source/version.txt")}
    directories = {Path("."), Path("source")}
    validate_engine_inventory(engine, files, directories)
    extra = directory / "extra.txt"
    extra.write_text("技术核查", encoding="utf-8")
    with pytest.raises(ValueError, match="未核查文件"):
        validate_engine_inventory(engine, files, directories)
    extra.unlink()
    other = engine / "other"
    other.mkdir()
    with pytest.raises(ValueError, match="未核查目录"):
        validate_engine_inventory(engine, files, directories)
    other.rmdir()
    alias = directory / "alias"
    alias.symlink_to(present)
    with pytest.raises(ValueError, match="符号链接"):
        validate_engine_inventory(engine, files, directories)
    alias.unlink()
    external = tmp_path / "external-link"
    os.link(present, external)
    with pytest.raises(ValueError, match="其他硬链接"):
        validate_engine_inventory(engine, files, directories)


@pytest.fixture
def bridge(tmp_path):
    store = ControlStore(tmp_path / "business.sqlite")
    store.initialize("ui-check")
    populate(store, "2026-10-28T10:00:00+08:00")
    return HermesBridge(store), tmp_path / "business.sqlite"


def test_read_valid_source_and_reject_scope_and_missing_source(bridge):
    adapter, database = bridge
    scope = ReadScope("boss-1", "ui-check", "selection", "1")
    before = hashlib.sha256(database.read_bytes()).hexdigest()
    result = adapter.read_documents(scope=scope, source_ids=["finance-note"])
    assert result["source_type"] == "SIMULATED"
    assert result["records"][0]["source_refs"][0]["status"] == "VALID"
    with pytest.raises(ValueError):
        adapter.read_documents(scope=ReadScope("boss-1", "ui-check", "selection", "old"), source_ids=["finance-note"])
    with pytest.raises(ValueError):
        adapter.read_documents(scope=scope, source_ids=["unknown"])
    assert hashlib.sha256(database.read_bytes()).hexdigest() == before


def test_document_read_requires_matching_transaction_and_current_source(bridge, tmp_path):
    adapter, database = bridge
    scope = ReadScope("boss-1", "ui-check", "selection", "1")
    with sqlite3.connect(database) as db:
        with pytest.raises(ValueError, match="数据库事务"):
            adapter.read_documents_in_transaction(db, scope=scope, source_ids=["finance-note"])
        db.execute("BEGIN")
        result = adapter.read_documents_in_transaction(db, scope=scope, source_ids=["finance-note"])
        assert result["source_type"] == "SIMULATED"
        assert result["records"][0]["source_refs"][0]["status"] == "VALID"
    with sqlite3.connect(tmp_path / "other.sqlite") as db:
        db.execute("BEGIN")
        with pytest.raises(ValueError, match="数据库事务"):
            adapter.read_documents_in_transaction(db, scope=scope, source_ids=["finance-note"])
    store = ControlStore(database)
    store.control("ui-check", "withdraw", {"source_id": "finance-note", "version": "1"})
    with sqlite3.connect(database) as db:
        db.execute("BEGIN")
        with pytest.raises(ValueError):
            adapter.read_documents_in_transaction(db, scope=scope, source_ids=["finance-note"])


def test_refuses_start_without_enforced_request_budget(bridge):
    adapter, _ = bridge
    with pytest.raises(RequestBudgetBoundaryUnavailable):
        adapter.start(run_id="run-1", lease_epoch=1, budget={"model_requests": 1})
    with pytest.raises(ValueError, match="完整"):
        adapter.start(run_id="run-1", lease_epoch=1, budget={}, actor_id="boss-1")


def test_event_sink_uses_current_lease_and_respects_cancellation(tmp_path):
    store = RunStore(tmp_path / "runs.sqlite")
    run_id = store.create_run("boss-1", "space-1", "request-1", "digest-1")
    lease = store.acquire_lease(run_id, 0, "worker-1", 60)
    config = EngineRunConfig(run_id, lease["epoch"], "903230b1e23e0c496b28e5d2e8c4f2639cd506b6", "http://127.0.0.1:1234", 3)
    sink = EngineEventSink(store, config, "worker-1")
    event = sink.emit("origin-1", "RUN_STARTED", {"engine_commit": config.engine_commit})
    assert sink.emit("origin-1", "RUN_STARTED", {"engine_commit": config.engine_commit}) == event
    assert store.events(run_id, 0)[0]["type"] == "RUN_STARTED"
    with pytest.raises(ValueError):
        sink.emit("origin-2", "TOOL_STARTED", {"tool_id": "read", "call_id": "one", "private": "text"})
    revision = store.read_run(run_id)["revision"]
    store.cancel(run_id, revision)
    assert sink.is_cancelled()
    with pytest.raises(ValueError):
        sink.emit("origin-3", "TOOL_STARTED", {"tool_id": "read", "call_id": "one"})


def test_engine_configuration_rejects_untrusted_endpoint():
    config = EngineRunConfig("run-1", 1, "903230b1e23e0c496b28e5d2e8c4f2639cd506b6", "https://api.deepseek.com", 1)
    with pytest.raises(ValueError):
        config.validate()


def test_process_configuration_rejects_invalid_budget_and_run_binding(bridge, tmp_path):
    run = EngineRunConfig("run-1", 1, "903230b1e23e0c496b28e5d2e8c4f2639cd506b6", "http://127.0.0.1:1234", 1)
    config = EngineProcessConfig(run, tmp_path, tmp_path, tmp_path, tmp_path, tmp_path, tmp_path, tmp_path, 1, 1, 1, 1, 1, 1, 0, 32, 1)
    with pytest.raises(ValueError, match="预算"):
        config.validate()
    with pytest.raises(ValueError, match="运行不匹配"):
        bridge[0].start(run_id="other", lease_epoch=1, budget={}, process_config=config)
    with pytest.raises(ValueError, match="预算"):
        bridge[0].start(run_id="run-1", lease_epoch=1, budget={}, process_config=config)
    supplied = {"model_requests": True, "rounds": 1, "tools": 1, "seconds": 1, "concurrency": 1, "context_tokens": 1, "files": 1, "file_bytes": 0}
    with pytest.raises(ValueError, match="预算"):
        bridge[0].start(run_id="run-1", lease_epoch=1, budget=supplied, process_config=config)


def test_process_manager_rejects_mismatched_run(tmp_path):
    store = RunStore(tmp_path / "runs.sqlite")
    run_id = store.create_run("boss-1", "space-1", "manager", "digest")
    lease = store.acquire_lease(run_id, 0, "worker", 60)
    config = EngineRunConfig(run_id, lease["epoch"], "903230b1e23e0c496b28e5d2e8c4f2639cd506b6", "http://127.0.0.1:1234", 1)
    other = EngineRunConfig(run_id, lease["epoch"], config.engine_commit, config.provider_url, 2)
    process_config = EngineProcessConfig(other, tmp_path, tmp_path, tmp_path, tmp_path, tmp_path, tmp_path, tmp_path, 1, 1, 1, 1, 1, 1, 1, 32, 1)
    with pytest.raises(ValueError, match="不匹配"):
        HermesProcessManager(EngineEventSink(store, config, "worker"), process_config)


def test_process_configuration_rejects_workspace_root(tmp_path):
    run = EngineRunConfig("run-1", 1, "903230b1e23e0c496b28e5d2e8c4f2639cd506b6", "http://127.0.0.1:1234", 1)
    executable = Path(sys.executable).resolve()
    config = EngineProcessConfig(run, tmp_path, executable, executable.parent, executable, tmp_path, tmp_path, executable, 1, 1, 1, 1, 1, 1, 1, 32, 1)
    with pytest.raises(ValueError, match="工作目录"):
        config.validate()


def test_process_configuration_rejects_wrong_archive(tmp_path):
    run = EngineRunConfig("run-1", 1, "903230b1e23e0c496b28e5d2e8c4f2639cd506b6", "http://127.0.0.1:1234", 1)
    executable = Path(sys.executable).resolve()
    engine = tmp_path / "engine"
    root = tmp_path / "workspaces"
    workspace = root / "run"
    engine.mkdir()
    workspace.mkdir(parents=True)
    config = EngineProcessConfig(run, engine, executable, executable.parent, executable, root, workspace, executable, 1, 1, 1, 1, 1, 1, 1, 32, 1)
    with pytest.raises(ValueError, match="归档摘要"):
        config.validate()


def test_engine_failure_event_uses_run_event_storage(tmp_path):
    store = RunStore(tmp_path / "runs.sqlite")
    run_id = store.create_run("boss-1", "space-1", "request-2", "digest-2")
    lease = store.acquire_lease(run_id, 0, "worker-1", 60)
    config = EngineRunConfig(run_id, lease["epoch"], "903230b1e23e0c496b28e5d2e8c4f2639cd506b6", "http://127.0.0.1:1234", 3)
    sink = EngineEventSink(store, config, "worker-1")
    sink.emit("failure-1", "RUN_FAILED", {"error_code": "ENGINE_INCOMPLETE"})
    event = store.events(run_id, 0)[0]
    assert event["type"] == "RUN_FAILED"
    assert event["payload"] == {"error_code": "ENGINE_INCOMPLETE"}
    with pytest.raises(ValueError):
        EngineEventSink(store, config, "other-worker").emit("failure-2", "RUN_FAILED", {"error_code": "ENGINE_INCOMPLETE"})


@pytest.mark.parametrize("cancel,exit_code,expected", [(True, 0, "RECONCILING"), (False, 4, "FAILED")])
def test_process_exit_updates_state_conservatively(tmp_path, cancel, exit_code, expected):
    store = RunStore(tmp_path / "runs.sqlite")
    run_id = store.create_run("boss-1", "space-1", "request-3", "digest-3")
    lease = store.acquire_lease(run_id, 0, "worker-1", 60)
    store.transition(run_id, store.read_run(run_id)["revision"], "RUNNING", "worker-1", lease["epoch"])
    config = EngineRunConfig(run_id, lease["epoch"], "903230b1e23e0c496b28e5d2e8c4f2639cd506b6", "http://127.0.0.1:1234", 3)
    sink = EngineEventSink(store, config, "worker-1")
    if cancel:
        store.cancel(run_id, store.read_run(run_id)["revision"])
    process = subprocess.Popen([sys.executable, "-c", f"raise SystemExit({exit_code})"])
    process.wait(timeout=10)
    assert EngineProcessSupervisor(sink, process).observe_exit() == expected
    assert store.read_run(run_id)["status"] == expected
    events = store.events(run_id, 0)
    assert any(event["type"] == "RUN_FAILED" for event in events) is (not cancel)
    assert EngineProcessSupervisor(sink, process).observe_exit() == expected
    assert store.events(run_id, 0) == events


def test_supervisor_stops_owned_process_on_cancel(tmp_path):
    store = RunStore(tmp_path / "runs.sqlite")
    run_id = store.create_run("boss-1", "space-1", "request-4", "digest-4")
    lease = store.acquire_lease(run_id, 0, "worker-1", 60)
    store.transition(run_id, store.read_run(run_id)["revision"], "RUNNING", "worker-1", lease["epoch"])
    config = EngineRunConfig(run_id, lease["epoch"], "903230b1e23e0c496b28e5d2e8c4f2639cd506b6", "http://127.0.0.1:1234", 3)
    sink = EngineEventSink(store, config, "worker-1")
    process = subprocess.Popen([sys.executable, "-c", "input()"], stdin=subprocess.PIPE)
    supervisor = EngineProcessSupervisor(sink, process)
    assert supervisor.step() == "RUNNING"
    store.cancel(run_id, store.read_run(run_id)["revision"])
    assert supervisor.step() == "CANCEL_SIGNAL_SENT"
    process.wait(timeout=10)
    assert supervisor.step() == "RECONCILING"
    assert supervisor.step() == "RECONCILING"
    assert store.read_run(run_id)["status"] == "RECONCILING"


def test_supervisor_stops_owned_process_at_time_limit(tmp_path):
    store = RunStore(tmp_path / "runs.sqlite")
    run_id = store.create_run("boss-1", "space-1", "time-limit", "digest")
    lease = store.acquire_lease(run_id, 0, "worker", 60)
    store.transition(run_id, store.read_run(run_id)["revision"], "RUNNING", "worker", lease["epoch"])
    config = EngineRunConfig(run_id, lease["epoch"], "903230b1e23e0c496b28e5d2e8c4f2639cd506b6", "http://127.0.0.1:1234", 1)
    process = subprocess.Popen([sys.executable, "-c", "input()"], stdin=subprocess.PIPE)
    supervisor = EngineProcessSupervisor(EngineEventSink(store, config, "worker"), process, max_seconds=0.1)
    assert asyncio.run(supervisor.monitor(interval=0.02)) == "FAILED"
    assert process.poll() is not None
    assert store.read_run(run_id)["status"] == "FAILED"
    failures = [event for event in store.events(run_id, 0) if event["type"] == "RUN_FAILED"]
    assert failures[0]["payload"]["error_code"] == "ENGINE_TIME_LIMIT"


@pytest.mark.parametrize("cancel", [False, True])
def test_supervisor_signals_owned_child_process_group(tmp_path, cancel):
    store = RunStore(tmp_path / "runs.sqlite")
    run_id = store.create_run("boss-1", "space-1", "group-time-limit", "digest")
    lease = store.acquire_lease(run_id, 0, "worker", 60)
    store.transition(run_id, store.read_run(run_id)["revision"], "RUNNING", "worker", lease["epoch"])
    config = EngineRunConfig(run_id, lease["epoch"], "903230b1e23e0c496b28e5d2e8c4f2639cd506b6", "http://127.0.0.1:1234", 1)
    child_code = "import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); print('ready',flush=True); time.sleep(60)"
    parent_code = "import subprocess,sys,time; subprocess.Popen([sys.executable,'-c',sys.argv[1]]); time.sleep(60)"
    process = subprocess.Popen([sys.executable, "-c", parent_code, child_code], stdout=subprocess.PIPE, bufsize=0, start_new_session=True)
    assert process.stdout.readline().strip() == b"ready"
    supervisor = EngineProcessSupervisor(EngineEventSink(store, config, "worker"), process, max_seconds=0.1, process_group=True)
    if cancel:
        store.cancel(run_id, store.read_run(run_id)["revision"])
    assert asyncio.run(supervisor.monitor(interval=0.02)) == ("RECONCILING" if cancel else "FAILED")
    assert select.select([process.stdout], [], [], 5)[0]
    assert os.read(process.stdout.fileno(), 1) == b""
    assert process.poll() is not None


def test_supervisor_rejects_shared_process_group(tmp_path):
    store = RunStore(tmp_path / "runs.sqlite")
    run_id = store.create_run("boss-1", "space-1", "shared-group", "digest")
    lease = store.acquire_lease(run_id, 0, "worker", 60)
    config = EngineRunConfig(run_id, lease["epoch"], "903230b1e23e0c496b28e5d2e8c4f2639cd506b6", "http://127.0.0.1:1234", 1)
    process = subprocess.Popen([sys.executable, "-c", "input()"], stdin=subprocess.PIPE)
    try:
        with pytest.raises(ValueError, match="独立会话"):
            EngineProcessSupervisor(EngineEventSink(store, config, "worker"), process, process_group=True)
    finally:
        process.terminate()
        process.wait(timeout=10)


def test_group_leader_exit_does_not_report_success(tmp_path):
    store = RunStore(tmp_path / "runs.sqlite")
    run_id = store.create_run("boss-1", "space-1", "leader-exit", "digest")
    lease = store.acquire_lease(run_id, 0, "worker", 60)
    store.transition(run_id, store.read_run(run_id)["revision"], "RUNNING", "worker", lease["epoch"])
    config = EngineRunConfig(run_id, lease["epoch"], "903230b1e23e0c496b28e5d2e8c4f2639cd506b6", "http://127.0.0.1:1234", 1)
    child_code = "import os,time; print(os.getpid(),flush=True); time.sleep(60)"
    parent_code = "import subprocess,sys; subprocess.Popen([sys.executable,'-c',sys.argv[1]]); input()"
    process = subprocess.Popen([sys.executable, "-c", parent_code, child_code], stdin=subprocess.PIPE, stdout=subprocess.PIPE, bufsize=0, start_new_session=True)
    supervisor = EngineProcessSupervisor(EngineEventSink(store, config, "worker"), process, process_group=True)
    child_pid = int(process.stdout.readline().strip())
    try:
        process.stdin.write(b"\n")
        process.stdin.flush()
        process.wait(timeout=10)
        assert supervisor.step() == "FAILED"
        os.kill(child_pid, 0)
        event = next(event for event in store.events(run_id, 0) if event["type"] == "RUN_FAILED")
        assert event["payload"]["error_code"] == "ENGINE_GROUP_UNVERIFIED"
    finally:
        os.kill(child_pid, signal.SIGKILL)
    assert select.select([process.stdout], [], [], 5)[0]
    assert os.read(process.stdout.fileno(), 1) == b""


def test_reaped_leader_does_not_use_saved_group_number(tmp_path):
    store = RunStore(tmp_path / "runs.sqlite")
    run_id = store.create_run("boss-1", "space-1", "reaped-leader", "digest")
    lease = store.acquire_lease(run_id, 0, "worker", 60)
    store.transition(run_id, store.read_run(run_id)["revision"], "RUNNING", "worker", lease["epoch"])
    config = EngineRunConfig(run_id, lease["epoch"], "903230b1e23e0c496b28e5d2e8c4f2639cd506b6", "http://127.0.0.1:1234", 1)
    child_code = "import os,time; print(os.getpid(),flush=True); time.sleep(60)"
    parent_code = "import subprocess,sys; subprocess.Popen([sys.executable,'-c',sys.argv[1]]); input()"
    process = subprocess.Popen([sys.executable, "-c", parent_code, child_code], stdin=subprocess.PIPE, stdout=subprocess.PIPE, bufsize=0, start_new_session=True)
    supervisor = EngineProcessSupervisor(EngineEventSink(store, config, "worker"), process, process_group=True)
    child_pid = int(process.stdout.readline().strip())
    try:
        process.stdin.write(b"\n")
        process.stdin.flush()
        process.wait(timeout=10)
        os.kill(child_pid, 0)
        assert supervisor.observe_exit() == "FAILED"
        os.kill(child_pid, 0)
    finally:
        os.kill(child_pid, signal.SIGKILL)


def test_group_signal_does_not_prove_detached_process_cleanup(tmp_path):
    store = RunStore(tmp_path / "runs.sqlite")
    run_id = store.create_run("boss-1", "space-1", "detached-child", "digest")
    lease = store.acquire_lease(run_id, 0, "worker", 60)
    store.transition(run_id, store.read_run(run_id)["revision"], "RUNNING", "worker", lease["epoch"])
    config = EngineRunConfig(run_id, lease["epoch"], "903230b1e23e0c496b28e5d2e8c4f2639cd506b6", "http://127.0.0.1:1234", 1)
    child_code = "import os,time; print(os.getpid(),flush=True); time.sleep(60)"
    parent_code = "import subprocess,sys,time; subprocess.Popen([sys.executable,'-c',sys.argv[1]],start_new_session=True); time.sleep(60)"
    process = subprocess.Popen([sys.executable, "-c", parent_code, child_code], stdout=subprocess.PIPE, bufsize=0, start_new_session=True)
    supervisor = EngineProcessSupervisor(EngineEventSink(store, config, "worker"), process, max_seconds=0.1, process_group=True)
    child_pid = int(process.stdout.readline().strip())
    try:
        assert asyncio.run(supervisor.monitor(interval=0.02)) == "FAILED"
        os.kill(child_pid, 0)
    finally:
        os.kill(child_pid, signal.SIGKILL)
    assert select.select([process.stdout], [], [], 5)[0]
    assert os.read(process.stdout.fileno(), 1) == b""


def test_supervisor_stops_owned_process_when_lease_lost(tmp_path):
    store = RunStore(tmp_path / "runs.sqlite")
    run_id = store.create_run("boss-1", "space-1", "request-5", "digest-5")
    lease = store.acquire_lease(run_id, 0, "worker-1", 60)
    store.transition(run_id, store.read_run(run_id)["revision"], "RUNNING", "worker-1", lease["epoch"])
    config = EngineRunConfig(run_id, lease["epoch"], "903230b1e23e0c496b28e5d2e8c4f2639cd506b6", "http://127.0.0.1:1234", 3)
    process = subprocess.Popen([sys.executable, "-c", "input()"], stdin=subprocess.PIPE)
    supervisor = EngineProcessSupervisor(EngineEventSink(store, config, "worker-1"), process)
    store.release_lease(run_id, "worker-1", lease["epoch"])
    with pytest.raises(ValueError):
        supervisor.step()
    process.wait(timeout=10)
    assert process.returncode != 0


def test_supervisor_monitor_cleanup_on_task_cancellation(tmp_path):
    store = RunStore(tmp_path / "runs.sqlite")
    run_id = store.create_run("boss-1", "space-1", "request-6", "digest-6")
    lease = store.acquire_lease(run_id, 0, "worker-1", 60)
    store.transition(run_id, store.read_run(run_id)["revision"], "RUNNING", "worker-1", lease["epoch"])
    config = EngineRunConfig(run_id, lease["epoch"], "903230b1e23e0c496b28e5d2e8c4f2639cd506b6", "http://127.0.0.1:1234", 3)
    process = subprocess.Popen([sys.executable, "-c", "input()"], stdin=subprocess.PIPE)
    supervisor = EngineProcessSupervisor(EngineEventSink(store, config, "worker-1"), process)

    async def exercise():
        task = asyncio.create_task(supervisor.monitor(interval=0.01))
        await asyncio.sleep(0.02)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(exercise())
    assert process.poll() is not None


def test_monitor_renews_lease_for_live_process(tmp_path):
    store = RunStore(tmp_path / "runs.sqlite")
    run_id = store.create_run("boss-1", "space-1", "request-7", "digest-7")
    lease = store.acquire_lease(run_id, 0, "worker-1", 5)
    store.transition(run_id, store.read_run(run_id)["revision"], "RUNNING", "worker-1", lease["epoch"])
    config = EngineRunConfig(run_id, lease["epoch"], "903230b1e23e0c496b28e5d2e8c4f2639cd506b6", "http://127.0.0.1:1234", 3)
    process = subprocess.Popen([sys.executable, "-c", "input()"], stdin=subprocess.PIPE)
    supervisor = EngineProcessSupervisor(EngineEventSink(store, config, "worker-1"), process, lease_ttl=5)

    async def exercise():
        monitoring = asyncio.create_task(supervisor.monitor(interval=0.05))
        deadline = asyncio.get_running_loop().time() + 8
        current = store.read_run(run_id)
        while current["lease_expires_at"] <= lease["expires_at"] and asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(0.05)
            current = store.read_run(run_id)
        assert current["lease_epoch"] == lease["epoch"]
        assert current["lease_expires_at"] > lease["expires_at"]
        store.cancel(run_id, current["revision"])
        assert await monitoring == "RECONCILING"

    asyncio.run(exercise())
    assert process.poll() is not None


def test_expired_run_recovery_does_not_restart_process(tmp_path):
    path = tmp_path / "runs.sqlite"
    store = RunStore(path)
    run_id = store.create_run("boss-1", "space-1", "request-8", "digest-8")
    lease = store.acquire_lease(run_id, 0, "worker-1", 1)
    store.transition(run_id, store.read_run(run_id)["revision"], "RUNNING", "worker-1", lease["epoch"])
    process = subprocess.Popen([sys.executable, "-c", "raise SystemExit(1)"])
    process.wait(timeout=10)
    with pytest.raises(ValueError):
        recover_expired_run(store, run_id)
    asyncio.run(asyncio.sleep(1.1))
    reopened = RunStore(path, allow_migration=False)
    recovered = recover_expired_run(reopened, run_id)
    assert recovered["status"] == "INTERRUPTED" and recovered["lease_owner"] is None
    assert reopened.events(run_id, 0)[-1]["payload"]["to"] == "INTERRUPTED"


def test_supervisor_stops_child_after_parent_cancellation(tmp_path):
    store = RunStore(tmp_path / "runs.sqlite")
    parent = store.create_run("boss-1", "space-1", "request-parent", "digest-parent")
    parent_lease = store.acquire_lease(parent, 0, "parent-worker", 60)
    store.transition(parent, store.read_run(parent)["revision"], "RUNNING", "parent-worker", parent_lease["epoch"])
    child = store.create_child_run(parent, "parent-worker", parent_lease["epoch"], "request-child", "digest-child")
    child_lease = store.acquire_lease(child, 0, "child-worker", 60)
    store.transition(child, store.read_run(child)["revision"], "RUNNING", "child-worker", child_lease["epoch"])
    config = EngineRunConfig(child, child_lease["epoch"], "903230b1e23e0c496b28e5d2e8c4f2639cd506b6", "http://127.0.0.1:1234", 3)
    process = subprocess.Popen([sys.executable, "-c", "input()"], stdin=subprocess.PIPE)
    sink = EngineEventSink(store, config, "child-worker")
    supervisor = EngineProcessSupervisor(sink, process)
    assert supervisor.step() == "RUNNING"
    sink.require_tool_access("boss-1", "space-1")
    store.cancel(parent, store.read_run(parent)["revision"])
    with pytest.raises(ValueError):
        sink.require_tool_access("boss-1", "space-1")
    with pytest.raises(ValueError):
        supervisor.step()
    process.wait(timeout=10)
    assert process.returncode != 0
