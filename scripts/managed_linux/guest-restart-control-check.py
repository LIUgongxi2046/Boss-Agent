import asyncio
import os
import secrets
import socket
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4

from aiohttp import ClientSession

from hermes_guest_identity import HermesGuestIdentityRegistry
from hermes_vm_credentials import load_vm_credential_pair, provision_vm_credentials


async def main():
    vm_id = str(uuid4())
    directory = Path("/var/lib/boss-vm") / ("control-restart-" + vm_id)
    directory.mkdir(mode=0o700)
    (directory / "identities").mkdir(mode=0o700)
    (directory / "workspaces").mkdir(mode=0o700)
    provision_vm_credentials(directory / "credentials", vm_id)
    host, _ = load_vm_credential_pair(directory / "credentials", vm_id)
    identities = HermesGuestIdentityRegistry(directory / "identities")
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    root_url = "https://127.0.0.1:" + str(port) + "/internal/v1/guest/"

    def start_control():
        subprocess.run(["/usr/bin/systemd-run", "--unit=boss-test-control", "--property=Type=notify", "--property=NotifyAccess=all",
            "--setenv=PYTHONPATH=/run/boss-deps/linux-target", "--setenv=PYTHONDONTWRITEBYTECODE=1",
            sys.executable, "/run/boss-checks/guest-restart-control-server.py", "--directory", str(directory),
            "--vm-id", vm_id, "--port", str(port)], check=True, timeout=15, stdout=subprocess.DEVNULL)

    def wait_control():
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            result = subprocess.run(["/usr/bin/systemctl", "show", "boss-test-control", "--property=SubState", "--value"],
                                    check=True, timeout=5, capture_output=True, text=True)
            if result.stdout.strip() == "running":
                return
            time.sleep(0.1)
        raise TimeoutError("客体控制服务未启动")

    async with ClientSession() as client:
        async def request(path, body):
            async with client.post(root_url + path, json=body, ssl=host.client, server_hostname=host.peer_name) as response:
                if response.status != 200:
                    raise ValueError("客体控制响应不可核查: " + path + " " + str(response.status))
                return await response.json()

        async def start_run(boot_id):
            run_id = str(uuid4())
            _, uid, gid = identities.ensure(run_id)
            workspace = directory / "workspaces" / run_id
            workspace.mkdir(mode=0o700)
            os.chown(workspace, uid, gid)
            role = workspace / "role"
            role.write_text("holder", encoding="ascii")
            os.chown(role, uid, gid)
            role.chmod(0o600)
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
                probe.bind(("127.0.0.1", 0))
                proxy_port = probe.getsockname()[1]
            budget = {"rounds": 1, "seconds": 60, "memory_bytes": 134217728, "processes": 32,
                      "cpu_percent": 100, "open_files": 64, "files": 16, "file_bytes": 1048576, "cpu_seconds": 20}
            bootstrap = {"endpoint": "http://127.0.0.1:" + str(proxy_port), "capability": secrets.token_urlsafe(32),
                         "provider_capability": secrets.token_urlsafe(32), "run_id": run_id,
                         "engine_commit": "903230b1e23e0c496b28e5d2e8c4f2639cd506b6"}
            key = {"run_id": run_id, "epoch": 1, "boot_id": boot_id}
            if await request("start", {**key, "budget": budget, "bootstrap": bootstrap}) != {"unit": "boss-" + run_id + "-1.service", "state": "UNKNOWN"}:
                raise ValueError("客体运行启动不可核查")
            deadline = time.monotonic() + 15
            while not (workspace / "ready").is_file() and time.monotonic() < deadline:
                await asyncio.sleep(0.1)
            if not (workspace / "ready").is_file():
                raise TimeoutError("客体运行未准备完成")
            return key

        start_control()
        wait_control()
        await asyncio.sleep(1)
        try:
            boot_id = (await request("identity", {}))["boot_id"]
            saved_key = await start_run(boot_id)
            if await request("stop", saved_key) != {"state": "UNKNOWN"}:
                raise ValueError("客体停止回执不可核查")
            saved = await request("final-exit", saved_key)
            running_key = await start_run(boot_id)
            subprocess.run(["/usr/bin/systemctl", "kill", "--signal=KILL", "boss-test-control.service"], check=True, timeout=15)
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                state = subprocess.run(["/usr/bin/systemctl", "show", "boss-test-control", "--property=ActiveState", "--value"],
                    check=True, timeout=5, capture_output=True, text=True).stdout.strip()
                if state == "failed":
                    break
                await asyncio.sleep(0.1)
            if state != "failed":
                raise TimeoutError("客体控制服务异常结束状态不可核查")
            subprocess.run(["/usr/bin/systemctl", "reset-failed", "boss-test-control.service"], check=True, timeout=15)
            await asyncio.sleep(1)
            start_control()
            wait_control()
            await asyncio.sleep(1)
            if (await request("identity", {}))["boot_id"] != boot_id or await request("final-exit", saved_key) != saved:
                raise ValueError("控制服务重启后已保存回执不可核查")
            if await request("final-exit-cleanup", saved_key) != saved:
                raise ValueError("控制服务重启后清理不可核查")
            if await request("stop", running_key) != {"state": "UNKNOWN"} or await request("final-exit-status", running_key) != {"state": "UNKNOWN"}:
                raise ValueError("控制服务异常期间运行状态不可核查")
            if await request("stop", running_key) != {"state": "UNKNOWN"}:
                raise ValueError("控制服务恢复停止不可重复")
            print("CONTROL_RESTART_SAVED_RECEIPT_READABLE", flush=True)
            print("CONTROL_RESTART_ACTIVE_RUN_REMAINS_UNKNOWN", flush=True)
        finally:
            subprocess.run(["/usr/bin/systemctl", "stop", "boss-test-control.service"], check=True, timeout=30)


asyncio.run(main())
