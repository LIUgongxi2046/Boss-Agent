import asyncio
import json
import sys
from pathlib import Path

import aiohttp
from websockets.asyncio.server import serve

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "validation"))

from boss_account_auth import AccountStore, provision_accounts
from boss_demo_accounts import prefill_response


def test_local_role_prefill_and_request_boundaries(tmp_path):
    directory = tmp_path / ".work" / "accounts"
    provision_accounts(directory)
    store = AccountStore(directory / "accounts.sqlite")
    accounts = json.loads((directory / "credentials.json").read_text())
    original = store.database.read_bytes()

    async def check():
        async def connection_handler(connection):
            await connection.close()

        for enabled in (False, True):
            async def process_request(connection, request):
                return prefill_response(store, connection, request, enabled)

            async with serve(connection_handler, "127.0.0.1", 0, process_request=process_request) as server:
                port = server.sockets[0].getsockname()[1]
                origin = f"http://127.0.0.1:{port}"
                headers = {"X-Boss-Demo-Prefill": "1", "Origin": origin, "Sec-Fetch-Site": "same-origin"}
                async with aiohttp.ClientSession() as client:
                    for account in accounts:
                        result = await client.get(origin + "/webui/demo-account", params={"role": account["role"]}, headers=headers)
                        assert result.status == 200
                        value = await result.json()
                        if enabled:
                            assert value == {"enabled": True, **account}
                            assert "api_token" not in value and "token" not in value
                        else:
                            assert value == {"enabled": False}
                        assert "no-store" in result.headers["Cache-Control"]
                        assert "Access-Control-Allow-Origin" not in result.headers
                    for invalid in ({}, {**headers, "Origin": "https://example.test"},
                                    {**headers, "Host": f"example.test:{port}"},
                                    {**headers, "Sec-Fetch-Site": "cross-site"}):
                        result = await client.get(origin + "/webui/demo-account?role=BOSS", headers=invalid)
                        assert result.status == 403
                        assert "password" not in await result.text()
                    if enabled:
                        for query in ("role=CONTACT", "role=BOSS&role=MAINTAINER", "role=BOSS&extra=1", ""):
                            result = await client.get(origin + "/webui/demo-account?" + query, headers=headers)
                            assert result.status == 400
                            assert "password" not in await result.text()

    asyncio.run(check())
    assert store.database.read_bytes() == original
