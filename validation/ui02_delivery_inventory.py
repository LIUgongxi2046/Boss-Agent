import json
import subprocess
from pathlib import Path

from fc04_delivery_inventory import digest

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "ui02-n3-dist"


def main():
    prepared = ROOT / ".work/product/nanobot/webui/src"
    for name in ("BossDesktop.tsx", "BossLogin.tsx", "boss-v6.css", "boss-login.css"):
        if (prepared / "boss-agent" / name).read_bytes() != (ROOT / "app/webui" / name).read_bytes():
            raise ValueError("UI02构建输入与正式源码不一致：" + name)
    prior = json.loads((ROOT / "evidence/feature-delivery/UI01/candidate-inventory.json").read_text())
    unchanged = prior["unchanged_business_dependencies"]
    for name, expected in unchanged.items():
        if digest(ROOT / name) != expected:
            raise ValueError("UI02改变了现有业务依赖：" + name)
    shared = {}
    for name in (".work/product/nanobot/webui/src/providers/ClientProvider.tsx", ".work/product/nanobot/webui/src/lib/nanobot-client.ts", ".work/product/nanobot/webui/src/lib/bootstrap.ts", "app/webui/BossLogin.tsx", "validation/desktop/main.cjs", "validation/desktop/preload.cjs"):
        actual = digest(ROOT / name)
        if actual != prior["sources"][name]:
            raise ValueError("UI02改变了既有认证、客户端或宿主权限：" + name)
        shared[name] = actual
    reports = {}
    for name in ("current.json", "business.json", "navigation.json", "launcher.json"):
        report = json.loads((ROOT / "evidence/feature-delivery/UI02" / name).read_text())
        if report["status"] != "PASS" or report["manifest_sha256"] != digest(DIST / "asset-manifest.json"):
            raise ValueError("UI02当前必要证据与制品不一致：" + name)
        reports[name] = digest(ROOT / "evidence/feature-delivery/UI02" / name)
    sources = set((ROOT / "app/webui").glob("*"))
    for pattern in ("validation/*.py", "validation/fc04_agent/*.py", "specs/*.json", "specs/*.yaml"):
        sources.update(ROOT.glob(pattern))
    sources.update(ROOT / name for name in ("scripts/run_ui02.command", "scripts/prepare_fc04.py", "validation/desktop/main.cjs", "validation/desktop/preload.cjs", "validation/desktop/check-ui02.cjs", "validation/desktop/check-ui02-business.cjs", "validation/desktop/fc03_morning_proxy.py"))
    sources.add(ROOT / "validation/desktop/check-ui02-navigation.cjs")
    sources.add(ROOT / "validation/desktop/check-ui02-launcher.cjs")
    for pattern in ("*.tsx", "*.ts", "*.css", "*.json"):
        sources.update(prepared.rglob(pattern))
    sources.update(ROOT / name for name in ("Boss-Agent-Desktop-Complete-v6/design-tokens.json", ".work/product/nanobot/LICENSE"))
    result = {"scope": "UI02_SHARED_PRODUCT_NATIVE_SHELL", "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "ui01_base_candidate": "386c577b67b2b53fc1989f258095547035750ad3", "unchanged_business_dependencies": unchanged, "unchanged_auth_client_host": shared,
        "sources": {str(path.relative_to(ROOT)): digest(path) for path in sorted(sources) if path.is_file()},
        "frontend_directory": str(DIST), "manifest_sha256": digest(DIST / "asset-manifest.json"), "index_sha256": digest(DIST / "index.html"),
        "frontend_files": {str(path.relative_to(DIST)): digest(path) for path in sorted(DIST.rglob("*")) if path.is_file()},
        "reports": reports, "visual": "NOT_RUN", "user_acceptance": "NOT_RUN"}
    target = ROOT / "evidence/feature-delivery/UI02/candidate-inventory.json"
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"inventory": str(target), "manifest_sha256": result["manifest_sha256"], "index_sha256": result["index_sha256"], "unchanged_business_dependencies": len(unchanged)}))


if __name__ == "__main__":
    main()
