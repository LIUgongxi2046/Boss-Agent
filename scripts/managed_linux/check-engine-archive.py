import argparse
import hashlib
import os
import tarfile
from pathlib import Path, PurePosixPath


parser = argparse.ArgumentParser()
parser.add_argument("archive", type=Path)
parser.add_argument("source", type=Path)
arguments = parser.parse_args()
source = arguments.source.resolve(strict=True)
if not source.is_dir():
    raise ValueError("Hermes 源码目录不可核查")

expected = set()
differences = []
with tarfile.open(arguments.archive, "r:gz") as archive:
    root = None
    for member in archive:
        parts = PurePosixPath(member.name).parts
        if not parts or any(part in (".", "..", "/") for part in parts):
            raise ValueError("源码归档路径无效")
        if root is None:
            root = parts[0]
        if parts[0] != root:
            raise ValueError("源码归档包含多个根目录")
        relative = PurePosixPath(*parts[1:])
        if relative == PurePosixPath("."):
            continue
        name = relative.as_posix()
        if name in expected:
            raise ValueError("源码归档包含重复路径")
        expected.add(name)
        target = source.joinpath(*relative.parts)
        if member.isdir():
            matches = target.is_dir() and not target.is_symlink()
        elif member.issym():
            matches = target.is_symlink() and os.readlink(target) == member.linkname
        elif member.isfile():
            matches = target.is_file() and not target.is_symlink()
            if matches:
                with archive.extractfile(member) as archived, target.open("rb") as current:
                    matches = hashlib.file_digest(archived, "sha256").digest() == hashlib.file_digest(current, "sha256").digest()
        else:
            raise ValueError("源码归档包含无法核查的文件类型")
        if not matches:
            differences.append(name)

actual = set()
for directory, directories, files in os.walk(source, followlinks=False):
    parent = Path(directory)
    actual.update((parent / name).relative_to(source).as_posix() for name in directories + files)
extra = sorted(actual - expected)
print("ARCHIVE_PATHS", len(expected))
print("DIFFERENT_PATHS", len(differences))
print("EXTRA_PATHS", len(extra))
for name in differences[:20]:
    print("DIFFERENT", name)
for name in extra[:20]:
    print("EXTRA", name)
if differences or extra:
    raise SystemExit(1)
