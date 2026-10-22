import hashlib
import json
import py_compile
from pathlib import Path
from urllib.parse import unquote, urlsplit

from markdown_it import MarkdownIt

from business import ROOT, now


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def npm_inventory(directory):
    lock = json.loads((directory / "package-lock.json").read_text())
    rows = []
    for relative, declared in lock["packages"].items():
        if not relative:
            continue
        package = directory / relative
        manifest = package / "package.json"
        if not manifest.is_file():
            rows.append({"path": relative, "locked_version": declared.get("version"), "installed": False, "optional": declared.get("optional", False)})
            continue
        actual = json.loads(manifest.read_text())
        assert actual["version"] == declared["version"], relative
        licenses = []
        for path in sorted(package.iterdir()):
            if path.is_file() and path.name.lower().startswith(("license", "copying", "notice")):
                licenses.append({"name": path.name, "sha256": digest(path), "content": path.read_text()})
        rows.append({"path": relative, "locked_version": declared["version"], "installed": True, "name": actual["name"], "license": actual.get("license"), "integrity": declared.get("integrity"), "license_files": licenses})
    return rows


def main():
    source = ROOT / ".work/upstream/nanobot-0.3.5"
    output = ROOT.parent / "evidence/T02/inventory"
    cache = ROOT / ".work/source-compilation"
    cache.mkdir(parents=True, exist_ok=True)
    baseline = json.loads((output / "source-files.json").read_text())
    docs, compiled = [], []
    parser = MarkdownIt()
    for row in baseline:
        relative = row["path"]
        path = source / relative
        assert digest(path) == row["sha256"], relative
        if relative.startswith("nanobot/") and path.suffix == ".py":
            py_compile.compile(str(path), cfile=str(cache / (row["sha256"] + ".pyc")), doraise=True)
            compiled.append(relative)
        if relative.startswith("docs/") and path.suffix == ".md":
            tokens = parser.parse(path.read_text())
            links = []
            for token in tokens:
                for child in token.children or []:
                    if child.type == "link_open":
                        address = child.attrGet("href")
                        url = urlsplit(address)
                        local = not url.scheme and not url.netloc and bool(url.path)
                        links.append({"href": address, "local": local, "target_exists": (path.parent / unquote(url.path)).exists() if local else None})
            docs.append({"path": relative, "sha256": row["sha256"], "content": path.read_text(), "links": links})
    frontend, desktop = npm_inventory(source / "webui"), npm_inventory(ROOT / "desktop")
    report = {"at": now(), "status": "PASS", "scope": "完整归档文件一致性、全部上游 nanobot Python 文件编译、完整官方 docs 资料集及本机 npm 依赖和许可文件收集；人工审查范围单独说明", "archive_files_checked": len(baseline), "python_files_compiled": len(compiled), "official_document_count": len(docs), "frontend_dependency_entries": len(frontend), "desktop_dependency_entries": len(desktop), "upstream_missing_local_links": [{"document": doc["path"], "href": link["href"]} for doc in docs for link in doc["links"] if link["target_exists"] is False], "manual_review_limit": "核心 SDK、架构、配置、Provider、WebUI、WebSocket、记忆、调度、开发、部署和采用路径已阅读；全部其他渠道指南、全部源码逐行和全部传递依赖条款的人工审查未完成"}
    for name, value in {"official-documents.json": docs, "frontend-installed-licenses.json": frontend, "desktop-installed-licenses.json": desktop, "source-audit.json": report}.items():
        (output / name).write_text(json.dumps(value, ensure_ascii=False, indent=2))
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
