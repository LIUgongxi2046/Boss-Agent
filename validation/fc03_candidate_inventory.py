import argparse
import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PREPARED = ROOT / ".work/product/nanobot/webui"
FRONTEND = ROOT / "fc03-n3-morning-dist"
N1 = Path("/Users/liuhaoxian/.codex/worktrees/boss-business/Boss-Agent")
N2 = Path("/Users/liuhaoxian/.codex/worktrees/boss-sop-writes/Boss-Agent")
PRODUCERS = [(N1, "e3faa5dcd90831d5e84e42c6ca66b418f85b767c", [
    "validation/boss_morning.py", "validation/boss_morning_projection.py", "validation/boss_morning_inputs.py",
    "validation/boss_today.py", "specs/morning.schema.json", "specs/morning-coverage.json"]),
    (N2, "42f949eda36b7bee4e5c5ece8da44e586fbd2b43", [
    "validation/fc03_agent/__init__.py", "validation/fc03_agent/formal.py", "validation/fc03_agent/runtime.py"])]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(directory, *args):
    return subprocess.check_output(["git", *args], cwd=directory)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", required=True)
    args = parser.parse_args()
    output = ROOT / "evidence/feature-delivery/FC03/candidate-inventory.json"
    report_path = ROOT / args.evidence
    assert report_path.parent == output.parent and report_path.is_file()
    report = json.loads(report_path.read_text())
    assert report["status"] == "PASS"
    assert report["manifest_sha256"] == digest(FRONTEND / "asset-manifest.json")
    assert report["index_sha256"] == digest(FRONTEND / "index.html")
    producer_inputs = []
    for directory, commit, paths in PRODUCERS:
        for path in paths:
            original = git(directory, "show", commit + ":" + path)
            expected = hashlib.sha256(original).hexdigest()
            assert digest(ROOT / path) == expected, path
            producer_inputs.append({"producer_directory": str(directory), "producer_commit": commit, "path": path, "sha256": expected})
    for name in ("BossDesktop.tsx", "BossAssignmentFlow.tsx", "boss-v6.css"):
        assert digest(ROOT / "app/webui" / name) == digest(PREPARED / "src/boss-agent" / name), name
    bridges = {"BossMorningView.tsx": "BossMorningView,type MorningReference", "BossMorningPreparation.tsx": "BossMorningPreparation", "MaintainerMorningCoverage.tsx": "MaintainerMorningCoverage"}
    for name, exports in bridges.items():
        assert (PREPARED / "src/boss-agent" / name).read_text() == "export {" + exports + "} from \"../../../../../../app/webui/" + name[:-4] + "\";\n"
    paths = set((ROOT / "validation").glob("*.py")) | set((ROOT / "validation/fc03_agent").glob("*.py"))
    for directory in ("fc02_agent", "sop_write_tools"):
        paths |= set((ROOT / "validation" / directory).rglob("*.py"))
    paths |= {ROOT / name for name in ("app/tests/test_public_morning.py", "app/tests/test_product_morning_runtime.py", "app/tests/test_fc03_morning.py", "validation/desktop/check-fc03-morning.cjs", "validation/desktop/fc03_morning_proxy.py")}
    paths |= set((ROOT / "app/tests/fc03_agent").glob("*.py"))
    paths.add(ROOT / "app/tests/test_product_bi_runtime.py")
    native_modified = [PREPARED.parent / name for name in git(PREPARED.parent, "diff", "--name-only", "-z").decode().split("\0") if name]
    assert all(path.is_file() for path in native_modified)
    paths |= set(native_modified)
    paths |= set((ROOT / "app/webui").glob("*.tsx")) | set((ROOT / "app/webui").glob("*.css")) | set((ROOT / "app/webui").glob("*.patch"))
    paths |= set((ROOT / "specs").glob("*.json")) | set((ROOT / "specs").glob("*.yaml"))
    paths |= set((PREPARED / "src/boss-agent").glob("*"))
    paths |= {PREPARED / name for name in ("package.json", "package-lock.json", "tsconfig.json", "tsconfig.build.json", "vite.config.ts", "src/App.tsx", "src/lib/nanobot-client.ts")}
    inputs = [{"path": str(path.relative_to(ROOT)), "sha256": digest(path)} for path in sorted(paths) if path.is_file()]
    assets = [{"path": str(path.relative_to(FRONTEND)), "sha256": digest(path)} for path in sorted(FRONTEND.rglob("*")) if path.is_file()]
    evidence = {str(path.relative_to(ROOT)): digest(path) for path in (
        report_path, ROOT / "evidence/feature-delivery/FC03/morning-public-combination-green.xml",
        ROOT / "evidence/feature-delivery/FC03/morning-sdk-schema-and-shared.xml",
        ROOT / "evidence/feature-delivery/FC03/morning-public-final.xml",
        ROOT / "evidence/feature-delivery/FC03/morning-fc01-shared.xml",
        ROOT / "docs/feature-delivery/FC03/check.xml", ROOT / "docs/feature-delivery/FC03/agent-check.xml",
        ROOT / "docs/feature-delivery/FC03/formal-check.xml", ROOT / "docs/feature-delivery/FC03/consumer-check.xml")}
    body = {"status": "PASS", "implementation_commit": git(ROOT, "rev-parse", "HEAD").decode().strip(),
        "upstream_commit": git(PREPARED.parent, "rev-parse", "HEAD").decode().strip(),
        "producer_inputs": producer_inputs, "inputs": inputs, "frontend_directory": str(FRONTEND),
        "manifest_sha256": report["manifest_sha256"], "index_sha256": report["index_sha256"], "assets": assets,
        "evidence_sha256": evidence, "direct_canonical_modules": ["app/webui/BossMorningView.tsx", "app/webui/BossToday.tsx", "app/webui/BossMorningPreparation.tsx", "app/webui/MaintainerMorningCoverage.tsx"],
        "prepared_sources_equal": ["BossDesktop.tsx", "BossAssignmentFlow.tsx", "boss-v6.css"],
        "external_api_mode": "SIMULATED_FIRST", "visual": "NOT_RUN", "full_feature_independent_verdict": "NOT_RUN"}
    output.write_text(json.dumps(body, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"status": "PASS", "report": str(output), "inputs": len(inputs), "assets": len(assets), "producer_inputs": len(producer_inputs)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
