import argparse
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "validation"))
from boss_account_auth import provision_accounts, validate_account_passwords
from application_paths import application_work_directory


def interactive_directory(directory):
    if (not directory.is_absolute() or directory.name != "accounts" or directory.parent.name != "application"
            or not directory.parent.parent.name.startswith("isolated-")):
        raise ValueError("交互式账号目录必须是独立应用目录下的 accounts")
    data_root = application_work_directory(Path(__file__).resolve().parents[1] / "validation", str(directory.parent.parent))
    if directory.parent.parent != data_root or data_root.exists() or data_root.is_symlink() or directory.exists() or directory.is_symlink():
        raise ValueError("交互式账号目录必须是尚未创建的独立目录")
    return directory


def main():
    parser = argparse.ArgumentParser(description="初始化本机老板及维护账号，不输出密码")
    parser.add_argument("--directory", type=Path, default=Path(__file__).resolve().parents[1] / "validation/.work/application/accounts")
    parser.add_argument("--interactive", action="store_true", help="由本人输入两种身份的密码")
    args = parser.parse_args()
    if args.interactive:
        directory = interactive_directory(args.directory)
        if not sys.stdin.isatty() or not sys.stderr.isatty():
            raise ValueError("交互式账号初始化需要本机终端")
        print("密码须由1至72个ASCII字符组成。")
        passwords = {}
        for role, label in (("BOSS", "老板"), ("MAINTAINER", "维护")):
            password = getpass.getpass(f"请输入{label}密码：")
            if password != getpass.getpass(f"请再次输入{label}密码："):
                raise ValueError("两次输入的密码不一致")
            passwords[role] = password
        validate_account_passwords(passwords)
        directory.parent.parent.mkdir(mode=0o700)
        directory.parent.mkdir(mode=0o700)
        (directory.parent.parent / "temp").mkdir(mode=0o700)
        provision_accounts(directory, passwords=passwords)
        print("本机账号已创建；请使用本人输入的密码登录")
    else:
        provision_accounts(args.directory)
        print("本机账号已创建；凭据保存在受保护目录的credentials.json")


if __name__ == "__main__":
    main()
