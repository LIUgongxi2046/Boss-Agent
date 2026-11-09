import json
import base64
import os
import select
import subprocess
import sys


def main():
    control_fd = int(os.environ["HERMES_PARENT_GUARD_FD"])
    config = json.loads(sys.stdin.buffer.readline())
    if not isinstance(config, dict) or set(config) != {"command", "env", "bootstrap", "pass_fds"}:
        raise ValueError("引擎启动配置无效")
    command = config["command"]
    if not isinstance(command, list) or not command or any(not isinstance(item, str) or not item for item in command):
        raise ValueError("引擎命令无效")
    if not os.path.isabs(command[0]):
        raise ValueError("引擎执行文件路径无效")
    if not isinstance(config["env"], dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in config["env"].items()):
        raise ValueError("引擎环境无效")
    if not isinstance(config["pass_fds"], list) or any(type(fd) is not int or fd < 0 for fd in config["pass_fds"]):
        raise ValueError("引擎描述符无效")
    bootstrap = base64.b64decode(config["bootstrap"], validate=True)
    queue = select.kqueue()
    child = None
    try:
        child = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL, close_fds=True, env=config["env"], pass_fds=tuple(config["pass_fds"]))
        change = select.kevent(child.pid, filter=select.KQ_FILTER_PROC, flags=select.KQ_EV_ADD | select.KQ_EV_ENABLE,
                               fflags=select.KQ_NOTE_EXIT)
        queue.control([change], 0, 0)
        sys.stdout.write(json.dumps({"engine_pid": child.pid}) + "\n")
        sys.stdout.flush()
        descriptor = child.stdin.fileno()
        os.set_blocking(descriptor, False)
        delivered = 0
        try:
            while True:
                if delivered == len(bootstrap) and not child.stdin.closed:
                    child.stdin.close()
                writable = [descriptor] if not child.stdin.closed else []
                readable, writable, _ = select.select([control_fd, queue.fileno()], writable, [])
                if control_fd in readable:
                    if os.read(control_fd, 1):
                        raise ValueError("父进程控制管道无效")
                    child.kill()
                    break
                if queue.fileno() in readable:
                    if delivered != len(bootstrap):
                        raise ValueError("引擎启动信息未完整传输")
                    break
                if writable:
                    delivered += os.write(descriptor, bootstrap[delivered:])
        finally:
            error = sys.exception()
            if error is not None:
                number = error.errno if isinstance(error, OSError) and type(error.errno) is int else None
                kind = type(error).__name__ if type(error).__module__ == "builtins" else "OTHER"
                sys.stdout.write(json.dumps({"engine_error": {"stage": "BOOTSTRAP_DELIVERY", "kind": kind, "errno": number}}) + "\n")
                sys.stdout.flush()
        child.wait()
        sys.stdout.write(json.dumps({"engine_exit": child.returncode}) + "\n")
        sys.stdout.flush()
    finally:
        if child is not None and child.returncode is None:
            child.kill()
            child.wait()
        queue.close()
        os.close(control_fd)


if __name__ == "__main__":
    main()
