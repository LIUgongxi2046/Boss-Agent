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
DIST = ROOT / "menu-n02-n3-dist"
EVIDENCE = ROOT / "evidence/menu-delivery/N02"
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
    if state["active_feature_id"] != "MENU-N02" or state["total_checkpoints"] != 26:
        raise ValueError("当前正式范围必须为MENU-N02完整26项")
    manifest = digest(DIST / "asset-manifest.json")
    directory = args.configuration_directory.resolve()
    if not directory.is_relative_to(ROOT / "validation/.work") or not directory.name.startswith("menu-n02-"):
        raise ValueError("配置必须来自独立N02检查目录")
    setup = json.loads((directory / "setup.json").read_text())
    if setup["feature_id"] != "MENU-N02" or setup["status"] != "READY" or setup["manifest_sha256"] != manifest or setup["runtime_configuration_values"] != VALUES:
        raise ValueError("当前启动初始化与制品或工具配置不符")
    with sqlite3.connect((directory / "business.sqlite").as_uri() + "?mode=ro", uri=True) as db:
        row = db.execute("SELECT body FROM objects WHERE namespace='ui-check' AND kind='configuration' AND id='current'").fetchone()
    if row is None:
        raise ValueError("当前实际Runtime没有启用配置")
    configuration = json.loads(row[0])
    expected_values = {**VALUES, "tool_scope": sorted(VALUES["tool_scope"]), "workspace_projections": sorted(VALUES["workspace_projections"])}
    if configuration["version"] != setup["configuration_version"] or any(configuration[field] != value for field, value in expected_values.items()):
        raise ValueError("实际启用配置与当前启动声明不一致")
    reports = {}
    for name in ("native.json", "task-entry-ui.json", "morning-entry.json", "return-position.json", "unknown.json", "input.json", "close.json", "native-privacy.json", "shared-layout.json", "launcher.json", "framework-current.json", "header.json"):
        report = json.loads((EVIDENCE / name).read_text())
        expected_status = "MEASURED" if name == "framework-current.json" else "PASS"
        if report["status"] != expected_status or report["manifest_sha256"] != manifest:
            raise ValueError("当前运行证据没有绑定准确制品：" + name)
        reports[name] = digest(EVIDENCE / name)
    for name in ("native-runtime-receiver.xml", "observable-failure-receiver.xml", "task-entry-receiver.xml", "task-entry-consumer-receiver.xml", "task-bound-consumer-receiver.xml", "task-bound-schema-receiver.xml", "context-reference-receiver.xml", "task-reference-receiver.xml", "native-file-receiver.xml", "received-domain.xml"):
        suites = list(ET.parse(EVIDENCE / name).getroot().iter("testsuite"))
        if not suites or any(int(suite.attrib["failures"]) or int(suite.attrib["errors"]) or int(suite.attrib["skipped"]) for suite in suites):
            raise ValueError("领域或消费者检查没有完整通过：" + name)
        reports[name] = digest(EVIDENCE / name)
    reports["reference-dom.json"] = digest(EVIDENCE / "reference-dom.json")
    for name in ("BossDesktop.tsx", "BossConversationWorkspace.tsx", "boss-n02.css"):
        if (ROOT / "app/webui" / name).read_bytes() != (PREPARED / "src/boss-agent" / name).read_bytes():
            raise ValueError("正式界面与当前准备内容不一致：" + name)
    tracked = subprocess.check_output(["git", "ls-files", "app/webui", "validation/*.py", "validation/*/*.py", "validation/*/*/*.py", "validation/desktop/*.cjs", "validation/desktop/*.mjs", "validation/desktop/package.json", "validation/desktop/package-lock.json", "validation/pyproject.toml", "validation/uv.lock", "scripts", "specs", "data/simulation", "docs/menu-delivery/N02", "Boss-Agent-Desktop-Complete-v6"], cwd=ROOT, text=True).splitlines()
    sources = {ROOT / name for name in tracked if (ROOT / name).is_file()}
    sources.update(path for path in (PREPARED / "src").rglob("*") if path.is_file() and path.suffix in {".tsx", ".ts", ".css", ".json"} and not {"tests", "__tests__"}.intersection(path.relative_to(PREPARED / "src").parts))
    sources.update(PREPARED / name for name in ("package.json", "package-lock.json", "tsconfig.json", "tsconfig.build.json", "vite.config.ts"))
    sources.add(PREPARED.parent / "LICENSE")
    if any(path.is_symlink() for path in sources):
        raise ValueError("候选源码不能通过符号链接采用其他内容")
    installed = Path(inspect.getfile(nanobot)).parent
    distributions = importlib.metadata.packages_distributions()["nanobot"]
    protected = {}
    for name, key in (("UI02", "historical_ui02"), ("MVP01", "historical_mvp01")):
        prior = state[key]
        frontend = ROOT / Path(prior["frontend_directory"]).name
        if digest(frontend / "asset-manifest.json") != prior["manifest_sha256"] or digest(frontend / "index.html") != prior["index_sha256"]:
            raise ValueError("已有用户体验制品发生变化：" + name)
        protected[name] = {"directory": str(frontend), "manifest_sha256": prior["manifest_sha256"], "index_sha256": prior["index_sha256"]}
    frozen = ROOT / "menu-f01-n3-dist"
    frozen_hashes = {"asset-manifest.json": "e3b36c80baac9bbba869d5012b53d38c43b2a05d1869ec9ce10a0c365bafd62c", "index.html": "11a935970330ddfa87e50faeb5f266cd27163f11750945e01797be25d3396b1f"}
    if any(digest(frozen / name) != expected for name, expected in frozen_hashes.items()):
        raise ValueError("F01原有体验制品发生变化")
    protected["F01"] = {"directory": str(frozen), **frozen_hashes}
    public_configuration = {field: configuration[field] for field in ("config_id", "version", "provider", "model_id", "api_type", "max_tool_rounds", "max_output_tokens", "timeout", "tool_scope", "workspace_read_mode", "workspace_projections", "enabled")}
    result = {"scope": "MENU-N02_FULL_26_CANDIDATE", "implementation_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "formal_state": {"path": str(args.formal_state.resolve()), "sha256": digest(args.formal_state), "active_feature_id": "MENU-N02", "total_checkpoints": 26},
        "sources": {str(path.relative_to(ROOT)): digest(path) for path in sorted(sources)},
        "installed_nanobot_directory": str(installed), "installed_nanobot_versions": {name: importlib.metadata.version(name) for name in distributions},
        "installed_nanobot_sources": {str(path.relative_to(installed)): digest(path) for path in sorted(installed.rglob("*.py"))},
        "frontend_directory": str(DIST), "manifest_sha256": manifest, "index_sha256": digest(DIST / "index.html"),
        "frontend_files": {str(path.relative_to(DIST)): digest(path) for path in sorted(DIST.rglob("*")) if path.is_file()},
        "runtime_configuration": public_configuration, "setup_sha256": digest(directory / "setup.json"), "reports": reports, "protected_frontends": protected,
        "external_api_mode": "SIMULATED_FIRST", "visual": "NOT_RUN", "user_acceptance": "NOT_RUN"}
    target = EVIDENCE / "candidate-inventory.json"
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"inventory": str(target), "manifest_sha256": manifest, "source_count": len(sources), "runtime_tool_count": len(configuration["tool_scope"])}))


if __name__ == "__main__":
    main()
