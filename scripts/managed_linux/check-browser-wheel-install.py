import argparse
import hashlib
import zipfile
from pathlib import Path, PurePosixPath


parser = argparse.ArgumentParser()
parser.add_argument("wheel", type=Path)
parser.add_argument("target", type=Path)
arguments = parser.parse_args()
target = arguments.target.resolve(strict=True)
wheel_hash = hashlib.sha256(arguments.wheel.read_bytes()).hexdigest()
expected = "5bdfdba0941698345166fe21a107d3ab2521c6817aa461f6ba3c0ea325b845cb"
if wheel_hash != expected:
    raise ValueError("browser-harness 本地修订 wheel 摘要不一致")

checked = 0
with zipfile.ZipFile(arguments.wheel) as wheel:
    names = wheel.namelist()
    if len(names) != len(set(names)):
        raise ValueError("wheel 包含重复路径")
    for item in wheel.infolist():
        path = PurePosixPath(item.filename)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("wheel 路径无效")
        if item.is_dir() or item.filename.endswith(".dist-info/RECORD"):
            continue
        installed = target.joinpath(*path.parts)
        if installed.is_symlink() or not installed.is_file() or installed.read_bytes() != wheel.read(item):
            raise ValueError("安装内容与 wheel 不一致：" + item.filename)
        checked += 1
print("WHEEL_SHA256", wheel_hash)
print("INSTALLED_TARGET", target)
print("MATCHED_FILES", checked)
print("RECORD_EXCLUDED", "installer updates file")
