import json
import resource
import subprocess
import sys
from pathlib import Path


mode = sys.argv[1]
if mode == "limits":
    print(json.dumps({name: resource.getrlimit(getattr(resource, name)) for name in ("RLIMIT_CORE", "RLIMIT_FSIZE", "RLIMIT_NOFILE", "RLIMIT_CPU")}))
elif mode == "child":
    subprocess.run([sys.executable, __file__, "limits"], check=True)
elif mode == "file":
    Path(sys.argv[2]).write_bytes(b"x" * 8192)
elif mode == "descriptors":
    opened = []
    while True:
        opened.append(open("/dev/null", "rb"))
elif mode == "raise":
    resource.setrlimit(resource.RLIMIT_FSIZE, (8192, 8192))
elif mode == "cpu":
    while True:
        pass
else:
    raise ValueError("资源检查参数无效")
