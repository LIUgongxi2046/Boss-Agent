import os
import json
import secrets
import sqlite3
import stat
import asyncio
from pathlib import Path
from urllib.parse import urlsplit

import bcrypt

ROLES = frozenset({"BOSS", "MAINTAINER"})


def private_file(path):
    if path.is_symlink() or not path.is_file():
        raise ValueError("账号文件必须为本机普通文件")
    if stat.S_IMODE(path.stat().st_mode) != 0o600 or path.stat().st_uid != os.getuid():
        raise PermissionError("账号文件需要当前用户持有且权限为0600")


def provision_accounts(directory):
    directory = Path(directory)
    if ".work" not in directory.absolute().parts:
        raise ValueError("账号目录必须位于本机忽略的.work目录")
    if directory.is_symlink():
        raise ValueError("账号目录不能使用符号链接")
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    directory.chmod(0o700)
    database = directory / "accounts.sqlite"
    credentials = directory / "credentials.json"
    if database.exists() or credentials.exists():
        raise FileExistsError("账号已初始化；重置需单独授权的本机操作")
    accounts = [{"username": username, "password": secrets.token_urlsafe(24), "role": role}
                for username, role in (("boss", "BOSS"), ("maintainer", "MAINTAINER"))]
    fd = os.open(database, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(fd)
    with sqlite3.connect(database) as db:
        db.execute("CREATE TABLE accounts (username TEXT PRIMARY KEY, password_hash BLOB NOT NULL, role TEXT NOT NULL CHECK(role IN ('BOSS','MAINTAINER')))")
        db.executemany("INSERT INTO accounts VALUES (?,?,?)", [
            (account["username"], bcrypt.hashpw(account["password"].encode(), bcrypt.gensalt(rounds=12)), account["role"])
            for account in accounts])
    with os.fdopen(os.open(credentials, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), "w") as output:
        json.dump(accounts, output, ensure_ascii=False)
    return database


class AccountStore:
    def __init__(self, database):
        self.database = Path(database)
        private_file(self.database)

    def connect(self):
        private_file(self.database)
        return sqlite3.connect(self.database)

    def authenticate(self, username, password, role):
        if not isinstance(role, str) or role not in ROLES or not isinstance(username, str) or not isinstance(password, str):
            return None
        if not username or len(username) > 64 or not username.isascii() or not password.isascii() or not 1 <= len(password) <= 72:
            return None
        with self.connect() as db:
            account = db.execute("SELECT password_hash,role FROM accounts WHERE username=?", (username,)).fetchone()
            # 未知账号使用已有摘要执行相同密码计算，响应不暴露账号存在状态。
            digest = account[0] if account else db.execute("SELECT password_hash FROM accounts ORDER BY username LIMIT 1").fetchone()[0]
        valid = bcrypt.checkpw(password.encode(), digest)
        return account[1] if valid and account and account[1] == role else None

    def bootstrap_role(self, request, token_roles, tokens):
        headers = request.headers
        username = headers.get("X-Boss-Username")
        password = headers.get("X-Boss-Password")
        expected = headers.get("X-Boss-Role")
        if username is not None or password is not None:
            return self.authenticate(username, password, expected)
        authorization = headers.get("Authorization", "")
        if not authorization.startswith("Bearer "):
            return None
        token = authorization.removeprefix("Bearer ")
        if not tokens.check_api_token(request):
            return None
        role = token_roles.get(token)
        return role if role in ROLES else None


def account_channel_class(role_channel_class):
    from websockets.datastructures import Headers
    from websockets.http11 import Request

    class AccountRoleChannel(role_channel_class):
        def __init__(self, *args, account_store, **kwargs):
            super().__init__(*args, **kwargs)
            self.account_store = account_store

        async def _dispatch_http(self, connection, request):
            address = urlsplit(request.path)
            if address.path != "/webui/bootstrap":
                return await super()._dispatch_http(connection, request)
            origin = request.headers.get("Origin")
            if address.query or origin and urlsplit(origin).netloc != request.headers.get("Host"):
                self.record(None, "account.bootstrap", 401)
                return connection.respond(401, "认证请求无效")
            role = await asyncio.to_thread(self.account_store.bootstrap_role, request, self.token_roles, self.gateway.tokens)
            if role is None:
                self.record(None, "account.bootstrap", 401)
                return connection.respond(401, "账号或密码无效")
            # RoleChannel继续负责nanobot令牌发放、身份关联、过期和退出。
            headers = Headers(request.headers.raw_items())
            for name in ("Authorization", "X-Nanobot-Auth", "X-Boss-Username", "X-Boss-Password", "X-Boss-Role"):
                if name in headers:
                    del headers[name]
            headers["X-Nanobot-Auth"] = self.secrets[role]
            response = await super()._dispatch_http(connection, Request(request.path, headers))
            response.headers["Cache-Control"] = "no-store"
            return response

    return AccountRoleChannel
