"""F01 delivery artifact verification (isolated synthetic build fixtures only)."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from verify_f01_candidate import PINNED_UPSTREAM, verify  # noqa: E402


def digest(contents: bytes) -> str:
    return hashlib.sha256(contents).hexdigest()


@pytest.fixture
def candidate(tmp_path: Path) -> Path:
    dist = tmp_path / "nanobot/nanobot/web/dist"
    dist.mkdir(parents=True)
    (dist / "assets").mkdir()
    index, bundle = b"<html>F01</html>", b"const ui = 'F01';"
    (dist / "index.html").write_bytes(index)
    (dist / "assets/app.js").write_bytes(bundle)
    overlay = json.dumps({"source_commit": PINNED_UPSTREAM}, sort_keys=True).encode()
    (tmp_path / "boss-build-manifest.json").write_bytes(overlay)
    (tmp_path / "boss-native-patches.json").write_text(
        json.dumps({"source_commit": PINNED_UPSTREAM}), encoding="utf-8"
    )
    (tmp_path / "boss-compiled-build.json").write_text(json.dumps({
        "format": "BOSS_AGENT_DIST_SHA256_V1",
        "repo_commit": "0" * 40,
        "nanobot_commit": PINNED_UPSTREAM,
        "index_html_sha256": digest(index),
        "overlay_manifest_sha256": digest(overlay),
        "assets": {"index.html": digest(index), "assets/app.js": digest(bundle)},
        "result": "BUILT_NOT_MAC_GUI_ACCEPTED",
        "desktop_v7_verified": False,
    }), encoding="utf-8")
    return tmp_path


def test_exact_current_bundle_manifest_can_be_verified_without_authentication(candidate):
    output = verify(candidate)
    assert output["result"] == "VERIFIED_BUILD_NOT_GUI_ACCEPTANCE"
    assert output["file_count"] == 2
    assert output["repo_commit"] == "0" * 40


@pytest.mark.parametrize("path", [
    "nanobot/nanobot/web/dist/index.html",
    "nanobot/nanobot/web/dist/assets/app.js",
    "boss-build-manifest.json",
])
def test_mutated_asset_or_overlay_blocks_candidate(candidate, path):
    (candidate / path).write_text("CHANGED", encoding="utf-8")
    with pytest.raises(ValueError):
        verify(candidate)


def test_unlisted_or_deleted_file_blocks_candidate(candidate):
    other = candidate / "nanobot/nanobot/web/dist/assets/rogue.js"
    other.write_text("extra", encoding="utf-8")
    with pytest.raises(ValueError):
        verify(candidate)
    other.unlink()
    (candidate / "nanobot/nanobot/web/dist/assets/app.js").unlink()
    with pytest.raises(ValueError):
        verify(candidate)


def test_false_mac_or_v7_acceptance_is_rejected(candidate):
    record = candidate / "boss-compiled-build.json"
    data = json.loads(record.read_text())
    data["desktop_v7_verified"] = True
    record.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        verify(candidate)


def test_symlink_asset_and_patch_manifest_are_rejected(candidate):
    path = candidate / "nanobot/nanobot/web/dist/assets/app.js"
    path.unlink()
    path.symlink_to(candidate / "nanobot/nanobot/web/dist/index.html")
    with pytest.raises(ValueError):
        verify(candidate)
    path.unlink()
    path.write_bytes(b"const ui = 'F01';")
    native = candidate / "boss-native-patches.json"
    native.unlink()
    native.symlink_to(candidate / "boss-build-manifest.json")
    with pytest.raises(ValueError):
        verify(candidate)


def test_local_source_mismatch_blocks_claim_of_same_install(candidate):
    with pytest.raises(ValueError, match="当前源代码提交与编译制品不一致"):
        verify(candidate, require_head=True)
