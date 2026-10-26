from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path
import yaml
from boss_auth_overlay import apply_auth_overlay
from boss_native_overlay import apply_native_overlay

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM_REV = "1bb712d3488915ca4ed9ccc1a93067ff722f5ab9"
UPSTREAM_URL = "https://github.com/HKUDS/nanobot.git"
SOURCE = ROOT / ".work" / "product" / "nanobot"
DESIGN = ROOT / "Boss-Agent-Desktop-Complete-v7"
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
        raise RuntimeError("561 个设计状态索引缺失，拒绝构建。")
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
    for dependency_file in ("package.json", "package-lock.json"):
        shutil.copy2(ROOT / "app" / "frontend" / dependency_file, SOURCE_WEBUI / dependency_file)
    for source_name, target_name in [
        ("BossDesktop.tsx", "BossDesktop.tsx"),
        ("BossMenuNavigation.tsx", "BossMenuNavigation.tsx"),
        ("boss-history.ts", "boss-history.ts"),
        ("boss-route.ts", "boss-route.ts"),
        ("BossLogin.tsx", "BossLogin.tsx"),
        ("BossToday.tsx", "BossToday.tsx"),
        ("BossOwnerPlans.tsx", "BossOwnerPlans.tsx"),
        ("BossAssignmentFlow.tsx", "BossAssignmentFlow.tsx"),
        ("BossWorkspaceView.tsx", "BossWorkspaceView.tsx"),
        ("BossSectorView.tsx", "BossSectorView.tsx"),
        ("BossAssignmentPicker.tsx", "BossAssignmentPicker.tsx"),
        ("BossVoiceAssignment.tsx", "BossVoiceAssignment.tsx"),
        ("BossMeetingApproval.tsx", "BossMeetingApproval.tsx"),
        ("BossMinutesAssignmentActions.tsx", "BossMinutesAssignmentActions.tsx"),
        ("BossMeetingBrief.tsx", "BossMeetingBrief.tsx"),
        ("BossMeetingArrangement.tsx", "BossMeetingArrangement.tsx"),
        ("BossTravelView.tsx", "BossTravelView.tsx"),
        ("BossPeopleMeeting.tsx", "BossPeopleMeeting.tsx"),
        ("BossOwnerPreferences.tsx", "BossOwnerPreferences.tsx"),
        ("BossSettingsHub.tsx", "BossSettingsHub.tsx"),
        ("BossTaskCenter.tsx", "BossTaskCenter.tsx"),
        ("BossPersonalCommitments.tsx", "BossPersonalCommitments.tsx"),
        ("MaintainerPromptVersion.tsx", "MaintainerPromptVersion.tsx"),
        ("BossResearchView.tsx", "BossResearchView.tsx"),
        ("MaintainerRuntimeRecords.tsx", "MaintainerRuntimeRecords.tsx"),
        ("RuntimeTaskTechnicalView.tsx", "RuntimeTaskTechnicalView.tsx"),
        ("ProductRuntimeConfiguration.tsx", "ProductRuntimeConfiguration.tsx"),
        ("MaintainerMemoryStatus.tsx", "MaintainerMemoryStatus.tsx"),
        ("MaintainerSkills.tsx", "MaintainerSkills.tsx"),
        ("MaintainerSkillVersions.tsx", "MaintainerSkillVersions.tsx"),
        ("MaintainerSimulationInspect.tsx", "MaintainerSimulationInspect.tsx"),
        ("BossAssignmentSourceReview.tsx", "BossAssignmentSourceReview.tsx"),
        ("BossSupplyQualityPanel.tsx", "BossSupplyQualityPanel.tsx"),
        ("BossSupplyQualityView.tsx", "BossSupplyQualityView.tsx"),
        ("MaintainerSupplyQuality.tsx", "MaintainerSupplyQuality.tsx"),
        ("BossCommunicationCalendar.tsx", "BossCommunicationCalendar.tsx"),
        ("MaintainerMessageReply.tsx", "MaintainerMessageReply.tsx"),
        ("MaintainerKnowledgeEditor.tsx", "MaintainerKnowledgeEditor.tsx"),
        ("MaintainerScheduler.tsx", "MaintainerScheduler.tsx"),
        ("boss-v6.css", "boss-v6.css"),
        ("boss-login.css", "boss-login.css"),
    ]:
        shutil.copy2(ROOT / "app" / "webui" / source_name, BOSS_DIR / target_name)
    # The baseline list predates N02/N03 and the shared navigation components.
    # Carry every checked-in first-party module into the pinned upstream build;
    # .patch files are instructions, not importable runtime modules.
    source_modules = sorted(
        module for module in (ROOT / "app" / "webui").iterdir()
        if module.is_file() and module.suffix in {".tsx", ".ts", ".css", ".json"}
    )
    for module in source_modules:
        shutil.copy2(module, BOSS_DIR / module.name)
    (BOSS_DIR / "page-meta.json").write_text(
        json.dumps(catalogue, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    # The source module lives in app/webui, while the installed module lives
    # in the isolated nanobot/boss-agent directory. Rebase only this known
    # design-metadata import onto the exact 72-page generated JSON.
    navigation = BOSS_DIR / "delivered-navigation.ts"
    navigation_source = navigation.read_text(encoding="utf-8")
    original_meta_import = "../../Boss-Agent-Desktop-Complete-v7/meta/页面配置.json"
    if navigation_source.count(original_meta_import) != 1:
        raise RuntimeError("经营导航源码与已审核的72页设计引用不匹配，拒绝自动改写")
    navigation.write_text(
        navigation_source.replace(original_meta_import, "./page-meta.json", 1),
        encoding="utf-8",
    )
    shutil.copy2(ROOT / "specs/simulation-query.schema.json", BOSS_DIR / "simulation-query.schema.json")
    (BOSS_DIR / "supply-quality-v1.json").write_text(
        json.dumps(yaml.safe_load((ROOT / "data/simulation/supply-quality-v1.yaml").read_text()), ensure_ascii=False) + "\n", encoding="utf-8",
    )
    for filename in ASSETS:
        shutil.copy2(DESIGN / "assets" / filename, ASSET_DIR / filename)
    for filename in ANIMATIONS:
        shutil.copy2(DESIGN / "animation" / filename, ASSET_DIR / filename)
    shutil.copy2(ROOT / "design/T27/assets/boss-flight-sprite.png", ASSET_DIR / "boss-flight-sprite.png")

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
    patched = apply_auth_overlay(patched, one_replace)
    native_manifest = apply_native_overlay(ROOT, SOURCE, patched, original)

    manifest = {
        "upstream": "HKUDS/nanobot",
        "source_commit": UPSTREAM_REV,
        "design_page_count": 72,
        "design_state_links": 561,
        "overlay": [f"app/webui/{module.name}" for module in source_modules],
        "overlay_sha256": {module.name: hashlib.sha256(module.read_bytes()).hexdigest() for module in source_modules},
        "design_meta_sha256": hashlib.sha256(meta_file.read_bytes()).hexdigest(),
        "frontend_dependencies_sha256": {
            name: hashlib.sha256((ROOT / "app" / "frontend" / name).read_bytes()).hexdigest()
            for name in ("package.json", "package-lock.json")
        },
        "source_modified": "pinned native WebUI overlay (working tree only)",
        "native_patches_manifest_sha256": hashlib.sha256(
            (ROOT / ".work" / "product" / "boss-native-patches.json").read_bytes()
        ).hexdigest(),
        "native_hunks_applied": native_manifest["hunks_applied"],
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
        subprocess.run(["npm", "ci", "--no-audit", "--no-fund", "--cache", str(ROOT / ".work" / "npm-cache")], cwd=SOURCE_WEBUI, check=True)
        subprocess.run(["npm", "run", "build"], cwd=SOURCE_WEBUI, check=True)
        dist = SOURCE / "nanobot" / "web" / "dist" / "index.html"
        if not dist.exists():
            raise RuntimeError("上游构建成功但未发现正式 dist/index.html")
        # The previous overlay manifest identifies the first-party source, but
        # not the resulting deployed bundle. Record an explicit content digest
        # only after a clean real Vite build, never during prepare-only calls.
        dist_root = dist.parent
        files = sorted(path for path in dist_root.rglob("*") if path.is_file())
        if not files:
            raise RuntimeError("正式前端编译结果为空，拒绝建立可交付指针")
        source_manifest = ROOT / ".work" / "product" / "boss-build-manifest.json"
        product = {
            "format": "BOSS_AGENT_DIST_SHA256_V1",
            "repo_commit": run("git", "rev-parse", "HEAD", cwd=ROOT),
            "nanobot_commit": UPSTREAM_REV,
            "index_html_sha256": hashlib.sha256(dist.read_bytes()).hexdigest(),
            "overlay_manifest_sha256": hashlib.sha256(source_manifest.read_bytes()).hexdigest(),
            "assets": {
                str(path.relative_to(dist_root)): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in files
            },
            "result": "BUILT_NOT_MAC_GUI_ACCEPTED",
            "desktop_v7_verified": False,
        }
        record = ROOT / ".work" / "product" / "boss-compiled-build.json"
        record.write_text(
            json.dumps(product, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print("构建完成：" + str(dist))
        print("制品校验：" + str(record))


if __name__ == "__main__":
    main()
