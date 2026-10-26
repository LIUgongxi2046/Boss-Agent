import hashlib
import json
import sqlite3
import uuid
from time import monotonic
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from aiohttp import web
from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parent
SPEC = json.loads((ROOT.parent / "specs/selection-probe.json").read_text())
TOOL_SCHEMA_EXTENSION = json.loads((ROOT.parent / "specs/business-tools.schema.json").read_text())
BI_SCHEMA = json.loads((ROOT.parent / "specs/bi-query.schema.json").read_text())
LEGACY_BI_DEFS = {"legacy_query_input": SPEC["io_schema"]["$defs"]["query_input"], "legacy_query_output": SPEC["io_schema"]["$defs"]["query_output"]}
SPEC["io_schema"] = {**SPEC["io_schema"], "$id": TOOL_SCHEMA_EXTENSION["$id"],
                     "$defs": {**SPEC["io_schema"]["$defs"], **TOOL_SCHEMA_EXTENSION["$defs"], **LEGACY_BI_DEFS, **BI_SCHEMA["$defs"]}}
OPERATIONS = {item["operation_id"]: item for item in SPEC["operations"]}


def now():
    return datetime.now(timezone.utc).isoformat()


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def checksum(value):
    return hashlib.sha256(encode(value).encode()).hexdigest()


def require(condition, message, error=web.HTTPConflict):
    if not condition:
        raise error(text=message)


def validate(name, value):
    schema = {**SPEC["io_schema"], "$ref": f"#/$defs/{name}"}
    errors = list(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(value))
    require(not errors, f"Schema 校验失败：{name}", web.HTTPBadRequest)


def initial_materials():
    details = []
    for period, quantity, revenue, cost in [("BASE", 10000, 40000000, 36000000), ("CURRENT", 12000, 48000000, 44160000)]:
        for index in range(4):
            details.append({"record_id": f"{period}-{index}", "region_id": "region-1", "product_id": f"product-{index % 2 + 1}", "legal_entity_id": "entity-1", "customer_id": f"customer-{index + 1}", "factory_id": f"factory-{index % 2 + 1}", "period": period, "quantity_tonnes": str(quantity // 4), "revenue_cny": str(revenue // 4), "cost_cny": str(cost // 4), "trade_type": "EXTERNAL_SALES", "version": "1"})
    return {
        "source_type": "SIMULATED", "generator_version": "T02-3", "seed": 20261022,
        "owner_id": "boss-1", "dataset_id": "selection", "dataset_version": "1",
        "business_clock": "2026-10-22T09:00:00+08:00",
        "boss_profile": {"owner_id": "boss-1", "goals": ["增长质量", "现金", "本人承诺"], "timezone": "Asia/Shanghai", "confirmed_reading_requirement": "简报优先展示现金与本人承诺。", "version": "1"},
        "metric_definitions": [{"metric_id": metric, "formula": formula, "unit": unit, "precision": "Decimal", "definition_version": "1", "scope": "region-1 EXTERNAL_SALES CNY", "settlement_state": "SETTLED"} for metric, formula, unit in [("sales_quantity", "SUM(quantity_tonnes)", "吨"), ("revenue", "SUM(revenue_cny)", "CNY"), ("cost", "SUM(cost_cny)", "CNY"), ("gross_profit", "revenue-cost", "CNY"), ("gross_margin", "gross_profit/revenue*100", "%"), ("gross_profit_per_tonne", "gross_profit/sales_quantity", "CNY/吨")]],
        "periods": {"BASE": ["2026-09-01", "2026-09-10"], "CURRENT": ["2026-10-01", "2026-10-10"]},
        "details": details,
        "contacts": [{"contact_id": "coordinator-1", "name": "陈明", "organization": "合成区域", "responsibility": "业务统筹", "valid_from": "2026-01-01", "valid_until": "2027-01-01"}, {"contact_id": "finance-1", "name": "李文", "organization": "合成财务", "responsibility": "财务材料作者", "valid_from": "2026-01-01", "valid_until": "2027-01-01"}, {"contact_id": "contact-2", "name": "陈明", "organization": "合成客户", "responsibility": "客户联系人", "valid_from": "2026-01-01", "valid_until": "2027-01-01"}],
        "meeting": {"meeting_id": "meeting-1", "owner_id": "boss-1", "participant_ids": ["coordinator-1", "finance-1"], "starts_at": "2026-10-23T09:00:00+08:00", "timezone": "Asia/Shanghai", "material_ids": ["finance-note", "meeting-minutes", "event-1"], "historical_commitment_ids": ["historical-1"], "version": "1"},
        "event": {"event_id": "event-1", "owner_id": "boss-1", "task_id": "historical-1", "coordinator_id": "coordinator-1", "meeting_id": "meeting-1", "status": "OPEN", "due_at": "2026-10-24T17:00:00+08:00", "evidence_requirements": ["经营原始明细"], "version": "1"},
        "historical_task": {"task_id": "historical-1", "owner_id": "boss-1", "status": "IN_PROGRESS", "due_at": "2026-10-24T17:00:00+08:00", "evidence_requirements": ["经营原始明细"], "version": "1"},
        "documents": [{"source_id": "finance-note", "author_contact_id": "finance-1", "version": "1", "source_type": "SIMULATED", "published_at": "2026-10-11T08:00:00+08:00", "valid_from": "2026-10-11T08:00:00+08:00", "access_scope": "boss-1", "original_locator": "sqlite:documents/finance-note", "content": "合成水产饲料外销明细；毛利=收入减成本，毛利率=毛利除收入，单吨毛利=毛利除吨数。原因贡献明细尚未提供。"}, {"source_id": "meeting-minutes", "author_contact_id": "coordinator-1", "version": "1", "source_type": "SIMULATED", "published_at": "2026-10-12T10:00:00+08:00", "valid_from": "2026-10-12T10:00:00+08:00", "access_scope": "boss-1", "original_locator": "sqlite:documents/meeting-minutes", "content": "合成历史会议纪要：historical-1 由 coordinator-1 统筹准备经营原始明细，尚未收到本人完成决定；关联经营事件 event-1 保持 OPEN。"}],
        "private_calendar": {"calendar_id": "private-1", "owner_id": "boss-1", "starts_at": "2026-10-24T18:00:00+08:00", "ends_at": "2026-10-24T19:00:00+08:00", "timezone": "Asia/Shanghai", "private_body": "获准模拟私人安排", "visibility": "PRIVATE"},
        "memory": {"memory_id": "memory-1", "memory_version": "1", "version": "1", "confirmation_state": "CONFIRMED", "text": "简报优先展示现金与本人承诺。"},
    }


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS objects(namespace TEXT, kind TEXT, id TEXT, body TEXT NOT NULL, PRIMARY KEY(namespace, kind, id));
                CREATE TABLE IF NOT EXISTS spaces(namespace TEXT PRIMARY KEY, active INTEGER NOT NULL, snapshot TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS idempotency(namespace TEXT, operation TEXT, key TEXT, digest TEXT, result TEXT, PRIMARY KEY(namespace, operation, key));
                CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY, namespace TEXT, operation TEXT, input TEXT, output TEXT, created_at TEXT);
            """)
            indexed = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='knowledge_text'").fetchone()
            db.executescript("""
                CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_text USING fts5(namespace UNINDEXED,source_id UNINDEXED,content,tokenize='trigram');
                CREATE TRIGGER IF NOT EXISTS document_text_insert AFTER INSERT ON objects WHEN new.kind='document' BEGIN
                    INSERT INTO knowledge_text(namespace,source_id,content) SELECT new.namespace,new.id,json_extract(new.body,'$.content') WHERE coalesce(json_extract(new.body,'$.withdrawn'),0)=0;
                END;
                CREATE TRIGGER IF NOT EXISTS document_text_update AFTER UPDATE ON objects WHEN new.kind='document' BEGIN
                    DELETE FROM knowledge_text WHERE namespace=old.namespace AND source_id=old.id;
                    INSERT INTO knowledge_text(namespace,source_id,content) SELECT new.namespace,new.id,json_extract(new.body,'$.content') WHERE coalesce(json_extract(new.body,'$.withdrawn'),0)=0;
                END;
                CREATE TRIGGER IF NOT EXISTS document_text_delete AFTER DELETE ON objects WHEN old.kind='document' BEGIN
                    DELETE FROM knowledge_text WHERE namespace=old.namespace AND source_id=old.id;
                END;
            """)
            if indexed is None:
                db.execute("INSERT INTO knowledge_text(namespace,source_id,content) SELECT namespace,id,json_extract(body,'$.content') FROM objects WHERE kind='document' AND coalesce(json_extract(body,'$.withdrawn'),0)=0")

    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA journal_mode=WAL")
        return db

    def get(self, db, ns, kind, key):
        row = db.execute("SELECT body FROM objects WHERE namespace=? AND kind=? AND id=?", (ns, kind, key)).fetchone()
        require(row is not None, "对象不存在", web.HTTPNotFound)
        return json.loads(row[0])

    def put(self, db, ns, kind, key, value):
        db.execute("INSERT INTO objects VALUES(?,?,?,?) ON CONFLICT(namespace,kind,id) DO UPDATE SET body=excluded.body", (ns, kind, key, encode(value)))

    def initialize(self, ns):
        data = initial_materials()
        with self.connect() as db:
            self.initialize_in_transaction(db, ns, data)
        return {"namespace": ns, "snapshot_sha256": checksum(data)}

    def initialize_in_transaction(self, db, ns, data):
        db.execute("INSERT INTO spaces VALUES(?,1,?)", (ns, checksum(data)))
        self.put(db, ns, "initial", "snapshot", data)
        if data["memory"] is not None:
            self.put(db, ns, "memory", "current", data["memory"])
        self.put(db, ns, "configuration", "current", {"config_id": "runtime-1", "version": "1", "provider": "deepseek", "api_type": "chat_completions", "model_id": "deepseek-flash", "credential_ref": "connection.json:credential_file", "tool_scope": list(OPERATIONS), "max_tool_rounds": 12, "timeout": 120, "enabled": True})
        self.put(db, ns, "schedule", "current", {"schedule_id": "schedule-1", "schedule_version": "1", "version": "1", "trigger": "EVENT_OR_TIME", "timezone": "Asia/Shanghai", "enabled": True, "canceled": False})
        self.put(db, ns, "clock", "current", {"at": data["business_clock"], "version": "1"})
        db.execute("CREATE VIRTUAL TABLE IF NOT EXISTS knowledge USING fts5(namespace UNINDEXED, source_id UNINDEXED, content)")
        for document in data["documents"]:
            self.put(db, ns, "document", document["source_id"], document)
            db.execute("INSERT INTO knowledge VALUES(?,?,?)", (ns, document["source_id"], document["content"]))

    def active(self, db, ns):
        row = db.execute("SELECT active FROM spaces WHERE namespace=?", (ns,)).fetchone()
        require(row is not None and row[0] == 1, "执行空间已失效")

    def authorize(self, ns, action, payload):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            return self.authorize_in_transaction(db, ns, action, payload)

    def authorize_in_transaction(self, db, ns, action, payload):
        require(action in ("create_assignment", "send_assignment", "extend_assignment", "complete_assignment"), "动作无效", web.HTTPBadRequest)
        self.active(db, ns)
        data = self.get(db, ns, "initial", "snapshot")
        auth_id = str(uuid.uuid4())
        issued = datetime.now(timezone.utc)
        self.put(db, ns, "authorization", auth_id, {"authorization_id": auth_id, "owner_id": data["owner_id"], "issuer_identity": "BOSS", "issuer": data["owner_id"], "source_instruction_id": str(uuid.uuid4()), "source_instruction": encode(payload), "action": action, "target_id": payload.get("task_id", "new-assignment"), "content_version": payload.get("content_version", payload.get("task_version", "1")), "scope": ns, "payload": payload, "version": "1", "revoked": False, "revoked_at": None, "valid_from": issued.isoformat(), "valid_until": (issued + timedelta(minutes=15)).isoformat()})
        self.put(db, ns, "authorization_binding", action, {"authorization_id": auth_id, "idempotency_key": checksum({"action": action, "payload": payload})})
        return auth_id

    def invoke(self, operation, payload):
        from boss_v7_configuration import record_use, tool_policy, validate_tool_value
        started = monotonic()
        require(operation in OPERATIONS, "未知业务操作", web.HTTPNotFound)
        validate(OPERATIONS[operation]["input_schema"].rsplit("/", 1)[1], payload)
        env = payload["envelope"]
        ns = env["execution_namespace"]
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self.active(db, ns)
            data = self.get(db, ns, "initial", "snapshot")
            from boss_execution_scope import require_dataset_scope
            require_dataset_scope(db, ns, data)
            require(all(env[field] == data[field] for field in ("owner_id", "dataset_id", "dataset_version")),
                    "本人或数据版本不符", web.HTTPForbidden)
            policy = tool_policy(db, operation, ns)
            validate_tool_value(policy, "input", payload)
            if operation in ("create_assignment", "send_assignment"):
                content = {k: v for k, v in payload.items() if k not in ("envelope", "authorization_id", "idempotency_key")}
                digest = checksum(content)
                previous = db.execute("SELECT digest,result FROM idempotency WHERE namespace=? AND operation=? AND key=?", (ns, operation, payload["idempotency_key"])).fetchone()
                if previous:
                    require(previous[0] == digest, "幂等内容冲突")
                    return json.loads(previous[1])
                auth = self.get(db, ns, "authorization", payload["authorization_id"])
                require(auth["authorization_id"] == payload["authorization_id"], "授权标识与当前对象不符", web.HTTPForbidden)
                self.require_current_authorization(auth, ns, data, operation, content)
                require(content == auth["payload"], "授权对象或内容版本不符", web.HTTPForbidden)
                used = db.execute("SELECT id FROM objects WHERE namespace=? AND kind=? AND json_extract(body,'$.authorization_id')=?",
                                  (ns, "task" if operation == "create_assignment" else "outbox", payload["authorization_id"])).fetchone()
                require(used is None, "当前授权已经产生业务结果，请查询原请求回执")
            result = getattr(self, operation)(db, ns, data, payload)
            validate(OPERATIONS[operation]["output_schema"].rsplit("/", 1)[1], result)
            validate_tool_value(policy, "output", result)
            if policy is not None:
                require(monotonic() - started <= policy["values"]["timeout_seconds"], "工具执行超过已启用的时间限制", web.HTTPRequestTimeout)
                record_use(self, db, "tools", operation, policy["version"], env["request_id"], ns)
            if operation in ("create_assignment", "send_assignment"):
                db.execute("INSERT INTO idempotency VALUES(?,?,?,?,?)", (ns, operation, payload["idempotency_key"], digest, encode(result)))
            audit_input = {"request_id": env["request_id"], "session_id": env["session_id"],
                           "owner_id": env["owner_id"], "dataset_id": env["dataset_id"], "dataset_version": env["dataset_version"],
                           **{key: payload[key] for key in ("authorization_id", "idempotency_key", "task_id", "query_id") if key in payload}}
            audit_output = {key: result[key] for key in (
                "task_id", "query_id", "status", "version", "message_id", "message_status",
                "task_status", "task_version", "authorization_id", "execution_namespace",
            ) if key in result}
            db.execute("INSERT INTO audit(namespace,operation,input,output,created_at) VALUES(?,?,?,?,?)", (ns, operation, encode(audit_input), encode(audit_output), now()))
        return result

    def require_current_authorization(self, authorization, ns, data, operation, content):
        require(authorization.get("owner_id") == data["owner_id"] and authorization.get("scope") == ns
                and authorization.get("issuer_identity") == "BOSS" and authorization.get("issuer") == data["owner_id"]
                and authorization.get("action") == operation and authorization.get("revoked") is False
                and authorization.get("target_id") == content.get("task_id", "new-assignment")
                and authorization.get("content_version") == content.get("content_version", content.get("task_version", "1")),
                "授权身份、范围或内容版本不符", web.HTTPForbidden)
        start = datetime.fromisoformat(authorization["valid_from"])
        end = datetime.fromisoformat(authorization["valid_until"])
        require(start.tzinfo is not None and end.tzinfo is not None and start <= datetime.now(timezone.utc) < end,
                "当前授权尚未生效或已经到期", web.HTTPForbidden)

    def assignment_sources(self, db, ns, data, source_ids):
        from boss_source_access import require_current_simulated_source
        require(source_ids and len(set(source_ids)) == len(source_ids), "交办来源缺少或重复", web.HTTPBadRequest)
        clock = self.get(db, ns, "clock", "current")["at"]
        documents = {source_id: require_current_simulated_source(self.get(db, ns, "document", source_id), data["owner_id"], clock)
                     for source_id in source_ids}
        from boss_supply_quality import DEFINITION, require_external_source_dependencies, external_adoption
        for document in documents.values():
            if document.get("simulation_definition") == DEFINITION:
                require_external_source_dependencies(self, db, ns, data, document)
            elif document.get("simulation_definition") == "FC04-ALERT-1":
                require(external_adoption(db, ns, data, clock, document)["state"] == "CURRENT", "经营报告的原始依据已变化，需要重新载入当前资料")
        return documents

    def require_current_assignment_sources(self, db, ns, data, task):
        documents = self.assignment_sources(db, ns, data, task["source_refs"])
        row = db.execute("SELECT body FROM objects WHERE namespace=? AND kind='assignment_source_binding' AND id=?", (ns, task["task_id"])).fetchone()
        require(row is not None, "交办缺少创建时来源绑定，需要本人重新核查")
        binding = json.loads(row[0])
        require(binding["task_id"] == task["task_id"] and binding["owner_id"] == data["owner_id"] and binding["dataset_id"] == data["dataset_id"]
                and binding["dataset_version"] == data["dataset_version"], "交办来源绑定不属于当前范围", web.HTTPForbidden)
        require(set(binding["source_versions"]) == set(documents) == set(binding["source_fingerprints"])
                and all(binding["source_versions"][identifier] == document["version"]
                        and binding["source_fingerprints"][identifier] == checksum(document) for identifier, document in documents.items()),
                "交办来源版本或内容已经变化，需要重新核查")
        if task.get("origin_source_id"):
            source_id = task["origin_source_id"]
            origin = self.assignment_sources(db, ns, data, [source_id])[source_id]
            require(binding.get("origin_source") == {"source_id": source_id, "version": origin["version"], "sha256": checksum(origin)},
                    "交办原始纪要的来源已经变化，需要重新核查")

    def require_current_coordinator(self, db, ns, data, coordinator_id):
        contacts = [contact for contact in data["contacts"] if contact["contact_id"] == coordinator_id]
        require(len(contacts) == 1, "负责人不在当前获准资料内", web.HTTPForbidden)
        today = datetime.fromisoformat(self.get(db, ns, "clock", "current")["at"]).astimezone(ZoneInfo(data["boss_profile"]["timezone"])).date()
        require(date.fromisoformat(contacts[0]["valid_from"]) <= today <= date.fromisoformat(contacts[0]["valid_until"]),
                "负责人在当前业务时间已经失效", web.HTTPForbidden)

    def _metric_source(self, db, ns, data):
        from boss_source_access import require_current_simulated_source
        document = self.get(db, ns, "document", "finance-note")
        require(document["source_id"] == "finance-note", "资料标识与当前引用不符", web.HTTPForbidden)
        return require_current_simulated_source(document, data["owner_id"], self.get(db, ns, "clock", "current")["at"])

    def source(self, document, data, quality_state):
        as_of = datetime.combine(date.fromisoformat(data["periods"]["CURRENT"][1]), time(23, 59, 59), ZoneInfo(data["boss_profile"]["timezone"]))
        return {"source_id": document["source_id"], "source_type": document["source_type"], "version": document["version"],
                "locator": document["original_locator"], "business_as_of": as_of.isoformat(),
                "source_updated_at": document["published_at"], "read_at": now(),
                "coverage": "region-1 水产饲料外销，两个十日期间", "quality_state": quality_state}

    def query_metrics(self, db, ns, data, p):
        if p.get("query_mode") == "SCOPED":
            from boss_bi_queries import query_metrics
            return query_metrics(self, db, ns, data, p)
        from boss_metrics import aggregate_metrics, compare_metrics
        from boss_v7_metrics import apply_configurations, display_rounding, policy_fingerprint, record_adoption
        document = self._metric_source(db, ns, data)
        require(p["region_id"] == "region-1" and p["definition_version"] == "1", "范围或口径不可用", web.HTTPBadRequest)
        require([p["period_start"], p["period_end"]] == data["periods"]["CURRENT"] and [p["comparison_start"], p["comparison_end"]] == data["periods"]["BASE"], "期间不可比", web.HTTPBadRequest)
        require(set(p["product_ids"]) <= {"product-1", "product-2"}, "产品资料缺少", web.HTTPBadRequest)
        records = [r for r in data["details"] if r["product_id"] in p["product_ids"]]
        values = []
        missing = []
        period_metrics = {}
        calculations = {}
        policy_at = datetime.now(timezone.utc)
        for period in ("BASE", "CURRENT"):
            group = [r for r in records if r["period"] == period]
            computed = aggregate_metrics(group)
            metrics, calculations[period] = apply_configurations(db, ns, group, computed["metrics"], cache=True, at=policy_at)
            period_metrics[period] = metrics
            missing.extend(period + ":" + field for field in computed["missing_fields"])
            missing.extend(period + ":" + identifier + ":" + field for identifier, calculation in calculations[period].items() for field in calculation["missing_fields"])
            for metric in p["metric_ids"]:
                value, unit, formula = metrics[metric]
                metric_scope = encode({"region_id": p["region_id"], "product_ids": p["product_ids"],
                                      "metric_configuration": {key: calculations[period][metric][key] for key in ("configuration_version", "scope", "breakdown")}}) if metric in calculations[period] else f"region-1 {p['product_ids']}"
                values.append({"metric_id": metric, "period_scope": period, "scope_description": metric_scope, "value": str(value) if value is not None else None, "unit": unit, "formula": formula, "definition_version": "1", "display_rounding": display_rounding(calculations[period][metric]) if metric in calculations[period] else "原始 Decimal 精度"})
        for metric, (value, unit, formula) in compare_metrics(period_metrics["BASE"], period_metrics["CURRENT"]).items():
            if metric in p["metric_ids"]:
                values.append({"metric_id": metric, "period_scope": "CHANGE", "scope_description": f"region-1 {p['product_ids']}", "value": str(value) if value is not None else None, "unit": unit, "formula": formula, "definition_version": "1", "display_rounding": "原始 Decimal 精度"})
        result = {"query_id": str(uuid.uuid4()), "envelope": p["envelope"], "values": values, "detail_refs": [r["record_id"] for r in records], "sources": [self.source(document, data, "INCOMPLETE" if missing else "COMPLETE")], "missing_fields": missing, "unexplained_causes": ["原因贡献明细尚未提供"]}
        self.put(db, ns, "query", result["query_id"], result)
        self.put(db, ns, "query_source_binding", result["query_id"], {
            "query_id": result["query_id"], "owner_id": data["owner_id"], "dataset_id": data["dataset_id"], "dataset_version": data["dataset_version"],
            "source_id": document["source_id"], "source_version": document["version"], "source_sha256": checksum(document),
            "detail_fingerprints": {row["record_id"]: checksum(row) for row in records},
            "metric_policy_sha256": policy_fingerprint(db, ns, policy_at), "metric_calculations": calculations,
        })
        record_adoption(self, db, ns, result["query_id"], calculations)
        return result

    def read_evidence(self, db, ns, data, p):
        query = self.get(db, ns, "query", p["query_id"])
        if "context_snapshot" in query:
            from boss_bi_queries import read_evidence
            return read_evidence(self, db, ns, data, p, query)
        require(set(p["detail_refs"]) <= set(query["detail_refs"]) and p["source_ids"] == ["finance-note"], "依据范围不符", web.HTTPForbidden)
        document = self._metric_source(db, ns, data)
        row = db.execute("SELECT body FROM objects WHERE namespace=? AND kind='query_source_binding' AND id=?", (ns, p["query_id"])).fetchone()
        require(row is not None, "查询缺少完整来源绑定，需要重新查询")
        binding = json.loads(row[0])
        from boss_v7_metrics import policy_fingerprint
        require(binding.get("metric_policy_sha256", checksum({})) == policy_fingerprint(db, ns), "指标配置已经变化，需要重新查询")
        require(binding["owner_id"] == data["owner_id"] and binding["dataset_id"] == data["dataset_id"]
                and binding["dataset_version"] == data["dataset_version"], "查询绑定不属于当前范围", web.HTTPForbidden)
        require(binding["source_id"] == document["source_id"] and binding["source_version"] == document["version"]
                and binding["source_sha256"] == checksum(document), "来源版本或内容已经变化，需要重新查询")
        records = [record for record in data["details"] if record["record_id"] in p["detail_refs"]]
        require(len(records) == len(p["detail_refs"]) and all(binding["detail_fingerprints"][record["record_id"]] == checksum(record) for record in records),
                "明细版本或内容已经变化，需要重新查询")
        return {"sources": [self.source(document, data, query["sources"][0]["quality_state"])],
                "original_records": [{"record_id": record["record_id"], "version": record["version"], "content": record} for record in records]
                + [{"record_id": document["source_id"], "version": document["version"], "content": document}],
                "definition_version": "1", "conflicts": [], "missing_fields": ["原因贡献明细"]}

    def create_assignment(self, db, ns, data, p, *, verified_morning_selection=False):
        from boss_supply_quality import DEFINITION
        require(p["coordinator_id"] == "coordinator-1", "负责人不属于当前业务范围", web.HTTPBadRequest)
        if p["related_meeting_id"] is not None:
            row = db.execute("SELECT body FROM objects WHERE namespace=? AND kind='meeting' AND id=?", (ns, p["related_meeting_id"])).fetchone()
            meeting = json.loads(row[0]) if row else data["meeting"]
            require(meeting["meeting_id"] == p["related_meeting_id"] and meeting["owner_id"] == data["owner_id"], "关联会议不属于当前本人范围", web.HTTPForbidden)
        require(len(set(p["related_event_ids"])) == len(p["related_event_ids"]), "关联事件重复", web.HTTPBadRequest)
        for identifier in p["related_event_ids"]:
            row = db.execute("SELECT body FROM objects WHERE namespace=? AND kind='event' AND id=?", (ns, identifier)).fetchone()
            event = json.loads(row[0]) if row else data["event"]
            # 正式维护事件从当前namespace继承本人；显式归属仍必须一致。
            require(event["event_id"] == identifier and event.get("owner_id", data["owner_id"]) == data["owner_id"], "关联事件不属于当前本人范围", web.HTTPForbidden)
        documents = self.assignment_sources(db, ns, data, p["source_refs"])
        # Existing unbound/MVP assignments retain their original dataset
        # whitelist. The only exception is a F01 selection already verified
        # against an authenticated CURRENT morning list, exact item, snapshot,
        # owner and document refs by BossCommandAPI._create.
        require(verified_morning_selection or all(
            identifier == "finance-note" or document.get("simulation_definition") in (DEFINITION, "FC04-ALERT-1")
            for identifier, document in documents.items()),
            "来源不属于当前明确支持的交办资料", web.HTTPBadRequest)
        self.require_current_coordinator(db, ns, data, p["coordinator_id"])
        due = datetime.fromisoformat(p["due_at"])
        from zoneinfo import available_timezones
        require(p["timezone"] in available_timezones(), "交办时区无效", web.HTTPBadRequest)
        require(due.astimezone(ZoneInfo(p["timezone"])).utcoffset() == due.utcoffset(), "交办期限与时区不符", web.HTTPBadRequest)
        require(due.tzinfo is not None and due > datetime.fromisoformat(self.get(db, ns, "clock", "current")["at"]),
                "交办期限必须晚于当前业务时间", web.HTTPBadRequest)
        task_id = str(uuid.uuid4())
        task = {k: p[k] for k in ("purpose", "coordinator_id", "due_at", "timezone", "evidence_requirements", "authorization_id", "related_meeting_id", "related_event_ids", "source_refs")}
        task["source_versions"] = {identifier: document["version"] for identifier, document in documents.items()}
        task.update(task_id=task_id, status="OPEN", version="1", message_ids=[], feedback_ids=[], completion_authorization_id=None, execution_namespace=ns)
        self.put(db, ns, "task", task_id, task)
        self.put(db, ns, "assignment_source_binding", task_id, {
            "task_id": task_id, "owner_id": data["owner_id"], "dataset_id": data["dataset_id"], "dataset_version": data["dataset_version"],
            "source_versions": {identifier: document["version"] for identifier, document in documents.items()},
            "source_fingerprints": {identifier: checksum(document) for identifier, document in documents.items()},
        })
        return {"task_id": task_id, "status": "OPEN", "version": "1", "authorization_id": p["authorization_id"], "execution_namespace": ns, "persisted_at": now()}

    def send_assignment(self, db, ns, data, p):
        task = self.get(db, ns, "task", p["task_id"])
        require(task["version"] == p["task_version"] and task["status"] == "OPEN", "任务版本或状态冲突")
        require(task["coordinator_id"] == p["recipient_id"], "收件人不符", web.HTTPForbidden)
        self.require_current_coordinator(db, ns, data, p["recipient_id"])
        self.require_current_assignment_sources(db, ns, data, task)
        new_version = str(int(task["version"]) + 1)
        result = {"message_id": str(uuid.uuid4()), "task_id": p["task_id"], "message_status": "SENT", "task_status": "WAITING_FEEDBACK", "task_version": new_version, "source_type": "SIMULATED", "sent_at": now()}
        self.put(db, ns, "outbox", result["message_id"], {**p, **result})
        task.update(status="WAITING_FEEDBACK", version=new_version, message_ids=[result["message_id"]])
        self.put(db, ns, "task", p["task_id"], task)
        return result

    def read_assignment(self, db, ns, data, p):
        task = self.get(db, ns, "task", p["task_id"])
        fields = SPEC["io_schema"]["$defs"]["read_output"]["properties"]
        return {field: task[field] for field in fields if field in task}

    def context(self, ns):
        from boss_memory import confirmed_memory, current_memory
        with self.connect() as db:
            db.execute("BEGIN")
            self.active(db, ns)
            memory = current_memory(db, ns)
            data = self.get(db, ns, "initial", "snapshot")
            return {"memory": confirmed_memory(db, ns, memory, data["owner_id"]), "memory_version": memory["version"] if memory else None, "configuration": self.get(db, ns, "configuration", "current")}

    def notify(self, ns, event_id):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self.active(db, ns)
            schedule = self.get(db, ns, "schedule", "current")
            if not schedule["enabled"] or schedule["canceled"]:
                return {"state": "SUPPRESSED", "reason": "计划暂停或取消"}
            key = f"notification:{event_id}"
            previous = db.execute("SELECT body FROM objects WHERE namespace=? AND kind='notification' AND id=?", (ns, key)).fetchone()
            if previous:
                return {"state": "SUPPRESSED", "reason": "重复事件"}
            result = {"state": "DELIVERED", "event_id": event_id, "schedule_version": schedule["version"], "source_type": "SIMULATED", "created_at": now()}
            self.put(db, ns, "notification", key, result)
            return result
