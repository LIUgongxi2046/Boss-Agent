from pathlib import Path

import pytest

from desktop_manifest import validate_desktop_manifest


def test_desktop_resources_reject_missing_and_duplicate():
    root = Path(__file__).resolve().parents[2]
    entries = (root / "desktop-resources.txt").read_text(encoding="utf-8").splitlines()
    validate_desktop_manifest(entries)
    with pytest.raises(RuntimeError, match="桌面资源清单缺少必要输入"):
        validate_desktop_manifest(entries[:-1])
    with pytest.raises(RuntimeError, match="桌面资源清单包含重复项"):
        validate_desktop_manifest([*entries, entries[0]])
