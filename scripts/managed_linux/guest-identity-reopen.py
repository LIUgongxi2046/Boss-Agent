import hashlib
import subprocess
import sys
from pathlib import Path

from hermes_guest_identity import HermesGuestIdentityRegistry


registry = HermesGuestIdentityRegistry(Path("/var/lib/boss-vm/identity-check"))
with registry.connect() as db:
    identities = db.execute("SELECT run_id,account,uid,state FROM guest_identities ORDER BY run_id").fetchall()
    controls = db.execute("SELECT run_id,epoch,boot_id,state FROM guest_control ORDER BY run_id,epoch").fetchall()
if len(identities) != 2 or len(controls) != 1 or controls[0][3] != "STOPPED":
    raise ValueError("持久身份或控制记录不匹配")
for run_id, account, uid, state in identities:
    if state != "READY" or registry.ensure(run_id) != (account, uid, uid):
        raise ValueError("重启后的账号不匹配")
run_id, epoch, boot_id, _ = controls[0]
if registry.read_control(run_id, epoch, boot_id) != "STOPPED":
    raise ValueError("重启后的控制记录不匹配")
if sys.argv[1:] == ["--attempt-replay"]:
    workspace_identity = {"root_run_id": run_id, "root_epoch": 1, "max_files": 16, "max_bytes": 1048576}
    registry.reserve_start(run_id, epoch, boot_id, hashlib.sha256(b"guest identity integration").hexdigest(), workspace_identity)
    raise RuntimeError("已停止请求意外允许重派")
check = subprocess.run([sys.executable, __file__, "--attempt-replay"], capture_output=True, text=True, timeout=15)
if check.returncode == 0 or "客体启动请求已经变化或停止" not in check.stderr:
    raise ValueError("重启后的重复请求拒绝不可核查")
print("GUEST_IDENTITY_AND_STOP_RECORD_REOPENED", len(identities), len(controls), flush=True)
print("GUEST_STOPPED_REPLAY_REJECTED", flush=True)
