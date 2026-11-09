from pathlib import Path

import pytest

from hermes_tool_registration import workspace_file_path


def test_workspace_file_paths_restrict_targets_and_allow_nested_creation(tmp_path):
    root = tmp_path / 'workspace'
    root.mkdir()
    saved = root / 'note.txt'
    saved.write_text('工作区内容', encoding='utf-8')
    assert workspace_file_path(root, 'note.txt', writing=False) == saved
    assert workspace_file_path(root, 'nested/new.txt', writing=True) == root / 'nested/new.txt'
    outside = tmp_path / 'outside.txt'
    outside.write_text('其他目录内容', encoding='utf-8')
    (root / 'link').symlink_to(outside)
    (root / 'linked-directory').symlink_to(tmp_path, target_is_directory=True)
    for value in ('../outside.txt', str(outside), 'link', 'linked-directory/outside.txt'):
        with pytest.raises(ValueError):
            workspace_file_path(root, value, writing=False)
    with pytest.raises(ValueError):
        workspace_file_path(root, 'linked-directory/new.txt', writing=True)
    assert outside.read_text(encoding='utf-8') == '其他目录内容'
