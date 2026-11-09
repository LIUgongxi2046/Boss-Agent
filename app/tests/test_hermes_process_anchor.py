import json
import fcntl
import os
import select
import signal
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from hermes_process_anchor import AnchorProcessGroup, GuardianBootstrapError, _require_engine_owned_by_anchor
from hermes_anchor_supervisor import AnchorExitObserver


ROOT = Path(__file__).resolve().parents[2]
ENGINE = Path(__file__).with_name("hermes_anchor_engine_probe.py").resolve()
SUPERVISOR = Path(__file__).with_name("hermes_anchor_supervisor_probe.py").resolve()
NO_SPAWN = Path(__file__).with_name("hermes_no_spawn.sb").resolve()
ENV = {"PATH": "/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE": "1"}


def test_guarded_engine_does_not_inherit_unrelated_descriptors(tmp_path):
    source = tmp_path / "independent-data"
    source.write_text("独立测试资料", encoding="utf-8")
    with source.open("rb") as opened, socket.socket() as listener:
        file_fd = fcntl.fcntl(opened.fileno(), fcntl.F_DUPFD, 200)
        socket_fd = fcntl.fcntl(listener.fileno(), fcntl.F_DUPFD, 201)
        os.set_inheritable(file_fd, True)
        os.set_inheritable(socket_fd, True)
        try:
            command = [sys.executable, "-c", "import os,sys; assert all(not os.path.exists('/dev/fd/'+value) for value in sys.argv[1:])",
                       str(file_fd), str(socket_fd)]
            anchor = AnchorProcessGroup.start(command, cwd=tmp_path, env=ENV, deferred=True, guarded=True)
            try:
                anchor.release_engine()
                assert anchor.read_engine_exit(timeout=10) == 0
            finally:
                if anchor.process.poll() is None:
                    anchor.reclaim()
                anchor.close_control()
        finally:
            os.close(file_fd)
            os.close(socket_fd)


def test_guarded_process_respects_sandbox_loopback_rule(tmp_path):
    work = tmp_path / "workspace"
    work.mkdir()
    allowed = socket.socket()
    denied = socket.socket()
    try:
        allowed.bind(("127.0.0.1", 0))
        allowed.listen()
        denied.bind(("127.0.0.1", 0))
        denied.listen()
        allowed_port = allowed.getsockname()[1]
        denied_port = denied.getsockname()[1]
        profile = Path(__file__).with_name("hermes_isolation_probe.sb").resolve()
        probe = Path(__file__).with_name("hermes_isolation_probe.py").resolve()
        prefix = ["/usr/bin/sandbox-exec", "-D", "PROTECTED=" + str(tmp_path), "-D", "WORK=" + str(work),
                  "-D", "ENDPOINT=localhost:" + str(allowed_port), "-f", str(profile), sys.executable, str(probe)]
        for port, expected in ((allowed_port, True), (denied_port, False)):
            anchor = AnchorProcessGroup.start(prefix + ["connect", str(port)], cwd=work, env=ENV,
                                              deferred=True, guarded=True)
            try:
                anchor.release_engine()
                exit_code = anchor.read_engine_exit(timeout=10)
                assert (exit_code == 0) is expected
            finally:
                if anchor.process.poll() is None:
                    anchor.reclaim()
                anchor.close_control()
        assert select.select([allowed], [], [], 0)[0] == [allowed]
        assert select.select([denied], [], [], 0)[0] == []
    finally:
        allowed.close()
        denied.close()


def test_guarded_engine_waits_for_permit_and_reads_bootstrap(tmp_path):
    output = tmp_path / "input"
    command = [sys.executable, "-c", "import pathlib,sys; pathlib.Path(sys.argv[1]).write_bytes(sys.stdin.buffer.read())", str(output)]
    group = AnchorProcessGroup.start(command, cwd=tmp_path, env=ENV, bootstrap=b"business-context", deferred=True, guarded=True)
    try:
        time.sleep(0.2)
        assert not output.exists()
        group.release_engine()
        assert group.read_engine_exit(timeout=10) == 0
        assert output.read_bytes() == b"business-context"
    finally:
        if group.process.poll() is None:
            group.reclaim()


def test_guarded_bootstrap_failure_reaches_supervisor(tmp_path):
    command = [sys.executable, "-c", "import time; time.sleep(0.2)"]
    group = AnchorProcessGroup.start(command, cwd=tmp_path, env=ENV, bootstrap=b"x" * (1024 * 1024), deferred=True, guarded=True)
    try:
        group.release_engine()
        with pytest.raises(GuardianBootstrapError) as failure:
            group.read_engine_exit(timeout=5)
        assert failure.value.stage == "BOOTSTRAP_DELIVERY"
        assert failure.value.kind in {"BrokenPipeError", "ValueError"}
        assert group.process.wait(timeout=5) != 0
    finally:
        if group.process.poll() is None:
            group.reclaim()
        group.close_control()


def test_guarded_bootstrap_failure_reclaims_when_acknowledgment_times_out(tmp_path):
    command = [sys.executable, "-c", "import time; time.sleep(0.2)"]
    group = AnchorProcessGroup.start(command, cwd=tmp_path, env=ENV, bootstrap=b"x" * (1024 * 1024), deferred=True, guarded=True, gate_timeout=0.5)
    try:
        group.release_engine()
        assert group.process.wait(timeout=5) != 0
        with pytest.raises(GuardianBootstrapError):
            group.read_engine_exit(timeout=2)
    finally:
        if group.process.poll() is None:
            group.reclaim()
        group.close_control()


def test_guarded_engine_enforces_file_limit_after_permit(tmp_path):
    output = tmp_path / "limited.bin"
    command = [sys.executable, "-c", "import pathlib,sys; pathlib.Path(sys.argv[1]).write_bytes(b'x'*2048)", str(output)]
    limits = {"file_bytes": 512, "open_files": 32, "cpu_seconds": 5}
    group = AnchorProcessGroup.start(command, cwd=tmp_path, env=ENV, deferred=True, guarded=True, limits=limits)
    try:
        assert os.getpgid(group.guardian_pid) == group.anchor_pid
        assert os.getsid(group.guardian_pid) == group.anchor_pid
        assert os.getpgid(group.engine_pid) == group.anchor_pid
        assert os.getsid(group.engine_pid) == group.anchor_pid
        assert not output.exists()
        group.release_engine()
        assert group.read_engine_exit(timeout=10) != 0
        assert output.stat().st_size <= 512
    finally:
        if group.process.poll() is None:
            group.reclaim()


def test_guarded_engine_enforces_cpu_limit_after_permit(tmp_path):
    limits = {"file_bytes": 1024, "open_files": 32, "cpu_seconds": 1}
    group = AnchorProcessGroup.start([sys.executable, "-c", "while True: pass"], cwd=tmp_path,
                                     env=ENV, deferred=True, guarded=True, limits=limits)
    try:
        group.release_engine()
        assert group.read_engine_exit(timeout=15) != 0
    finally:
        if group.process.poll() is None:
            group.reclaim()


def test_guarded_engine_exits_after_anchor_is_killed(tmp_path):
    ready = tmp_path / "engine.pid"
    command = [sys.executable, str(ENGINE), "ready_sleep", str(ready)]
    group = AnchorProcessGroup.start(command, cwd=tmp_path, env=ENV, deferred=True, guarded=True)
    queue = select.kqueue()
    try:
        queue.control([select.kevent(group.engine_pid, filter=select.KQ_FILTER_PROC,
                                     flags=select.KQ_EV_ADD | select.KQ_EV_ENABLE,
                                     fflags=select.KQ_NOTE_EXIT)], 0, 0)
        group.release_engine()
        assert read_pid(ready) == group.engine_pid
        os.kill(group.anchor_pid, signal.SIGKILL)
        group.process.wait(timeout=5)
        events = queue.control(None, 1, 5)
        assert any(event.ident == group.engine_pid and event.fflags & select.KQ_NOTE_EXIT for event in events)
    finally:
        queue.close()
        if group.process.poll() is None:
            group.reclaim()
        group.close_control()


def test_guardian_failure_reclaims_live_anchor_group(tmp_path):
    ready = tmp_path / "engine.pid"
    group = AnchorProcessGroup.start([sys.executable, str(ENGINE), "ready_sleep", str(ready)],
                                     cwd=tmp_path, env=ENV, guarded=True)
    observer = AnchorExitObserver(group)
    try:
        assert read_pid(ready) == group.engine_pid
        assert os.getpgid(group.guardian_pid) == group.anchor_pid
        assert os.getsid(group.guardian_pid) == group.anchor_pid
        assert os.getpgid(group.engine_pid) == group.anchor_pid
        assert os.getsid(group.engine_pid) == group.anchor_pid
        os.kill(group.guardian_pid, signal.SIGKILL)
        group.process.wait(timeout=5)
        observed = set()
        deadline = time.monotonic() + 5
        while len(observed) < 2 and time.monotonic() < deadline:
            observed.update(observer.poll(timeout=max(0, deadline - time.monotonic())))
        assert group.anchor_pid in observed
        assert group.engine_pid in observed
        assert group.process.returncode == -signal.SIGKILL
    finally:
        observer.close()
        if group.process.poll() is None:
            group.reclaim()
        group.close_control()


def test_guardian_failure_reclaims_same_group_descendants(tmp_path):
    ready = tmp_path / "grandchild.pid"
    group = AnchorProcessGroup.start([sys.executable, str(ENGINE), "grandchild", str(ready)],
                                     cwd=tmp_path, env=ENV, guarded=True)
    queue = select.kqueue()
    try:
        child_pid = read_pid(Path(str(ready) + ".child"))
        grandchild_pid = read_pid(ready)
        for pid in (group.engine_pid, child_pid, grandchild_pid):
            assert os.getpgid(pid) == group.anchor_pid
            queue.control([select.kevent(pid, filter=select.KQ_FILTER_PROC,
                                         flags=select.KQ_EV_ADD | select.KQ_EV_ENABLE,
                                         fflags=select.KQ_NOTE_EXIT)], 0, 0)
        os.kill(group.guardian_pid, signal.SIGKILL)
        group.process.wait(timeout=5)
        observed = set()
        deadline = time.monotonic() + 5
        while len(observed) < 3 and time.monotonic() < deadline:
            observed.update(event.ident for event in queue.control(None, 3, max(0, deadline - time.monotonic()))
                            if event.fflags & select.KQ_NOTE_EXIT)
        assert observed == {group.engine_pid, child_pid, grandchild_pid}
    finally:
        queue.close()
        if group.process.poll() is None:
            group.reclaim()
        group.close_control()


def test_kqueue_observes_engine_fork_and_child_exit(tmp_path):
    child_path = tmp_path / "child.pid"
    group = AnchorProcessGroup.start([sys.executable, str(ENGINE), "sleep_child", str(child_path)],
                                     cwd=tmp_path, env=ENV, deferred=True, guarded=True)
    queue = select.kqueue()
    try:
        queue.control([select.kevent(group.engine_pid, filter=select.KQ_FILTER_PROC,
                                     flags=select.KQ_EV_ADD | select.KQ_EV_ENABLE,
                                     fflags=select.KQ_NOTE_FORK)], 0, 0)
        group.release_engine()
        child_pid = read_pid(child_path)
        events = queue.control(None, 1, 5)
        assert any(event.ident == group.engine_pid and event.fflags & select.KQ_NOTE_FORK for event in events)
        queue.control([select.kevent(child_pid, filter=select.KQ_FILTER_PROC,
                                     flags=select.KQ_EV_ADD | select.KQ_EV_ENABLE,
                                     fflags=select.KQ_NOTE_EXIT)], 0, 0)
        group.reclaim()
        events = queue.control(None, 1, 5)
        assert any(event.ident == child_pid and event.fflags & select.KQ_NOTE_EXIT for event in events)
    finally:
        queue.close()
        if group.process.poll() is None:
            group.reclaim()
        group.close_control()


def test_guarded_blocked_bootstrap_exits_after_anchor_is_killed(tmp_path):
    command = [sys.executable, str(ENGINE), "no_read"]
    group = AnchorProcessGroup.start(command, cwd=tmp_path, env=ENV, bootstrap=b"x" * (1024 * 1024), guarded=True)
    queue = select.kqueue()
    try:
        queue.control([select.kevent(group.engine_pid, filter=select.KQ_FILTER_PROC,
                                     flags=select.KQ_EV_ADD | select.KQ_EV_ENABLE,
                                     fflags=select.KQ_NOTE_EXIT)], 0, 0)
        os.kill(group.anchor_pid, signal.SIGKILL)
        group.process.wait(timeout=5)
        assert any(event.ident == group.engine_pid and event.fflags & select.KQ_NOTE_EXIT
                   for event in queue.control(None, 1, 5))
    finally:
        queue.close()
        if group.process.poll() is None:
            group.reclaim()
        group.close_control()


def test_guarded_blocked_bootstrap_reclaims_after_cancellation(tmp_path):
    command = [sys.executable, str(ENGINE), "no_read"]
    group = AnchorProcessGroup.start(command, cwd=tmp_path, env=ENV, bootstrap=b"x" * (1024 * 1024), guarded=True)
    observer = AnchorExitObserver(group)
    try:
        started = time.monotonic()
        group.reclaim()
        observed = set()
        deadline = time.monotonic() + 5
        while len(observed) < 2 and time.monotonic() < deadline:
            observed.update(observer.poll(timeout=max(0, deadline - time.monotonic())))
        assert observed == {group.anchor_pid, group.engine_pid}
        assert time.monotonic() - started < 10
    finally:
        observer.close()
        if group.process.poll() is None:
            group.reclaim()
        group.close_control()


def test_kqueue_observes_anchor_exit_and_engine_exit_independently(tmp_path):
    ready = tmp_path / "engine.pid"
    group = AnchorProcessGroup.start([sys.executable, str(ENGINE), "ready_sleep", str(ready)], cwd=tmp_path, env=ENV)
    observer = AnchorExitObserver(group)
    engine_ended = False
    try:
        assert read_pid(ready) == group.engine_pid
        os.kill(group.anchor_pid, signal.SIGKILL)
        group.process.wait(timeout=10)
        events = observer.poll(timeout=5)
        assert group.anchor_pid in events
        assert group.engine_pid not in events
        os.kill(group.engine_pid, 0)
        os.kill(group.engine_pid, signal.SIGKILL)
        events = observer.poll(timeout=5)
        assert group.engine_pid in events
        engine_ended = True
    finally:
        observer.close()
        group.close_control()
        if group.process.poll() is None:
            group.process.kill()
            group.process.wait(timeout=10)
        if not engine_ended:
            os.kill(group.engine_pid, signal.SIGKILL)


def test_restricted_engine_cannot_start_detached_child(tmp_path):
    control = subprocess.run(["/usr/bin/sandbox-exec", "-f", str(NO_SPAWN), sys.executable, "-c", "pass"], capture_output=True, timeout=10)
    assert control.returncode == 0, control.stderr.decode()
    child_path = tmp_path / "detached.pid"
    command = ["/usr/bin/sandbox-exec", "-f", str(NO_SPAWN), sys.executable, str(ENGINE), "detached", str(child_path)]
    group = AnchorProcessGroup.start(command, cwd=tmp_path, env=ENV)
    try:
        assert group.read_engine_exit(timeout=10) != 0
        assert not child_path.exists()
    finally:
        if group.process.poll() is None:
            group.reclaim()


def test_restricted_engine_survives_abnormal_anchor_exit(tmp_path):
    control = subprocess.run(["/usr/bin/sandbox-exec", "-f", str(NO_SPAWN), sys.executable, "-c", "pass"], capture_output=True, timeout=10)
    assert control.returncode == 0, control.stderr.decode()
    ready = tmp_path / "engine.pid"
    command = ["/usr/bin/sandbox-exec", "-f", str(NO_SPAWN), sys.executable, str(ENGINE), "ready_sleep", str(ready)]
    group = AnchorProcessGroup.start(command, cwd=tmp_path, env=ENV)
    try:
        assert read_pid(ready) == group.engine_pid
        os.kill(group.anchor_pid, signal.SIGKILL)
        group.process.wait(timeout=10)
        os.kill(group.engine_pid, 0)
        with pytest.raises(ValueError, match="锚点进程已经退出"):
            group.reclaim()
    finally:
        if group.process.poll() is None:
            group.reclaim()
        else:
            group.close_control()
            os.kill(group.engine_pid, signal.SIGKILL)


def test_deferred_engine_waits_for_release(tmp_path):
    output = tmp_path / "started"
    command = [sys.executable, "-c", "import pathlib,sys; pathlib.Path(sys.argv[1]).write_text('started')", str(output)]
    group = AnchorProcessGroup.start(command, cwd=tmp_path, env=ENV, deferred=True)
    try:
        time.sleep(0.2)
        assert not output.exists()
        assert group.poll_engine_exit() is None
        group.release_engine()
        assert group.read_engine_exit(timeout=10) == 0
        assert output.read_text() == "started"
        with pytest.raises(ValueError):
            group.release_engine()
    finally:
        if group.process.poll() is None:
            group.reclaim()


def test_deferred_engine_reclaimed_before_release(tmp_path):
    output = tmp_path / "started"
    command = [sys.executable, "-c", "import pathlib,sys; pathlib.Path(sys.argv[1]).write_text('started')", str(output)]
    group = AnchorProcessGroup.start(command, cwd=tmp_path, env=ENV, deferred=True)
    assert group.reclaim() == -signal.SIGKILL
    assert not output.exists()


def test_deferred_engine_timeout_prevents_execution(tmp_path):
    output = tmp_path / "started"
    command = [sys.executable, "-c", "import pathlib,sys; pathlib.Path(sys.argv[1]).write_text('started')", str(output)]
    group = AnchorProcessGroup.start(command, cwd=tmp_path, env=ENV, deferred=True, gate_timeout=0.2)
    try:
        assert group.read_engine_exit(timeout=10) != 0
        assert not output.exists()
        with pytest.raises((TimeoutError, ValueError)):
            group.release_engine(timeout=0.2)
    finally:
        if group.process.poll() is None:
            group.reclaim()


def test_late_release_preserves_engine_exit(tmp_path):
    group = AnchorProcessGroup.start([sys.executable, "-c", "pass"], cwd=tmp_path, env=ENV,
                                     deferred=True, gate_timeout=0.1)
    try:
        time.sleep(0.3)
        with pytest.raises((TimeoutError, ValueError)):
            group.release_engine(timeout=1)
        assert group.read_engine_exit(timeout=5) != 0
    finally:
        if group.process.poll() is None:
            group.reclaim()


def test_immediate_exit_keeps_ack_and_exit_reports(tmp_path):
    for _ in range(10):
        group = AnchorProcessGroup.start([sys.executable, "-c", "pass"], cwd=tmp_path, env=ENV, deferred=True)
        try:
            group.release_engine()
            assert group.read_engine_exit(timeout=10) == 0
        finally:
            if group.process.poll() is None:
                group.reclaim()


def test_anchor_reports_immediate_engine_exit(tmp_path):
    group = AnchorProcessGroup.start([sys.executable, "-c", "pass"], cwd=tmp_path, env=ENV)
    try:
        assert group.read_engine_exit(timeout=10) == 0
    finally:
        if group.process.poll() is None:
            group.reclaim()


def test_anchor_exit_report_wait_respects_timeout(tmp_path):
    group = AnchorProcessGroup.start([sys.executable, str(ENGINE), "sleep"], cwd=tmp_path, env=ENV)
    try:
        started = time.monotonic()
        with pytest.raises(TimeoutError):
            group.read_engine_exit(timeout=0.1)
        assert time.monotonic() - started < 2
    finally:
        if group.process.poll() is None:
            group.reclaim()


def read_pid(path, timeout=10):
    deadline = time.monotonic() + timeout
    content = path.read_text(encoding="utf-8").strip() if path.exists() else ""
    while not content.isdigit() and time.monotonic() < deadline:
        time.sleep(0.02)
        content = path.read_text(encoding="utf-8").strip() if path.exists() else ""
    if not content.isdigit():
        raise AssertionError("进程编号文件未写入")
    return int(content)


def test_anchor_resource_limits_apply_to_anchor(tmp_path):
    pid_file = tmp_path / "anchor.pid"
    limits = {"file_bytes": 1, "open_files": 32, "cpu_seconds": 5}
    with pytest.raises(ValueError):
        AnchorProcessGroup.start([sys.executable, "-c", "pass"], cwd=tmp_path, env=ENV,
                                 limits=limits, pid_file=pid_file)


def test_anchor_resource_limits_apply_to_engine_file_size(tmp_path):
    output = tmp_path / "large.bin"
    code = "import pathlib,sys; pathlib.Path(sys.argv[1]).write_bytes(b'x'*2048)"
    limits = {"file_bytes": 512, "open_files": 32, "cpu_seconds": 5}
    group = AnchorProcessGroup.start([sys.executable, "-c", code, str(output)],
                                     cwd=tmp_path, env=ENV, limits=limits)
    try:
        assert group.read_engine_exit(timeout=10) != 0
    finally:
        if group.process.poll() is None:
            group.reclaim()


def test_anchor_resource_limits_apply_to_engine_cpu(tmp_path):
    code = "while True: pass"
    limits = {"file_bytes": 1024, "open_files": 32, "cpu_seconds": 1}
    group = AnchorProcessGroup.start([sys.executable, "-c", code],
                                     cwd=tmp_path, env=ENV, limits=limits)
    try:
        assert group.read_engine_exit(timeout=15) != 0
    finally:
        if group.process.poll() is None:
            group.reclaim()


def test_anchor_resource_limits_apply_to_engine_descriptors(tmp_path):
    output = tmp_path / "open.bin"
    code = (
        "import os,sys\n"
        "try:\n"
        "    while True: os.open(sys.argv[1], os.O_CREAT | os.O_RDWR)\n"
        "except OSError:\n"
        "    sys.exit(42)\n"
    )
    limits = {"file_bytes": 1024, "open_files": 32, "cpu_seconds": 5}
    group = AnchorProcessGroup.start([sys.executable, "-c", code, str(output)],
                                     cwd=tmp_path, env=ENV, limits=limits)
    try:
        assert group.read_engine_exit(timeout=10) == 42
    finally:
        if group.process.poll() is None:
            group.reclaim()


def test_anchor_resource_limits_reject_invalid_values(tmp_path):
    with pytest.raises(ValueError, match="资源限制无效"):
        AnchorProcessGroup.start([sys.executable, "-c", "pass"], cwd=tmp_path, env=ENV,
                                 limits={"file_bytes": 1, "open_files": 8, "cpu_seconds": 5})


def test_anchor_closes_start_input_and_control_descriptors(tmp_path):
    group = AnchorProcessGroup.start([sys.executable, str(ENGINE), "sleep"],
                                     cwd=tmp_path, env=ENV, bootstrap=b"")
    try:
        assert group.process.stdin is not None and group.process.stdin.closed
        assert group.control_write is not None
        group.reclaim()
        assert group.control_write is None
        assert group.process.stdin.closed
        assert group.process.stdout.closed
    finally:
        if group.process.poll() is None:
            group.reclaim()
        group.close_control()


def test_anchor_closes_control_when_reclaim_times_out(tmp_path):
    read_fd, write_fd = os.pipe()
    process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], start_new_session=True)
    group = AnchorProcessGroup(process, write_fd, process.pid, None)
    try:
        with pytest.raises(subprocess.TimeoutExpired):
            group.reclaim()
        assert group.control_write is None
        assert process.poll() is None
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=10)
        os.close(read_fd)


def test_anchor_reports_engine_group_and_session_ownership(tmp_path):
    group = AnchorProcessGroup.start([sys.executable, str(ENGINE), "sleep"],
                                     cwd=tmp_path, env=ENV, bootstrap=b"")
    try:
        assert os.getpgid(group.engine_pid) == group.anchor_pid
        assert os.getsid(group.engine_pid) == group.anchor_pid
    finally:
        if group.process.poll() is None:
            group.reclaim()


def test_engine_ownership_rejects_foreign_process_group(tmp_path):
    anchor = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"], start_new_session=True)
    engine = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"], start_new_session=True)
    try:
        with pytest.raises(ValueError, match="引擎进程组或会话归属无效"):
            _require_engine_owned_by_anchor(anchor.pid, engine.pid)
    finally:
        for process in (engine, anchor):
            if process.poll() is None:
                process.kill()
                process.wait(timeout=10)


def test_engine_ownership_rejects_exited_engine(tmp_path):
    anchor = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"], start_new_session=True)
    engine = subprocess.Popen([sys.executable, "-c", "pass"])
    engine.wait(timeout=10)
    try:
        with pytest.raises(ProcessLookupError):
            _require_engine_owned_by_anchor(anchor.pid, engine.pid)
    finally:
        if anchor.poll() is None:
            anchor.kill()
            anchor.wait(timeout=10)


def test_anchor_reclaims_lingering_child_after_engine_exit(tmp_path):
    child_path = tmp_path / "child.pid"
    group = AnchorProcessGroup.start([sys.executable, str(ENGINE), "lingering", str(child_path)],
                                     cwd=tmp_path, env=ENV, bootstrap=b"")
    try:
        child_pid = read_pid(child_path)
        assert group.read_engine_exit(timeout=10) == 0
        assert group.process.poll() is None
        assert os.getpgid(group.anchor_pid) == group.anchor_pid
        assert os.getsid(group.anchor_pid) == group.anchor_pid
        assert group.reclaim() == -signal.SIGKILL
        time.sleep(0.2)
        with pytest.raises(ProcessLookupError):
            os.kill(child_pid, 0)
    finally:
        if group.process.poll() is None:
            group.reclaim()


def test_anchor_reclaim_is_single_flight(tmp_path):
    group = AnchorProcessGroup.start([sys.executable, str(ENGINE), "sleep"],
                                     cwd=tmp_path, env=ENV, bootstrap=b"")
    barrier = threading.Barrier(2)
    outcomes = []

    def reclaim_once():
        barrier.wait()
        try:
            outcomes.append(("code", group.reclaim()))
        except ValueError as error:
            outcomes.append(("error", str(error)))

    threads = [threading.Thread(target=reclaim_once) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)
    assert all(not thread.is_alive() for thread in threads)
    assert len([item for item in outcomes if item[0] == "code"]) == 1
    assert len([item for item in outcomes if item[0] == "error"]) == 1
    assert "回收已经开始" in next(item[1] for item in outcomes if item[0] == "error")


def test_anchor_refuses_reclaim_after_process_reaped(tmp_path):
    group = AnchorProcessGroup.start([sys.executable, str(ENGINE), "sleep"],
                                     cwd=tmp_path, env=ENV, bootstrap=b"")
    assert group.reclaim() == -signal.SIGKILL
    with pytest.raises(ValueError, match="回收已经开始"):
        group.reclaim()


def test_anchor_cleans_group_when_supervisor_is_killed(tmp_path):
    output = tmp_path / "supervisor.json"
    child_path = tmp_path / "child.pid"
    supervisor_env = {"PATH": "/usr/bin:/bin", "PYTHONPATH": str(ROOT / "validation"),
                      "PYTHONDONTWRITEBYTECODE": "1"}
    supervisor = subprocess.Popen([sys.executable, str(SUPERVISOR), str(ENGINE), str(output), str(child_path)],
                                  cwd=tmp_path, env=supervisor_env)
    try:
        deadline = time.monotonic() + 10
        while not output.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        data = json.loads(output.read_text(encoding="utf-8"))
        child_pid = read_pid(child_path)
        os.kill(supervisor.pid, signal.SIGKILL)
        supervisor.wait(timeout=10)
        time.sleep(0.5)
        with pytest.raises(ProcessLookupError):
            os.kill(data["anchor_pid"], 0)
        with pytest.raises(ProcessLookupError):
            os.kill(data["engine_pid"], 0)
        with pytest.raises(ProcessLookupError):
            os.kill(child_pid, 0)
    finally:
        if supervisor.poll() is None:
            supervisor.kill()
            supervisor.wait(timeout=10)


def test_anchor_rejects_missing_executable_before_spawn(tmp_path):
    with pytest.raises(ValueError, match="执行文件无效"):
        AnchorProcessGroup.start(["/nonexistent/engine"], cwd=tmp_path, env=ENV)


def test_anchor_start_failure_reaps_anchor_and_closes_control(tmp_path):
    failing = tmp_path / "not-executable"
    failing.write_text("#!/bin/sh\n", encoding="utf-8")
    failing.chmod(0o600)
    pid_file = tmp_path / "anchor.pid"
    with pytest.raises(ValueError):
        AnchorProcessGroup.start([str(failing)], cwd=tmp_path, env=ENV, pid_file=pid_file)
    anchor_pid = int(pid_file.read_text(encoding="utf-8"))
    with pytest.raises(ProcessLookupError):
        os.kill(anchor_pid, 0)


def test_guarded_start_failure_reaps_anchor(tmp_path):
    failing = tmp_path / "not-executable"
    failing.write_text("#!/bin/sh\n", encoding="utf-8")
    failing.chmod(0o600)
    pid_file = tmp_path / "anchor.pid"
    with pytest.raises(ValueError, match="锚点进程未报告"):
        AnchorProcessGroup.start([str(failing)], cwd=tmp_path, env=ENV, guarded=True, pid_file=pid_file)
    with pytest.raises(ProcessLookupError):
        os.kill(int(pid_file.read_text(encoding="utf-8")), 0)


def test_anchor_watcher_reclaims_when_bootstrap_write_is_blocked(tmp_path):
    group = AnchorProcessGroup.start([sys.executable, str(ENGINE), "no_read"],
                                     cwd=tmp_path, env=ENV, bootstrap=b"x" * (1024 * 1024))
    group.close_control()
    assert group.wait(timeout=10) == -signal.SIGKILL
    time.sleep(0.2)
    with pytest.raises(ProcessLookupError):
        os.kill(group.engine_pid, 0)


def test_anchor_engine_has_no_inherited_unrelated_descriptors(tmp_path):
    output = tmp_path / "descriptors.json"
    inherited_path = tmp_path / "inherited"
    inherited_fd = os.open(inherited_path, os.O_CREAT | os.O_RDWR, 0o600)
    os.set_inheritable(inherited_fd, True)
    group = AnchorProcessGroup.start([sys.executable, str(ENGINE), "fd_exists", str(output), str(inherited_fd)],
                                     cwd=tmp_path, env=ENV, bootstrap=b"")
    assert group.read_engine_exit(timeout=10) == 0
    result = json.loads(output.read_text(encoding="utf-8"))
    assert result["descriptor"] == inherited_fd
    assert result["exists"] is False
    assert result["stdin"] is True and result["stdout"] is True and result["stderr"] is True
    group.reclaim()
    os.close(inherited_fd)


def test_anchor_group_signal_does_not_reach_new_session_child(tmp_path):
    child_path = tmp_path / "detached.pid"
    group = AnchorProcessGroup.start([sys.executable, str(ENGINE), "detached", str(child_path)],
                                     cwd=tmp_path, env=ENV, bootstrap=b"")
    child_pid = read_pid(child_path)
    assert group.read_engine_exit(timeout=10) == 0
    group.reclaim()
    time.sleep(0.2)
    os.kill(child_pid, 0)
    os.kill(child_pid, signal.SIGKILL)


def test_anchor_cleanup_timeout_kills_child_and_preserves_original_error(tmp_path):
    read_fd, write_fd = os.pipe()
    process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], stdin=subprocess.PIPE, start_new_session=True)
    group = AnchorProcessGroup(process, write_fd, process.pid, None)
    try:
        def fail_then_cleanup():
            try:
                raise ValueError("original-start-error")
            finally:
                group._cleanup_failed_start()

        with pytest.raises(ValueError, match="original-start-error"):
            fail_then_cleanup()
        assert process.poll() is not None
        assert group.control_write is None
        assert process.stdin is not None and process.stdin.closed
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=10)
        os.close(read_fd)


def test_anchor_reclaims_same_group_grandchild(tmp_path):
    grandchild_path = tmp_path / "grandchild.pid"
    child_path = Path(str(grandchild_path) + ".child")
    group = AnchorProcessGroup.start([sys.executable, str(ENGINE), "grandchild", str(grandchild_path)],
                                     cwd=tmp_path, env=ENV, bootstrap=b"")
    try:
        child_pid = read_pid(child_path)
        grandchild_pid = read_pid(grandchild_path)
        assert group.reclaim() == -signal.SIGKILL
        time.sleep(0.2)
        for pid in (child_pid, grandchild_pid):
            with pytest.raises(ProcessLookupError):
                os.kill(pid, 0)
    finally:
        if group.process.poll() is None:
            group.reclaim()


def test_anchor_refuses_reclaim_after_anchor_exit(tmp_path):
    child_path = tmp_path / "child.pid"
    group = AnchorProcessGroup.start([sys.executable, str(ENGINE), "sleep_child", str(child_path)],
                                     cwd=tmp_path, env=ENV, bootstrap=b"")
    child_pid = read_pid(child_path)
    try:
        os.kill(group.anchor_pid, signal.SIGKILL)
        group.process.wait(timeout=10)
        with pytest.raises(ValueError, match="锚点进程已经退出"):
            group.reclaim()
        os.kill(child_pid, 0)
    finally:
        group.close_control()
        os.kill(child_pid, signal.SIGKILL)
        os.kill(group.engine_pid, signal.SIGKILL)


def test_anchor_cleanup_handles_child_exit_before_signal(tmp_path):
    read_fd, write_fd = os.pipe()
    process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(0.05)"], start_new_session=True)
    group = AnchorProcessGroup(process, write_fd, process.pid, None)
    try:
        def fail_then_cleanup():
            try:
                raise ValueError("original-start-error")
            finally:
                group._cleanup_failed_start()

        with pytest.raises(ValueError, match="original-start-error"):
            fail_then_cleanup()
        assert process.poll() is not None
        assert group.control_write is None
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=10)
        os.close(read_fd)
