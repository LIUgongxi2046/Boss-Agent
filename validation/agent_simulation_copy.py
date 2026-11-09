import hashlib
import os
import sqlite3
from contextlib import closing
from pathlib import Path
from uuid import uuid4

from agent_simulation_snapshot import SIMULATION_ROOT


def publish_simulation_copy(source, directory, *, expected_sha256=None):
    if not isinstance(source, sqlite3.Connection):
        raise ValueError("需要独立模拟数据库连接")
    main = source.execute("PRAGMA database_list").fetchone()
    root = SIMULATION_ROOT.resolve()
    destination = Path(directory).resolve()
    if main is None or main[1] != "main" or not Path(main[2]).resolve().is_relative_to(root) or Path(main[2]).name != "business.sqlite" or not destination.is_relative_to(root) or not destination.is_dir():
        raise ValueError("仅允许独立模拟数据库和目录")
    final = destination / "published.sqlite"
    sidecars = [Path(str(final) + suffix) for suffix in ("-wal", "-shm", "-journal")]
    if final.is_symlink() or any(item.exists() for item in sidecars):
        raise ValueError("模拟目标文件不可核查")
    if final.exists():
        if not final.is_file() or not isinstance(expected_sha256, str) or len(expected_sha256) != 64:
            raise ValueError("模拟目标已经存在")
        with final.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        if digest != expected_sha256:
            raise ValueError("模拟目标摘要不符")
        return {"sha256": digest, "created": False}
    if expected_sha256 is not None:
        raise ValueError("原模拟目标缺少")
    stage = destination / (".copy-" + uuid4().hex + ".sqlite")
    stage.touch(exist_ok=False, mode=0o600)
    try:
        with closing(sqlite3.connect(stage)) as target:
            source.backup(target)
            if target.execute("PRAGMA journal_mode=DELETE").fetchone() != ("delete",):
                raise ValueError("模拟副本日志状态不可核查")
            if target.execute("PRAGMA integrity_check").fetchone() != ("ok",) or target.execute("PRAGMA foreign_key_check").fetchall():
                raise ValueError("模拟副本完整性不可核查")
        with stage.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
            os.fsync(stream.fileno())
        os.link(stage, final, follow_symlinks=False)
        return {"sha256": digest, "created": True}
    finally:
        stage.unlink()
