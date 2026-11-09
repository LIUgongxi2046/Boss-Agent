import socket
import sys
from pathlib import Path

action, target = sys.argv[1:]
if action == "read":
    Path(target).read_text(encoding="utf-8")
elif action == "write":
    Path(target).write_text("模拟隔离资料", encoding="utf-8")
elif action == "connect":
    with socket.create_connection(("127.0.0.1", int(target)), timeout=3):
        pass
elif action == "connect-ipv6":
    with socket.socket(socket.AF_INET6, socket.SOCK_STREAM) as connection:
        connection.settimeout(3)
        connection.connect(("::1", int(target)))
elif action == "connect-mapped":
    with socket.socket(socket.AF_INET6, socket.SOCK_STREAM) as connection:
        connection.settimeout(3)
        connection.connect(("::ffff:127.0.0.1", int(target)))
elif action == "connect-unix":
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(3)
        connection.connect(target)
elif action == "inherited-unix":
    with socket.socket(fileno=int(target)) as connection:
        connection.sendall(b"probe")
else:
    raise ValueError("隔离检查动作无效")
