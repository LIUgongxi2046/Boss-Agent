import argparse
import hashlib
import importlib.metadata
import inspect
import json
import sqlite3
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import nanobot

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "menu-f01-rework-n3-dist"
EVIDENCE = ROOT / "evidence/menu-delivery/F01"
PREPARED = ROOT / ".work/product/nanobot/webui"
sys.path.insert(0, str(ROOT / "scripts"))

from prepare_menu_n02 import VALUES


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--formal-state", type=Path, required=True)
    parser.add_argument("--configuration-directory", type=Path, required=True)
    args = parser.parse_args()
    state = json.loads(args.formal_state.read_text())
    if state["active_feature_id"] != "MENU-F01" or state["total_checkpoints"] != 18:
        raise ValueError("正式范围必须为今日工作完整18项")
    delivery_path = ROOT / "docs/menu-delivery/F01/delivery-rework.json"
    delivery = json.loads(delivery_path.read_text())
    ids = {f"MENU-F01.C{index:02}" for index in range(1, 19)}
    if set(delivery["checkpoint_development_evidence"]) != ids:
        raise ValueError("今日工作检查点范围不符")
    if delivery["development_covered_checkpoints"] != 18 or delivery["user_verified_checkpoints"] is not None:
        raise ValueError("开发与用户验收计数不符")
    if any(row["status"] != "COVERED" for row in delivery["checkpoint_development_evidence"].values()):
        raise ValueError("必要开发证据尚未完整登记")
    manifest = digest(DIST / "asset-manifest.json")
    if delivery["manifest_sha256"] != manifest or delivery["index_sha256"] != digest(DIST / "index.html"):
        raise ValueError("今日工作交付记录没有采用当前制品")
    reports = {}
    for name in ("rework-design.json", "rework-behavior.json", "rework-native.json", "rework-launcher.json"):
        report = json.loads((EVIDENCE / name).read_text())
        if report["status"] != "PASS" or report["manifest_sha256"] != manifest:
            raise ValueError("当前必要检查没有采用准确制品：" + name)
        reports[name] = digest(EVIDENCE / name)
    for name in ("combination.xml", "native-adapter.xml"):
        suites = list(ET.parse(EVIDENCE / name).getroot().iter("testsuite"))
        if not suites or any(int(suite.attrib["failures"]) or int(suite.attrib["errors"]) for suite in suites):
            raise ValueError("保留的领域与适配器证据不完整：" + name)
        reports[name] = digest(EVIDENCE / name)
    baseline = json.loads((ROOT / "evidence/menu-delivery/N02/candidate-inventory.json").read_text())
    business = {}
    for name, expected in baseline["sources"].items():
        if name.startswith("specs/") or name.startswith("validation/") and name.endswith(".py"):
            if digest(ROOT / name) != expected:
                raise ValueError("设计修订改变了已接收业务依赖：" + name)
            business[name] = expected
    for name in ("BossDesktop.tsx", "BossConversationWorkspace.tsx", "boss-n02.css"):
        if (ROOT / "app/webui" / name).read_bytes() != (PREPARED / "src/boss-agent" / name).read_bytes():
            raise ValueError("正式界面与构建采用的内容不符：" + name)
    for name in ("validation/desktop/main.cjs", "validation/desktop/preload.cjs", "app/webui/BossLogin.tsx"):
        if digest(ROOT / name) != baseline["sources"][name]:
            raise ValueError("设计修订改变了既有认证与宿主：" + name)
    directory = args.configuration_directory.resolve()
    if not directory.is_relative_to(ROOT / "validation/.work") or not directory.name.startswith("menu-f01-rework-"):
        raise ValueError("初始化资料必须来自独立今日工作目录")
    setup = json.loads((directory / "setup.json").read_text())
    if setup["feature_id"] != "MENU-F01" or setup["status"] != "READY" or setup["manifest_sha256"] != manifest or setup["runtime_configuration_values"] != VALUES:
        raise ValueError("当前初始化声明不符")
    with sqlite3.connect((directory / "business.sqlite").as_uri() + "?mode=ro", uri=True) as db:
        row = db.execute("SELECT body FROM objects WHERE namespace='ui-check' AND kind='configuration' AND id='current'").fetchone()
    if row is None:
        raise ValueError("实际Runtime尚未启用配置")
    configuration = json.loads(row[0])
    expected_values = {**VALUES, "tool_scope": sorted(VALUES["tool_scope"]), "workspace_projections": sorted(VALUES["workspace_projections"])}
    if configuration["version"] != setup["configuration_version"] or any(configuration[field] != value for field, value in expected_values.items()):
        raise ValueError("实际启用配置与初始化声明不符")
    protected = {}
    for name, key in (("F01", "historical_menu_f01"), ("N02", "historical_menu_n02"), ("UI02", "historical_ui02"), ("MVP01", "historical_mvp01")):
        prior = state[key]
        frontend = ROOT / Path(prior["frontend_directory"]).name
        if digest(frontend / "asset-manifest.json") != prior["manifest_sha256"] or digest(frontend / "index.html") != prior["index_sha256"]:
            raise ValueError("已有用户体验制品发生变化：" + name)
        protected[name] = {"directory": str(frontend), "manifest_sha256": prior["manifest_sha256"], "index_sha256": prior["index_sha256"]}
    installed = Path(inspect.getfile(nanobot)).parent
    for name, expected in baseline["installed_nanobot_sources"].items():
        if digest(installed / name) != expected:
            raise ValueError("设计修订改变了已接收实际SDK：" + name)
    tracked = subprocess.check_output(["git", "ls-files", "app/webui", "validation/*.py", "validation/*/*.py", "validation/*/*/*.py", "validation/desktop/*.cjs", "validation/desktop/package.json", "validation/desktop/package-lock.json", "scripts", "specs", "data/simulation", "docs/menu-delivery/F01", "Boss-Agent-Desktop-Complete-v6"], cwd=ROOT, text=True).splitlines()
    sources = {ROOT / name for name in tracked if (ROOT / name).is_file()}
    sources.update(path for path in (PREPARED / "src").rglob("*") if path.is_file() and path.suffix in {".tsx", ".ts", ".css", ".json"} and not {"tests", "__tests__"}.intersection(path.relative_to(PREPARED / "src").parts))
    sources.update(PREPARED / name for name in ("package.json", "package-lock.json", "tsconfig.json", "tsconfig.build.json", "vite.config.ts"))
    sources.add(PREPARED.parent / "LICENSE")
    if any(path.is_symlink() for path in sources):
        raise ValueError("候选源码不能通过符号链接采用其他内容")
    public_configuration = {field: configuration[field] for field in ("config_id", "version", "provider", "model_id", "api_type", "max_tool_rounds", "max_output_tokens", "timeout", "tool_scope", "workspace_read_mode", "workspace_projections", "enabled")}
    result = {"scope": "MENU-F01_FULL_18_DESIGN_REWORK", "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "baseline_candidate": "8e135b8c8b09e0aa3b95ceddb9146868565fa8d7", "formal_state_sha256": digest(args.formal_state),
        "delivery_record": {"path": str(delivery_path), "sha256": digest(delivery_path)}, "unchanged_business_dependencies": business,
        "sources": {str(path.relative_to(ROOT)): digest(path) for path in sorted(sources)},
        "installed_nanobot_directory": str(installed), "installed_nanobot_versions": {name: importlib.metadata.version(name) for name in importlib.metadata.packages_distributions()["nanobot"]},
        "installed_nanobot_sources": {str(path.relative_to(installed)): digest(path) for path in sorted(installed.rglob("*.py"))},
        "frontend_directory": str(DIST), "manifest_sha256": manifest, "index_sha256": digest(DIST / "index.html"),
        "frontend_files": {str(path.relative_to(DIST)): digest(path) for path in sorted(DIST.rglob("*")) if path.is_file()},
        "reports": reports, "runtime_configuration": public_configuration, "setup_sha256": digest(directory / "setup.json"), "protected_frontends": protected,
        "external_api_mode": "SIMULATED_FIRST", "visual": "NOT_RUN", "user_acceptance": "NOT_RUN"}
    target = EVIDENCE / "rework-candidate-inventory.json"
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"inventory": str(target), "source_count": len(sources), "unchanged_business_dependencies": len(business), "manifest_sha256": manifest, "runtime_tool_count": len(configuration["tool_scope"])}))


if __name__ == "__main__":
    main()
