import argparse
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "validation"))

from boss_comprehensive_simulation import populate
from boss_account_auth import AccountStore, private_file, provision_accounts
from boss_admin_current import current_snapshot
from boss_simulation_api import SimulationAPI
from business import initial_materials
from controls import ControlStore


def main():
    parser = argparse.ArgumentParser(description="生成关联业务仿真资料并保留已有账号、会话与配置")
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--business-at", required=True)
    parser.add_argument("--create", action="store_true")
    parser.add_argument("--runtime-from", type=Path)
    parser.add_argument("--initialize-accounts", action="store_true", help="创建本机随机账号；已有账号保持")
    args = parser.parse_args()
    clock = datetime.fromisoformat(args.business_at)
    if clock.tzinfo is None:
        raise ValueError("业务时钟必须包含时区")
    if args.create and clock < datetime.fromisoformat(initial_materials()["business_clock"]):
        raise ValueError("业务日期早于初始化基准时钟")
    if args.runtime_from is not None and not args.create:
        raise ValueError("运行配置引用只用于创建独立验证资料")
    if args.directory.is_symlink():
        raise ValueError("资料目录不能使用符号链接")
    directory = args.directory.resolve()
    if directory.parent != (ROOT / "validation/.work").resolve():
        raise ValueError("资料目录必须位于 validation/.work 的直接子目录")
    database = directory / "business.sqlite"
    if database.is_symlink():
        raise ValueError("业务数据库不能使用符号链接")
    if args.create and database.exists():
        raise FileExistsError("独立业务资料已经存在")
    if not args.create and not database.is_file():
        raise FileNotFoundError("业务资料尚未初始化")
    account_directory = directory / "accounts"
    account_files = [account_directory / "accounts.sqlite", account_directory / "credentials.json"]
    accounts_present = all(path.exists() for path in account_files)
    if args.initialize_accounts:
        if account_directory.is_symlink() or any(path.is_symlink() for path in account_files):
            raise ValueError("账号资料不能使用符号链接")
        if any(path.exists() for path in account_files) and not accounts_present:
            raise ValueError("账号资料不完整，需要检查已有文件")
        if accounts_present:
            for path in account_files:
                private_file(path)
            with AccountStore(account_files[0]).connect() as account_db:
                if {row[0] for row in account_db.execute("SELECT role FROM accounts")} != {"BOSS", "MAINTAINER"}:
                    raise ValueError("已有账号缺少必要身份")
    runtime_records = []
    if args.runtime_from is not None:
        reference = args.runtime_from.resolve(strict=True)
        if reference.parent != (ROOT / "validation/.work").resolve() or reference == directory:
            raise ValueError("运行配置来源必须是独立本机验收资料目录")
        reference_database = reference / "business.sqlite"
        if reference_database.is_symlink() or not reference_database.is_file():
            raise FileNotFoundError("运行配置来源缺少普通业务数据库")
        # 配置来源只读打开，初始化不会创建或修改来源资料。
        with sqlite3.connect(reference_database.as_uri() + "?mode=ro", uri=True) as source:
            active = source.execute("SELECT body FROM objects WHERE namespace='ui-check' AND kind='model_connection_active' AND id='current'").fetchone()
            if active is None:
                raise ValueError("来源没有已启用的模型配置")
            metadata_kinds = {"configuration", "configuration_draft", "configuration_revision", "model_connection_active", "model_connection_draft", "model_connection_revision", "model_connection_validation"}
            runtime_records = [(kind, identifier, json.loads(body)) for kind, identifier, body in source.execute("SELECT kind,id,body FROM objects WHERE namespace='ui-check'") if kind in metadata_kinds]
    if args.create:
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        directory.chmod(0o700)
        ControlStore(database).initialize("ui-check")
        database.chmod(0o600)
    store = ControlStore(database)
    if runtime_records:
        with store.connect() as target:
            for kind, identifier, body in runtime_records:
                store.put(target, "ui-check", kind, identifier, body)
    result = populate(store, args.business_at)
    reader = SimulationAPI(store)
    counts = {f"SI{index:02d}": len(reader.query("BOSS", {"interface_id": f"SI{index:02d}", "object_ids": [], "filters": {}})["records"]) for index in range(1, 15)}
    if not all(counts.values()):
        raise ValueError("部分业务接口缺少仿真资料")
    with store.connect() as db:
        initial = store.get(db, "ui-check", "initial", "snapshot")
        administrator = current_snapshot(store, db, initial)
    account_status = "NOT_REQUESTED"
    if args.initialize_accounts:
        if not accounts_present:
            provision_accounts(account_directory)
        account_status = "PRESERVED" if accounts_present else "CREATED"
    print(json.dumps({**result, "interface_counts": counts, "administrator_counts": administrator["counts"],
                      "accounts": account_status, "external_model_requests": 0}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
