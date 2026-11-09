import asyncio
import os
import secrets
import socket
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4

from aiohttp import ClientSession, web

from hermes_guest_control import HermesGuestControl
from hermes_guest_identity import HermesGuestIdentityRegistry
from hermes_guest_proxy import HermesGuestRuntimeProxy
from hermes_guest_slice import slice_name
from hermes_guest_systemd import HermesGuestSystemd
from hermes_vm_credentials import load_vm_credential_pair, provision_vm_credentials


async def main():
    test_id = str(uuid4())
    parent = Path("/run") / ("boss-control-check-" + test_id)
    parent.mkdir(mode=0o700)
    credentials_directory = parent / "credentials"
    provision_vm_credentials(credentials_directory, test_id)
    host, guest = load_vm_credential_pair(credentials_directory, test_id)
    other_directory = parent / "other-credentials"
    provision_vm_credentials(other_directory, str(uuid4()))
    identities_directory = Path("/var/lib/boss-vm") / ("control-check-" + test_id)
    identities_directory.mkdir(mode=0o700)
    identities = HermesGuestIdentityRegistry(identities_directory)
    root = Path("/run") / ("boss-control-workspaces-" + test_id)
    root.mkdir(mode=0o700)
    run_id = str(uuid4())
    _, uid, gid = identities.ensure(run_id)
    workspace = root / run_id
    workspace.mkdir(mode=0o700)
    os.chown(workspace, uid, gid)
    role = workspace / "role"
    role.write_text("holder", encoding="ascii")
    os.chown(role, uid, gid)
    role.chmod(0o600)
    manager = HermesGuestSystemd(python=Path(sys.executable).resolve(), entry=Path("/run/boss-checks/guest-identity-probe.py"),
                                 engine=Path("/run/boss-checks"), dependencies=Path("/run/boss-deps/linux-target"), workspace_root=root,
                                 identities=identities, supervisor_unit="boss-test-control.service")
    proxy = HermesGuestRuntimeProxy(guest.client, guest.peer_name, guest.peer_sha256, 1024)
    control = HermesGuestControl(manager, proxy, guest.server, guest.peer_sha256)
    runner = web.AppRunner(control.application())
    await runner.setup()
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    port = listener.getsockname()[1]
    await web.SockSite(runner, listener, ssl_context=guest.server).start()
    root_url = "https://127.0.0.1:" + str(port) + "/internal/v1/guest/"
    try:
        rejected = await asyncio.create_subprocess_exec(
            "/usr/bin/openssl", "s_client", "-quiet", "-verify_return_error", "-connect", "127.0.0.1:" + str(port),
            "-servername", host.peer_name, "-CAfile", str(credentials_directory / "host/ca.pem"),
            "-cert", str(other_directory / "host/certificate.pem"), "-key", str(other_directory / "host/private-key.pem"),
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        output, errors = await asyncio.wait_for(rejected.communicate(b"POST /internal/v1/guest/identity HTTP/1.0\r\n\r\n"), 15)
        if rejected.returncode == 0 or b"verify return:1" not in errors or b"200 OK" in output:
            raise ValueError("客体控制没有拒绝其他证书")
        async with ClientSession() as session:
            async def request(path, body, expected=200):
                async with session.post(root_url + path, json=body, ssl=host.client, server_hostname=host.peer_name) as response:
                    if response.status != expected:
                        raise ValueError(f"客体控制响应状态不匹配: {path} 实际 {response.status}，预期 {expected}")
                    return await response.json() if expected == 200 else await response.text()

            boot = await request("identity", {})
            boot_id = Path("/proc/sys/kernel/random/boot_id").read_text(encoding="ascii").strip()
            if boot != {"boot_id": boot_id}:
                raise ValueError("客体启动身份不匹配")
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
                probe.bind(("127.0.0.1", 0))
                proxy_port = probe.getsockname()[1]
            budget = {"rounds": 1, "seconds": 30, "memory_bytes": 134217728, "processes": 32,
                      "cpu_percent": 100, "open_files": 64, "files": 16, "file_bytes": 1048576, "cpu_seconds": 10}
            bootstrap = {"endpoint": "http://127.0.0.1:" + str(proxy_port), "capability": secrets.token_urlsafe(32),
                         "provider_capability": secrets.token_urlsafe(32), "run_id": run_id,
                         "engine_commit": "903230b1e23e0c496b28e5d2e8c4f2639cd506b6"}
            start = {"run_id": run_id, "epoch": 1, "boot_id": boot_id, "budget": budget, "bootstrap": bootstrap}
            unit = "boss-" + run_id + "-1.service"
            if await request("start", start) != {"unit": unit, "state": "UNKNOWN"}:
                raise ValueError("客体启动回执不匹配")
            try:
                if (run_id, 1) not in control.references:
                    raise ValueError("客体启动缺少 unit 引用")
                with HermesGuestIdentityRegistry(identities_directory).connect() as db:
                    binding = db.execute("SELECT boot_id,unit,invocation,slice FROM guest_slice_bindings WHERE run_id=? AND epoch=1", (run_id,)).fetchone()
                if binding != (boot_id, unit, control.references[(run_id, 1)].invocation.hex(), slice_name(run_id, 1)):
                    raise ValueError("客体 slice 持久绑定不可核查")
                print("GUEST_SLICE_BINDING_DURABLE", flush=True)
                if await request("start", start) != {"unit": unit, "state": "UNKNOWN"}:
                    raise ValueError("客体重复启动回执不匹配")
                deadline = time.monotonic() + 15
                while not (workspace / "ready").is_file() and time.monotonic() < deadline:
                    await asyncio.sleep(0.1)
                if not (workspace / "ready").is_file():
                    raise TimeoutError("客体运行没有准备完成")
                key = {"run_id": run_id, "epoch": 1, "boot_id": boot_id}
                if await request("final-exit-status", key) != {"state": "UNKNOWN"}:
                    raise ValueError("活动运行的最终退出状态无效")
                inspected = await request("inspect", key)
                if inspected != {"unit": unit, "process_exited": False, "state": "UNKNOWN"}:
                    raise ValueError("客体运行检查不匹配")
                first_cpu = await request("cpu", key)
                second_cpu = await request("cpu", key)
                slice_first = await request("cpu-slice", key)
                slice_second = await request("cpu-slice", key)
                if slice_first["source"] != "SLICE_CPU_NSEC_V1" or slice_second["source"] != "SLICE_CPU_NSEC_V1" or slice_first["unit"] != unit or slice_second["boot_id"] != boot_id or type(slice_first["cpu_ns"]) is not int or slice_first["cpu_ns"] < 0 or slice_second["cpu_ns"] < slice_first["cpu_ns"]:
                    raise ValueError("客体 slice CPU 采样不可核查")
                print("GUEST_SLICE_CPU_NSEC", slice_first["cpu_ns"], slice_second["cpu_ns"], flush=True)
                parallel_id = str(uuid4())
                _, parallel_uid, parallel_gid = identities.ensure(parallel_id)
                parallel_workspace = root / parallel_id
                parallel_workspace.mkdir(mode=0o700)
                os.chown(parallel_workspace, parallel_uid, parallel_gid)
                parallel_role = parallel_workspace / "role"
                parallel_role.write_text("holder", encoding="ascii")
                os.chown(parallel_role, parallel_uid, parallel_gid)
                parallel_role.chmod(0o600)
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as parallel_probe:
                    parallel_probe.bind(("127.0.0.1", 0))
                    parallel_port = parallel_probe.getsockname()[1]
                parallel_start = {**start, "run_id": parallel_id, "bootstrap": {**bootstrap, "run_id": parallel_id, "endpoint": "http://127.0.0.1:" + str(parallel_port)}}
                parallel_key = {"run_id": parallel_id, "epoch": 1, "boot_id": boot_id}
                parallel_unit = "boss-" + parallel_id + "-1.service"
                if await request("start", parallel_start) != {"unit": parallel_unit, "state": "UNKNOWN"}:
                    raise ValueError("并发运行启动不可核查")
                try:
                    deadline = time.monotonic() + 15
                    while not (parallel_workspace / "ready").is_file() and time.monotonic() < deadline:
                        await asyncio.sleep(0.1)
                    if not (parallel_workspace / "ready").is_file():
                        raise TimeoutError("并发运行没有准备完成")
                    parallel_cpu = await request("cpu-slice", parallel_key)
                    current_cpu = await request("cpu-slice", key)
                    with identities.connect() as db:
                        groups = db.execute("SELECT slice FROM guest_slice_bindings WHERE run_id IN (?,?) ORDER BY run_id", (run_id, parallel_id)).fetchall()
                    if len(groups) != 2 or {value[0] for value in groups} != {slice_name(run_id, 1), slice_name(parallel_id, 1)} or parallel_cpu["unit"] != parallel_unit or current_cpu["unit"] != unit or current_cpu["cpu_ns"] < slice_second["cpu_ns"]:
                        raise ValueError("并发运行 slice 身份不可核查")
                    print("GUEST_CONCURRENT_SLICE_IDENTITIES_OK", flush=True)
                finally:
                    if await request("stop", parallel_key) != {"state": "UNKNOWN"}:
                        raise ValueError("并发运行停止不可核查")
                parallel_final = await request("final-exit", parallel_key)
                if parallel_final["cpu_ns"] < parallel_cpu["cpu_ns"] or await request("final-exit-cleanup", parallel_key) != parallel_final:
                    raise ValueError("并发运行最终用量不可核查")
                if (set(first_cpu) != {"unit", "boot_id", "cpu_ns"} or first_cpu["unit"] != unit or first_cpu["boot_id"] != boot_id
                        or type(first_cpu["cpu_ns"]) is not int or first_cpu["cpu_ns"] <= 0
                        or second_cpu["unit"] != unit or second_cpu["boot_id"] != boot_id
                        or type(second_cpu["cpu_ns"]) is not int or second_cpu["cpu_ns"] < first_cpu["cpu_ns"]):
                    raise ValueError("客体 CPU 读数不匹配")
                print("GUEST_TLS_CPU_USAGE_NS", first_cpu["cpu_ns"], second_cpu["cpu_ns"], flush=True)
            finally:
                if await request("stop", {"run_id": run_id, "epoch": 1, "boot_id": boot_id}) != {"state": "UNKNOWN"}:
                    raise ValueError("客体停止回执不匹配")
            if HermesGuestIdentityRegistry(identities_directory).read_control(run_id, 1, boot_id) != "STOPPED":
                raise ValueError("客体停止记录不可重读")
            expected_exit = {"run_id": run_id, "epoch": 1, "boot_id": boot_id, "unit": unit, "state": "UNKNOWN", "cpu_ns": None}
            if await request("exit", key) != expected_exit or await request("exit", key) != expected_exit:
                raise ValueError("客体退出记录不匹配")
            if HermesGuestIdentityRegistry(identities_directory).read_exit(run_id, 1, boot_id) != expected_exit:
                raise ValueError("客体退出记录不可重读")
            with HermesGuestIdentityRegistry(identities_directory).connect() as db:
                observation = db.execute("SELECT boot_id,unit,unit_state,cpu_ns,kill_mode FROM guest_exit_observations WHERE run_id=? AND epoch=1", (run_id,)).fetchone()
            if observation is None or observation[:2] != (boot_id, unit) or observation[2] not in {"inactive", "failed"} or type(observation[3]) is not int or observation[4] != "control-group":
                raise ValueError("客体停止观察不可重读")
            exit_observation = await request("exit-observation", key)
            if exit_observation["state"] != "UNKNOWN" or exit_observation["unit"] != unit or exit_observation["cpu_ns"] != observation[3] or await request("exit-observation", key) != exit_observation:
                raise ValueError("客体停止观察通信不可核查")
            final_exit = await request("final-exit", key)
            if await request("final-exit-status", key) != {"state": "FINAL"}:
                raise ValueError("客体最终退出状态不可核查")
            if final_exit != await request("final-exit", key) or final_exit != HermesGuestIdentityRegistry(identities_directory).read_final_exit(run_id, 1, boot_id) or final_exit["slice"] != slice_name(run_id, 1) or final_exit["invocation"] != exit_observation["invocation"] or final_exit["source"] != "SLICE_CPU_NSEC_V1" or final_exit["cpu_ns"] < slice_second["cpu_ns"]:
                raise ValueError("客体最终退出记录不可核查")
            if await request("stop", key) != {"state": "UNKNOWN"} or await request("final-exit", key) != final_exit:
                raise ValueError("客体重复停止结果不可核查")
            if not (Path("/sys/fs/cgroup") / slice_name(run_id, 1)).is_dir():
                raise ValueError("客体 slice 提前清理")
            if await request("final-exit-cleanup", key) != final_exit or await request("final-exit-cleanup", key) != final_exit:
                raise ValueError("客体重复清理结果不可核查")
            if (Path("/sys/fs/cgroup") / slice_name(run_id, 1)).exists():
                raise ValueError("客体 slice 尚未清理")
            print("GUEST_FINAL_EXIT_DURABLE", final_exit["cpu_ns"], flush=True)
            print("GUEST_TLS_UNKNOWN_EXIT_DURABLE", flush=True)
            await request("cpu", key, expected=409)
            await request("cpu-slice", key, expected=409)
            print("GUEST_TLS_STOPPED_CPU_REJECTED", flush=True)
            print("GUEST_TLS_CONTROL_IDENTITY_START_INSPECT_STOP_OK", flush=True)
            print("GUEST_TLS_CONTROL_DUPLICATE_AND_DURABLE_STOP_OK", flush=True)
            print("GUEST_TLS_CONTROL_WRONG_CERTIFICATE_REJECTED", flush=True)
            quick_id = str(uuid4())
            _, quick_uid, quick_gid = identities.ensure(quick_id)
            quick_workspace = root / quick_id
            quick_workspace.mkdir(mode=0o700)
            os.chown(quick_workspace, quick_uid, quick_gid)
            for name, value in (("role", "holder"), ("finish", "ready")):
                path = quick_workspace / name
                path.write_text(value, encoding="ascii")
                os.chown(path, quick_uid, quick_gid)
                path.chmod(0o600)
            quick_bootstrap = {**bootstrap, "run_id": quick_id}
            quick_start = {**start, "run_id": quick_id, "bootstrap": quick_bootstrap}
            quick_key = {"run_id": quick_id, "epoch": 1, "boot_id": boot_id}
            quick_unit = "boss-" + quick_id + "-1.service"
            if await request("start", quick_start) != {"unit": quick_unit, "state": "UNKNOWN"} or (quick_id, 1) not in control.references:
                raise ValueError("快速退出运行缺少 unit 引用")
            deadline = time.monotonic() + 15
            while (await request("inspect", quick_key))["process_exited"] is False and time.monotonic() < deadline:
                await asyncio.sleep(0.1)
            if (await request("inspect", quick_key))["process_exited"] is not True:
                raise TimeoutError("快速退出运行尚未结束")
            if await request("stop", quick_key) != {"state": "UNKNOWN"}:
                raise ValueError("快速退出停止回执无效")
            with HermesGuestIdentityRegistry(identities_directory).connect() as db:
                observed = db.execute("SELECT unit_state,cpu_ns FROM guest_exit_observations WHERE run_id=? AND epoch=1", (quick_id,)).fetchone()
            if observed is None or observed[0] not in {"inactive", "failed"} or type(observed[1]) is not int:
                raise ValueError("快速退出观察不可核查")
            quick_final = await request("final-exit", quick_key)
            if quick_final != await request("final-exit", quick_key) or quick_final["run_id"] != quick_id or quick_final["cpu_ns"] <= 0:
                raise ValueError("自然退出最终记录不可核查")
            if await request("final-exit-cleanup", quick_key) != quick_final:
                raise ValueError("自然退出清理不可核查")
            print("GUEST_NATURAL_FINAL_EXIT_DURABLE", quick_final["cpu_ns"], flush=True)
            print("GUEST_TLS_QUICK_EXIT_OBSERVED", flush=True)
            failure_id = str(uuid4())
            _, failure_uid, failure_gid = identities.ensure(failure_id)
            failure_workspace = root / failure_id
            failure_workspace.mkdir(mode=0o700)
            os.chown(failure_workspace, failure_uid, failure_gid)
            failure_role = failure_workspace / "role"
            failure_role.write_text("holder", encoding="ascii")
            os.chown(failure_role, failure_uid, failure_gid)
            failure_role.chmod(0o600)
            failure_bootstrap = {**bootstrap, "run_id": failure_id}
            failure_start = {**start, "run_id": failure_id, "bootstrap": failure_bootstrap}
            failure_key = {"run_id": failure_id, "epoch": 1, "boot_id": boot_id}
            failure_unit = "boss-" + failure_id + "-1.service"
            if await request("start", failure_start) != {"unit": failure_unit, "state": "UNKNOWN"}:
                raise ValueError("清理检查运行未启动")
            proxy_server = control.runs[(failure_id, 1)][4]
            control.references[(failure_id, 1)].bus.disconnect()
            await request("stop", failure_key, expected=500)
            if proxy_server.is_serving() or (failure_id, 1) in control.references:
                raise ValueError("引用异常时监听器未关闭")
            if HermesGuestIdentityRegistry(identities_directory).read_exit(failure_id, 1, boot_id)["state"] != "UNKNOWN":
                raise ValueError("引用异常时未知退出记录不可核查")
            if await request("final-exit-status", failure_key) != {"state": "UNKNOWN"}:
                raise ValueError("引用异常时最终退出状态不可核查")
            with HermesGuestIdentityRegistry(identities_directory).connect() as db:
                if db.execute("SELECT count(*) FROM guest_final_receipts WHERE run_id=?", (failure_id,)).fetchone() != (0,):
                    raise ValueError("引用异常产生了最终退出记录")
            print("GUEST_TLS_REFERENCE_FAILURE_CLEANUP_OK", flush=True)
            timeout_id = str(uuid4())
            _, timeout_uid, timeout_gid = identities.ensure(timeout_id)
            timeout_workspace = root / timeout_id
            timeout_workspace.mkdir(mode=0o700)
            os.chown(timeout_workspace, timeout_uid, timeout_gid)
            timeout_role = timeout_workspace / "role"
            timeout_role.write_text("ignore-term", encoding="ascii")
            os.chown(timeout_role, timeout_uid, timeout_gid)
            timeout_role.chmod(0o600)
            timeout_bootstrap = {**bootstrap, "run_id": timeout_id}
            timeout_budget = {**budget, "seconds": 120, "cpu_seconds": 120}
            timeout_start = {**start, "run_id": timeout_id, "bootstrap": timeout_bootstrap, "budget": timeout_budget}
            timeout_key = {"run_id": timeout_id, "epoch": 1, "boot_id": boot_id}
            timeout_unit = "boss-" + timeout_id + "-1.service"
            if await request("start", timeout_start) != {"unit": timeout_unit, "state": "UNKNOWN"}:
                raise ValueError("停止超时检查运行未启动")
            timeout_server = control.runs[(timeout_id, 1)][4]
            try:
                deadline = time.monotonic() + 15
                while not (timeout_workspace / "ready").is_file() and time.monotonic() < deadline:
                    await asyncio.sleep(0.1)
                if not (timeout_workspace / "ready").is_file():
                    raise TimeoutError("停止超时检查运行未就绪")
                pids = [int((timeout_workspace / name).read_text(encoding="ascii")) for name in ("holder-pid", "child-pid")]
                if await request("stop", timeout_key) != {"state": "UNKNOWN"}:
                    raise ValueError("停止回执不可核查")
                if any(Path("/proc", str(pid)).exists() for pid in pids):
                    raise ValueError("停止后检查进程仍然存在")
                if timeout_server.is_serving() or (timeout_id, 1) in control.references:
                    raise ValueError("停止超时时引用或监听器未关闭")
                if HermesGuestIdentityRegistry(identities_directory).read_exit(timeout_id, 1, boot_id)["state"] != "UNKNOWN":
                    raise ValueError("停止超时时未知记录不可核查")
                timeout_final = await request("final-exit", timeout_key)
                if timeout_final["run_id"] != timeout_id or timeout_final["cpu_ns"] <= 0:
                    raise ValueError("终止后最终退出记录不可核查")
                if await request("final-exit-cleanup", timeout_key) != timeout_final:
                    raise ValueError("终止后清理不可核查")
                print("GUEST_TLS_STOP_ESCALATION_PROCESSES_EXITED", flush=True)
            finally:
                subprocess.run(["/usr/bin/systemctl", "stop", timeout_unit], check=True, timeout=30)
    finally:
        await runner.cleanup()


asyncio.run(main())
