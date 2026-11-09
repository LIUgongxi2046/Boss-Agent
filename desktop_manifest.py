DESKTOP_REQUIRED = {
    "validation/desktop/package.json", "validation/desktop/package-lock.json",
    "validation/desktop/package.mjs", "validation/desktop/package-output.cjs", "validation/desktop/main.cjs",
    "validation/desktop/preload.cjs", "validation/desktop/branding.cjs",
    "validation/desktop/branding/boss-agent.png", "validation/desktop/branding/boss-agent.icns",
}


def validate_desktop_manifest(entries):
    if len(entries) != len(set(entries)):
        raise RuntimeError("桌面资源清单包含重复项")
    if set(entries) != DESKTOP_REQUIRED:
        raise RuntimeError("桌面资源清单缺少必要输入或包含未允许内容")
