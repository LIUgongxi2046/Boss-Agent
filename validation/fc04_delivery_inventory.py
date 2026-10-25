import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "fc04-n3-dist"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    prepared = ROOT / ".work/product/nanobot/webui/src"
    for name in ("BossDesktop.tsx", "boss-v6.css"):
        if (prepared / "boss-agent" / name).read_bytes() != (ROOT / "app/webui" / name).read_bytes():
            raise ValueError("当前构建输入与正式源码不一致：" + name)
    producers = {
        "35f5f3970897140947adf2a09f873584cd391292": ["validation/boss_alert_policy.py", "validation/boss_alert_rules.py", "validation/boss_alert_dispatch.py", "validation/boss_business_alerts.py", "validation/controls.py", "validation/business.py", "validation/boss_simulation_api.py", "specs/business-alert.schema.json", "specs/business-alert-input.json"],
        "1636a0771a3cc390f6ae4dccf8a0273725c24d21": ["validation/fc04_agent/__init__.py", "validation/fc04_agent/runtime.py", "validation/fc04_agent/contract.py"],
    }
    for commit, names in producers.items():
        for name in names:
            original = subprocess.check_output(["git", "show", commit + ":" + name], cwd=ROOT)
            if original != (ROOT / name).read_bytes():
                raise ValueError("当前领域或工具模块与准确生产者不一致：" + name)
    sources = set((ROOT / "app/webui").glob("*"))
    for pattern in ("validation/*.py", "validation/fc04_agent/*.py", "specs/*.json", "specs/*.yaml", "app/tests/test_fc04*.py", "app/tests/test_product_reminders.py"):
        sources.update(ROOT.glob(pattern))
    sources.update(ROOT / name for name in ("scripts/prepare_fc04.py", "scripts/run_fc04.command", "validation/desktop/main.cjs", "validation/desktop/preload.cjs", "validation/desktop/check-fc04-journey.cjs", "validation/desktop/check-fc04-public.cjs", "validation/desktop/check-fc04-launcher.cjs"))
    for pattern in ("*.tsx", "*.ts", "*.css"):
        sources.update(prepared.rglob(pattern))
    files = {str(path.relative_to(ROOT)): digest(path) for path in sorted(sources) if path.is_file()}
    assets = {str(path.relative_to(DIST)): digest(path) for path in sorted(DIST.rglob("*")) if path.is_file()}
    output = {"scope": "FC04_CURRENT_BUILD_AND_RECEIVED_INPUTS", "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "sources": files, "frontend_directory": str(DIST), "manifest_sha256": digest(DIST / "asset-manifest.json"), "index_sha256": digest(DIST / "index.html"),
        "frontend_files": assets, "received_producers_unchanged": producers, "visual": "NOT_RUN", "user_acceptance": "NOT_RUN"}
    target = ROOT / "evidence/feature-delivery/FC04/candidate-inventory.json"
    target.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"inventory": str(target), "manifest_sha256": output["manifest_sha256"], "index_sha256": output["index_sha256"], "source_count": len(files)}))


if __name__ == "__main__":
    main()
