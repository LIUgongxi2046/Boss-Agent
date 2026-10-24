import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "validation"))

from application_paths import application_work_directory, application_ports, application_frontend_directory


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", type=Path, default=ROOT / "validation/.work/mvp01-experience")
    parser.add_argument("--frontend", type=Path, default=ROOT / "fc04-n3-dist")
    parser.add_argument("--ports", default='{"business":9961,"webui":9962,"gateway":19961}')
    parser.add_argument("--feature-id", choices=("FC04", "UI01"), default="FC04")
    args = parser.parse_args()
    directory = application_work_directory(ROOT / "validation", str(args.directory))
    frontend = application_frontend_directory(ROOT / "validation", str(args.frontend))
    ports = application_ports(args.ports)
    baseline = json.loads((directory / "setup.json").read_text())
    if baseline["status"] != "READY" or baseline["scope_id"] != "BOSS-MVP-1" or baseline["ports"] != ports:
        raise ValueError("现有资料范围或端口与MVP记录不符")
    if not (directory / "business.sqlite").is_file() or not (directory / "accounts/credentials.json").is_file():
        raise FileNotFoundError("现有MVP资料或账号文件不完整，请通过既有入口核查")
    print(json.dumps({"status": "READY_TO_START", "scope": "BOSS-PRIORITY-ITERATION", "feature_id": args.feature_id, "directory": str(directory),
        "frontend_directory": str(frontend), "manifest_sha256": hashlib.sha256((frontend / "asset-manifest.json").read_bytes()).hexdigest(),
        "configuration_changed": False, "credentials_read": False, "business_records_changed": False}, ensure_ascii=False))


if __name__ == "__main__":
    main()
