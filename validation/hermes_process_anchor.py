import base64
import json
import math
import os
import select
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path


class GuardianBootstrapError(RuntimeError):
    def __init__(self, kind, number):
        super().__init__("引擎启动信息传输失败")
        self.stage = "BOOTSTRAP_DELIVERY"
        self.kind = kind
        self.errno = number


def _require_engine_owned_by_anchor(anchor_pid, engine_pid):
    if type(anchor_pid) is not int or type(engine_pid) is not int or anchor_pid <= 0 or engine_pid <= 0 or anchor_pid == engine_pid:
        raise ValueError("锚点或引擎进程编号无效")
    if os.getpgid(anchor_pid) != anchor_pid or os.getsid(anchor_pid) != anchor_pid:
        raise ValueError("锚点进程组身份无效")
    if os.getpgid(engine_pid) != anchor_pid or os.getsid(engine_pid) != anchor_pid:
        raise ValueError("引擎进程组或会话归属无效")


def _resource_limited_command(command, limits):
    if limits is None:
        return list(command)
    if not isinstance(limits, dict) or set(limits) != {"file_bytes", "open_files", "cpu_seconds"}:
        raise ValueError("锚点或引擎资源限制无效")
    if any(type(limits[key]) is not int for key in limits):
        raise ValueError("锚点或引擎资源限制无效")
    if limits["file_bytes"] <= 0 or limits["open_files"] < 16 or limits["cpu_seconds"] <= 0:
        raise ValueError("锚点或引擎资源限制无效")
    executor = Path(__file__).with_name("hermes_resource_exec.py")
    python = Path(sys.executable)
    if not executor.is_file() or not python.is_absolute() or not python.is_file():
        raise ValueError("资源限制执行器无效")
    return [str(python), str(executor),
            "--file-bytes", str(limits["file_bytes"]),
            "--open-files", str(limits["open_files"]),
            "--cpu-seconds", str(limits["cpu_seconds"]),
            *command]


def _read_guard_start_report(stream, timeout):
    deadline = time.monotonic() + timeout
    data = bytearray()
    while not data.endswith(b"\n"):
        ready, _, _ = select.select([stream], [], [], max(0, deadline - time.monotonic()))
        if not ready:
            raise TimeoutError("引擎监督启动报告超时")
        chunk = os.read(stream.fileno(), 1)
        if not chunk:
            raise ValueError("引擎监督未报告启动")
        data.extend(chunk)
        if len(data) > 4096:
            raise ValueError("引擎监督启动报告过长")
    return json.loads(data)


class AnchorProcessGroup:
    def __init__(self, process, control_write, anchor_pid, engine_pid):
        self.process = process
        self.control_write = control_write
        self.anchor_pid = anchor_pid
        self.engine_pid = engine_pid
        self.guardian_pid = None
        self._reclaim_lock = threading.Lock()
        self._reclaim_attempted = False
        self._message_buffer = bytearray()
        self._deferred = False
        self._pending_engine_exit = None
        self._read_lock = threading.Lock()
        self.gate_status = None
        self._gate_pending = False

    @classmethod
    def start(cls, command, *, cwd, env, bootstrap=b"", timeout=10, pid_file=None, limits=None, deferred=False, gate_timeout=10, guarded=False):
        if not isinstance(command, list) or not command or any(not isinstance(item, str) or not item for item in command):
            raise ValueError("锚点启动命令无效")
        if not Path(command[0]).is_absolute() or not Path(command[0]).is_file():
            raise ValueError("锚点启动执行文件无效")
        if not isinstance(cwd, Path) or not cwd.is_dir():
            raise ValueError("锚点工作目录无效")
        if not isinstance(env, dict) or any(not isinstance(key, str) or not isinstance(value, str) for key, value in env.items()):
            raise ValueError("锚点环境无效")
        if not isinstance(bootstrap, bytes):
            raise ValueError("锚点启动信息无效")
        if type(deferred) is not bool:
            raise ValueError("锚点启动许可配置无效")
        if type(guarded) is not bool:
            raise ValueError("引擎监督配置无效")
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("锚点启动时限无效")
        if isinstance(gate_timeout, bool) or not isinstance(gate_timeout, (int, float)) or not math.isfinite(gate_timeout) or gate_timeout <= 0:
            raise ValueError("锚点启动许可时限无效")
        if pid_file is not None and (not isinstance(pid_file, Path) or pid_file.is_symlink()):
            raise ValueError("锚点诊断文件无效")
        anchor_command = _resource_limited_command([sys.executable, str(Path(__file__).resolve()), "--anchor"], limits)
        engine_command = _resource_limited_command(command, limits)
        read_fd, write_fd = os.pipe()
        anchor_env = {"PATH": "/usr/bin:/bin", "HERMES_ANCHOR_CONTROL_FD": str(read_fd),
                      "PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1"}
        process = None
        try:
            process = subprocess.Popen(anchor_command,
                                       stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                       cwd=str(cwd), env=anchor_env, start_new_session=True, pass_fds=(read_fd,), close_fds=True)
        finally:
            if process is None:
                os.close(read_fd)
                os.close(write_fd)
        os.close(read_fd)
        group = cls(process, write_fd, None, None)
        group._deferred = deferred
        started = False
        try:
            config = {"command": engine_command, "cwd": str(cwd), "env": env, "bootstrap": base64.b64encode(bootstrap).decode("ascii"), "deferred": deferred, "gate_timeout": gate_timeout, "guarded": guarded, "startup_timeout": timeout}
            if pid_file is not None:
                config["pid_file"] = str(pid_file)
            process.stdin.write((json.dumps(config, ensure_ascii=False) + "\n").encode("utf-8"))
            process.stdin.flush()
            group._close_stdin()
            message = group._read_message(timeout)
            expected = {"anchor_pid", "engine_pid", "guardian_pid"} if guarded else {"anchor_pid", "engine_pid"}
            if set(message) != expected or message["anchor_pid"] != process.pid or type(message["engine_pid"]) is not int or message["engine_pid"] <= 0 or message["engine_pid"] == message["anchor_pid"]:
                raise ValueError("锚点进程报告无效")
            _require_engine_owned_by_anchor(message["anchor_pid"], message["engine_pid"])
            if guarded:
                _require_engine_owned_by_anchor(message["anchor_pid"], message["guardian_pid"])
                if message["guardian_pid"] == message["engine_pid"]:
                    raise ValueError("引擎监督进程编号无效")
                group.guardian_pid = message["guardian_pid"]
            group.anchor_pid = message["anchor_pid"]
            group.engine_pid = message["engine_pid"]
            started = True
            return group
        finally:
            if not started:
                group._cleanup_failed_start()

    def _read_message(self, timeout):
        deadline = time.monotonic() + timeout
        while b"\n" not in self._message_buffer:
            remaining = max(0, deadline - time.monotonic())
            ready, _, _ = select.select([self.process.stdout], [], [], remaining)
            if not ready:
                raise TimeoutError("锚点进程未在时限内报告")
            chunk = os.read(self.process.stdout.fileno(), 4096)
            if not chunk:
                raise ValueError("锚点进程未报告")
            self._message_buffer.extend(chunk)
        line, _, remainder = self._message_buffer.partition(b"\n")
        self._message_buffer = bytearray(remainder)
        message = json.loads(line)
        if not isinstance(message, dict):
            raise ValueError("锚点进程报告格式无效")
        if set(message) == {"engine_error"}:
            error = message["engine_error"]
            if not isinstance(error, dict) or set(error) != {"stage", "kind", "errno"} or error["stage"] != "BOOTSTRAP_DELIVERY" or not isinstance(error["kind"], str) or not error["kind"].isascii() or not error["kind"].isidentifier() or len(error["kind"]) > 80 or not (error["errno"] is None or type(error["errno"]) is int):
                raise ValueError("引擎监督错误报告无效")
            try:
                with self._reclaim_lock:
                    if self.control_write is not None:
                        os.write(self.control_write, b"E")
            finally:
                raise GuardianBootstrapError(error["kind"], error["errno"])
        return message

    def _cleanup_failed_start(self):
        self.close_control()
        self._close_stdin()
        deadline = time.monotonic() + 10
        while self.process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.02)
        if self.process.poll() is None:
            self.process.kill()
            self.process.wait(timeout=10)
        self._close_stdin()
        if self.process.stdout is not None and not self.process.stdout.closed:
            self.process.stdout.close()

    def read_engine_exit(self, *, timeout=10):
        with self._read_lock:
            if self._pending_engine_exit is not None:
                result = self._pending_engine_exit
                self._pending_engine_exit = None
                return result
            message = self._read_exit_message(timeout)
        if set(message) != {"engine_exit"} or type(message["engine_exit"]) is not int:
            raise ValueError("引擎退出报告无效")
        return message["engine_exit"]

    def poll_engine_exit(self):
        with self._read_lock:
            if self._pending_engine_exit is not None:
                result = self._pending_engine_exit
                self._pending_engine_exit = None
                return result
            try:
                message = self._read_exit_message(0)
            except TimeoutError:
                return None
        if set(message) != {"engine_exit"} or type(message["engine_exit"]) is not int:
            raise ValueError("引擎退出报告无效")
        return message["engine_exit"]

    def _read_exit_message(self, timeout):
        deadline = time.monotonic() + timeout
        while True:
            message = self._read_message(max(0, deadline - time.monotonic()))
            if self._gate_pending and message in ({"gate": "RELEASED"}, {"gate": "UNCONFIRMED"}):
                self.gate_status = message["gate"]
                self._gate_pending = False
                continue
            return message

    def reclaim(self):
        with self._reclaim_lock:
            if self._reclaim_attempted:
                raise ValueError("锚点回收已经开始")
            self._reclaim_attempted = True
            descriptor = self.control_write
            if descriptor is None:
                raise ValueError("锚点控制管道已经关闭")
            self.control_write = None
        try:
            if self.process.poll() is not None:
                raise ValueError("锚点进程已经退出，进程组归属不可核查")
            if os.getpgid(self.anchor_pid) != self.anchor_pid or os.getsid(self.anchor_pid) != self.anchor_pid:
                raise ValueError("锚点进程组身份不可核查")
            os.write(descriptor, b"stop")
            return self.process.wait(timeout=10)
        finally:
            os.close(descriptor)
            self._close_stdin()
            if self.process.poll() is not None:
                with self._read_lock:
                    if self.process.stdout is not None and not self.process.stdout.closed:
                        self.process.stdout.close()

    def release_engine(self, *, timeout=10):
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("锚点启动许可时限无效")
        with self._read_lock:
            with self._reclaim_lock:
                if not self._deferred or self._reclaim_attempted or self.control_write is None or self.process.poll() is not None:
                    raise ValueError("锚点启动许可不可用")
                os.write(self.control_write, b"G")
                self._deferred = False
                self._gate_pending = True
            deadline = time.monotonic() + timeout
            while True:
                message = self._read_message(max(0, deadline - time.monotonic()))
                if set(message) == {"engine_exit"} and type(message["engine_exit"]) is int and self._pending_engine_exit is None:
                    self._pending_engine_exit = message["engine_exit"]
                    continue
                if message in ({"gate": "RELEASED"}, {"gate": "UNCONFIRMED"}):
                    self.gate_status = message["gate"]
                    self._gate_pending = False
                if message != {"gate": "RELEASED"}:
                    raise ValueError("引擎启动许可未确认")
                return

    def close_control(self):
        with self._reclaim_lock:
            descriptor = self.control_write
            self.control_write = None
        if descriptor is not None:
            os.close(descriptor)

    def _close_stdin(self):
        if self.process.stdin is not None and not self.process.stdin.closed:
            self.process.stdin.close()

    def wait(self, timeout=10):
        return self.process.wait(timeout=timeout)


def _anchor_main():
    config = json.loads(sys.stdin.buffer.readline())
    required = {"command", "cwd", "env", "bootstrap", "deferred", "gate_timeout", "guarded", "startup_timeout"}
    if not isinstance(config, dict) or not required.issubset(config) or set(config) - required - {"pid_file"}:
        raise ValueError("锚点启动配置无效")
    control_fd = int(os.environ["HERMES_ANCHOR_CONTROL_FD"])
    pid_file = config.get("pid_file")
    if pid_file is not None:
        if not isinstance(pid_file, str) or not pid_file:
            raise ValueError("锚点诊断文件无效")
        Path(pid_file).write_text(str(os.getpid()), encoding="utf-8")

    gate_read, gate_write = os.pipe()
    ack_read, ack_write = os.pipe()
    output_lock = threading.Lock()
    error_ack = threading.Event()

    def watch_control():
        while True:
            message = os.read(control_fd, 1)
            if message == b"G":
                os.write(gate_write, b"G")
                if select.select([ack_read], [], [], config["gate_timeout"])[0] and os.read(ack_read, 1) == b"G":
                    with output_lock:
                        sys.stdout.write(json.dumps({"gate": "RELEASED"}) + "\n")
                        sys.stdout.flush()
                else:
                    with output_lock:
                        sys.stdout.write(json.dumps({"gate": "UNCONFIRMED"}) + "\n")
                        sys.stdout.flush()
            elif message == b"E":
                error_ack.set()
            else:
                os.killpg(0, signal.SIGKILL)

    threading.Thread(target=watch_control, daemon=True).start()
    command = config["command"]
    if config["deferred"]:
        command = [sys.executable, "-I", "-S", str(Path(__file__).with_name("hermes_start_gate.py")), str(gate_read), str(ack_write), str(config["gate_timeout"]), *command]
    guard_write = None
    if config["guarded"]:
        guard_started = False
        try:
            guard_read, guard_write = os.pipe()
            guard_env = {"PATH": "/usr/bin:/bin", "HERMES_PARENT_GUARD_FD": str(guard_read), "PYTHONDONTWRITEBYTECODE": "1"}
            engine_fds = [gate_read, ack_write] if config["deferred"] else []
            guard = subprocess.Popen([sys.executable, str(Path(__file__).with_name("hermes_parent_guard.py"))],
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                     cwd=config["cwd"], env=guard_env, close_fds=True,
                                     pass_fds=(guard_read, *engine_fds))
            os.close(guard_read)
            guard_config = {"command": command, "env": config["env"], "bootstrap": config["bootstrap"], "pass_fds": engine_fds}
            guard.stdin.write((json.dumps(guard_config) + "\n").encode())
            guard.stdin.close()
            report = _read_guard_start_report(guard.stdout, config["startup_timeout"])
            if set(report) != {"engine_pid"} or type(report["engine_pid"]) is not int or report["engine_pid"] <= 0:
                raise ValueError("引擎监督启动报告无效")
            engine_pid = report["engine_pid"]
            os.close(ack_write)
            with output_lock:
                sys.stdout.write(json.dumps({"anchor_pid": os.getpid(), "engine_pid": engine_pid, "guardian_pid": guard.pid}) + "\n")
                sys.stdout.flush()
            guard_started = True
        finally:
            if not guard_started:
                os.killpg(0, signal.SIGKILL)
    else:
        engine = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                  stderr=subprocess.DEVNULL, cwd=config["cwd"], env=config["env"],
                                  close_fds=True, start_new_session=False, pass_fds=(gate_read, ack_write) if config["deferred"] else ())
        engine_pid = engine.pid
        os.close(ack_write)
        with output_lock:
            sys.stdout.write(json.dumps({"anchor_pid": os.getpid(), "engine_pid": engine_pid}) + "\n")
            sys.stdout.flush()
    if config["guarded"]:
        finished = False
        try:
            line = guard.stdout.readline()
            if not line:
                raise ValueError("引擎监督未报告退出")
            report = json.loads(line)
            if set(report) == {"engine_error"}:
                with output_lock:
                    sys.stdout.write(json.dumps(report) + "\n")
                    sys.stdout.flush()
                error_ack.wait(config["gate_timeout"])
                raise ValueError("引擎监督报告启动信息传输失败")
            if set(report) != {"engine_exit"} or type(report["engine_exit"]) is not int:
                raise ValueError("引擎监督退出报告无效")
            exit_code = report["engine_exit"]
            if guard.wait() != 0:
                raise ValueError("引擎监督进程异常退出")
            os.close(guard_write)
            finished = True
        finally:
            if not finished:
                os.killpg(0, signal.SIGKILL)
    else:
        bootstrap = base64.b64decode(config["bootstrap"])
        if bootstrap:
            engine.stdin.write(bootstrap)
            engine.stdin.flush()
        engine.stdin.close()
        exit_code = engine.wait()
    with output_lock:
        sys.stdout.write(json.dumps({"engine_exit": exit_code}) + "\n")
        sys.stdout.flush()
    time.sleep(3600)


if __name__ == "__main__":
    _anchor_main()
