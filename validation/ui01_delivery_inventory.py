import json
import subprocess
from pathlib import Path

from fc04_delivery_inventory import digest

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "ui01-n3-dist"


def main():
    prepared = ROOT / ".work/product/nanobot/webui/src"
    for name in ("BossDesktop.tsx", "BossLogin.tsx", "boss-v6.css", "boss-login.css"):
        if (prepared / "boss-agent" / name).read_bytes() != (ROOT / "app/webui" / name).read_bytes():
            raise ValueError("UI01构建输入与正式源码不一致：" + name)
    previous = json.loads((ROOT / "evidence/feature-delivery/FC04/candidate-inventory.json").read_text())
    unchanged = {}
    for name, expected in previous["sources"].items():
        if name.startswith("specs/") or name.startswith("validation/") and not name.startswith("validation/desktop/"):
            actual = digest(ROOT / name)
            if actual != expected:
                raise ValueError("UI01改变了现有业务依赖：" + name)
            unchanged[name] = actual
    report = json.loads((ROOT / "evidence/feature-delivery/UI01/current.json").read_text())
    if report["status"] != "PASS" or report["manifest_sha256"] != digest(DIST / "asset-manifest.json"):
        raise ValueError("当前UI01必要桌面证据与制品不一致")
    sources = set((ROOT / "app/webui").glob("*"))
    for pattern in ("validation/*.py", "validation/fc04_agent/*.py", "specs/*.json", "specs/*.yaml"):
        sources.update(ROOT.glob(pattern))
    sources.update(ROOT / name for name in ("scripts/run_ui01.command", "scripts/prepare_fc04.py", "validation/desktop/main.cjs", "validation/desktop/preload.cjs", "validation/desktop/check-ui01.cjs"))
    for pattern in ("*.tsx", "*.ts", "*.css"):
        sources.update(prepared.rglob(pattern))
    result = {"scope": "UI01_NAVIGATION_LOGIN_ONLY", "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "business_base_candidate": "dd5c9e5e78f6035c05278465304ecbc6fbe9bca0", "unchanged_business_dependencies": unchanged,
        "sources": {str(path.relative_to(ROOT)): digest(path) for path in sorted(sources) if path.is_file()},
        "frontend_directory": str(DIST), "manifest_sha256": digest(DIST / "asset-manifest.json"), "index_sha256": digest(DIST / "index.html"),
        "frontend_files": {str(path.relative_to(DIST)): digest(path) for path in sorted(DIST.rglob("*")) if path.is_file()},
        "visual": "NOT_RUN", "user_acceptance": "NOT_RUN"}
    target = ROOT / "evidence/feature-delivery/UI01/candidate-inventory.json"
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"inventory": str(target), "manifest_sha256": result["manifest_sha256"], "index_sha256": result["index_sha256"], "unchanged_business_dependencies": len(unchanged)}))


if __name__ == "__main__":
    main()
