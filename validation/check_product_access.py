import asyncio
import json
import uuid
from pathlib import Path
from urllib.parse import quote

import httpx
import websockets


ROOT = Path(__file__).resolve().parent
HOST = "http://127.0.0.1:8872"


async def check():
    access = json.loads((ROOT / ".work/application/access.json").read_text())
    results = []
    async with httpx.AsyncClient(base_url=HOST, timeout=15, trust_env=False) as http:
        for route in ("/webui/bootstrap", "/api/boss/identity", "/api/boss/ui/dashboard"):
            response = await http.get(route)
            assert response.status_code == 401, (route, response.status_code)
            results.append({"route": route, "role": "UNAUTHENTICATED", "status": 401})
        for role in ("BOSS", "MAINTAINER"):
            response = await http.get("/webui/bootstrap", headers={"X-Nanobot-Auth": access[role]})
            assert response.status_code == 200, (role, response.status_code)
            boot = response.json()
            headers = {"Authorization": "Bearer " + boot["api_token"]}
            identity = await http.get("/api/boss/identity", headers=headers)
            assert identity.status_code == 200
            assert identity.json()["role"] == role
            route = "/api/boss/ui/dashboard"
            response = await http.get(route, headers=headers)
            assert response.status_code == (200 if role == "BOSS" else 403)
            results.append({"route": route, "role": role, "status": response.status_code})
            if role == "BOSS":
                contact = response.json()["contacts"][0]["contact_id"]
                contact_login = await http.get("/webui/bootstrap", headers={"X-Nanobot-Auth": contact})
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
            uri = "ws://127.0.0.1:8872" + boot["ws_path"] + "?token=" + quote(boot["token"], safe="")
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
            after_logout = await http.get("/api/boss/identity", headers=headers)
            assert after_logout.status_code == 401
            results.append({"action": "boss.auth.logout", "role": role, "status": after_logout.status_code})
    return {"checks": results, "model_invoked": False, "business_write": False, "visual_acceptance": "NOT_RUN"}


if __name__ == "__main__":
    print(json.dumps(asyncio.run(check()), ensure_ascii=False, indent=2))
