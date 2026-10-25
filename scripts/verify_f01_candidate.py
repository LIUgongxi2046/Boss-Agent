#!/usr/bin/env python3
"""Read-only hash and source check for one exact Boss-Agent F01 frontend build.

Point --bundle at the directory *containing* boss-compiled-build.json and
nanobot/nanobot/web/dist. Does not authenticate, initialize, start or alter
the user's running application.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PINNED_UPSTREAM = "1bb712d3488915ca4ed9ccc1a93067ff722f5ab9"
FORMAT = "BOSS_AGENT_DIST_SHA256_V1"
SHA_LENGTH = 64


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sha(value: object) -> bool:
    return isinstance(value, str) and len(value) == SHA_LENGTH and all(
        digit in "0123456789abcdef" for digit in value
    )


def verify(bundle: Path, *, require_head: bool = False) -> dict:
    root = bundle.resolve(strict=True)
    record_path = root / "boss-compiled-build.json"
    if not record_path.is_file() or record_path.is_symlink():
        raise ValueError("当前制品缺少非符号链接的准确构建声明")
    record = json.loads(record_path.read_text(encoding="utf-8"))
    if not isinstance(record, dict) or set(record) != {
        "format", "repo_commit", "nanobot_commit", "index_html_sha256",
        "overlay_manifest_sha256", "assets", "result", "desktop_v7_verified",
    }:
        raise ValueError("制品校验声明与正式字段不符")
    if record["format"] != FORMAT or record["nanobot_commit"] != PINNED_UPSTREAM:
        raise ValueError("制品格式或 nanobot 固定源码版本不匹配")
    if (record["result"] != "BUILT_NOT_MAC_GUI_ACCEPTED" or
            record["desktop_v7_verified"] is not False):
        raise ValueError("不能将当前构建声明为尚未验证的 Mac/v7 验收通过")
    if (not isinstance(record["repo_commit"], str) or len(record["repo_commit"]) != 40 or
            any(char not in "0123456789abcdef" for char in record["repo_commit"])):
        raise ValueError("当前制品没有合法源码提交编号")
    if not _sha(record["index_html_sha256"]) or not _sha(record["overlay_manifest_sha256"]):
        raise ValueError("编译制品摘要无效")
    if (not isinstance(record["assets"], dict) or not record["assets"] or
            "index.html" not in record["assets"]):
        raise ValueError("编译资源目录清单缺失")
    output = root / "nanobot" / "nanobot" / "web" / "dist"
    if not output.is_dir() or output.is_symlink():
        raise ValueError("前端制品目录不存在或为符号链接")
    observed = {}
    for path in output.rglob("*"):
        if path.is_symlink():
            raise ValueError("前端制品包含不可核验的符号链接")
        if path.is_file():
            observed[path.relative_to(output).as_posix()] = digest(path)
    if observed != record["assets"] or observed.get("index.html") != record["index_html_sha256"]:
        raise ValueError("静态资源与准确构建摘要不一致，拒绝使用")
    if any(not _sha(value) for value in observed.values()):
        raise ValueError("存在非法资源摘要")
    overlay = root / "boss-build-manifest.json"
    native = root / "boss-native-patches.json"
    if (not overlay.is_file() or overlay.is_symlink() or
            digest(overlay) != record["overlay_manifest_sha256"] or
            not native.is_file() or native.is_symlink()):
        raise ValueError("第一方叠加源码或原生补丁来源记录不可核验")
    build = json.loads(overlay.read_text(encoding="utf-8"))
    patch = json.loads(native.read_text(encoding="utf-8"))
    if build.get("source_commit") != PINNED_UPSTREAM or patch.get("source_commit") != PINNED_UPSTREAM:
        raise ValueError("构建源码引用与固定 nanobot 版本不一致")
    if require_head:
        head = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip()
        if head != record["repo_commit"]:
            raise ValueError("当前源代码提交与编译制品不一致：应使用隔离工作树核验准确版本，禁止重置现有工作树")
        changed = subprocess.check_output(
            ["git", "status", "--porcelain=v1", "--untracked-files=no", "--",
             "app", "validation", "scripts", "specs",
             "Boss-Agent-Desktop-Complete-v6"], cwd=ROOT, text=True
        ).strip()
        if changed:
            raise ValueError("当前功能或设计源码存在未提交修改；不能冒充准确仓库版本，原文件不会被覆盖")
        module_hashes = build.get("overlay_sha256")
        if not isinstance(module_hashes, dict) or not module_hashes:
            raise ValueError("F01 编译清单没有第一方模块内容摘要")
        for name, expected in module_hashes.items():
            if (not isinstance(name, str) or "/" in name or name.startswith(".")
                    or not _sha(expected)):
                raise ValueError("第一方模块来源映射非法")
            file = ROOT / "app/webui" / name
            if not file.is_file() or file.is_symlink() or digest(file) != expected:
                raise ValueError("F01 当前第一方模块与制品声明不一致：" + name)
    return {
        "result": "VERIFIED_BUILD_NOT_GUI_ACCEPTANCE",
        "repo_commit": record["repo_commit"],
        "source_commit": PINNED_UPSTREAM,
        "file_count": len(observed),
        "index_sha256": observed["index.html"],
        "frontend_directory": str(output),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", type=Path, default=ROOT / ".work" / "product")
    parser.add_argument("--require-head", action="store_true")
    args = parser.parse_args()
    print(json.dumps(verify(args.bundle, require_head=args.require_head),
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
