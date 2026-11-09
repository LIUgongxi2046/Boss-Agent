import json
import os
import subprocess
import sys
import time
from pathlib import Path


guard_path = Path(sys.argv[1]).resolve()
output = Path(sys.argv[2])
read_fd, write_fd = os.pipe()
environment = {"PATH": "/usr/bin:/bin", "HERMES_PARENT_GUARD_FD": str(read_fd), "PYTHONDONTWRITEBYTECODE": "1"}
guard = subprocess.Popen([sys.executable, str(guard_path)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.DEVNULL, env=environment, pass_fds=(read_fd,), close_fds=True)
os.close(read_fd)
config = {"command": [sys.executable, "-c", "import time; time.sleep(5)"], "env": {"PATH": "/usr/bin:/bin"}, "bootstrap": "", "pass_fds": []}
guard.stdin.write((json.dumps(config) + "\n").encode())
guard.stdin.close()
message = json.loads(guard.stdout.readline())
output.write_text(json.dumps({"guard_pid": guard.pid, "engine_pid": message["engine_pid"]}), encoding="utf-8")
time.sleep(30)
os.close(write_fd)
