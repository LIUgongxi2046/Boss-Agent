import argparse
import json
import subprocess
import time
from pathlib import Path


parser = argparse.ArgumentParser()
parser.add_argument("mount", type=Path)
parser.add_argument("source")
arguments = parser.parse_args()
if not arguments.mount.is_absolute() or not arguments.source:
    raise ValueError("受管工作区监督身份无效")

while True:
    result = subprocess.run(["/usr/bin/findmnt", "--json", "--mountpoint", str(arguments.mount),
                             "--output", "TARGET,FSTYPE,SOURCE"], check=True, timeout=5, capture_output=True, text=True)
    entries = json.loads(result.stdout)["filesystems"]
    if len(entries) != 1 or entries[0] != {"target": str(arguments.mount), "fstype": "fuse.juicefs", "source": arguments.source}:
        raise ValueError("受管工作区挂载身份已经变化")
    subprocess.run(["/usr/bin/systemd-notify", "WATCHDOG=1"], check=True, timeout=5,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(0.1)
