import json
from decimal import Decimal
from urllib.parse import parse_qs

from aiohttp import web

from business import checksum, now, require
from boss_dataset_generator import GENERATOR_VERSION, RELATIONSHIP_VERSION, SCALES, IMPORT_VALIDATOR, generate_facts
from boss_supply_quality import ENTITY_CONFIG, SupplyQualityAPI, bound_source_references, external_records
from boss_v7_store import NAMESPACE, optional, rows, text
from boss_execution_scope import validate_namespace, require_dataset_scope

CATALOG = "dataset-catalog"
KIND = "dataset_definition"
PAGE_SIZE = 25


def _context(facts, namespace):
    initial = facts["initial"]
    return {"namespace": namespace, "owner_id": initial["owner_id"], "dataset_id": initial["dataset_id"],
            "dataset_version": initial["dataset_version"], "timezone": initial["boss_profile"]["timezone"],
            "clock": initial["business_clock"], "periods": initial["periods"]}


def _content_hash(db, namespace):
    records = [(kind, identifier, json.loads(body)) for kind, identifier, body in db.execute(
        "SELECT kind,id,body FROM objects WHERE namespace=? ORDER BY kind,id", (namespace,)).fetchall()]
    return checksum(records)


def _public(item, current):
    return {"id": item["id"], "version": item["version"], **item["parameters"], "state": item["state"],
            "created_at": item["created_at"], "counts": item["counts"], "checks": item["checks"],
            "facts_sha256": item["facts_sha256"], "provenance": item["provenance"], "totals": item["totals"],
            "validated_at": item["validated_at"], "candidate_namespace": item["candidate_namespace"],
            **({} if current else {"state": "NEEDS_REVIEW", "checks": [
                {"name": "资料完整性", "state": "NEEDS_REVIEW", "message": "候选资料与生成摘要不一致，需要核查当前资料。"}]})}


class DatasetWorkspace:
    def __init__(self, store, runtime_control=None):
        self.store = store
        self.supply = SupplyQualityAPI(store)
        self.runtime_control = runtime_control

    def impact(self, db):
        require(self.runtime_control is not None, "当前服务未连接原生会话，无法核查重置影响", web.HTTPServiceUnavailable)
        require(self.runtime_control.store.path.resolve() == self.store.path.resolve(), "原生运行与当前资料不属于同一实例")
        self.store.active(db, NAMESPACE)
        sessions = self.runtime_control.loop.sessions.list_sessions()
        native_references = sorted(({"key": item["key"], "created_at": item["created_at"], "updated_at": item["updated_at"]}
                                    for item in sessions), key=lambda item: item["key"])
        records = [(kind, identifier, json.loads(body)) for kind, identifier, body in db.execute(
            "SELECT kind,id,body FROM objects WHERE namespace=? AND kind<>'dataset_reset_impact' ORDER BY kind,id", (NAMESPACE,))]
        counts = {}
        for kind, _, _ in records:
            counts[kind] = counts.get(kind, 0) + 1
        runs = [body for kind, _, body in records if kind == "runtime_run"
                and body["status"] in {"QUEUED", "RUNNING", "WAITING_INPUT"} and body["finished_at"] is None]
        runtime = self.runtime_control.snapshot()
        model_jobs = sorted(key for key, task in self.runtime_control.models.tasks.items() if not task.done())
        version = checksum({"namespace": NAMESPACE, "objects": records, "sessions": native_references,
                            "native_directory": str(self.runtime_control.loop.sessions.sessions_dir), "runtime": runtime,
                            "model_validation_jobs": model_jobs})
        return {"version": version, "namespace": NAMESPACE, "sessions": len(sessions),
                "memories": counts.get("memory", 0), "tasks": counts.get("task", 0),
                "plans": counts.get("owner_plan", 0), "outbox": counts.get("outbox", 0), "active_runs": len(runs),
                "schedule_configurations": counts.get("schedule", 0),
                "model_validation_jobs": len(model_jobs),
                "private_body_available_here": False, "checked_at": now(), "state": "CURRENT"}

    def checked_impact(self, db):
        saved = optional(db, "dataset_reset_impact", "current")
        if saved is None or self.runtime_control is None:
            return None
        current = self.impact(db)
        return {**saved, "state": "CURRENT" if current["version"] == saved["version"] else "STALE"}

    def read(self, db, initial):
        from boss_admin_current import current_snapshot
        from boss_execution_transition import transition_status
        controller = self.runtime_control.execution_transition if self.runtime_control is not None else None
        transition_available = controller is not None and controller.available
        definitions = rows(db, KIND, CATALOG)
        history = []
        for namespace, in db.execute("SELECT namespace FROM spaces WHERE active=0 ORDER BY namespace").fetchall():
            if namespace.startswith("dataset-candidate:"):
                continue
            manifest = optional(db, "execution_space", "current", namespace)
            if manifest is not None and manifest["state"] == "PREPARED":
                continue
            previous = optional(db, "initial", "snapshot", namespace)
            if previous is not None:
                archive = optional(db, "execution_archive", namespace, CATALOG)
                history.append({"namespace": namespace, "dataset_id": previous["dataset_id"], "version": previous["dataset_version"],
                                "state": "READ_ONLY", "created_at": manifest["created_at"] if manifest else None,
                                "history_available": archive is not None})
        return {"current_snapshot": current_snapshot(self.store, db, initial), "datasets": [_public(item, checksum(item["facts"]) == item["facts_sha256"]
                                    and _content_hash(db, item["candidate_namespace"]) == item["candidate_sha256"])
                             for item in sorted(definitions, key=lambda item: item["created_at"], reverse=True)],
                "current": {"dataset_id": initial["dataset_id"], "version": initial["dataset_version"], "namespace": NAMESPACE,
                            "business_clock": self.store.get(db, NAMESPACE, "clock", "current")["at"]},
                "generator_versions": [GENERATOR_VERSION], "relationship_versions": [RELATIONSHIP_VERSION],
                "scales": [{"id": key, "label": value[1]} for key, value in SCALES.items()], "history": history,
                "reset_impact": self.checked_impact(db), "inspection_available": self.runtime_control is not None,
                "transition_available": transition_available,
                "transitions": [transition_status(db, row["request_id"]) for row in rows(db, "execution_transition", CATALOG)],
                "transition_reason": None if transition_available else "当前服务尚未准备执行空间切换。"}

    def definition(self, db, identifier):
        identifier = text(identifier, "数据集编号", 100)
        result = optional(db, KIND, identifier, CATALOG)
        require(result is not None, "已生成的数据集不存在", web.HTTPNotFound)
        return result

    def history(self, db, namespace, query):
        from runtime_records_query import read_runtime_records
        validate_namespace(namespace)
        self.store.active(db, NAMESPACE)
        archive = optional(db, "execution_archive", namespace, CATALOG)
        require(archive is not None and archive["state"] == "READ_ONLY", "历史执行空间不存在", web.HTTPNotFound)
        require(db.execute("SELECT active FROM spaces WHERE namespace=?", (namespace,)).fetchone() == (0,), "历史空间状态已经变化")
        parameters = parse_qs(query, keep_blank_values=True)
        require(all(len(values) == 1 for values in parameters.values()), "历史查询字段重复", web.HTTPBadRequest)
        runs = read_runtime_records(self.store, "MAINTAINER", namespace, query={key: values[0] for key, values in parameters.items()}, historical=True)
        initial = self.store.get(db, namespace, "initial", "snapshot")
        counts = dict(db.execute("SELECT kind,count(*) FROM objects WHERE namespace=? GROUP BY kind", (namespace,)))
        return {"namespace": namespace, "state": "READ_ONLY", "dataset_id": initial["dataset_id"],
                "dataset_version": initial["dataset_version"], "archived_at": archive["archived_at"],
                "private_body_available_here": False, "current_evidence_eligible": False,
                "counts": {"sessions": len(archive["sessions"]), **{kind: counts.get(kind, 0) for kind in
                           ("memory", "task", "owner_plan", "outbox", "query", "runtime_run")}}, "runtime": runs}

    def stage_execution(self, db, identifier, version, namespace, previous_namespace):
        validate_namespace(namespace)
        self.store.active(db, previous_namespace)
        item = self.definition(db, identifier)
        require(item["version"] == version, "数据集版本已经变化")
        self.validate(db, item)
        require(db.execute("SELECT 1 FROM spaces WHERE namespace=?", (namespace,)).fetchone() is None,
                "目标执行空间已经存在")
        facts = item["facts"]
        self.store.initialize_in_transaction(db, namespace, facts["initial"])
        db.execute("UPDATE spaces SET active=0 WHERE namespace=?", (namespace,))
        for request in facts["imports"]:
            self.supply._import(db, _context(facts, namespace), request)
        manifest = {"namespace": namespace, "previous_namespace": previous_namespace, "dataset_id": item["id"],
                    "dataset_version": item["version"], "facts_sha256": item["facts_sha256"], "created_at": now(),
                    "state": "PREPARED", "runtime_adopted_at": None,
                    "prepared_content_sha256": _content_hash(db, namespace)}
        self.store.put(db, namespace, "execution_space", "current", manifest)
        require_dataset_scope(db, namespace, facts["initial"])
        return manifest

    def commit_execution(self, db, namespace, previous_namespace, expected_facts_sha256):
        self.store.active(db, previous_namespace)
        manifest = self.store.get(db, namespace, "execution_space", "current")
        require(manifest["state"] == "PREPARED" and manifest["previous_namespace"] == previous_namespace
                and manifest["facts_sha256"] == expected_facts_sha256, "准备空间与当前切换要求不一致")
        current = db.execute("SELECT namespace FROM spaces WHERE active=1").fetchall()
        require(current == [(previous_namespace,)], "当前执行空间无法唯一确定")
        inflight = db.execute(
            "SELECT 1 FROM objects WHERE namespace=? AND kind='runtime_run' "
            "AND json_extract(body,'$.status') IN ('QUEUED','RUNNING','WAITING_INPUT') "
            "AND json_extract(body,'$.finished_at') IS NULL LIMIT 1", (previous_namespace,)).fetchone()
        require(inflight is None, "当前运行尚未停止，需要完成暂停后切换")
        prepared = [(kind, identifier, json.loads(body)) for kind, identifier, body in db.execute(
            "SELECT kind,id,body FROM objects WHERE namespace=? AND kind<>'execution_space' ORDER BY kind,id", (namespace,))]
        require(checksum(prepared) == manifest["prepared_content_sha256"], "准备资料发生变化，需要重新核查")
        manifest.update(state="PENDING_RUNTIME", activated_at=now())
        self.store.put(db, namespace, "execution_space", "current", manifest)
        previous = optional(db, "execution_space", "current", previous_namespace)
        if previous is not None:
            previous.update(state="READ_ONLY", archived_at=now(), replaced_by=namespace)
            self.store.put(db, previous_namespace, "execution_space", "current", previous)
        db.execute("UPDATE spaces SET active=0 WHERE namespace=?", (previous_namespace,))
        db.execute("UPDATE spaces SET active=1 WHERE namespace=?", (namespace,))
        return manifest

    def mutate(self, db, action, payload):
        if action == "generate":
            facts = generate_facts({key: value for key, value in payload.items() if key != "client_request_id"})
            previous = optional(db, KIND, facts["id"], CATALOG)
            if previous is not None:
                require(previous["facts_sha256"] == checksum(facts), "同一生成版本产生了不同事实")
                self.validate(db, previous)
                return {"dataset_id": previous["id"], "version": previous["version"], "state": previous["state"],
                        "facts_sha256": previous["facts_sha256"], "reused": True}
            namespace = "dataset-candidate:" + facts["id"] + ":v" + facts["version"]
            self.store.initialize_in_transaction(db, namespace, facts["initial"])
            db.execute("UPDATE spaces SET active=0 WHERE namespace=?", (namespace,))
            context = _context(facts, namespace)
            for request in facts["imports"]:
                IMPORT_VALIDATOR.validate(request)
                self.supply._import(db, context, request)
            item = {key: facts[key] for key in ("id", "version", "parameters", "provenance", "totals", "counts")}
            item.update({"facts": facts, "facts_sha256": checksum(facts), "candidate_namespace": namespace,
                         "candidate_sha256": _content_hash(db, namespace), "created_at": now(), "state": "GENERATED"})
            item["checks"] = self.validate(db, item)
            item.update({"state": "VALIDATED", "validated_at": now()})
            self.store.put(db, CATALOG, KIND, item["id"], item)
            return {"dataset_id": item["id"], "version": item["version"], "state": item["state"],
                    "facts_sha256": item["facts_sha256"], "reused": False}
        if action == "validate":
            require(set(payload) == {"client_request_id", "dataset_id", "expected_dataset_version"}, "关系检查字段无效", web.HTTPBadRequest)
            item = self.definition(db, payload["dataset_id"])
            require(payload["expected_dataset_version"] == item["version"], "数据集版本已经变化")
            item["checks"] = self.validate(db, item)
            item.update({"state": "VALIDATED", "validated_at": now()})
            self.store.put(db, CATALOG, KIND, item["id"], item)
            return {"dataset_id": item["id"], "version": item["version"], "state": item["state"], "checks": item["checks"]}
        if action == "inspect-reset":
            require(set(payload) == {"client_request_id", "expected_namespace"}, "影响检查字段无效", web.HTTPBadRequest)
            require(payload["expected_namespace"] == NAMESPACE, "当前执行空间已经变化")
            impact = self.impact(db)
            self.store.put(db, NAMESPACE, "dataset_reset_impact", "current", impact)
            return impact
        require(action in {"load", "reset"}, "数据集操作不存在", web.HTTPNotFound)
        controller = self.runtime_control.execution_transition if self.runtime_control is not None else None
        require(controller is not None, "当前服务未连接执行空间切换组件")
        return controller.request(db, action, payload)

    def validate(self, db, item):
        facts, namespace = item["facts"], item["candidate_namespace"]
        require(checksum(facts) == item["facts_sha256"], "数据集事实与生成摘要不一致")
        require(_content_hash(db, namespace) == item["candidate_sha256"], "候选资料发生变化，需要核查内容完整性")
        initial = self.store.get(db, namespace, "initial", "snapshot")
        require(initial == facts["initial"], "候选初始资料与生成记录不一致")
        require(initial["memory"] is None and initial["private_calendar"] is None and not initial["boss_profile"]["goals"]
                and not initial["boss_profile"]["confirmed_reading_requirement"], "生成资料不能包含本人确认内容", web.HTTPForbidden)
        for kind in ("authorization", "authorization_binding", "memory", "task", "outbox", "runtime_run", "owner_goals", "owner_notice"):
            require(not rows(db, kind, namespace), "生成候选不能包含本人决定或执行结果", web.HTTPForbidden)
        details = initial["details"]
        require(len({row["record_id"] for row in details}) == len(details), "经营明细编号重复")
        for period, totals in facts["totals"].items():
            selected = [row for row in details if row["period"] == period]
            require(bool(selected), "比较期间缺少经营明细")
            for field, total in totals.items():
                require(sum(Decimal(row[field]) for row in selected) == Decimal(total), "经营汇总与原始明细不一致")
        context = _context(facts, namespace)
        world = external_records(db, namespace)
        contacts = {contact["contact_id"]: contact for contact in initial["contacts"]}
        require(len(contacts) == len(initial["contacts"]), "初始联系人编号重复")
        meeting, event, historical = initial["meeting"], initial["event"], initial["historical_task"]
        require(set(meeting["participant_ids"]) <= contacts.keys(), "会议参与者缺少联系人资料")
        document_ids = {document["source_id"] for document in initial["documents"]}
        require(set(meeting["material_ids"]) <= document_ids | {event["event_id"]}, "会议材料引用不存在")
        require(event["meeting_id"] == meeting["meeting_id"] and event["task_id"] == historical["task_id"]
                and event["coordinator_id"] in contacts and meeting["historical_commitment_ids"] == [historical["task_id"]],
                "会议、事件与历史事项关系不完整")
        require(all(document["author_contact_id"] in contacts for document in initial["documents"]), "初始来源作者缺少联系人资料")
        for request in facts["imports"]:
            IMPORT_VALIDATOR.validate(request)
            for entry in request["records"]:
                kind = entry["entity_type"]
                identifier = entry["data"][ENTITY_CONFIG[kind]["id"]]
                require((kind, identifier) in world, "生成的关联资料尚未保存")
                record = world[(kind, identifier)]
                require(record["data"] == entry["data"], "关联资料与原始生成事实不一致")
                self.supply._validate_record(record, None, initial, context)
                self.supply._validate_relationships(record, world, contacts, initial)
                references = bound_source_references(db, context, kind, record)
                require(bool(references), "关联资料缺少来源采用记录")
                for reference in references:
                    document = self.store.get(db, namespace, "document", reference["source_id"])
                    require(document["version"] == reference["version"] and checksum(document) == reference["source_sha256"],
                            "资料来源版本与采用记录不一致")
        self.supply._validate_processing(world)
        self.supply._validate_cost_periods(world)
        return [{"name": "实体关系", "state": "PASSED", "message": f"已核查{len(world)}项供需与品质记录的引用、作者和业务归属。"},
                {"name": "数值平衡", "state": "PASSED", "message": "期间汇总由经营明细计算，库存可用量及加工投入产出关系通过检查。"},
                {"name": "来源属性", "state": "PASSED", "message": "全部生成资料标记SIMULATED，来源版本与内容摘要一致。"},
                {"name": "本人决定隔离", "state": "PASSED", "message": "候选空间没有生成本人记忆、目标确认、动作授权或执行结果。"}]

    def details(self, db, identifier, query):
        item = self.definition(db, identifier)
        parsed = parse_qs(query, keep_blank_values=True)
        require(set(parsed) <= {"kind", "offset"} and all(len(values) == 1 for values in parsed.values()), "生成明细查询字段无效", web.HTTPBadRequest)
        kind = parsed.get("kind", ["financial_detail"])[0]
        offset_text = parsed.get("offset", ["0"])[0]
        require(offset_text.isascii() and offset_text.isdecimal() and len(offset_text) <= 8, "明细位置无效", web.HTTPBadRequest)
        offset = int(offset_text)
        require(kind in item["counts"] and offset >= 0, "生成明细范围无效", web.HTTPBadRequest)
        facts = item["facts"]
        if kind == "financial_detail":
            records = facts["initial"]["details"]
        elif kind == "initial_contact":
            records = facts["initial"]["contacts"]
        elif kind == "initial_document":
            records = facts["initial"]["documents"]
        else:
            records = [self.store.get(db, item["candidate_namespace"], kind, entry["data"][ENTITY_CONFIG[kind]["id"]])
                       for request in facts["imports"] for entry in request["records"] if entry["entity_type"] == kind]
        require(checksum(facts) == item["facts_sha256"] and _content_hash(db, item["candidate_namespace"]) == item["candidate_sha256"],
                "生成明细完整性检查失败")
        return {"dataset_id": item["id"], "version": item["version"], "source_type": "SIMULATED", "kind": kind,
                "facts_sha256": item["facts_sha256"], "offset": offset, "limit": PAGE_SIZE,
                "total": len(records), "records": records[offset:offset + PAGE_SIZE], "read_at": now()}
