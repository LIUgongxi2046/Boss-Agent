import os
import socket
import sys
from pathlib import Path


action, target = sys.argv[1:]
if action == "read":
    print(Path(target).read_text(encoding="utf-8"))
elif action == "write":
    Path(target).write_text("隔离写入", encoding="utf-8")
elif action == "connect":
    with socket.create_connection(("127.0.0.1", int(target)), timeout=3):
        print("connected")
elif action == "fork":
    child = os.fork()
    if child == 0:
        os._exit(0)
    os.waitpid(child, 0)
    print("forked")
elif action == "exec":
    child = os.posix_spawn(sys.executable, [sys.executable, "-c", "pass"], os.environ)
    os.waitpid(child, 0)
    print("spawned")
else:
    raise ValueError("隔离检查动作无效")
