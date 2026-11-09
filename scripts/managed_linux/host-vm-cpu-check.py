import argparse
import secrets
import sys
import time
from pathlib import Path

import pytest

from agent_run_launch_transaction import RunLaunchTransaction
from agent_run_concurrency import RunConcurrencyBudget
from agent_run_store import RunStore
from hermes_cpu_budget import HermesCPUBudget
from hermes_process_evidence import HermesProcessEvidence
from hermes_vm_host import HermesVMHostClient
from hermes_vm_identity import HermesVMRunAccess, HermesVMRunBindings
from hermes_vm_manager import HermesVMManager
from test_hermes_process_evidence import expire_lease


parser = argparse.ArgumentParser()
parser.add_argument("--executable", type=Path, required=True)
parser.add_argument("--executable-sha256", required=True)
parser.add_argument("--directory", type=Path, required=True)
parser.add_argument("--credentials", type=Path, required=True)
parser.add_argument("--dependencies", type=Path, required=True)
parser.add_argument("--engine", type=Path, required=True)
parser.add_argument("--results", type=Path, required=True)
parser.add_argument("--runtime-port", type=int, required=True)
parser.add_argument("--control-port", type=int, required=True)
parser.add_argument("--cancel-before-stop", action="store_true")
arguments = parser.parse_args()
results = arguments.results.resolve(strict=True)
store = RunStore(results / "runs.sqlite")
concurrency = RunConcurrencyBudget(store, allow_migration=True)
evidence = HermesProcessEvidence(store, allow_migration=True)
run_id = store.create_run("boss-1", "ui-check", "request", "request-digest")
lease = store.acquire_lease(run_id, 0, "worker", 180)
epoch = lease["epoch"]
store.transition(run_id, lease["revision"], "RUNNING", "worker", epoch)
concurrency.configure(run_id, "worker", epoch, 1)
store.configure_file_budget(run_id, "worker", epoch, 16, 1048576)
with store.connect() as db:
    db.execute("BEGIN IMMEDIATE")
    concurrency.reserve_in_transaction(db, run_id, "worker", epoch, "slot", "digest")
bindings = HermesVMRunBindings(store, allow_migration=True)
cpu_budget = HermesCPUBudget(store, allow_migration=True)
workspace = results / run_id
workspace.mkdir(mode=0o700)
manager = HermesVMManager.start(
    arguments.executable, arguments.directory, arguments.credentials, arguments.executable_sha256,
    arguments.runtime_port, arguments.control_port,
    {"memory_bytes": 1073741824, "processes": 64, "cpu_percent": 100},
    dependencies_directory=arguments.dependencies, engine_directory=arguments.engine,
)
try:
    print("VM_MANAGER_STARTED", flush=True)
    if not sys.stdin.readline():
        raise ValueError("客体启动等待被中断")
    boot_id = manager.control.identity()
    with RunLaunchTransaction(store).hold(run_id, "worker", epoch) as db:
        unit = evidence.record_vm_start_in_transaction(db, bindings, run_id, "slot", "digest", "worker", epoch,
                                                       "boss-1", "ui-check", manager.vm_id, boot_id, workspace)
    access = HermesVMRunAccess(bindings, run_id, "slot", "worker", epoch, manager.vm_id, boot_id, workspace)
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        cpu_budget.configure_in_transaction(db, run_id, "worker", epoch, 20_000_000_000)
        if not cpu_budget.reserve_in_transaction(db, access, 20_000_000_000):
            raise ValueError("CPU 预留未创建")
    host = HermesVMHostClient(access, manager.control.context, manager.control.guest_name,
                              manager.control.guest_certificate_sha256, arguments.control_port)
    budget = {"rounds": 1, "seconds": 45, "memory_bytes": 1073741824, "processes": 64,
              "cpu_percent": 100, "open_files": 64, "files": 16, "file_bytes": 1048576, "cpu_seconds": 20}
    bootstrap = {"endpoint": "http://127.0.0.1:" + str(arguments.runtime_port), "capability": secrets.token_urlsafe(32),
                 "provider_capability": secrets.token_urlsafe(32), "run_id": run_id,
                 "engine_commit": "903230b1e23e0c496b28e5d2e8c4f2639cd506b6"}
    started = False
    prepared = False
    try:
        host.prepare_workspace(budget, bootstrap)
        prepared = True
        host.workspace_status(budget, bootstrap)
        host.start(budget, bootstrap)
        started = True
        prepared = False
        time.sleep(1)
        slice_first = host.slice_cpu_usage()
        slice_second = host.slice_cpu_usage()
        if slice_first["source"] != "SLICE_CPU_NSEC_V1" or slice_second["source"] != slice_first["source"] or slice_second["cpu_ns"] < slice_first["cpu_ns"]:
            raise ValueError("宿主 slice CPU 累计读数不匹配")
        print("HOST_VSOCK_SLICE_CPU_NSEC", slice_first["cpu_ns"], slice_second["cpu_ns"], flush=True)
        first = cpu_budget.record_sample(host, "sample-1")
        second = cpu_budget.record_sample(host, "sample-2")
        replay = cpu_budget.record_sample(host, "sample-1")
        if first <= 0 or second < first or replay != first:
            raise ValueError("宿主 CPU 累计读数不匹配")
        with store.connect() as db:
            saved = db.execute("SELECT reserved_ns,observed_ns FROM hermes_cpu_reservations WHERE run_id=? AND request_key=?", (run_id, "slot")).fetchone()
            count = db.execute("SELECT count(*) FROM hermes_cpu_samples WHERE run_id=? AND request_key=?", (run_id, "slot")).fetchone()
        if saved != (20_000_000_000, second) or count != (2,):
            raise ValueError("CPU 累计记录不可重读")
        print("HOST_VSOCK_CPU_PERSISTED_NS", first, second, "REPLAY", replay, flush=True)
        if arguments.cancel_before_stop:
            store.cancel(run_id, store.read_run(run_id)["revision"], request_key="cancel-check")
            with pytest.raises(ValueError):
                host.cpu_usage()
            print("HOST_VSOCK_CANCEL_BLOCKS_RUNNING_ACCESS", flush=True)
        host.stop()
        started = False
        unknown = cpu_budget.record_unknown_exit(host)
        if cpu_budget.record_unknown_exit(host) != unknown or unknown["state"] != "UNKNOWN" or unknown["cpu_ns"] is not None:
            raise ValueError("客体未知退出记录不可重读")
        observation = cpu_budget.record_unknown_exit_observation(host)
        if cpu_budget.record_unknown_exit_observation(host) != observation or observation["state"] != "UNKNOWN":
            raise ValueError("客体退出观察不可重读")
        with pytest.raises(ValueError, match="CPU 清理缺少最终结算"):
            cpu_budget.cleanup_settled_exit(host)
        final = cpu_budget.settle_final_exit(host)
        if cpu_budget.settle_final_exit(host) != final or final["cpu_ns"] < second or final["invocation"] != observation["invocation"]:
            raise ValueError("客体最终结算不可重读")
        if cpu_budget.cleanup_settled_exit(host) != final or cpu_budget.cleanup_settled_exit(host) != final:
            raise ValueError("客体最终清理不可重读")
        print("HOST_VSOCK_FINAL_CPU_SETTLED_NS", final["cpu_ns"], flush=True)
        if not arguments.cancel_before_stop:
            child = store.create_child_run(run_id, "worker", epoch, "child", "child-digest")
            child_lease = store.acquire_lease(child, 0, "child-worker", 180)
            store.transition(child, child_lease["revision"], "RUNNING", "child-worker", child_lease["epoch"])
            child_workspace = results / child
            child_workspace.mkdir(mode=0o700)
            with store.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                concurrency.reserve_in_transaction(db, child, "child-worker", child_lease["epoch"], "child-slot", "child-digest")
                evidence.record_vm_start_in_transaction(db, bindings, child, "child-slot", "child-digest", "child-worker", child_lease["epoch"], "boss-1", "ui-check", manager.vm_id, boot_id, child_workspace)
            child_access = HermesVMRunAccess(bindings, child, "child-slot", "child-worker", child_lease["epoch"], manager.vm_id, boot_id, child_workspace)
            available = 20_000_000_000 - final["cpu_ns"]
            if available <= 0:
                raise ValueError("CPU 剩余额度无效")
            with store.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                with pytest.raises(ValueError, match="CPU 预算不足"):
                    cpu_budget.reserve_in_transaction(db, child_access, available + 1)
                if not cpu_budget.reserve_in_transaction(db, child_access, available):
                    raise ValueError("CPU 剩余额度没有预留")
            print("HOST_VSOCK_FINAL_BUDGET_REUSED_NS", available, flush=True)
        with store.connect() as db:
            if db.execute("SELECT count(*) FROM hermes_cpu_unknown_exits WHERE run_id=?", (run_id,)).fetchone() != (1,):
                raise ValueError("宿主未知退出记录不唯一")
            if db.execute("SELECT reserved_ns FROM hermes_cpu_reservations WHERE run_id=?", (run_id,)).fetchone() != (20_000_000_000,):
                raise ValueError("未知退出未保留 CPU 预留")
            if db.execute("SELECT count(*) FROM hermes_cpu_exit_observations WHERE run_id=?", (run_id,)).fetchone() != (1,):
                raise ValueError("宿主退出观察不唯一")
            if db.execute("SELECT cpu_ns FROM hermes_cpu_final_exits WHERE run_id=?", (run_id,)).fetchone() != (final["cpu_ns"],):
                raise ValueError("宿主最终结算不可重读")
            if db.execute("SELECT state FROM agent_concurrency_reservations WHERE run_id=? AND request_key='slot'", (run_id,)).fetchone() != ("RELEASED",):
                raise ValueError("宿主并发预留未释放")
        print("HOST_VSOCK_UNKNOWN_EXIT_DURABLE", flush=True)
        expire_lease(store, run_id)
        with pytest.raises(ValueError):
            cpu_budget.record_sample(host, "expired-lease")
        with store.connect() as db:
            count = db.execute("SELECT count(*) FROM hermes_cpu_samples WHERE run_id=? AND request_key=?", (run_id, "slot")).fetchone()
        if count != (2,):
            raise ValueError("过期租约写入了 CPU 采样")
        print("HOST_VSOCK_EXPIRED_LEASE_REJECTED", flush=True)
    finally:
        if started:
            host.stop()
            print("GUEST_STOP_REQUESTED", flush=True)
        elif prepared:
            host.release_workspace()
finally:
    manager.stop()
    print("VM_MANAGER_GRACEFUL_STOP_OK", flush=True)
