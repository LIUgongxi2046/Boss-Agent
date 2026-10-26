from urllib.parse import unquote

from aiohttp import web

from business import now, require
from boss_owner_authorizations import revoke
from boss_v7_memory import read_memory, mutate_memory
from boss_v7_owner_records import authorizations, decisions, notification_history
from boss_v7_runs import read_runs, cancel_run
from boss_v7_store import NAMESPACE, execute_transaction, read_receipt, role_required
from boss_session_history import session_history

PREFIX = "boss.owner_workspace."
ACTIONS = {PREFIX + domain + "." + action: "BOSS" for domain, actions in {
    "personal-memory": ("confirm", "delete", "reconcile"), "authorizations": ("revoke",), "runs": ("cancel",),
}.items() for action in actions}
DOMAINS = {"personal-memory", "authorizations", "decisions", "notification-history", "runs", "session-history"}


class OwnerWorkspaceAPI:
    def __init__(self, store):
        self.store = store

    def read(self, role, path, query):
        role_required(role, "BOSS")
        parts = path.removeprefix("/api/boss/ui/owner/").split("/")
        domain = parts[0]
        require(domain in DOMAINS, "没有对应的本人页面接口", web.HTTPNotFound)
        require(domain == "session-history" or not query, "当前读取不接受查询参数", web.HTTPBadRequest)
        if len(parts) == 3 and parts[1] == "requests":
            return read_receipt(self.store, role, "BOSS", PREFIX, domain, unquote(parts[2]))
        require(len(parts) == 1, "本人页面路径无效", web.HTTPNotFound)
        with self.store.connect() as db:
            db.execute("BEGIN")
            self.store.active(db, NAMESPACE)
            snapshot = self.store.get(db, NAMESPACE, "initial", "snapshot")
            if domain == "session-history":
                data = session_history(db, snapshot, query)
            elif domain == "personal-memory":
                data = read_memory(self.store, db, snapshot)
            elif domain == "runs":
                data = {"runs": read_runs(self.store, db, snapshot)}
            elif domain == "notification-history":
                data = {"records": notification_history(db, snapshot)}
            elif domain == "decisions":
                data = {"records": decisions(db, snapshot)}
            else:
                data = {"records": authorizations(db, snapshot)}
            return {"projection": domain, "private_body_available_here": True, "namespace": NAMESPACE,
                    "business_clock": self.store.get(db, NAMESPACE, "clock", "current")["at"], "read_at": now(), **data}

    def execute(self, api, role, command, payload):
        require(command in ACTIONS, "本人操作不存在", web.HTTPNotFound)
        domain, action = command.removeprefix(PREFIX).split(".")

        def mutate(db, snapshot):
            if domain == "personal-memory":
                return mutate_memory(api, db, snapshot, action, payload)
            if domain == "runs":
                return cancel_run(api, db, snapshot, payload)
            return revoke(api, db, snapshot, payload)

        return execute_transaction(api, role, "BOSS", command, payload, mutate)
