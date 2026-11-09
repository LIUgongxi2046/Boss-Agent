import os
import subprocess
import sys

action = sys.argv[1]
if action == "fork":
    pid = os.fork()
    if pid == 0:
        os._exit(0)
    _, status = os.waitpid(pid, 0)
    if status != 0:
        raise ValueError("子进程退出状态无效")
elif action == "spawn":
    pid = os.posix_spawn("/usr/bin/true", ["/usr/bin/true"], os.environ)
    _, status = os.waitpid(pid, 0)
    if status != 0:
        raise ValueError("子进程退出状态无效")
elif action == "detached":
    subprocess.run(["/usr/bin/true"], start_new_session=True, check=True)
elif action != "current":
    raise ValueError("检查动作无效")
