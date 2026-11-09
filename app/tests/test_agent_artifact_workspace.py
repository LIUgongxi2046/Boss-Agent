import os
from uuid import uuid4

import pytest

from agent_artifact_workspace import ArtifactWorkspace


def test_workspace_creation_and_reopen(tmp_path):
    mapping = ArtifactWorkspace(tmp_path.resolve())
    first, second = str(uuid4()), str(uuid4())
    first_path = mapping.create(first)
    second_path = mapping.create(second)
    assert first_path != second_path
    assert mapping.open(first) == first_path
    assert first_path.stat().st_mode & 0o777 == 0o700
    with pytest.raises(FileExistsError):
        mapping.create(first)
    with pytest.raises(RuntimeError):
        mapping.restore(first)


def test_workspace_rejects_links_and_changed_root(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    mapping = ArtifactWorkspace(root.resolve())
    run_id = str(uuid4())
    os.symlink(tmp_path, root / run_id)
    with pytest.raises(ValueError):
        mapping.open(run_id)
    root.rename(tmp_path / "old")
    root.mkdir()
    with pytest.raises(ValueError):
        mapping.create(str(uuid4()))
    with pytest.raises(ValueError):
        mapping.open("../other")
