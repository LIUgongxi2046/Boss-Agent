import argparse
import os
import secrets
import sys
import time
from pathlib import Path
from uuid import uuid4

from hermes_guest_identity import HermesGuestIdentityRegistry
from hermes_guest_systemd import HermesGuestSystemd


parser = argparse.ArgumentParser()
parser.add_argument("--workspace-root", type=Path)
parser.add_argument("--supervisor-unit", default="boss-test-engine.service")
arguments = parser.parse_args()
run_id = str(uuid4())
identity_directory = Path("/var/lib/boss-vm") / ("engine-import-check-" + run_id)
identity_directory.mkdir(mode=0o700)
identities = HermesGuestIdentityRegistry(identity_directory)
_, uid, gid = identities.ensure(run_id)
if arguments.workspace_root is None:
    root = Path("/run") / ("boss-engine-workspaces-" + run_id)
    root.mkdir(mode=0o700)
else:
    root = arguments.workspace_root
    if not root.is_absolute() or root.is_symlink() or root.resolve(strict=True) != root or not root.is_dir():
        raise ValueError("引擎检查工作区不可核查")
workspace = root / run_id
workspace.mkdir(mode=0o700)
os.chown(workspace, uid, gid)
role = workspace / "role"
role.write_text("engine", encoding="ascii")
os.chown(role, uid, gid)
role.chmod(0o600)
engine = Path("/run/boss-deps/cache/sdists-v10/path/7f514581f9b997f3/xYP5jZaAg8X-8QWQ/src")
manager = HermesGuestSystemd(python=Path(sys.executable).resolve(), entry=Path("/run/boss-checks/guest-identity-probe.py"),
                             engine=engine, dependencies=Path("/run/boss-deps/linux-target"), workspace_root=root,
                             identities=identities, supervisor_unit=arguments.supervisor_unit)
boot_id = Path("/proc/sys/kernel/random/boot_id").read_text(encoding="ascii").strip()
budget = {"rounds": 1, "seconds": 60, "memory_bytes": 402653184, "processes": 32,
          "cpu_percent": 100, "open_files": 128, "files": 16, "file_bytes": 1048576, "cpu_seconds": 20}
bootstrap = {"endpoint": "http://127.0.0.1:19999", "capability": secrets.token_urlsafe(32),
             "provider_capability": secrets.token_urlsafe(32), "run_id": run_id,
             "engine_commit": "903230b1e23e0c496b28e5d2e8c4f2639cd506b6"}
unit, process = manager.launch(run_id, 1, boot_id, budget, bootstrap)
try:
    deadline = time.monotonic() + 30
    while not (workspace / "ready").is_file() and time.monotonic() < deadline:
        if process.poll() is not None:
            diagnostic = workspace / "engine-diagnostic.log"
            if diagnostic.is_file():
                lines = diagnostic.read_text(encoding="utf-8").splitlines()
                if lines:
                    raise ValueError("客体引擎启动失败：" + lines[-1])
            raise ValueError("客体引擎导入提前结束")
        time.sleep(0.1)
    if not (workspace / "ready").is_file():
        raise TimeoutError("客体引擎导入等待超时")
    for path in workspace.rglob("*"):
        if path.is_file() and not path.is_symlink():
            content = path.read_bytes()
            if any(bootstrap[name].encode("ascii") in content for name in ("capability", "provider_capability")):
                raise ValueError("客体引擎凭据出现在工作区文件")
    print("GUEST_SANDBOXED_HERMES_INITIALIZATION_OK", flush=True)
finally:
    manager.stop(run_id, 1)
    process.wait(timeout=15)
