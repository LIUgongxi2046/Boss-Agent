#!/usr/bin/env python3
"""Fail CI when secrets or live local credential files are accidentally tracked.

This scanner never prints a matched secret. It scans source/config/docs tracked
by Git only; ignored runtime files and the user's credential are never read.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BANNED_TRACKED = {
    "boss agent.md",
    "validation/connection.json",
    "validation/.env",
}
BANNED_PREFIXES = ("validation/.work/", ".work/",)
SECRET_PATTERNS = (
    re.compile(rb"\bsk-[A-Za-z0-9_-]{25,}\b"),
    re.compile(rb"(?i)DEEPSEEK_API_KEY\s*[:=]\s*['\"]sk-"),
)
PREFIXES_TO_SCAN = ("app/", "validation/", "scripts/", "docs/", ".github/")
ROOT_FILES = {".gitignore", "README.md", "delivery-ledger.json"}


def scan_tracked():
    raw = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT)
    paths = [part.decode("utf-8") for part in raw.split(b"\0") if part]
    failed = []
    for relative in paths:
        if relative in BANNED_TRACKED or relative.startswith(BANNED_PREFIXES):
            failed.append(relative + "（本机私密文件不允许入库）")
            continue
        if not (relative.startswith(PREFIXES_TO_SCAN) or relative in ROOT_FILES):
            continue
        if relative.startswith(("validation/uv.lock", "validation/desktop/package-lock.json")):
            continue
        path = ROOT / relative
        if not path.is_file() or path.stat().st_size > 2_000_000:
            continue
        data = path.read_bytes()
        if b"\x00" in data[:8192]:
            continue
        if any(pattern.search(data) for pattern in SECRET_PATTERNS):
            failed.append(relative + "（存在疑似密钥值）")
    return failed


def main():
    failed = scan_tracked()
    if failed:
        print("机密检查未通过，仅列出文件名（不会输出匹配文本）：", file=sys.stderr)
        for item in failed:
            print(" - " + item, file=sys.stderr)
        raise SystemExit(1)
    print("PASS: 当前 Git 跟踪文件无已识别的密钥格式或本地凭据路径。")


if __name__ == "__main__":
    main()
