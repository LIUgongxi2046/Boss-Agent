#!/usr/bin/env python3
"""Reproducibly overlay Boss-Agent Desktop v6 React onto fixed nanobot WebUI.

This modifies *only* a private .work/product checkout, never upstream GitHub,
and never embeds the original static 72 HTML pages as if they were a product.
A local network connection is required for first-time upstream checkout/npm ci.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM_REV = "1bb712d3488915ca4ed9ccc1a93067ff722f5ab9"
UPSTREAM_URL = "https://github.com/HKUDS/nanobot.git"
SOURCE = ROOT / ".work" / "product" / "nanobot"
DESIGN = ROOT / "Boss-Agent-Desktop-Complete-v6"
SOURCE_WEBUI = SOURCE / "webui"
SRC = SOURCE_WEBUI / "src"
BOSS_DIR = SRC / "boss-agent"
ASSET_DIR = SOURCE_WEBUI / "public" / "boss-brand"
ANIMATIONS = [
    "01-待机悬浮.webp", "02-语音倾听.webp",
    "03-思考分析.webp", "04-执行推进.webp",
    "05-完成确认.webp", "06-通知提醒.webp",
]
ASSETS = [
    "boss-logo-from-reference.png", "dapeng-front.png",
    "dapeng-side.png", "dapeng-think.png", "dapeng-execute.png",
]


def run(*args: str, cwd: Path | None = None) -> str:
    result = subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True)
    return result.stdout.strip()


def one_replace(contents: str, source: str, replacement: str, label: str) -> str:
    count = contents.count(source)
    if count != 1:
        raise RuntimeError(f"上游 {label} 不符：预期 1，实际 {count}。固定源码已变更，不能强制补丁。")
    return contents.replace(source, replacement, 1)


def ensure_source() -> None:
    if not SOURCE.exists():
        SOURCE.parent.mkdir(parents=True, exist_ok=True)
        print("正在获取固定 nanobot v0.3.5 源码…")
        run("git", "clone", "--filter=blob:none", "--no-checkout", UPSTREAM_URL, str(SOURCE))
        run("git", "checkout", "--detach", UPSTREAM_REV, cwd=SOURCE)
    if not (SOURCE / ".git").exists():
        raise RuntimeError("目标路径存在，但不是 Git 仓库；已拒绝覆盖。")
    remote = run("git", "remote", "get-url", "origin", cwd=SOURCE)
    if not (remote.rstrip("/").endswith("HKUDS/nanobot.git") or
            remote.rstrip("/").endswith("HKUDS/nanobot")):
        raise RuntimeError("来源仓库与已锁定的 HKUDS/nanobot 不符。")
    revision = run("git", "rev-parse", "HEAD", cwd=SOURCE)
    if revision != UPSTREAM_REV:
        raise RuntimeError(f"上游 commit 不符：{revision}。请移开旧 checkout 后重新生成。")


def copy_overlay() -> None:
    meta_file = DESIGN / "meta" / "页面配置.json"
    catalogue = json.loads(meta_file.read_text(encoding="utf-8"))
    if len(catalogue) != 72 or len(set(catalogue)) != 72:
        raise RuntimeError("设计页面不是精确的 72 项，拒绝生成 UI。")
    missing = [k for k in catalogue if not (DESIGN / "pages" / f"{k}-{catalogue[k]['title']}.html").exists()]
    if missing:
        raise RuntimeError(f"设计源缺页：{missing}")
    states = json.loads((DESIGN / "meta" / "v6-状态关联.json").read_text(encoding="utf-8"))
    if len(states) != 561:
        raise RuntimeError("561 个 v6 状态索引缺失，拒绝构建。")
    mapping = json.loads((ROOT / "specs" / "hld-72-page-map.json").read_text(encoding="utf-8"))
    mapped = {row["page_id"]: row for row in mapping["pages"]}
    if set(mapped) != set(catalogue):
        raise RuntimeError("架构72页映射与设计源不一致，拒绝构建。")
    for page_id, metadata in catalogue.items():
        item = mapped[page_id]
        if item["title"] != metadata["title"] or not item["upstream_reuse_anchor_ids"]:
            raise RuntimeError(f"设计到开源复用锚点失配：{page_id}")
    indexed = {row["page_id"] for row in states}
    if len(indexed) != 51 or len(set(catalogue) - indexed) != 21:
        raise RuntimeError("F/A/V 状态页与 N/D 通用状态继承数量不一致。")

    BOSS_DIR.mkdir(parents=True, exist_ok=True)
    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    for source_name, target_name in [
        ("BossDesktop.tsx", "BossDesktop.tsx"),
        ("BossAssignmentFlow.tsx", "BossAssignmentFlow.tsx"),
        ("BossWorkspaceView.tsx", "BossWorkspaceView.tsx"),
        ("BossSectorView.tsx", "BossSectorView.tsx"),
        ("BossAssignmentPicker.tsx", "BossAssignmentPicker.tsx"),
        ("BossVoiceAssignment.tsx", "BossVoiceAssignment.tsx"),
        ("BossMeetingApproval.tsx", "BossMeetingApproval.tsx"),
        ("BossMinutesAssignmentActions.tsx", "BossMinutesAssignmentActions.tsx"),
        ("BossMeetingBrief.tsx", "BossMeetingBrief.tsx"),
        ("BossTaskCenter.tsx", "BossTaskCenter.tsx"),
        ("BossPersonalCommitments.tsx", "BossPersonalCommitments.tsx"),
        ("MaintainerPromptVersion.tsx", "MaintainerPromptVersion.tsx"),
        ("BossResearchView.tsx", "BossResearchView.tsx"),
        ("BossCommunicationCalendar.tsx", "BossCommunicationCalendar.tsx"),
        ("MaintainerMessageReply.tsx", "MaintainerMessageReply.tsx"),
        ("MaintainerKnowledgeEditor.tsx", "MaintainerKnowledgeEditor.tsx"),
        ("MaintainerScheduler.tsx", "MaintainerScheduler.tsx"),
        ("boss-v6.css", "boss-v6.css"),
    ]:
        shutil.copy2(ROOT / "app" / "webui" / source_name, BOSS_DIR / target_name)
    (BOSS_DIR / "page-meta.json").write_text(
        json.dumps(catalogue, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    for filename in ASSETS:
        shutil.copy2(DESIGN / "assets" / filename, ASSET_DIR / filename)
    for filename in ANIMATIONS:
        shutil.copy2(DESIGN / "animation" / filename, ASSET_DIR / filename)

    # Read the pristine pinned source from Git every time for idempotence.
    original = subprocess.run(
        ["git", "show", "HEAD:webui/src/App.tsx"], cwd=SOURCE,
        check=True, capture_output=True, text=True,
    ).stdout
    patched = one_replace(
        original,
        'import { ThemeProvider, useTheme } from "@/hooks/useTheme";',
        'import { ThemeProvider, useTheme } from "@/hooks/useTheme";\n'
        'import { BossDesktop } from "./boss-agent/BossDesktop";',
        "ThemeProvider import",
    )
    patched = one_replace(
        patched,
        '    <ThemeProvider theme={theme}>\n      <div\n',
        '    <ThemeProvider theme={theme}>\n'
        '      <BossDesktop getToken={getToken} onLogout={onLogout} onStartChat={onStartAutomationChat}>\n'
        '      <div\n',
        "authenticated Shell boundary",
    )
    patched = one_replace(
        patched,
        '      </div>\n    </ThemeProvider>\n  );\n}\n',
        '      </div>\n      </BossDesktop>\n    </ThemeProvider>\n  );\n}\n',
        "closing Shell boundary",
    )
    app_file = SRC / "App.tsx"
    existing = app_file.read_text(encoding="utf-8")
    if existing != original and existing != patched:
        raise RuntimeError("上游 App.tsx 存在非本工具改动；已拒绝覆盖。")
    app_file.write_text(patched, encoding="utf-8")

    manifest = {
        "upstream": "HKUDS/nanobot",
        "source_commit": UPSTREAM_REV,
        "design_page_count": 72,
        "design_state_links": 561,
        "overlay": ["app/webui/BossDesktop.tsx", "app/webui/boss-v6.css"],
        "design_meta_sha256": hashlib.sha256(meta_file.read_bytes()).hexdigest(),
        "source_modified": "webui/src/App.tsx (working tree only)",
    }
    manifest_path = ROOT / ".work" / "product" / "boss-build-manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("桌面 React overlay 已准备，72 页路由元数据和大鹏素材完整。")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--build", action="store_true", help="执行 npm ci + npm run build，要求可联网安装上游依赖")
    args = parser.parse_args()
    ensure_source()
    copy_overlay()
    if args.build:
        print("准备上游锁定前端依赖并编译…")
        subprocess.run(["npm", "ci"], cwd=SOURCE_WEBUI, check=True)
        subprocess.run(["npm", "run", "build"], cwd=SOURCE_WEBUI, check=True)
        dist = SOURCE / "nanobot" / "web" / "dist" / "index.html"
        if not dist.exists():
            raise RuntimeError("上游构建成功但未发现正式 dist/index.html")
        print("构建完成：" + str(dist))


if __name__ == "__main__":
    main()
