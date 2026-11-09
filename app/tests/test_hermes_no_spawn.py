import subprocess
import sys
from pathlib import Path

import pytest


PROBE = Path(__file__).with_name("hermes_process_creation_probe.py").resolve()
PROFILE = Path(__file__).with_name("hermes_no_spawn.sb").resolve()


@pytest.mark.parametrize("action", ["current", "fork", "spawn", "detached"])
def test_process_creation_boundary(action):
    command = [sys.executable, str(PROBE), action]
    control = subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True, timeout=15, check=False)
    assert control.returncode == 0
    restricted = subprocess.run(["/usr/bin/sandbox-exec", "-f", str(PROFILE), *command], stdin=subprocess.DEVNULL, capture_output=True, timeout=15, check=False)
    if action == "current":
        assert restricted.returncode == 0
    else:
        assert restricted.returncode != 0
        assert b"PermissionError" in restricted.stderr and b"Operation not permitted" in restricted.stderr
