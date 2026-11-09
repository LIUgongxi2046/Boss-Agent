import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from urllib.parse import unquote, urlparse


EXPECTED = {
    "pyproject.toml": "8c9de0a63a81281a24c721f45051fe9fcf8e09ac6ea4ed4ac95e3b96f049b5e3",
    "uv.lock": "e6d08c634c3f9a252a896135a9c30324776fa343ce68432e88d22f2968f257e2",
    "run_agent.py": "da1fba4fb3cfd2153832087e904f8d47ac1a55e853e399cb7885f4bdf986e129",
    "tools/registry.py": "0dd8939f3e102679a8236ab688653a906f3914ce9921000df13ef7a9b240d36c",
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("python", type=Path)
    arguments = parser.parse_args()
    source = arguments.source.resolve(strict=True)
    python = arguments.python.absolute()
    if not python.is_file():
        raise ValueError("Hermes Python 不存在")
    for name, expected in EXPECTED.items():
        file = source / name
        if file.is_symlink() or not file.is_file():
            raise ValueError(f"Hermes 文件不是普通文件：{name}")
        if hashlib.sha256(file.read_bytes()).hexdigest() != expected:
            raise ValueError(f"Hermes 文件摘要不一致：{name}")
    result = subprocess.run(
        [str(python), "-c", "import importlib.metadata as m; print(m.distribution('hermes-agent').read_text('direct_url.json'))"],
        check=True, capture_output=True, text=True,
    )
    metadata = json.loads(result.stdout)
    location = urlparse(metadata["url"])
    if location.scheme != "file" or location.netloc or Path(unquote(location.path)).resolve() != source:
        raise ValueError("Hermes 环境指向其他源码目录")
    if metadata.get("dir_info", {}).get("editable") is not True:
        raise ValueError("Hermes 环境不是声明的 editable 安装")
    print("四个固定文件摘要和 editable 来源检查通过")
    print("此检查不覆盖其余源码、依赖兼容或运行隔离")


if __name__ == "__main__":
    main()
