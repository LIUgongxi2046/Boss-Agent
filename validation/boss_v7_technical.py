from urllib.parse import unquote

from aiohttp import web

from business import now, require
from boss_v7_audit import read_audit
from boss_v7_knowledge import mutate_knowledge, read_knowledge, search_knowledge
from boss_v7_configuration import CONFIG_DOMAINS, authorize_technical, mutate_configuration, read_configuration
from boss_v7_local_system import read_local_system
from boss_v7_models import ModelConnections
from boss_v7_datasets import DatasetWorkspace
from boss_v7_evaluation import cancel as evaluation_cancel, read_evaluation, start as evaluation_start
from boss_v7_simulation_events import advance_clock, read_simulation_events, record as record_simulation_event
from boss_v7_relationships import read_relationships, save_contact
from boss_secretary import read_secretary, save_secretary
from boss_v7_store import NAMESPACE, execute_transaction, read_receipt, role_required

PREFIX = "boss.technical."
ACTIONS = {PREFIX + name: "MAINTAINER" for name in (
    "relationships.save", "secretary.save", "knowledge.ingest", "knowledge.revise", "knowledge.withdraw",
)}
ACTIONS.update({PREFIX + domain + "." + action: "MAINTAINER" for domain in CONFIG_DOMAINS for action in ("save", "validate", "activate")})
ACTIONS.update({PREFIX + "models." + action: "MAINTAINER" for action in ("save", "validate", "activate", "cancel")})
ACTIONS.update({PREFIX + "datasets." + action: "MAINTAINER" for action in ("generate", "validate", "load", "reset", "inspect-reset")})
ACTIONS.update({PREFIX + "evaluation." + action: "MAINTAINER" for action in ("start", "reset", "cancel")})
ACTIONS.update({PREFIX + "simulation-events." + action: "MAINTAINER" for action in ("inject", "reply", "advance-clock")})
DOMAINS = {"secretary", "relationships", "audit", "knowledge", "local-system", "models", "datasets", "evaluation", "simulation-events"} | CONFIG_DOMAINS


class TechnicalWorkspaceAPI:
    def __init__(self, store, runtime_control=None):
        self.store = store
        self.runtime_control = runtime_control
        self.models = runtime_control.models if runtime_control is not None else ModelConnections(store)
        self.datasets = DatasetWorkspace(store, runtime_control)

    def read(self, role, path, query):
        role_required(role, "MAINTAINER")
        parts = path.removeprefix("/api/boss/ui/admin/technical/").split("/")
        domain = parts[0]
        require(domain in DOMAINS, "没有对应的技术页面接口", web.HTTPNotFound)
        authorize_technical(self.store, domain, "READ")
        if len(parts) == 3 and domain == "datasets" and parts[1] == "history":
            with self.store.connect() as db:
                db.execute("BEGIN")
                return self.datasets.history(db, unquote(parts[2]), query)
        if len(parts) == 3 and domain == "datasets" and parts[2] == "records":
            with self.store.connect() as db:
                db.execute("BEGIN")
                self.store.active(db, NAMESPACE)
                return self.datasets.details(db, unquote(parts[1]), query)
        if parts == ["knowledge", "search"]:
            with self.store.connect() as db:
                db.execute("BEGIN")
                self.store.active(db, NAMESPACE)
                snapshot = self.store.get(db, NAMESPACE, "initial", "snapshot")
                return search_knowledge(self.store, db, snapshot, query)
        require(not query, "当前读取不接受查询参数", web.HTTPBadRequest)
        if len(parts) == 3 and parts[1] == "requests":
            return read_receipt(self.store, role, "MAINTAINER", PREFIX, domain, unquote(parts[2]))
        require(len(parts) == 1, "技术页面路径无效", web.HTTPNotFound)
        with self.store.connect() as db:
            db.execute("BEGIN")
            self.store.active(db, NAMESPACE)
            snapshot = self.store.get(db, NAMESPACE, "initial", "snapshot")
            if domain == "secretary":
                data = read_secretary(self.store, db, snapshot)
            elif domain == "datasets":
                data = self.datasets.read(db, snapshot)
            elif domain == "models":
                data = self.models.read(db)
            elif domain in CONFIG_DOMAINS:
                data = read_configuration(self.store, db, snapshot, domain)
            elif domain == "relationships":
                data = read_relationships(self.store, db, snapshot)
            elif domain == "knowledge":
                data = read_knowledge(self.store, db, snapshot)
            elif domain == "local-system":
                data = read_local_system(self.store, db)
            elif domain == "evaluation":
                data = read_evaluation(self.store, db, snapshot)
            elif domain == "simulation-events":
                data = read_simulation_events(self.store, db, snapshot, query)
            else:
                data = read_audit(db)
            return {"projection": domain, "private_body_available_here": False, "namespace": NAMESPACE, "read_at": now(), **data}

    def execute(self, api, role, command, payload):
        require(command in ACTIONS, "技术操作不存在", web.HTTPNotFound)
        role_required(role, "MAINTAINER")
        domain, action = command.removeprefix(PREFIX).split(".")
        authorize_technical(self.store, domain, "WRITE")
        def mutate(db, snapshot):
            if domain == "secretary":
                return save_secretary(api, db, snapshot, payload)
            if domain == "datasets":
                return self.datasets.mutate(db, action, payload)
            if domain == "models":
                return self.models.mutate(api, db, action, payload)
            if domain in CONFIG_DOMAINS:
                return mutate_configuration(api, db, snapshot, domain, action, payload)
            if domain == "evaluation":
                if action == "cancel":
                    return evaluation_cancel(api, db, payload)
                return evaluation_start(api, db, snapshot, payload, reset=action == "reset")
            if domain == "simulation-events":
                if action == "advance-clock":
                    return advance_clock(api.store, db, snapshot, payload)
                return record_simulation_event(api.store, db, snapshot, payload, action)
            if command == PREFIX + "relationships.save":
                return save_contact(api, db, snapshot, payload)
            return mutate_knowledge(api, db, snapshot, payload, action)
        receipt = execute_transaction(api, role, "MAINTAINER", command, payload, mutate)
        if domain == "models":
            self.models.enqueue(receipt)
        if domain == "datasets" and action in {"load", "reset"} and self.runtime_control is not None:
            self.runtime_control.execution_transition.enqueue(receipt)
        return receipt
