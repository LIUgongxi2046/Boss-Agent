import json
from dataclasses import asdict, replace

from aiohttp import web

from agent_run_broker import RunIdentity
from boss_conversation import ConversationAPI
from business import checksum
from conversation_agent.queries import ConversationQueries
from fc02_agent import Fc02Context, QueryBinding, bind_query
from hermes_run_authority import HermesRunAuthority


def bi_tool_definitions(store, namespace):
    from model_probe import BusinessTool
    if not isinstance(namespace, str) or not namespace:
        raise ValueError("经营工具定义需要执行空间")
    tools = [BusinessTool(name, store, {"execution_namespace": namespace}, {}, []) for name in ("query_metrics", "read_evidence")]
    return [{"name": tool.name, "description": tool.description, "parameters": tool.parameters} for tool in tools]


def continue_query_binding(previous_binding, current_binding):
    if not isinstance(previous_binding, QueryBinding) or not isinstance(current_binding, QueryBinding) or previous_binding.previous_query_id is None or current_binding.previous_query_id is not None:
        raise ValueError("经营追问绑定不可核查")
    values = json.loads(current_binding.parameters_json)
    previous = json.loads(previous_binding.previous_parameters_json)
    values["parent_query_id"] = previous_binding.previous_query_id
    changed = {key for key in values if key not in previous or values[key] != previous[key]}
    fields = set(previous_binding.overridden_fields) | changed | {"question", "parent_query_id"}
    return bind_query(values, previous_query_id=previous_binding.previous_query_id,
                      previous_parameters=previous, overridden_fields=fields)


def bi_request_id(run_id, goal_revision):
    if not isinstance(run_id, str) or not run_id or type(goal_revision) is not int or goal_revision < 1:
        raise ValueError("经营查询运行版本无效")
    return run_id if goal_revision == 1 else run_id + ":goal:" + str(goal_revision)


class HermesBIQueryAuthority:
    def __init__(self, scope):
        from agent_run_scope import RunScopeService
        if not isinstance(scope, RunScopeService):
            raise ValueError("经营查询授权需要实际会话范围")
        self.scope = scope
        self.store = scope.store
        self.planner = ConversationQueries(self.store, ConversationAPI(self.store))

    def prepare(self, request, identity, payload, *, goal_snapshot=None):
        if not isinstance(request, web.Request) or not isinstance(identity, RunIdentity) or identity.role != "BOSS" or not callable(identity.verify):
            raise web.HTTPUnauthorized(text="经营查询需要实际本人会话")
        identity.verify()
        if not isinstance(payload, dict) or not isinstance(payload.get("goal"), str) or not isinstance(payload.get("selected_refs"), list):
            raise web.HTTPBadRequest(text="经营查询输入不可核查")
        chat_id = payload.get("conversation_id")
        if chat_id not in identity.conversation_ids or not set(payload["selected_refs"]).issubset(identity.source_refs):
            raise web.HTTPForbidden(text="经营查询来源不属于当前本人会话")
        proof = self.scope.prove(chat_id, payload["selected_refs"])
        if (proof.owner_id, proof.namespace) != (identity.actor_id, identity.space_id):
            raise web.HTTPForbidden(text="经营查询本人身份不可核查")
        query = {"chat_id": proof.chat_id, "session_id": proof.session_id}
        if goal_snapshot is None:
            plan = self.planner.plan(payload["goal"], query)
        else:
            if not isinstance(goal_snapshot, dict) or set(goal_snapshot) != {"goal", "inputs"} or goal_snapshot["goal"] != payload["goal"] or not isinstance(goal_snapshot["inputs"], list) or not goal_snapshot["inputs"]:
                raise ValueError("经营查询目标版本不可核查")
            pending = None
            plan = None
            previous_binding = None
            for index, text in enumerate([goal_snapshot["goal"], *[item[4] for item in goal_snapshot["inputs"]]]):
                if not isinstance(text, str) or not text.strip():
                    raise ValueError("经营查询补充目标不可核查")
                if "重新" in text:
                    previous_binding = None
                plan = self.planner.plan(text if pending is None else "补充 " + text, query, pending_scope=pending,
                                         use_implicit_previous=False)
                if plan.binding is not None:
                    if previous_binding is not None and previous_binding.previous_query_id is not None and plan.binding.previous_query_id is None and "重新" not in text:
                        plan = replace(plan, binding=continue_query_binding(previous_binding, plan.binding))
                    previous_binding = plan.binding
                    values = json.loads(plan.binding.parameters_json)
                    pending = json.dumps({key: value for key, value in values.items() if key not in {"question", "parent_query_id", "query_mode"}}, ensure_ascii=False)
                elif plan.pending_scope is not None:
                    pending = plan.pending_scope
                elif index != 0:
                    raise web.HTTPConflict(text="当前补充目标缺少明确经营查询范围")
        if plan.required_inputs:
            raise web.HTTPConflict(text="；".join(plan.required_inputs))
        if not isinstance(plan.binding, QueryBinding):
            raise web.HTTPConflict(text="当前目标缺少明确经营查询范围")
        pins = {source: (version, digest) for source, version, digest in proof.source_pins}
        if not plan.references or any(kind != "document" or source not in pins or pins[source][0] != version for kind, source, version in plan.references):
            raise web.HTTPForbidden(text="经营查询来源未获当前运行选择")
        binding = plan.binding
        values = {"parameters": json.loads(binding.parameters_json), "previous_query_id": binding.previous_query_id,
                  "previous_parameters": json.loads(binding.previous_parameters_json) if binding.previous_parameters_json else None,
                  "overridden_fields": sorted(binding.overridden_fields)}
        identity.verify()
        return {"owner_id": proof.owner_id, "namespace": proof.namespace, "dataset_id": proof.dataset_id,
                "dataset_version": proof.dataset_version, "chat_id": proof.chat_id, "session_id": proof.session_id,
                "scope_proof": json.loads(json.dumps(asdict(proof), ensure_ascii=False)),
                "goal_sha256": checksum(payload["goal"]), "binding": values, "binding_sha256": checksum(values),
                "references": [list(item) for item in plan.references],
                **({"goal_snapshot_sha256": checksum(goal_snapshot)} if goal_snapshot is not None else {})}

    def save_in_transaction(self, db, run_id, prepared, *, goal_snapshot=None):
        if not db.in_transaction or not isinstance(run_id, str) or not isinstance(prepared, dict):
            raise ValueError("经营查询授权需要当前运行事务")
        row = db.execute("SELECT actor_id,space_id,conversation_id,goal,scope_proof,goal_revision FROM agent_runs WHERE run_id=?", (run_id,)).fetchone()
        revision = row[5] if row is not None else None
        if row is None or (row[0], row[1], row[2], checksum(row[3]), json.loads(row[4])) != (
                prepared["owner_id"], prepared["namespace"], prepared["chat_id"], prepared["goal_sha256"], prepared["scope_proof"]):
            raise ValueError("经营查询授权与运行身份不匹配")
        if revision == 1 and goal_snapshot is not None or revision != 1 and (goal_snapshot is None or prepared.get("goal_snapshot_sha256") != checksum(goal_snapshot)):
            raise ValueError("经营查询授权与目标版本不匹配")
        if revision > 1:
            from agent_run_method_selection import AgentRunMethodSelection
            current_snapshot, _ = AgentRunMethodSelection._goal_snapshot(db, run_id, revision)
            if goal_snapshot != current_snapshot:
                raise ValueError("经营查询目标快照已经变化")
        record = {**prepared, "run_id": run_id, "goal_revision": revision}
        record_id = run_id if revision == 1 else run_id + ":" + str(revision)
        existing = db.execute("SELECT body FROM objects WHERE namespace=? AND kind='hermes_bi_query_authorization' AND id=?",
                              (prepared["namespace"], record_id)).fetchone()
        if existing is None:
            self.store.put(db, prepared["namespace"], "hermes_bi_query_authorization", record_id, record)
        elif json.loads(existing[0]) != record:
            raise ValueError("经营查询授权已经变化")
        return record

    def require_in_transaction(self, db, authority, *, allow_pending=False):
        if not db.in_transaction or not isinstance(authority, HermesRunAuthority) or authority.services.scope is not self.scope:
            raise ValueError("经营查询需要当前产品运行授权")
        authority.require_in_transaction(db)
        run_id = authority.sink.config.run_id
        run = db.execute("SELECT actor_id,space_id,conversation_id,goal,scope_proof,goal_revision,applied_goal_revision FROM agent_runs WHERE run_id=?", (run_id,)).fetchone()
        if run is None or (not allow_pending and run[5] != run[6]) or (allow_pending and run[5] < run[6]):
            raise web.HTTPConflict(text="经营查询授权与当前运行不一致")
        record_id = run_id if run[5] == 1 else run_id + ":" + str(run[5])
        row = db.execute("SELECT body FROM objects WHERE namespace=? AND kind='hermes_bi_query_authorization' AND id=?",
                         (self.scope.namespace, record_id)).fetchone()
        if row is None:
            raise web.HTTPConflict(text="当前运行缺少经营查询授权")
        record = json.loads(row[0])
        if run is None or (record.get("run_id"), record.get("owner_id"), record.get("namespace"), record.get("chat_id"), record.get("goal_sha256"), record.get("scope_proof"), record.get("goal_revision")) != (
                run_id, run[0], run[1], run[2], checksum(run[3]), json.loads(run[4]), run[5]) or (not allow_pending and run[5] != run[6]):
            raise web.HTTPConflict(text="经营查询授权与当前运行不一致")
        if run[5] > 1:
            from agent_run_method_selection import AgentRunMethodSelection
            snapshot, _ = AgentRunMethodSelection._goal_snapshot(db, run_id, run[5])
            if record.get("goal_snapshot_sha256") != checksum(snapshot):
                raise web.HTTPConflict(text="经营查询授权目标版本已经变化")
        values = record.get("binding")
        if not isinstance(values, dict) or set(values) != {"parameters", "previous_query_id", "previous_parameters", "overridden_fields"} or checksum(values) != record.get("binding_sha256"):
            raise ValueError("经营查询绑定不可核查")
        binding = bind_query(values["parameters"], previous_query_id=values["previous_query_id"],
                             previous_parameters=values["previous_parameters"], overridden_fields=values["overridden_fields"])
        proof = record["scope_proof"]
        if (record.get("dataset_id"), record.get("dataset_version"), record.get("session_id")) != (proof["dataset_id"], proof["dataset_version"], proof["session_id"]):
            raise ValueError("经营查询会话身份不可核查")
        for kind, source_id, version in record["references"]:
            if kind != "document":
                raise ValueError("经营查询来源类型无效")
            source = self.scope.read_source_in_transaction(db, authority.sink.store, run_id, authority.sink.lease_owner,
                                                           authority.sink.config.lease_epoch, source_id)
            if source["version"] != version:
                raise web.HTTPConflict(text="经营查询来源版本已经变化")
        return record, binding

    def bind_epoch(self, authority):
        with authority.sink.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self.bind_epoch_in_transaction(db, authority)

    def bind_epoch_in_transaction(self, db, authority):
        record, _ = self.require_in_transaction(db, authority, allow_pending=True)
        run_id, epoch = authority.sink.config.run_id, authority.sink.config.lease_epoch
        key = run_id + ":" + str(epoch)
        if record["goal_revision"] > 1:
            key += ":" + str(record["goal_revision"])
        expected = {"run_id": run_id, "epoch": epoch, "owner": authority.sink.lease_owner,
                    "binding_sha256": record["binding_sha256"], "scope_sha256": checksum(record["scope_proof"])}
        if record["goal_revision"] > 1:
            expected["goal_revision"] = record["goal_revision"]
        existing = db.execute("SELECT body FROM objects WHERE namespace=? AND kind='hermes_bi_query_epoch' AND id=?",
                              (self.scope.namespace, key)).fetchone()
        if existing is None:
            self.store.put(db, self.scope.namespace, "hermes_bi_query_epoch", key, expected)
        elif json.loads(existing[0]) != expected:
            raise ValueError("经营查询运行版本已经变化")

    def context(self, authority):
        with authority.sink.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            record, binding = self.require_in_transaction(db, authority)
            run_id, epoch = authority.sink.config.run_id, authority.sink.config.lease_epoch
            key = run_id + ":" + str(epoch)
            if record["goal_revision"] > 1:
                key += ":" + str(record["goal_revision"])
            saved = db.execute("SELECT body FROM objects WHERE namespace=? AND kind='hermes_bi_query_epoch' AND id=?",
                               (self.scope.namespace, key)).fetchone()
            expected = {"run_id": run_id, "epoch": epoch, "owner": authority.sink.lease_owner,
                        "binding_sha256": record["binding_sha256"], "scope_sha256": checksum(record["scope_proof"])}
            if record["goal_revision"] > 1:
                expected["goal_revision"] = record["goal_revision"]
            if saved is None or json.loads(saved[0]) != expected:
                raise web.HTTPConflict(text="经营查询运行版本尚未绑定")
            readable = frozenset({binding.previous_query_id}) if binding.previous_query_id else frozenset()
            return Fc02Context("BOSS", record["owner_id"], record["namespace"], record["dataset_id"], record["dataset_version"],
                               bi_request_id(run_id, record["goal_revision"]), record["session_id"], True, (binding,), readable)
