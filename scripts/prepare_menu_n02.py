import argparse
import asyncio
import hashlib
import json
import os
import sys
from pathlib import Path
from uuid import uuid4

import aiohttp

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "validation"))

from application_paths import application_work_directory, application_ports
from boss_account_auth import provision_accounts
from conversation_agent.native import CONVERSATION_TOOLS
from fc03_agent.formal import FORMAL_TOOLS
from prepare_mvp01 import MVP_RUNTIME_TOOLS

TOOLS = sorted(set(CONVERSATION_TOOLS) | FORMAL_TOOLS | set(MVP_RUNTIME_TOOLS))
VALUES = {"max_tool_rounds": 12, "max_output_tokens": 700, "tool_scope": TOOLS,
          "workspace_read_mode": "WORKSPACE_PROJECTIONS",
          "workspace_projections": ["notifications", "travel", "calendar", "research"]}
PROTECTED_PORTS = {9961, 9962, 19961, 10411, 10412, 20411, 10611, 10612, 20611}


async def prepare(directory, frontend, ports, *, feature_id="MENU-N02"):
    manifest = hashlib.sha256((frontend / "asset-manifest.json").read_bytes()).hexdigest()
    marker = directory / "setup.json"
    if directory.exists():
        saved = json.loads(marker.read_text())
        if any(saved.get(key) != value for key, value in {"feature_id": feature_id, "status": "READY",
                "ports": ports, "manifest_sha256": manifest, "runtime_configuration_values": VALUES}.items()):
            raise ValueError("已有聊天交办资料与当前制品或配置声明不符，请保留资料并核查")
        for name in ("business.sqlite", "runtime-scope.json", "accounts/accounts.sqlite", "accounts/credentials.json"):
            if not (directory / name).is_file() or (directory / name).is_symlink():
                raise FileNotFoundError("已有聊天交办资料缺少有效文件：" + name)
        return {**saved, "existing_data_reused": True}
    directory.mkdir(mode=0o700)
    (directory / "tmp").mkdir(mode=0o700)
    provision_accounts(directory / "accounts")
    accounts = json.loads((directory / "accounts/credentials.json").read_text())
    maintainer = next(account for account in accounts if account["role"] == "MAINTAINER")
    environment = {**os.environ, "BOSS_PRODUCT_UI": "1", "BOSS_EXECUTION_SCOPE": "BOSS-PRIORITY-ITERATION",
        "BOSS_APPLICATION_WORK_DIR": str(directory), "BOSS_APPLICATION_PORTS": json.dumps(ports),
        "BOSS_PRODUCT_FRONTEND_DIR": str(frontend), "TMPDIR": str(directory / "tmp"), "PYTHONDONTWRITEBYTECODE": "1"}
    log = directory / "initialization.log"
    with log.open("x") as output:
        log.chmod(0o600)
        process = await asyncio.create_subprocess_exec(str(ROOT / "validation/.venv/bin/python"),
            str(ROOT / "validation/application.py"), cwd=ROOT, env=environment, stdout=output, stderr=output)
        try:
            async with asyncio.timeout(90):
                while True:
                    if process.returncode is not None:
                        raise RuntimeError("聊天交办初始化服务已经退出，请核查本机初始化记录")
                    instance = directory / "instance.json"
                    if instance.is_file() and json.loads(instance.read_text())["pid"] == process.pid:
                        break
                    await asyncio.sleep(0.1)
            origin = "http://127.0.0.1:" + str(ports["webui"])
            async with aiohttp.ClientSession() as session:
                async with session.get(origin + "/webui/bootstrap", headers={"X-Boss-Username": maintainer["username"],
                        "X-Boss-Password": maintainer["password"], "X-Boss-Role": "MAINTAINER"}) as response:
                    response.raise_for_status()
                    auth = await response.json()
                async with session.ws_connect(auth["ws_url"] + "?token=" + auth["token"]) as socket:
                    async def command(action, payload):
                        request_id = str(uuid4())
                        await socket.send_json({"type": "webui_request", "request_id": request_id, "action": action, "payload": payload})
                        async with asyncio.timeout(30):
                            async for message in socket:
                                if message.type != aiohttp.WSMsgType.TEXT:
                                    raise RuntimeError("初始化维护连接没有返回正式文本回执")
                                value = json.loads(message.data)
                                if value.get("event") == "webui_response" and value.get("request_id") == request_id:
                                    if value["ok"] is not True:
                                        raise RuntimeError("初始化维护操作未完成：" + action)
                                    return value["result"]
                        raise TimeoutError("初始化维护操作尚未取得原请求回执")
                    async with session.get(origin + "/api/boss/ui/admin/runtime-configuration",
                            headers={"Authorization": "Bearer " + auth["api_token"]}) as response:
                        response.raise_for_status()
                        current = await response.json(content_type=None)
                    if not set(TOOLS) <= set(current["available_tools"]):
                        raise ValueError("当前Runtime没有全部聊天交办与既有共享工具")
                    draft = await command("boss.runtime.save", {"client_request_id": str(uuid4()),
                        "expected_version": current["draft"]["version"] if current["draft"] else "0", "values": VALUES})
                    checked = await command("boss.runtime.validate", {"client_request_id": str(uuid4()),
                        "expected_version": draft["version"], "expected_content_sha256": draft["content_sha256"]})
                    active = await command("boss.runtime.activate", {"client_request_id": str(uuid4()),
                        "expected_version": checked["version"], "expected_content_sha256": checked["content_sha256"],
                        "expected_active_version": current["current"]["version"]})
            result = {"feature_id": feature_id, "status": "READY", "scope_id": "BOSS-PRIORITY-ITERATION",
                "ports": ports, "frontend_directory": str(frontend), "manifest_sha256": manifest,
                "runtime_configuration_values": VALUES, "configuration_version": active["version"],
                "external_api_mode": "SIMULATED_FIRST", "automatic_form_login": False}
            marker.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
            marker.chmod(0o600)
            return {**result, "existing_data_reused": False}
        finally:
            if process.returncode is None:
                process.terminate()
                async with asyncio.timeout(30):
                    await process.wait()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", type=Path, default=ROOT / "validation/.work/menu-n02-release-experience")
    parser.add_argument("--frontend", type=Path, default=ROOT / "menu-n02-n3-dist")
    parser.add_argument("--ports", default='{"business":10711,"webui":10712,"gateway":20711}')
    args = parser.parse_args()
    directory = application_work_directory(ROOT / "validation", str(args.directory))
    if not directory.name.startswith("menu-n02-"):
        raise ValueError("聊天交办需要独立menu-n02资料目录")
    frontend = args.frontend.resolve()
    if frontend != ROOT / "menu-n02-n3-dist" or not (frontend / "asset-manifest.json").is_file():
        raise ValueError("聊天交办需要准确独立前端制品")
    ports = application_ports(args.ports)
    if set(ports.values()) & PROTECTED_PORTS:
        raise ValueError("聊天交办不能占用已有用户体验端口")
    print(json.dumps(asyncio.run(prepare(directory, frontend, ports)), ensure_ascii=False))


if __name__ == "__main__":
    main()
