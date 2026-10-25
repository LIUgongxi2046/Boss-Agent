import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "validation"))

from application_paths import application_work_directory, application_ports
from fc03_agent.formal import FORMAL_TOOLS
from prepare_mvp01 import MVP_RUNTIME_TOOLS, prepare


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", type=Path, default=ROOT / "validation/.work/menu-f01-experience")
    parser.add_argument("--frontend", type=Path, default=ROOT / "menu-f01-n3-dist")
    parser.add_argument("--ports", default='{"business":10611,"webui":10612,"gateway":20611}')
    args = parser.parse_args()
    directory = application_work_directory(ROOT / "validation", str(args.directory))
    if not directory.name.startswith("menu-f01-"):
        raise ValueError("今日工作只能使用独立menu-f01资料目录")
    frontend = args.frontend.resolve()
    if frontend != ROOT / "menu-f01-n3-dist" or not (frontend / "asset-manifest.json").is_file():
        raise ValueError("今日工作需要当前准确的独立前端制品")
    ports = application_ports(args.ports)
    if set(ports.values()) & {9961, 9962, 19961, 10411, 10412, 20411}:
        raise ValueError("今日工作端口不能占用现有用户体验")
    reused = directory.exists()
    if reused:
        setup = json.loads((directory / "setup.json").read_text())
        if setup["status"] != "READY" or setup["scope_id"] != "BOSS-MVP-1" or setup["ports"] != ports:
            raise ValueError("现有今日工作资料范围或端口与初始化记录不符")
        if not (directory / "business.sqlite").is_file() or not (directory / "accounts/credentials.json").is_file():
            raise FileNotFoundError("现有今日工作业务资料或账号文件不完整")
    else:
        asyncio.run(prepare(directory, frontend, ports, runtime_tools=tuple(sorted(FORMAL_TOOLS | set(MVP_RUNTIME_TOOLS)))))
    setup = json.loads((directory / "setup.json").read_text())
    if not FORMAL_TOOLS <= set(setup.get("runtime_tool_scope", [])):
        raise ValueError("当前初始化记录没有四项正式晨间工具，请保留现有资料并核查配置")
    print(json.dumps({"status": "READY_TO_START", "feature_id": "MENU-F01", "scope": "BOSS-PRIORITY-ITERATION",
        "directory": str(directory), "frontend_directory": str(frontend), "ports": ports,
        "external_api_mode": "SIMULATED_FIRST", "existing_data_reused": reused, "automatic_form_login": False}, ensure_ascii=False))


if __name__ == "__main__":
    main()
