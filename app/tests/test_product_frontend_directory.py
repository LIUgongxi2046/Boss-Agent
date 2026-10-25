import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "validation"))
from application_paths import application_frontend_directory


def test_independent_build_preserves_default_frontend(tmp_path):
    root = tmp_path / "project" / "validation"
    default = root.parent / ".work/product/nanobot/nanobot/web/dist"
    default.mkdir(parents=True)
    (default / "index.html").write_text("default")
    candidate = root.parent / "fc01-dist"
    candidate.mkdir()
    (candidate / "index.html").write_text("candidate")
    assert application_frontend_directory(root) == default
    assert application_frontend_directory(root, str(candidate)) == candidate
    assert (default / "index.html").read_text() == "default"


def test_frontend_directory_rejects_missing_or_external_build(tmp_path):
    root = tmp_path / "project" / "validation"
    with pytest.raises(ValueError):
        application_frontend_directory(root, "relative")
    with pytest.raises(ValueError):
        application_frontend_directory(root, str(tmp_path / "external"))
    with pytest.raises(FileNotFoundError):
        application_frontend_directory(root, str(root.parent / "missing"))
