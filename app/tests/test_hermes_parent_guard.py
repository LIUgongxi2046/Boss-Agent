import base64
import json
import os
import select
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from hermes_process_anchor import _read_guard_start_report


ROOT = Path(__file__).resolve().parents[2]
GUARD = ROOT / "validation/hermes_parent_guard.py"
PROBE = Path(__file__).with_name("hermes_parent_guard_probe.py")


def test_guard_start_report_wait_has_deadline(tmp_path):
    read_fd, write_fd = os.pipe()
    environment = {"PATH": "/usr/bin:/bin", "HERMES_PARENT_GUARD_FD": str(read_fd), "PYTHONDONTWRITEBYTECODE": "1"}
    guard = subprocess.Popen([sys.executable, str(GUARD)], cwd=tmp_path, env=environment,
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, pass_fds=(read_fd,))
    os.close(read_fd)
    try:
        started = time.monotonic()
        with pytest.raises(TimeoutError, match="启动报告超时"):
            _read_guard_start_report(guard.stdout, 0.2)
        assert time.monotonic() - started < 2
        assert guard.poll() is None
    finally:
        os.close(write_fd)
        guard.kill()
        guard.wait(timeout=5)
        guard.stdin.close()
        guard.stdout.close()
        guard.stderr.close()


def test_guard_reaps_engine_that_finishes_normally(tmp_path):
    read_fd, write_fd = os.pipe()
    environment = {"PATH": "/usr/bin:/bin", "HERMES_PARENT_GUARD_FD": str(read_fd), "PYTHONDONTWRITEBYTECODE": "1"}
    guard = subprocess.Popen([sys.executable, str(GUARD)], cwd=tmp_path, env=environment,
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, pass_fds=(read_fd,))
    os.close(read_fd)
    try:
        config = {"command": [sys.executable, "-c", "pass"], "env": {"PATH": "/usr/bin:/bin"}, "bootstrap": "", "pass_fds": []}
        payload = (json.dumps(config) + "\n").encode()
        output, error = guard.communicate(payload, timeout=5)
        assert guard.returncode == 0, error.decode()
        reports = [json.loads(line) for line in output.splitlines()]
        assert reports[0]["engine_pid"] > 0
        assert reports[1] == {"engine_exit": 0}
    finally:
        os.close(write_fd)
        if guard.poll() is None:
            guard.kill()
            guard.wait(timeout=5)


def test_guard_reports_failed_bootstrap_delivery(tmp_path):
    read_fd, write_fd = os.pipe()
    environment = {"PATH": "/usr/bin:/bin", "HERMES_PARENT_GUARD_FD": str(read_fd), "PYTHONDONTWRITEBYTECODE": "1"}
    guard = subprocess.Popen([sys.executable, str(GUARD)], cwd=tmp_path, env=environment,
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, pass_fds=(read_fd,))
    os.close(read_fd)
    try:
        config = {"command": [sys.executable, "-c", "pass"], "env": {"PATH": "/usr/bin:/bin"},
                  "bootstrap": base64.b64encode(b"x" * (1024 * 1024)).decode(), "pass_fds": []}
        output, error = guard.communicate((json.dumps(config) + "\n").encode(), timeout=10)
        assert guard.returncode != 0, (output, error)
    finally:
        os.close(write_fd)
        if guard.poll() is None:
            guard.kill()
            guard.wait(timeout=5)


def test_guard_reports_exit_when_control_pipe_closes(tmp_path):
    read_fd, write_fd = os.pipe()
    environment = {"PATH": "/usr/bin:/bin", "HERMES_PARENT_GUARD_FD": str(read_fd), "PYTHONDONTWRITEBYTECODE": "1"}
    guard = subprocess.Popen([sys.executable, str(GUARD)], cwd=tmp_path, env=environment,
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, pass_fds=(read_fd,))
    os.close(read_fd)
    try:
        config = {"command": [sys.executable, "-c", "import time; time.sleep(5)"], "env": {"PATH": "/usr/bin:/bin"}, "bootstrap": "", "pass_fds": []}
        guard.stdin.write((json.dumps(config) + "\n").encode())
        guard.stdin.close()
        assert json.loads(guard.stdout.readline())["engine_pid"] > 0
        os.close(write_fd)
        write_fd = None
        assert json.loads(guard.stdout.readline()) == {"engine_exit": -signal.SIGKILL}
        assert guard.wait(timeout=5) == 0
    finally:
        if write_fd is not None:
            os.close(write_fd)
        if guard.poll() is None:
            guard.kill()
            guard.wait(timeout=5)


def test_guard_reaps_owned_engine_after_parent_exit(tmp_path):
    output = tmp_path / "processes.json"
    parent = subprocess.Popen([sys.executable, str(PROBE), str(GUARD), str(output)], cwd=tmp_path)
    queue = select.kqueue()
    try:
        deadline = time.monotonic() + 5
        while not output.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        identities = json.loads(output.read_text(encoding="utf-8"))
        changes = [select.kevent(identities[key], filter=select.KQ_FILTER_PROC,
                                 flags=select.KQ_EV_ADD | select.KQ_EV_ENABLE, fflags=select.KQ_NOTE_EXIT)
                   for key in ("guard_pid", "engine_pid")]
        queue.control(changes, 0, 0)
        os.kill(parent.pid, signal.SIGKILL)
        parent.wait(timeout=5)
        observed = set()
        deadline = time.monotonic() + 4
        while len(observed) < 2 and time.monotonic() < deadline:
            observed.update(event.ident for event in queue.control(None, 2, max(0, deadline - time.monotonic()))
                            if event.fflags & select.KQ_NOTE_EXIT)
        assert observed == {identities["guard_pid"], identities["engine_pid"]}
    finally:
        queue.close()
        if parent.poll() is None:
            parent.kill()
            parent.wait(timeout=5)
