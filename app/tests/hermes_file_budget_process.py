import hashlib
import os
import sys
from pathlib import Path
from uuid import uuid4

from agent_run_store import RunStore


database, run_id, owner, epoch, request_key, file_path = sys.argv[1:]
path = Path(file_path)
with path.open("rb") as source:
    digest = hashlib.file_digest(source, "sha256").hexdigest()
size = path.stat().st_size
store = RunStore(Path(database), allow_migration=False)
print("READY", flush=True)
if os.read(sys.stdin.fileno(), 1) != b"x":
    raise ValueError("文件预算检查未获得启动许可")
with store.connect() as db:
    db.execute("BEGIN IMMEDIATE")
    store.reserve_file_in_transaction(db, run_id, owner, int(epoch), request_key, digest, str(uuid4()), size)
