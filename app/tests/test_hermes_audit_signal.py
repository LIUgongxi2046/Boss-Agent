import ctypes
import errno
import os
import signal
import socket
import sys
from pathlib import Path

from hermes_anchor_supervisor import AnchorExitObserver
from hermes_process_anchor import AnchorProcessGroup


PROBE = Path(__file__).with_name("hermes_audit_peer_probe.py").resolve()
ENV = {"PATH": "/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE": "1"}


def test_audit_token_targets_engine_after_anchor_exit(tmp_path):
    path = Path(__file__).resolve().parents[2] / ".work" / ("audit-" + str(os.getpid()) + ".sock")
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
        listener.bind(str(path))
        listener.listen(1)
        listener.settimeout(5)
        group = AnchorProcessGroup.start([sys.executable, str(PROBE), str(path)], cwd=tmp_path, env=ENV)
        observer = AnchorExitObserver(group)
        try:
            with listener.accept()[0] as connection:
                assert connection.recv(5) == b"ready"
                assert connection.getsockopt(0, 2) == group.engine_pid
                token = connection.getsockopt(0, 6, 32)
                assert len(token) == 32
                group.process.kill()
                group.process.wait(timeout=5)
                assert group.anchor_pid in observer.poll(timeout=5)
                signal_process = ctypes.CDLL(None).proc_signal_with_audittoken
                signal_process.argtypes = [ctypes.c_void_p, ctypes.c_int]
                signal_process.restype = ctypes.c_int
                opaque_token = ctypes.create_string_buffer(token, len(token))
                assert signal_process(opaque_token, signal.SIGKILL) == 0
                assert group.engine_pid in observer.poll(timeout=5)
                assert signal_process(opaque_token, 0) == errno.ESRCH
        finally:
            observer.close()
            group.close_control()
            if group.process.poll() is None:
                group.reclaim()
            path.unlink()
