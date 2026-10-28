import ipaddress
import json
from urllib.parse import parse_qs, urlsplit

from boss_account_auth import ROLES, private_file


def prefill_response(account_store, connection, request, enabled):
    def response(status, body):
        result = connection.respond(status, json.dumps(body, ensure_ascii=False))
        del result.headers["Content-Type"]
        result.headers["Content-Type"] = "application/json; charset=utf-8"
        result.headers["Cache-Control"] = "no-store, private"
        result.headers["Pragma"] = "no-cache"
        result.headers["X-Content-Type-Options"] = "nosniff"
        return result

    local_port = connection.local_address[1]
    allowed_hosts = {f"127.0.0.1:{local_port}", f"localhost:{local_port}", f"[::1]:{local_port}"}
    host = request.headers.get("Host", "")
    origin = request.headers.get("Origin")
    if (not ipaddress.ip_address(connection.remote_address[0]).is_loopback
            or host not in allowed_hosts
            or request.headers.get("X-Boss-Demo-Prefill") != "1"
            or request.headers.get("Sec-Fetch-Site", "same-origin") != "same-origin"
            or origin is not None and origin != "http://" + host):
        return response(403, {"error": "仅允许本机同源页面读取验收账号"})
    if not enabled:
        return response(200, {"enabled": False})
    query = parse_qs(urlsplit(request.path).query, keep_blank_values=True)
    if set(query) != {"role"} or len(query["role"]) != 1 or query["role"][0] not in ROLES:
        return response(400, {"error": "请选择老板或管理员"})
    credentials = account_store.database.parent / "credentials.json"
    private_file(credentials)
    accounts = json.loads(credentials.read_text())
    selected = [account for account in accounts if account["role"] == query["role"][0]]
    if len(selected) != 1 or not all(isinstance(selected[0][key], str) and selected[0][key] for key in ("username", "password")):
        raise ValueError("当前身份缺少唯一有效的本机验收账号")
    account = selected[0]
    return response(200, {"enabled": True, "role": account["role"], "username": account["username"], "password": account["password"]})
