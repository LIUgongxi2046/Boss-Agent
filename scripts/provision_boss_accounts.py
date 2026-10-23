import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "validation"))
from boss_account_auth import provision_accounts


def main():
    parser = argparse.ArgumentParser(description="初始化本机老板及维护账号，不输出密码")
    parser.add_argument("--directory", type=Path, default=Path(__file__).resolve().parents[1] / "validation/.work/application/accounts")
    args = parser.parse_args()
    provision_accounts(args.directory)
    print("本机账号已创建；凭据保存在受保护目录的credentials.json")


if __name__ == "__main__":
    main()
