import os
from uuid import uuid4

import pytest

from hermes_guest_workspace_directory import prepare_private_workspace


def test_private_workspace_preserves_existing_content_and_rejects_links(tmp_path):
    tmp_path.chmod(0o700)
    run_id = str(uuid4())
    workspace = prepare_private_workspace(tmp_path.resolve(), run_id, os.getuid(), os.getgid())
    assert workspace == tmp_path / run_id
    assert (workspace / ".temporary").is_dir()
    item = workspace / "record.txt"
    item.write_text("运行记录", encoding="utf-8")
    assert prepare_private_workspace(tmp_path.resolve(), run_id, os.getuid(), os.getgid()) == workspace
    assert item.read_text(encoding="utf-8") == "运行记录"
    other_id = str(uuid4())
    (tmp_path / other_id).symlink_to(workspace, target_is_directory=True)
    with pytest.raises(OSError):
        prepare_private_workspace(tmp_path.resolve(), other_id, os.getuid(), os.getgid())


def test_private_workspace_requires_private_root(tmp_path):
    tmp_path.chmod(0o755)
    with pytest.raises(ValueError, match="根目录权限无效"):
        prepare_private_workspace(tmp_path.resolve(), str(uuid4()), os.getuid(), os.getgid())
