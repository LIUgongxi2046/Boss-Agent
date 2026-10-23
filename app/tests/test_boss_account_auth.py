import json
import stat
import sys
import asyncio
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "validation"))
from boss_account_auth import AccountStore, provision_accounts


def test_real_local_accounts_and_passwords():
    directory = ROOT / ".work" / "t27-account-check"
    if not (directory / "accounts.sqlite").exists():
        provision_accounts(directory)
    credentials = json.loads((directory / "credentials.json").read_text())
    store = AccountStore(directory / "accounts.sqlite")
    for account in credentials:
        assert store.authenticate(account["username"], account["password"], account["role"]) == account["role"]
        assert store.authenticate(account["username"], account["password"] + "!", account["role"]) is None
        other = "MAINTAINER" if account["role"] == "BOSS" else "BOSS"
        assert store.authenticate(account["username"], account["password"], other) is None
    assert store.authenticate("contact-1", credentials[0]["password"], "BOSS") is None
    assert store.authenticate("boss", "", "BOSS") is None
    assert store.authenticate("boss", "x" * 73, "BOSS") is None
    assert store.authenticate("boss", credentials[0]["password"], "CONTACT") is None
    assert store.authenticate("boss", credentials[0]["password"], []) is None
    with store.connect() as db:
        rows = db.execute("SELECT password_hash FROM accounts").fetchall()
    assert len(rows) == 2
    assert all(row[0].startswith(b"$2b$12$") for row in rows)
    assert all(account["password"].encode() not in (directory / "accounts.sqlite").read_bytes() for account in credentials)
    assert stat.S_IMODE(directory.stat().st_mode) == 0o700
    for name in ("credentials.json", "accounts.sqlite"):
        assert stat.S_IMODE((directory / name).stat().st_mode) == 0o600
    with pytest.raises(FileExistsError):
        provision_accounts(directory)
    assert AccountStore(directory / "accounts.sqlite").authenticate(**credentials[0]) == "BOSS"


def test_nanobot_account_lifecycle():
    sys.path.insert(0, str(ROOT / "design/T27"))
    from server import account_server, ACCOUNTS
    import aiohttp
    from websockets.asyncio.client import connect

    async def check():
        async with account_server() as (_, port):
            origin = f"http://127.0.0.1:{port}"
            accounts = json.loads((ACCOUNTS / "credentials.json").read_text())
            async with aiohttp.ClientSession() as client:
                assert (await client.get(origin + "/webui/bootstrap")).status == 401
                for account in accounts:
                    headers = {"X-Boss-Username": account["username"], "X-Boss-Password": account["password"], "X-Boss-Role": account["role"]}
                    denied = await client.get(origin + "/webui/bootstrap", headers={**headers, "X-Boss-Password": account["password"] + "!"})
                    assert denied.status == 401
                    other = "MAINTAINER" if account["role"] == "BOSS" else "BOSS"
                    assert (await client.get(origin + "/webui/bootstrap", headers={**headers, "X-Boss-Role": other})).status == 401
                    assert (await client.get(origin + "/webui/bootstrap", headers={**headers, "Origin": "https://example.com"})).status == 401
                    response = await client.get(origin + "/webui/bootstrap", headers=headers)
                    assert response.status == 200
                    boot = await response.json()
                    bearer = {"Authorization": "Bearer " + boot["api_token"]}
                    identity = await client.get(origin + "/api/boss/identity", headers=bearer)
                    assert json.loads(await identity.text())["role"] == account["role"]
                    assert (await client.get(origin + "/webui/bootstrap", headers=bearer)).status == 200
                    if account["role"] == "MAINTAINER":
                        assert (await client.get(origin + "/api/sessions", headers=bearer)).status == 403
                    async with connect(f"ws://127.0.0.1:{port}/?token=" + boot["token"]) as ws:
                        assert json.loads(await ws.recv())["event"] == "ready"
                        await ws.send(json.dumps({"type": "webui_request", "action": "boss.auth.logout", "request_id": "t27-logout", "payload": {}}))
                        result = json.loads(await ws.recv())
                        assert result["ok"] is True
                    assert (await client.get(origin + "/api/boss/identity", headers=bearer)).status == 401
                    assert (await client.get(origin + "/webui/bootstrap", headers=bearer)).status == 401
                    login = await client.get(origin + "/webui/bootstrap", headers=headers)
                    assert login.status == 200
                expires = {"Authorization": "Bearer " + (await login.json())["api_token"]}
                await asyncio.sleep(31)
                assert (await client.get(origin + "/webui/bootstrap", headers=expires)).status == 401
                assert (await client.get(origin + "/api/boss/identity", headers=expires)).status == 401
                assert (await client.get(origin + "/webui/bootstrap", headers=headers)).status == 200
        async with account_server() as (_, port):
            async with aiohttp.ClientSession() as client:
                assert (await client.get(f"http://127.0.0.1:{port}/webui/bootstrap", headers=headers)).status == 200

    asyncio.run(check())
