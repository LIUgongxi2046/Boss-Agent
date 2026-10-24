import argparse
import asyncio
import hashlib
import json
import os
import sys
from pathlib import Path
from uuid import uuid4

import aiohttp

from prepare_mvp01 import prepare as prepare_mvp

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "validation"))

from application_paths import application_work_directory, application_ports

REQUIRED_TOOLS = {"bossSupplyQualityRead", "bossSupplyQualityQuery", "bossEvidenceRead", "bossSupplyQualityPrepare", "read_assignment", "assignmentSourcesRead"}


async def prepare(directory, frontend, ports):
    if not directory.exists():
        await prepare_mvp(directory, ROOT / "mvp01-n3-dist", ports)
    baseline = json.loads((directory / "setup.json").read_text())
    if baseline["status"] != "READY" or baseline["scope_id"] != "BOSS-MVP-1" or baseline["ports"] != ports:
        raise ValueError("当前资料目录与已保存的MVP范围或端口不符，请核查现有入口")
    credentials = {row["role"]: row for row in json.loads((directory / "accounts/credentials.json").read_text())}
    identity = str(uuid4())
    environment = {**os.environ, "BOSS_PRODUCT_UI": "1", "BOSS_EXECUTION_SCOPE": "BOSS-PRIORITY-ITERATION", "BOSS_APPLICATION_WORK_DIR": str(directory),
        "BOSS_APPLICATION_PORTS": json.dumps(ports), "BOSS_PRODUCT_FRONTEND_DIR": str(frontend), "TMPDIR": str(directory / "tmp")}
    log = directory / ("fc07-initialization-" + identity + ".log")
    with log.open("x") as output:
        log.chmod(0o600)
        process = await asyncio.create_subprocess_exec(str(ROOT / "validation/.venv/bin/python"), str(ROOT / "validation/application.py"), cwd=ROOT, env=environment, stdout=output, stderr=output)
        try:
            async with asyncio.timeout(90):
                while True:
                    if process.returncode is not None:
                        raise RuntimeError("当前资料服务尚未取得启动条件，请查看本机初始化日志；已有桌面需要正常关闭后再启动当前入口")
                    instance = directory / "instance.json"
                    if instance.is_file() and json.loads(instance.read_text())["pid"] == process.pid:
                        break
                    await asyncio.sleep(0.1)
            origin = "http://127.0.0.1:" + str(ports["webui"])
            async with aiohttp.ClientSession() as session:
                account = credentials["MAINTAINER"]
                async with session.get(origin + "/webui/bootstrap", headers={"X-Boss-Username": account["username"], "X-Boss-Password": account["password"], "X-Boss-Role": "MAINTAINER"}) as response:
                    response.raise_for_status()
                    auth = await response.json()
                async with session.get(origin + "/api/boss/ui/admin/runtime-configuration", headers={"Authorization": "Bearer " + auth["api_token"]}) as response:
                    response.raise_for_status()
                    state = await response.json(content_type=None)
                current = state["current"]
                if not REQUIRED_TOOLS <= set(current["tool_scope"]) or current["max_tool_rounds"] < 6 or current["enabled"] is not True:
                    if state["draft"] and state["draft"]["validation_status"] != "ACTIVATED":
                        raise ValueError("当前维护配置存在尚未采用的编辑，请在原配置页面核查后继续")
                    async with session.ws_connect(auth["ws_url"] + "?token=" + auth["token"]) as socket:
                        async def command(action, payload):
                            request = str(uuid4())
                            await socket.send_json({"type": "webui_request", "request_id": request, "action": action, "payload": payload})
                            async with asyncio.timeout(30):
                                async for message in socket:
                                    if message.type != aiohttp.WSMsgType.TEXT:
                                        raise RuntimeError("当前配置连接已经结束，请核查原维护记录")
                                    body = json.loads(message.data)
                                    if body.get("event") == "webui_response" and body.get("request_id") == request:
                                        if body["ok"] is not True:
                                            raise RuntimeError("当前配置动作未完成：" + action + " · " + json.dumps(body["error"], ensure_ascii=False))
                                        return body["result"]
                            raise RuntimeError("当前配置尚未取得回执，请核查原维护记录")
                        values = {"max_tool_rounds": max(current["max_tool_rounds"], 6), "max_output_tokens": state["effective"]["max_output_tokens"], "tool_scope": sorted(set(current["tool_scope"]) | REQUIRED_TOOLS)}
                        draft = await command("boss.runtime.save", {"client_request_id": "fc07-save-" + identity, "expected_version": state["draft"]["version"] if state["draft"] else "0", "values": values})
                        checked = await command("boss.runtime.validate", {"client_request_id": "fc07-check-" + identity, "expected_version": draft["version"], "expected_content_sha256": draft["content_sha256"]})
                        current = await command("boss.runtime.activate", {"client_request_id": "fc07-enable-" + identity, "expected_version": checked["version"], "expected_content_sha256": checked["content_sha256"], "expected_active_version": current["version"]})
            marker = directory / "fc07-setup.json"
            marker.write_text(json.dumps({"scope_id": "BOSS-PRIORITY-ITERATION", "feature_id": "FC07", "status": "READY", "ports": ports,
                "frontend_directory": str(frontend), "manifest_sha256": hashlib.sha256((frontend / "asset-manifest.json").read_bytes()).hexdigest(),
                "configuration_version": current["version"], "business_database": str(directory / "business.sqlite"), "mvp_database_preserved": True, "external_api_mode": "SIMULATED_FIRST"}, ensure_ascii=False, indent=2) + "\n")
            marker.chmod(0o600)
            print(json.dumps({"status": "READY", "scope": "BOSS-PRIORITY-ITERATION", "directory": str(directory), "credentials": str(directory / "accounts/credentials.json")}, ensure_ascii=False))
        finally:
            if process.returncode is None:
                process.terminate()
                async with asyncio.timeout(30):
                    await process.wait()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", type=Path, default=ROOT / "validation/.work/mvp01-experience")
    parser.add_argument("--frontend", type=Path, default=ROOT / "fc07-n3-dist")
    parser.add_argument("--ports", default='{"business":9961,"webui":9962,"gateway":19961}')
    args = parser.parse_args()
    directory = application_work_directory(ROOT / "validation", str(args.directory))
    frontend = args.frontend.resolve()
    if not frontend.is_relative_to(ROOT) or not (frontend / "asset-manifest.json").is_file():
        raise ValueError("当前FC07前端制品不存在或超出工程范围")
    asyncio.run(prepare(directory, frontend, application_ports(args.ports)))


if __name__ == "__main__":
    main()
