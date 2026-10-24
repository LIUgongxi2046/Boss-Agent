import argparse
import asyncio
import json
from pathlib import Path

from prepare_menu_n02 import ROOT, PROTECTED_PORTS, prepare
from application_paths import application_work_directory, application_ports


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", type=Path, default=ROOT / "validation/.work/menu-f01-rework-release-experience")
    parser.add_argument("--frontend", type=Path, default=ROOT / "menu-f01-rework-n3-dist")
    parser.add_argument("--ports", default='{"business":10621,"webui":10622,"gateway":20621}')
    args = parser.parse_args()
    directory = application_work_directory(ROOT / "validation", str(args.directory))
    if not directory.name.startswith("menu-f01-rework-"):
        raise ValueError("今日工作需要独立menu-f01-rework资料目录")
    frontend = args.frontend.resolve()
    if frontend != ROOT / "menu-f01-rework-n3-dist" or not (frontend / "asset-manifest.json").is_file():
        raise ValueError("今日工作需要准确独立前端制品")
    ports = application_ports(args.ports)
    if set(ports.values()) & (PROTECTED_PORTS | {10711, 10712, 20711}):
        raise ValueError("今日工作不能占用已有用户体验端口")
    print(json.dumps(asyncio.run(prepare(directory, frontend, ports, feature_id="MENU-F01")), ensure_ascii=False))


if __name__ == "__main__":
    main()
