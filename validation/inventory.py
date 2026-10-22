import hashlib
import importlib.metadata
import json
import platform
import sys
import tarfile
import tomllib
from pathlib import Path

from business import ROOT, now


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    source = ROOT / ".work/upstream/nanobot-0.3.5"
    output = ROOT.parent / "evidence/T02/inventory"
    output.mkdir(parents=True, exist_ok=True)
    archive = ROOT / ".work/nanobot-v0.3.5.tar.gz"
    assert digest(archive) == "907d179f428ca321236058efef721f942eb11917d3874887d37b33fd0e208525", "固定源码归档校验和不一致"
    tag = json.loads((ROOT / ".work/nanobot-annotated-tag.json").read_text())
    assert tag["object"]["sha"] == "1bb712d3488915ca4ed9ccc1a93067ff722f5ab9"
    distributions = []
    for distribution in sorted(importlib.metadata.distributions(), key=lambda d: d.metadata["Name"].lower()):
        meta = distribution.metadata
        distributions.append({"name": meta["Name"], "version": distribution.version, "license_expression": meta.get("License-Expression"), "license_declaration": meta.get("License"), "license_files": meta.get_all("License-File", []), "classifiers": meta.get_all("Classifier", []), "requires_dist": meta.get_all("Requires-Dist", [])})
    frontend = json.loads((source / "webui/package-lock.json").read_text())
    with tarfile.open(archive, "r:gz") as package:
        files = []
        for member in package.getmembers():
            if not member.isfile():
                continue
            relative = Path(member.name).relative_to("nanobot-0.3.5")
            archived = hashlib.sha256(package.extractfile(member).read()).hexdigest()
            current = source / relative
            files.append({"path": str(relative), "sha256": archived, "current_sha256": digest(current) if current.exists() else None})
    lock = tomllib.loads((ROOT / "uv.lock").read_text())
    installed_root = Path(importlib.metadata.distribution("nanobot-ai").locate_file("nanobot"))
    comparison = []
    for path in sorted((source / "nanobot").rglob("*.py")):
        if "tests" in path.parts:
            continue
        relative = path.relative_to(source / "nanobot")
        installed = installed_root / relative
        comparison.append({"path": str(relative), "source_sha256": digest(path), "installed_sha256": digest(installed) if installed.exists() else None, "matches": installed.exists() and digest(installed) == digest(path)})
    bundle = [{"path": str(path.relative_to(installed_root)), "sha256": digest(path)} for path in sorted((installed_root / "web/dist").rglob("*")) if path.is_file()]
    rebuilt = [{"path": str(path.relative_to(source / "nanobot")), "sha256": digest(path)} for path in sorted((source / "nanobot/web/dist").rglob("*")) if path.is_file()]
    licenses = []
    for distribution in importlib.metadata.distributions():
        for relative in distribution.files or []:
            if any(part.lower().startswith(("license", "copying", "notice")) for part in relative.parts):
                path = Path(distribution.locate_file(relative))
                if path.is_file():
                    licenses.append({"distribution": distribution.metadata["Name"], "version": distribution.version, "path": str(relative), "sha256": digest(path), "content": path.read_text(errors="strict")})
    report = {"at": now(), "repository": "https://github.com/HKUDS/nanobot", "tag": "v0.3.5", "commit": tag["object"]["sha"], "archive_sha256": digest(archive), "python": sys.version, "machine": platform.machine(), "macos": platform.mac_ver()[0], "installed_distribution_count": len(distributions), "locked_distribution_count": len(lock["package"]), "upstream_files": len(files), "source_changes": [row["path"] for row in files if row["sha256"] != row["current_sha256"]], "python_source_comparison_count": len(comparison), "python_source_mismatches": [row["path"] for row in comparison if not row["matches"]], "bundled_webui_files": len(bundle), "rebuilt_webui_files": len(rebuilt), "frontend_rebuilt": bool(rebuilt), "rebuilt_matches_release_bundle": rebuilt == bundle, "frontend_reproducible_build": "一次源码构建成功；跨环境字节复现尚未执行", "dependency_license_review": "声明及安装分发包内可定位许可原文已收集；全部条款的人工审查未完成"}
    values = {"result.json": report, "source-files.json": files, "python-dependencies.json": distributions, "python-license-texts.json": licenses, "frontend-dependencies.json": frontend["packages"], "python-source-comparison.json": comparison, "webui-bundle.json": bundle, "rebuilt-webui.json": rebuilt}
    for name, value in values.items():
        (output / name).write_text(json.dumps(value, ensure_ascii=False, indent=2))
    for name in ("LICENSE", "THIRD_PARTY_NOTICES.md", "pyproject.toml"):
        (output / name).write_bytes((source / name).read_bytes())
    (output / "upstream-tag.json").write_bytes((ROOT / ".work/nanobot-annotated-tag.json").read_bytes())
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
