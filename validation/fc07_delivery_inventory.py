import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "fc07-n3-dist"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    prepared = ROOT / ".work/product/nanobot/webui/src"
    for name in ("BossDesktop.tsx", "boss-v6.css"):
        if (prepared / "boss-agent" / name).read_bytes() != (ROOT / "app/webui" / name).read_bytes():
            raise ValueError("当前构建输入与正式源码不一致：" + name)
    producers = {
        "c13996a43ec663fef639a375ff16c38f5f9d5774": ["validation/controls.py", "validation/business.py", "validation/boss_self_commitments.py", "validation/boss_assignment_extensions.py", "specs/assignment-extension.schema.json"],
        "c6834f96376d18f14793bc2a4c3e6c4ca568f282": ["validation/fc07_agent/__init__.py", "validation/fc07_agent/runtime.py", "validation/fc07_agent/contract.py"],
    }
    for commit, names in producers.items():
        for name in names:
            original = subprocess.check_output(["git", "show", commit + ":" + name], cwd=ROOT)
            if original != (ROOT / name).read_bytes():
                raise ValueError("当前接收模块与正式生产者不一致：" + name)
    sources = set((ROOT / "app/webui").glob("*"))
    for pattern in ("validation/*.py", "validation/fc07_agent/*.py", "specs/*.json", "specs/*.yaml"):
        sources.update(ROOT.glob(pattern))
    sources.update(ROOT / name for name in ("scripts/prepare_fc07.py", "scripts/run_fc07.command", "validation/desktop/main.cjs"))
    sources.update(prepared.rglob("*.tsx"))
    sources.update(prepared.rglob("*.ts"))
    sources.update(prepared.rglob("*.css"))
    files = {str(path.relative_to(ROOT)): digest(path) for path in sorted(sources) if path.is_file()}
    assets = {str(path.relative_to(DIST)): digest(path) for path in sorted(DIST.rglob("*")) if path.is_file()}
    output = {"scope": "FC07_CURRENT_BUILD_AND_RECEIVED_INPUTS", "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "sources": files, "frontend_directory": str(DIST), "manifest_sha256": digest(DIST / "asset-manifest.json"), "index_sha256": digest(DIST / "index.html"),
        "frontend_files": assets, "received_producers_unchanged": producers, "visual": "NOT_RUN", "user_acceptance": "NOT_RUN"}
    target = ROOT / "evidence/feature-delivery/FC07/candidate-inventory.json"
    target.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"inventory": str(target), "manifest_sha256": output["manifest_sha256"], "source_count": len(files)}))


if __name__ == "__main__":
    main()
