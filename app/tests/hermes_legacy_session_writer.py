import sys
from pathlib import Path

from boss_memory_sessions import MemorySessionManager
from controls import ControlStore

root = Path(sys.argv[1])
store = ControlStore(root / "business.sqlite")
sessions = MemorySessionManager(root / "workspace", business_store=store, sessions_root=root / "sessions")
session = sessions.get_or_create("websocket:legacy-check")
session.add_message("user", "跨进程核查会议资料")
print("ready", flush=True)
sys.stdin.readline()
print("writing", flush=True)
sessions.save(session, fsync=True)
print("saved", flush=True)
