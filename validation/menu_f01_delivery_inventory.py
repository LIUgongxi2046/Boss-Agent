import inspect
import json
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

import nanobot

from fc04_delivery_inventory import digest

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "menu-f01-n3-dist"
EVIDENCE = ROOT / "evidence/menu-delivery/F01"


def main():
    prepared = ROOT / ".work/product/nanobot/webui/src"
    if (prepared / "boss-agent/BossDesktop.tsx").read_bytes() != (ROOT / "app/webui/BossDesktop.tsx").read_bytes():
        raise ValueError("今日工作构建入口与正式BossDesktop源码不一致")
    prior = json.loads((ROOT / "evidence/feature-delivery/UI02/candidate-inventory.json").read_text())
    expected_changes = {"specs/data-dictionary.json", "specs/morning.schema.json", "specs/openapi.yaml", "specs/product-morning.openapi.yaml", "specs/runtime-records.schema.json",
        "validation/application.py", "validation/boss_command_api.py", "validation/boss_morning.py", "validation/boss_morning_projection.py", "validation/boss_owner_authorizations.py",
        "validation/boss_today.py", "validation/product_morning.py", "validation/role_channel.py"}
    changed, unchanged = {}, {}
    for name, expected in prior["unchanged_business_dependencies"].items():
        actual = digest(ROOT / name)
        (unchanged if actual == expected else changed)[name] = actual
    if set(changed) != expected_changes:
        raise ValueError("当前菜单的业务依赖变化与接收范围不符")
    protected = {}
    for name in (".work/product/nanobot/webui/src/providers/ClientProvider.tsx", ".work/product/nanobot/webui/src/lib/bootstrap.ts", "app/webui/BossLogin.tsx", "validation/desktop/main.cjs", "validation/desktop/preload.cjs"):
        actual = digest(ROOT / name)
        if actual != prior["sources"][name]:
            raise ValueError("当前菜单改变了既有认证或宿主权限：" + name)
        protected[name] = actual
    reports = {}
    for name in ("behavior.json", "native.json", "launcher.json"):
        report = json.loads((EVIDENCE / name).read_text())
        if report["status"] != "PASS" or report["manifest_sha256"] != digest(DIST / "asset-manifest.json"):
            raise ValueError("当前必要运行证据与制品不一致：" + name)
        reports[name] = digest(EVIDENCE / name)
    for name in ("combination.xml", "native-adapter.xml"):
        suites = list(ET.parse(EVIDENCE / name).getroot().iter("testsuite"))
        if not suites or any(int(suite.attrib["failures"]) or int(suite.attrib["errors"]) for suite in suites):
            raise ValueError("当前限定检查没有通过：" + name)
        reports[name] = digest(EVIDENCE / name)
    reports["reference-dom.json"] = digest(EVIDENCE / "reference-dom.json")
    sources = set((ROOT / "app/webui").glob("*"))
    for pattern in ("validation/*.py", "validation/fc03_agent/*.py", "validation/fc04_agent/*.py", "validation/fc07_agent/*.py", "validation/sop_write_tools/fc01/*.py", "specs/*.json", "specs/*.yaml", "data/simulation/*.yaml"):
        sources.update(ROOT.glob(pattern))
    for pattern in ("*.tsx", "*.ts", "*.css", "*.json"):
        sources.update(prepared.rglob(pattern))
    for pattern in ("scripts/*menu_f01*", "validation/desktop/*menu-f01*", "Boss-Agent-Desktop-Complete-v6/design-v6*", "Boss-Agent-Desktop-Complete-v6/style.css"):
        sources.update(ROOT.glob(pattern))
    sources.update(ROOT / name for name in ("scripts/prepare_mvp01.py", "validation/desktop/main.cjs", "validation/desktop/preload.cjs", "validation/desktop/fc03_morning_proxy.py",
        "Boss-Agent-Desktop-Complete-v6/design-tokens.json", "Boss-Agent-Desktop-Complete-v6/pages/F01-今日工作.html", "Boss-Agent-Desktop-Complete-v6/meta/页面配置.json",
        ".work/product/nanobot/LICENSE", ".work/product/nanobot/webui/package.json", ".work/product/nanobot/webui/tsconfig.json"))
    runtime = Path(inspect.getfile(nanobot)).parent
    result = {"scope": "MENU-F01_FULL_18", "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "ui02_base_candidate": "b7fdc76c81ef693da75511d736db60d92550784c", "domain_producer": "89d26855ba7d1fdb8bbe9ff0795a00562c9f53ab", "agent_producer": "961b8f68a037d819e4a705e6d6c7ba0d10c7d1da",
        "changed_business_dependencies": changed, "unchanged_business_dependencies": unchanged, "unchanged_authentication_and_host": protected,
        "sources": {str(path.relative_to(ROOT)): digest(path) for path in sorted(sources) if path.is_file()},
        "installed_nanobot_directory": str(runtime), "installed_nanobot_sources": {str(path.relative_to(runtime)): digest(path) for path in sorted(runtime.rglob("*.py"))},
        "frontend_directory": str(DIST), "manifest_sha256": digest(DIST / "asset-manifest.json"), "index_sha256": digest(DIST / "index.html"),
        "frontend_files": {str(path.relative_to(DIST)): digest(path) for path in sorted(DIST.rglob("*")) if path.is_file()}, "reports": reports,
        "external_api_mode": "SIMULATED_FIRST", "visual": "NOT_RUN", "user_acceptance": "NOT_RUN"}
    target = EVIDENCE / "candidate-inventory.json"
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"inventory": str(target), "manifest_sha256": result["manifest_sha256"], "index_sha256": result["index_sha256"], "changed_business_dependencies": len(changed), "unchanged_business_dependencies": len(unchanged)}))


if __name__ == "__main__":
    main()
