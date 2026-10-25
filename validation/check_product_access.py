import asyncio
import argparse
import json
import uuid
from pathlib import Path
from urllib.parse import quote

import httpx
import websockets
import yaml
from jsonschema import Draft202012Validator
from application_paths import application_work_directory, application_ports
from boss_account_auth import AccountStore, private_file


ROOT = Path(__file__).resolve().parent
AUTH_SCHEMA = yaml.safe_load((ROOT.parent / "specs/product-auth.openapi.yaml").read_text())
AUTH_VALIDATORS = {name: Draft202012Validator({**AUTH_SCHEMA, "$ref": "#/components/schemas/" + name})
                   for name in ("Bootstrap", "Identity", "LogoutResult")}


async def check(directory):
    directory = application_work_directory(ROOT, str(directory.resolve(strict=True)))
    AccountStore(directory / "accounts/accounts.sqlite")
    credentials = directory / "accounts/credentials.json"
    private_file(credentials)
    access = {account["role"]: account for account in json.loads(credentials.read_text())}
    ports = application_ports(json.dumps(json.loads((directory / "instance.json").read_text())["ports"]))
    host = "http://127.0.0.1:" + str(ports["webui"])
    results = []
    async with httpx.AsyncClient(base_url=host, timeout=15, trust_env=False) as http:
        for route in ("/webui/bootstrap", "/api/boss/identity", "/api/boss/ui/dashboard"):
            response = await http.get(route)
            assert response.status_code == 401, (route, response.status_code)
            results.append({"route": route, "role": "UNAUTHENTICATED", "status": 401})
        for role in ("BOSS", "MAINTAINER"):
            account = access[role]
            response = await http.get("/webui/bootstrap", headers={"X-Boss-Username": account["username"],
                "X-Boss-Password": account["password"], "X-Boss-Role": role})
            assert response.status_code == 200, (role, response.status_code)
            boot = response.json()
            assert AUTH_VALIDATORS["Bootstrap"].is_valid(boot), "公开认证响应不符合当前Schema"
            headers = {"Authorization": "Bearer " + boot["api_token"]}
            identity = await http.get("/api/boss/identity", headers=headers)
            assert identity.status_code == 200
            assert AUTH_VALIDATORS["Identity"].is_valid(identity.json()), "身份响应不符合当前Schema"
            assert identity.json()["role"] == role
            route = "/api/boss/ui/dashboard"
            response = await http.get(route, headers=headers)
            assert response.status_code == (200 if role == "BOSS" else 403)
            results.append({"route": route, "role": role, "status": response.status_code})
            if role == "BOSS":
                contact = response.json()["contacts"][0]["contact_id"]
                contact_login = await http.get("/webui/bootstrap", headers={"X-Boss-Username": contact,
                    "X-Boss-Password": account["password"], "X-Boss-Role": "BOSS"})
                assert contact_login.status_code == 401
                results.append({"route": "/webui/bootstrap", "role": "EXTERNAL_CONTACT", "status": 401})
            if role == "MAINTAINER":
                response = await http.get("/api/sessions", headers=headers)
                assert response.status_code == 403
            memory_status = await http.get("/api/boss/ui/admin/memory-status", headers=headers)
            assert memory_status.status_code == (200 if role == "MAINTAINER" else 403)
            if role == "MAINTAINER":
                assert memory_status.json()["private_body_available_here"] is False
                assert "text" not in memory_status.json()["memory"]
            results.append({"route": "/api/boss/ui/admin/memory-status", "role": role, "status": memory_status.status_code})
            uri = host.replace("http:", "ws:") + boot["ws_path"] + "?token=" + quote(boot["token"], safe="")
            async with websockets.connect(uri, open_timeout=15, proxy=None) as socket:
                ready = json.loads(await asyncio.wait_for(socket.recv(), 15))
                assert ready["event"] == "ready"
                # 使用对方身份字段发起越权请求，身份仍由连接决定。
                action = "boss.assignment.create" if role == "MAINTAINER" else "boss.simulation.feedback"
                request_id = str(uuid.uuid4())
                await socket.send(json.dumps({
                    "type": "webui_request", "request_id": request_id,
                    "action": action, "payload": {"role": "BOSS" if role == "MAINTAINER" else "MAINTAINER"},
                }))
                async with asyncio.timeout(15):
                    while True:
                        frame = json.loads(await socket.recv())
                        if frame.get("request_id") == request_id:
                            break
                assert frame["ok"] is False
                assert frame["error"]["status"] == 403
                results.append({"action": action, "role": role, "status": 403})
                logout_id = str(uuid.uuid4())
                await socket.send(json.dumps({"type": "webui_request", "request_id": logout_id, "action": "boss.auth.logout", "payload": {}}))
                async with asyncio.timeout(15):
                    while True:
                        signed_out = json.loads(await socket.recv())
                        if signed_out.get("request_id") == logout_id:
                            break
                assert signed_out["ok"] is True
                assert AUTH_VALIDATORS["LogoutResult"].is_valid(signed_out["result"]), "退出回执不符合当前Schema"
            after_logout = await http.get("/api/boss/identity", headers=headers)
            assert after_logout.status_code == 401
            results.append({"action": "boss.auth.logout", "role": role, "status": after_logout.status_code})
    return {"checks": results, "application_directory": str(directory.relative_to(ROOT)), "actual_response_schema_verified": True,
            "model_invoked": False, "business_write": False, "visual_acceptance": "NOT_RUN"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--application-directory", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(asyncio.run(check(args.application_directory)), ensure_ascii=False, indent=2))
