import argparse
import asyncio
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import aiohttp
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "validation"))

from application_paths import application_work_directory, application_ports
from boss_account_auth import provision_accounts

MVP_RUNTIME_TOOLS = ("bossSupplyQualityRead", "bossSupplyQualityQuery", "bossEvidenceRead", "bossSupplyQualityPrepare")

async def prepare(directory, frontend, ports, *, runtime_tools=MVP_RUNTIME_TOOLS):
    manifest = hashlib.sha256((frontend / "asset-manifest.json").read_bytes()).hexdigest()
    marker = directory / "setup.json"
    if directory.exists():
        if not marker.is_file():
            raise FileExistsError("已有资料目录缺少初始化完成记录，请保留目录并核查原请求")
        saved = json.loads(marker.read_text())
        assert saved["scope_id"] == "BOSS-MVP-1" and saved["ports"] == ports and saved["manifest_sha256"] == manifest
        print(json.dumps({"status": "READY", "directory": str(directory), "credentials": str(directory / "accounts/credentials.json")}, ensure_ascii=False))
        return
    directory.mkdir(mode=0o700)
    (directory / "tmp").mkdir(mode=0o700)
    provision_accounts(directory / "accounts")
    credentials = {row["role"]: row for row in json.loads((directory / "accounts/credentials.json").read_text())}
    environment = {**os.environ, "BOSS_PRODUCT_UI": "1", "BOSS_EXECUTION_SCOPE": "BOSS-MVP-1",
        "BOSS_APPLICATION_WORK_DIR": str(directory), "BOSS_APPLICATION_PORTS": json.dumps(ports), "BOSS_PRODUCT_FRONTEND_DIR": str(frontend), "TMPDIR": str(directory / "tmp")}
    log = directory / "initialization.log"
    with log.open("x") as output:
        log.chmod(0o600)
        process = await asyncio.create_subprocess_exec(str(ROOT / "validation/.venv/bin/python"), str(ROOT / "validation/application.py"), cwd=ROOT, env=environment, stdout=output, stderr=output)
        try:
            async with asyncio.timeout(90):
                while True:
                    if process.returncode is not None:
                        raise RuntimeError("采购体验初始化服务已退出，请查看本机初始化日志")
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
                async with session.ws_connect(auth["ws_url"] + "?token=" + auth["token"]) as socket:
                    async def command(action, payload):
                        key = str(uuid4())
                        await socket.send_json({"type": "webui_request", "request_id": key, "action": action, "payload": payload})
                        async with asyncio.timeout(30):
                            async for message in socket:
                                assert message.type == aiohttp.WSMsgType.TEXT
                                body = json.loads(message.data)
                                if body.get("event") == "webui_response" and body.get("request_id") == key:
                                    if body["ok"] is not True:
                                        raise RuntimeError("正式维护操作未完成：" + action + " · " + json.dumps(body["error"], ensure_ascii=False))
                                    return body["result"]
                        raise RuntimeError("正式维护操作尚未取得回执，请核查原编号")
                    definition = yaml.safe_load((ROOT / "data/simulation/supply-quality-v1.yaml").read_text())
                    initial = await command("boss.simulation.supply_quality.import", definition["initial_request"])
                    cost_input = json.loads(subprocess.check_output([str(ROOT / "validation/.venv/bin/python"), str(ROOT / "validation/fc01_cost_token_input.py")], cwd=ROOT))
                    costs = await command("boss.simulation.supply_quality.import", cost_input)
                    async with session.get(origin + "/api/boss/ui/admin/runtime-configuration", headers={"Authorization": "Bearer " + auth["api_token"]}) as response:
                        response.raise_for_status()
                        state = await response.json(content_type=None)
                    values = {"max_tool_rounds": 6, "max_output_tokens": 700, "tool_scope": list(runtime_tools)}
                    draft = await command("boss.runtime.save", {"client_request_id": "mvp01-runtime-save-v1", "expected_version": state["draft"]["version"] if state["draft"] else "0", "values": values})
                    checked = await command("boss.runtime.validate", {"client_request_id": "mvp01-runtime-validate-v1", "expected_version": draft["version"], "expected_content_sha256": draft["content_sha256"]})
                    active = await command("boss.runtime.activate", {"client_request_id": "mvp01-runtime-activate-v1", "expected_version": checked["version"], "expected_content_sha256": checked["content_sha256"], "expected_active_version": state["current"]["version"]})
            result = {"scope_id": "BOSS-MVP-1", "status": "READY", "ports": ports, "frontend": str(frontend), "manifest_sha256": manifest,
                "initial_import_records": initial["record_count"], "existing_cost_report_records": costs["record_count"], "configuration_version": active["version"],
                "source_inputs": ["data/simulation/supply-quality-v1.yaml", "validation/fc01_cost_token_input.py"], "runtime_tool_scope": list(runtime_tools), "external_api_mode": "SIMULATED_FIRST"}
            marker.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
            marker.chmod(0o600)
            print(json.dumps({"status": "READY", "directory": str(directory), "credentials": str(directory / "accounts/credentials.json")}, ensure_ascii=False))
        finally:
            if process.returncode is None:
                process.terminate()
                async with asyncio.timeout(30):
                    await process.wait()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", type=Path, default=ROOT / "validation/.work/mvp01-experience")
    parser.add_argument("--frontend", type=Path, default=ROOT / "mvp01-n3-dist")
    parser.add_argument("--ports", default='{"business":9961,"webui":9962,"gateway":19961}')
    args = parser.parse_args()
    directory = application_work_directory(ROOT / "validation", str(args.directory))
    frontend = args.frontend.resolve()
    assert frontend.is_relative_to(ROOT) and (frontend / "index.html").is_file()
    asyncio.run(prepare(directory, frontend, application_ports(args.ports)))


if __name__ == "__main__":
    main()
