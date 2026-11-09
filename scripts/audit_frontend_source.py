import argparse
import subprocess
from pathlib import Path


UPSTREAM_REVISION = "1bb712d3488915ca4ed9ccc1a93067ff722f5ab9"
UPSTREAM_WEBUI_TREE = "bb1aa81aa1a85533010e8201a8376615be8cc437"
UPSTREAM_CHANNELS_TREE = "6569cc8cd4f0065eaebe7c9b1b3b94f703294e75"
UPSTREAM_CLIENT_EVENTS_TREE = "c71921224c7b72ee0179699391aba476e587156c"
ROOT = Path(__file__).resolve().parents[1]


def git(source, *arguments):
    return subprocess.run(
        ["git", "-C", str(source), *arguments],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    args = parser.parse_args()
    source = args.source.resolve(strict=True)
    if Path(git(source, "rev-parse", "--show-toplevel")).resolve() != source:
        raise ValueError("上游源码目录不是 Git 仓库根目录")
    revision = git(source, "rev-parse", "HEAD")
    if revision != UPSTREAM_REVISION:
        raise ValueError("上游源码提交与固定版本不一致")
    tree = git(source, "rev-parse", "HEAD:webui")
    if tree != UPSTREAM_WEBUI_TREE:
        raise ValueError("上游 WebUI tree 与固定版本不一致")
    channels = git(source, "rev-parse", "HEAD:nanobot/channels")
    if channels != UPSTREAM_CHANNELS_TREE:
        raise ValueError("上游渠道 tree 与固定版本不一致")
    client_events = git(source, "rev-parse", "HEAD:packages/client-events")
    if client_events != UPSTREAM_CLIENT_EVENTS_TREE:
        raise ValueError("上游客户端事件 tree 与固定版本不一致")
    changes = git(source, "status", "--porcelain", "--untracked-files=all", "--", "webui", "nanobot/channels", "packages/client-events", "LICENSE")
    if changes:
        raise ValueError("上游前端输入存在未提交内容")
    manifest = ROOT / "frontend-build-resources.txt"
    if manifest.is_symlink() or not manifest.is_file():
        raise ValueError("前端构建资源清单必须是普通文件")
    entries = manifest.read_text(encoding="utf-8").splitlines()
    patches = [ROOT / name for name in entries if name.startswith("app/frontend/upstream-") and name.endswith(".patch")]
    if len(patches) != 11 or len(set(patches)) != 11 or any(path.is_symlink() or not path.is_file() for path in patches):
        raise ValueError("前端集成补丁清单无效")
    git(source, "apply", "--cached", "--check", *(str(path) for path in patches))
    print(f"上游提交: {revision}")
    print(f"WebUI tree: {tree}")
    print(f"渠道 tree: {channels}")
    print(f"客户端事件 tree: {client_events}")
    print("前端集成补丁对固定 index 的适用性检查通过")
    print("上游前端输入没有未提交的已跟踪或未忽略文件")


if __name__ == "__main__":
    main()
