import json
import os
import subprocess
import sys
import time
from pathlib import Path


mode = sys.argv[1]
if mode == "lingering":
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(5)"])
    Path(sys.argv[2]).write_text(str(child.pid), encoding="utf-8")
    time.sleep(0.1)
    sys.exit(0)
if mode == "sleep":
    time.sleep(30)
    sys.exit(0)
if mode == "ready_sleep":
    Path(sys.argv[2]).write_text(str(os.getpid()), encoding="utf-8")
    time.sleep(30)
    sys.exit(0)
if mode == "no_read":
    time.sleep(30)
    sys.exit(0)
if mode == "sleep_child":
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    Path(sys.argv[2]).write_text(str(child.pid), encoding="utf-8")
    time.sleep(30)
    sys.exit(0)
if mode == "grandchild":
    child_code = ("import subprocess,sys,time,pathlib; "
                  "g=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)']); "
                  "pathlib.Path(sys.argv[1]).write_text(str(g.pid)); time.sleep(30)")
    child = subprocess.Popen([sys.executable, "-c", child_code, sys.argv[2]])
    Path(sys.argv[2] + ".child").write_text(str(child.pid), encoding="utf-8")
    time.sleep(30)
    sys.exit(0)
if mode == "detached":
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"], start_new_session=True)
    Path(sys.argv[2]).write_text(str(child.pid), encoding="utf-8")
    sys.exit(0)
if mode == "fd_exists":
    descriptor = int(sys.argv[3])
    result = {"descriptor": descriptor, "exists": os.path.exists("/dev/fd/" + str(descriptor)),
              "stdin": os.path.exists("/dev/fd/0"), "stdout": os.path.exists("/dev/fd/1"),
              "stderr": os.path.exists("/dev/fd/2")}
    Path(sys.argv[2]).write_text(json.dumps(result), encoding="utf-8")
    sys.exit(0)
raise ValueError("未知引擎探针模式")
