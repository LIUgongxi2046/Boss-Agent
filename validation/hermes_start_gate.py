import os
import select
import sys


descriptor = int(sys.argv[1])
acknowledgement = int(sys.argv[2])
timeout = float(sys.argv[3])
command = sys.argv[4:]
if not select.select([descriptor], [], [], timeout)[0]:
    raise TimeoutError("引擎启动许可超时")
if os.read(descriptor, 1) != b"G":
    raise ValueError("引擎启动许可无效")
os.close(descriptor)
os.write(acknowledgement, b"G")
os.close(acknowledgement)
os.execvpe(command[0], command, os.environ)
