import argparse
import hashlib
import json
import os
import stat
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("upstream", type=Path)
    parser.add_argument("dependencies", type=Path)
    arguments = parser.parse_args()
    upstream = arguments.upstream.resolve(strict=True)
    dependencies = arguments.dependencies.resolve(strict=True)
    roots = {
        "product": ROOT / "app/webui",
        "product_vite_config": ROOT / "app/frontend/vite.independent.config.mts",
        "product_tsconfig": ROOT / "app/frontend/tsconfig.independent.json",
        "product_package": ROOT / "app/frontend/package.json",
        "product_lock": ROOT / "app/frontend/package-lock.json",
        "specs": ROOT / "specs",
        "design_meta": ROOT / "Boss-Agent-Desktop-Complete-v7/meta",
        "design_assets": ROOT / "Boss-Agent-Desktop-Complete-v7/assets",
        "design_animation": ROOT / "Boss-Agent-Desktop-Complete-v7/animation",
        "sprite": ROOT / "design/T27/assets/boss-flight-sprite.png",
        "artifact_schema": ROOT / "validation/agent_artifact_schema.json",
        "upstream_webui": upstream / "webui",
        "upstream_channels": upstream / "nanobot/channels",
        "upstream_client_events": upstream / "packages/client-events",
        "dependency_package": dependencies / "package.json",
        "dependency_lock": dependencies / "package-lock.json",
        "dependency_modules": dependencies / "node_modules",
        "node": Path("/usr/local/bin/node").resolve(strict=True),
        "trace_config": ROOT / ".work/upgrade2/u2-01/frontend-trace.config.mts",
        "sandbox_profile": ROOT / ".work/upgrade2/u2-01/readonly-frontend-input.sb",
        "fingerprint_tool": Path(__file__).resolve(strict=True),
    }
    records = []

    def record(label, item):
        info = item.lstat()
        entry = {"path": label, "mode": stat.S_IMODE(info.st_mode)}
        if stat.S_ISLNK(info.st_mode):
            entry.update(kind="symlink", target=os.readlink(item))
        elif stat.S_ISREG(info.st_mode):
            entry.update(kind="file", sha256=hashlib.sha256(item.read_bytes()).hexdigest())
        elif stat.S_ISDIR(info.st_mode):
            entry.update(kind="directory")
        else:
            raise ValueError(f"构建输入类型不受支持：{label}")
        records.append(entry)

    for label, root in roots.items():
        record(label, root)
        if not root.is_dir() or root.is_symlink():
            continue
        for directory, dirs, files in os.walk(root, followlinks=False):
            dirs.sort()
            files.sort()
            base = Path(directory)
            for name in dirs + files:
                item = base / name
                record(f"{label}/{item.relative_to(root).as_posix()}", item)
    print(json.dumps(records, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
