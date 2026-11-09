import argparse
import sys
from pathlib import Path

from hermes_bridge import EngineProcessConfig, EngineRunConfig


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("archive", type=Path)
    parser.add_argument("profile", type=Path)
    args = parser.parse_args()
    root = args.root.resolve(strict=True)
    executable = Path(sys.executable).resolve(strict=True)
    run = EngineRunConfig("inventory-check", 1, "903230b1e23e0c496b28e5d2e8c4f2639cd506b6", "http://127.0.0.1:1234", 1)
    config = EngineProcessConfig(run, root / "engine", args.archive, executable.parent, executable,
                                 root, root / "work", args.profile, 1, 1, 1, 1, 1, 1, 1024, 16, 1)
    config.validate()
    print("SOURCE_INVENTORY_VERIFIED")


if __name__ == "__main__":
    main()
