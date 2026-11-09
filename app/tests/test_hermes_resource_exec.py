import json
import os
import signal
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from agent_run_store import RunStore
from hermes_bridge import EngineEventSink, EngineProcessConfig, EngineRunConfig
from hermes_process_manager import HermesProcessManager

ROOT = Path(__file__).resolve().parents[2]
LAUNCHER = ROOT / "validation/hermes_resource_exec.py"
PROBE = ROOT / "app/tests/hermes_resource_probe.py"


def run_probe(mode, *arguments, file_bytes=1024, open_files=32, cpu_seconds=2):
    command = [sys.executable, str(LAUNCHER), "--file-bytes", str(file_bytes), "--open-files", str(open_files),
               "--cpu-seconds", str(cpu_seconds), sys.executable, str(PROBE), mode, *map(str, arguments)]
    return subprocess.run(command, capture_output=True, text=True, timeout=10, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})


def test_limits_inherit_across_exec_and_child():
    result = run_probe("child")
    assert result.returncode == 0
    assert json.loads(result.stdout) == {"RLIMIT_CORE": [0, 0], "RLIMIT_FSIZE": [1024, 1024], "RLIMIT_NOFILE": [32, 32], "RLIMIT_CPU": [2, 2]}


def test_file_descriptor_and_hard_limit_enforcement(tmp_path):
    target = tmp_path / "resource-output"
    result = run_probe("file", target)
    assert result.returncode != 0 and target.stat().st_size <= 1024
    result = run_probe("descriptors")
    assert result.returncode != 0 and "Too many open files" in result.stderr
    result = run_probe("raise")
    assert result.returncode != 0 and "not allowed to raise maximum limit" in result.stderr


def test_cpu_limit_and_invalid_configuration():
    result = run_probe("cpu", cpu_seconds=1)
    assert result.returncode in {-signal.SIGKILL, -signal.SIGXCPU}
    result = run_probe("limits", open_files=1)
    assert result.returncode != 0 and "进程资源限制无效" in result.stderr


def test_manager_resource_command_transmits_limits_and_rejects_invalid_values(tmp_path):
    store = RunStore(tmp_path / "runs.sqlite")
    run_id = store.create_run("boss-1", "space-1", "resource-check", "resource-digest")
    lease = store.acquire_lease(run_id, 0, "worker", 60)
    run = EngineRunConfig(run_id, lease["epoch"], "903230b1e23e0c496b28e5d2e8c4f2639cd506b6", "http://127.0.0.1:1234", 1)
    executable = Path(sys.executable).absolute()
    config = EngineProcessConfig(run, tmp_path, tmp_path, executable.parent, executable, tmp_path, tmp_path, tmp_path, 1, 1, 10, 1, 1, 1, 1024, 32, 2)
    manager = HermesProcessManager(EngineEventSink(store, run, "worker"), config)
    command = manager._resource_command([str(PROBE), "child"])
    result = subprocess.run(command, capture_output=True, text=True, timeout=10, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
    assert result.returncode == 0
    assert json.loads(result.stdout) == {"RLIMIT_CORE": [0, 0], "RLIMIT_FSIZE": [1024, 1024], "RLIMIT_NOFILE": [32, 32], "RLIMIT_CPU": [2, 2]}
    target = tmp_path / "limited-file"
    result = subprocess.run(manager._resource_command([str(PROBE), "file", str(target)]), capture_output=True, text=True, timeout=10, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
    assert result.returncode != 0 and target.stat().st_size <= 1024
    for invalid in (replace(config, max_file_bytes=0), replace(config, max_open_files=15), replace(config, max_cpu_seconds=True)):
        with pytest.raises(ValueError, match="资源预算"):
            HermesProcessManager(EngineEventSink(store, run, "worker"), invalid)._resource_command([str(PROBE), "child"])
