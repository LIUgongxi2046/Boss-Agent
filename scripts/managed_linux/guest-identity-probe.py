import json
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import aiohttp


bootstrap = json.loads(sys.stdin.buffer.read())
if aiohttp.__version__ != "3.14.5":
    raise ValueError("客体运行依赖版本不匹配")
workspace = Path.cwd()
role = (workspace / "role").read_text(encoding="ascii").strip()
if workspace != Path("/mnt") and bootstrap["run_id"] != workspace.name:
    raise ValueError("运行身份不匹配")
if role == "holder":
    (workspace / "holder-pid").write_text(str(os.getpid()), encoding="ascii")
    (workspace / "ready").write_text("ready", encoding="ascii")
elif role == "ignore-term":
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    child = subprocess.Popen(["/usr/bin/sleep", "120"], start_new_session=True)
    (workspace / "holder-pid").write_text(str(os.getpid()), encoding="ascii")
    (workspace / "child-pid").write_text(str(child.pid), encoding="ascii")
    (workspace / "ready").write_text("ready", encoding="ascii")
elif role == "tree":
    child = subprocess.Popen(["/usr/bin/sleep", "30"])
    (workspace / "holder-pid").write_text(str(os.getpid()), encoding="ascii")
    (workspace / "child-pid").write_text(str(child.pid), encoding="ascii")
    (workspace / "ready").write_text("ready", encoding="ascii")
elif role == "cpu":
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    children = [subprocess.Popen(["/usr/bin/yes"], stdout=subprocess.DEVNULL, start_new_session=True) for _ in range(2)]
    (workspace / "holder-pid").write_text(str(os.getpid()), encoding="ascii")
    (workspace / "child-pids").write_text(" ".join(str(child.pid) for child in children), encoding="ascii")
    (workspace / "ready").write_text("ready", encoding="ascii")
elif role == "shm":
    result = subprocess.run(["/usr/bin/touch", "/dev/shm/boss-" + bootstrap["run_id"]],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    (workspace / "shared-memory-result").write_text("denied" if result.returncode else "allowed", encoding="ascii")
    (workspace / "ipc-namespace").write_text(os.readlink("/proc/self/ns/ipc"), encoding="ascii")
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connected = connection.connect_ex("/run/dbus/system_bus_socket") == 0
    (workspace / "system-bus-result").write_text("allowed" if connected else "denied", encoding="ascii")
    (workspace / "ready").write_text("ready", encoding="ascii")
elif role == "engine":
    sys.stderr = (workspace / "engine-diagnostic.log").open("w", encoding="utf-8")
    sys.path.insert(0, sys.argv[1])
    from run_agent import AIAgent
    from model_tools import get_tool_definitions
    from hermes_tool_names import PRODUCT_TOOL_NAMES
    from hermes_tool_registration import registered_product_tools
    from hermes_transport_client import HermesTransportClient
    client = HermesTransportClient(bootstrap["endpoint"], bootstrap["capability"], bootstrap["run_id"])
    try:
        with registered_product_tools(client):
            agent = AIAgent(model="deepseek-flash", provider="deepseek", api_mode="chat_completions",
                            api_key=bootstrap["provider_capability"], base_url=bootstrap["endpoint"],
                            enabled_toolsets=["boss_domain"], max_iterations=1, run_budget_seconds=60,
                            quiet_mode=True, skip_context_files=True, skip_memory=True,
                            skip_background_review=True, cwd=str(workspace))
            try:
                definitions = get_tool_definitions(enabled_toolsets=["boss_domain"], quiet_mode=True, skip_tool_search_assembly=True)
                if {item["function"]["name"] for item in definitions} != PRODUCT_TOOL_NAMES:
                    raise ValueError("客体引擎工具集合不可核查")
            finally:
                agent.close()
    finally:
        client.close()
    (workspace / "ready").write_text("ready", encoding="ascii")
elif role == "checker":
    target = Path((workspace / "target").read_text(encoding="ascii").strip())
    if not target.is_absolute():
        raise ValueError("其他运行路径无效")
    holder_pid = int((workspace / "holder-pid").read_text(encoding="ascii"))
    if (workspace / "own-file").read_text(encoding="ascii") != "own":
        raise ValueError("当前运行读取失败")
    checks = {
        "cross_workspace": ["/usr/bin/cat", str(target)],
        "cross_root": ["/usr/bin/cat", "/proc/" + str(holder_pid) + "/root/mnt/own-file"],
        "cross_environ": ["/usr/bin/cat", "/proc/" + str(holder_pid) + "/environ"],
        "cross_memory": ["/usr/bin/head", "-c", "1", "/proc/" + str(holder_pid) + "/mem"],
        "cross_descriptors": ["/usr/bin/ls", "/proc/" + str(holder_pid) + "/fd"],
        "cross_signal": ["/usr/bin/kill", "-0", str(holder_pid)],
    }
    result = {name: subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode != 0
              for name, command in checks.items()}
    result["own_workspace"] = True
    result["uid"] = os.getuid()
    (workspace / "result.json").write_text(json.dumps(result, sort_keys=True), encoding="utf-8")
else:
    raise ValueError("技术检查角色无效")
deadline = time.monotonic() + (120 if role == "ignore-term" else 30)
while not (workspace / "finish").exists() and time.monotonic() < deadline:
    time.sleep(0.1)
if not (workspace / "finish").exists():
    raise TimeoutError("技术检查等待超时")
