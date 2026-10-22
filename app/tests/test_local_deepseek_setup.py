"""Local-secret onboarding tests. Only test fixtures, never actual user keys."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "configure_local_deepseek.py"
spec = importlib.util.spec_from_file_location("boss_configure_local_deepseek", SCRIPT)
assert spec and spec.loader
script = importlib.util.module_from_spec(spec)
spec.loader.exec_module(script)

DUMMY = "sk-" + "x" * 40  # Synthetic test-only token, never a real credential.


@pytest.fixture
def project(tmp_path):
    (tmp_path / "validation").mkdir()
    (tmp_path / ".gitignore").write_text(
        "boss agent.md\nvalidation/connection.json\n", encoding="utf-8"
    )
    return tmp_path


def test_single_markdown_key_creates_private_untracked_files(project, capsys):
    upload = project.parent / "uploaded-user-file.md"
    upload.write_text("DeepSeek - key：" + DUMMY + "\n", encoding="utf-8")
    report = script.configure(project, upload)
    assert report["api_request_sent"] == "NO"
    assert report["credential"] == "LOCAL_FILE_ONLY"
    assert report["connection"] == "PRIVATE_REFERENCE_ONLY"
    secret = project / "boss agent.md"
    config = project / "validation" / "connection.json"
    assert secret.exists() and config.exists()
    assert DUMMY in secret.read_text()
    assert DUMMY not in config.read_text()
    assert secret.stat().st_mode & 0o077 == 0
    assert config.stat().st_mode & 0o077 == 0
    assert DUMMY not in capsys.readouterr().out


def test_multiple_or_missing_tokens_are_rejected(project):
    upload = project.parent / "multiple-tokens.md"
    upload.write_text(DUMMY + "\n" + "sk-" + "y" * 40)
    with pytest.raises(script.CredentialConfigurationError):
        script.configure(project, upload)
    assert not (project / "boss agent.md").exists()
    upload.write_text("No token here")
    with pytest.raises(script.CredentialConfigurationError):
        script.configure(project, upload)


def test_symlink_source_and_target_are_rejected(project):
    upload = project.parent / "source.md"
    upload.write_text(DUMMY)
    link = project.parent / "source-link.md"
    link.symlink_to(upload)
    with pytest.raises(script.CredentialConfigurationError):
        script.configure(project, link)
    (project / "boss agent.md").symlink_to(upload)
    with pytest.raises(script.CredentialConfigurationError):
        script.configure(project, upload)


def test_different_existing_secret_requires_explicit_rotation(project):
    upload = project.parent / "old.md"
    upload.write_text(DUMMY)
    script.configure(project, upload)
    new_file = project.parent / "new.md"
    replacement = "sk-" + "z" * 40
    new_file.write_text(replacement)
    with pytest.raises(script.CredentialConfigurationError):
        script.configure(project, new_file)
    assert DUMMY in (project / "boss agent.md").read_text()
    report = script.configure(project, new_file, replace=True)
    assert report["api_request_sent"] == "NO"
    assert replacement in (project / "boss agent.md").read_text()
    assert (project / "boss agent.md").stat().st_mode & 0o077 == 0


def test_connection_config_fails_closed_on_unapproved_model(project):
    upload = project.parent / "user.md"
    upload.write_text(DUMMY)
    script.configure(project, upload)
    path = project / "validation" / "connection.json"
    config = json.loads(path.read_text())
    config["provider"] = "other"
    path.write_text(json.dumps(config))
    with pytest.raises(script.CredentialConfigurationError):
        script.configure(project, upload)


def test_local_secret_paths_are_gitignored_in_real_repo():
    gitignore = (ROOT / ".gitignore").read_text()
    for path in ("boss agent.md", "validation/connection.json", "validation/.work/", ".work/"):
        assert path in gitignore.splitlines()
    assert "DEEPSEEK_API_KEY" not in (
        ROOT / "validation" / "connection.example.json"
    ).read_text()
