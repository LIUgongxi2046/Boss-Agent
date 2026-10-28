import json
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "validation"))

from boss_account_auth import AccountStore, provision_accounts
from boss_command_api import BossCommandAPI
from boss_page_api import BossPageAPI
from controls import ControlStore


@pytest.fixture
def seed_directory():
    directory = ROOT / "validation/.work" / ("initializer-check-" + uuid4().hex)
    yield directory
    for candidate in (directory, directory.with_name(directory.name + "-missing")):
        if candidate.exists():
            shutil.rmtree(candidate)


def initialize(directory, *options, clock="2026-10-28T09:00:00+08:00"):
    return subprocess.run([sys.executable, str(ROOT / "scripts/prepare_comprehensive_simulation.py"),
                           "--directory", str(directory), "--business-at", clock, *options],
                          cwd=ROOT, capture_output=True, text=True)


def objects(directory):
    with sqlite3.connect(directory / "business.sqlite") as db:
        return list(db.execute("SELECT namespace,kind,id,body FROM objects ORDER BY namespace,kind,id"))


def test_cli_creates_complete_shared_business_data_and_private_random_accounts(seed_directory):
    result = initialize(seed_directory, "--create", "--initialize-accounts")
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert all(report["interface_counts"].values()) and len(report["interface_counts"]) == 14
    assert report["administrator_counts"]["task_summary"] == 12
    assert report["administrator_counts"]["initial_contact"] == 14
    assert report["accounts"] == "CREATED"
    assert (seed_directory / "business.sqlite").stat().st_mode & 0o777 == 0o600
    credentials_file = seed_directory / "accounts/credentials.json"
    assert credentials_file.stat().st_mode & 0o777 == 0o600
    credentials = json.loads(credentials_file.read_text())
    assert {row["role"] for row in credentials} == {"BOSS", "MAINTAINER"}
    accounts = AccountStore(seed_directory / "accounts/accounts.sqlite")
    for row in credentials:
        assert len(row["password"]) >= 24 and row["password"] not in result.stdout + result.stderr
        assert accounts.authenticate(row["username"], row["password"], row["role"]) == row["role"]
    store = ControlStore(seed_directory / "business.sqlite")
    assert BossPageAPI(store).serve("BOSS", "/api/boss/ui/tasks")[0] == 200
    with store.connect() as db:
        assert db.execute("SELECT count(*) FROM objects WHERE kind='runtime_run'").fetchone()[0] == 0


def test_cli_repeat_preserves_owner_action_and_existing_accounts(seed_directory):
    assert initialize(seed_directory, "--create", "--initialize-accounts").returncode == 0
    store = ControlStore(seed_directory / "business.sqlite")
    task = BossPageAPI(store).serve("BOSS", "/api/boss/ui/tasks")[1]["tasks"][0]
    status, receipt = BossCommandAPI(store).execute("BOSS", "boss.assignment.cancel", {
        "client_request_id": "initializer-owner-cancel", "task_id": task["task_id"], "task_version": task["version"], "reason": "本人取消当前模拟交办"})
    assert status == 200, receipt
    before = objects(seed_directory)
    credentials = (seed_directory / "accounts/credentials.json").read_bytes()
    repeated = initialize(seed_directory, "--initialize-accounts")
    assert repeated.returncode == 0, repeated.stderr
    assert json.loads(repeated.stdout)["accounts"] == "PRESERVED"
    assert objects(seed_directory) == before
    assert (seed_directory / "accounts/credentials.json").read_bytes() == credentials
    rejected = initialize(seed_directory, "--create", "--initialize-accounts")
    assert rejected.returncode != 0
    assert objects(seed_directory) == before


@pytest.mark.parametrize("clock,reason", [("2026-10-28T09:00:00", "时区"), ("2026-10-01T09:00:00+08:00", "早于")])
def test_invalid_clock_is_rejected_before_creating_data_or_accounts(seed_directory, clock, reason):
    result = initialize(seed_directory, "--create", "--initialize-accounts", clock=clock)
    assert result.returncode != 0 and reason in result.stderr
    assert not seed_directory.exists()


def test_missing_runtime_reference_is_rejected_without_creating_any_database(seed_directory):
    source = seed_directory.with_name(seed_directory.name + "-missing")
    result = initialize(seed_directory, "--create", "--runtime-from", str(source))
    assert result.returncode != 0
    assert not seed_directory.exists() and not source.exists()


def test_partial_account_directory_is_preserved_without_creating_business_database(seed_directory):
    provision_accounts(seed_directory / "accounts")
    credentials = (seed_directory / "accounts/credentials.json").read_bytes()
    (seed_directory / "accounts/accounts.sqlite").unlink()
    result = initialize(seed_directory, "--create", "--initialize-accounts")
    assert result.returncode != 0 and "账号资料不完整" in result.stderr
    assert not (seed_directory / "business.sqlite").exists()
    assert (seed_directory / "accounts/credentials.json").read_bytes() == credentials
