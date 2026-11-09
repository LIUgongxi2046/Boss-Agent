import hashlib
import json
from dataclasses import asdict
from pathlib import Path

from agent_run_broker import RunBroker, RunIdentity
from agent_run_scope import RunScopeService
from agent_run_store import RunStore
from boss_source_access import require_current_business_source
from business import checksum
from hermes_bridge import EngineEventSink
from hermes_domain_intents import draft_domain_request_key


TOOLS = {"save_meeting_draft": ("meeting", "meeting_draft", "boss.meeting.draft.save"), "meetingDraftSave": ("meeting", "meeting_draft", "boss.meeting.draft.save"), "save_minutes_draft": ("minutes", "minutes", "boss.minutes.save")}


class RunActionDrafts:
    def __init__(self, runs, scope):
        if not isinstance(runs, RunStore) or not isinstance(scope, RunScopeService) or runs.path.resolve() != scope.store.path.resolve():
            raise ValueError("草稿与运行数据库不一致")
        self.runs, self.scope = runs, scope

    def inspect_in_transaction(self, db, sink, goal_revision, result_seq, last_input_seq, *, terminal=False, expected_lease_epoch=None, run_id=None, identity=None):
        main = db.execute("PRAGMA database_list").fetchone()
        if not db.in_transaction or main is None or main[1] != "main" or Path(main[2]).resolve() != self.runs.path.resolve():
            raise ValueError("运行草稿核查需要同一数据库事务")
        if type(goal_revision) is not int or goal_revision < 1 or type(result_seq) is not int or type(last_input_seq) is not int or (terminal and (not isinstance(run_id, str) or not run_id.strip() or type(expected_lease_epoch) is not int or expected_lease_epoch < 1 or not isinstance(identity, RunIdentity))) or (not terminal and (not isinstance(sink, EngineEventSink) or sink.store.path.resolve() != self.runs.path.resolve())):
            raise ValueError("运行草稿核查参数无效")
        migration = Path(__file__).parent / "migrations" / "upgrade2_tool_budget_001.sql"
        recorded = db.execute("SELECT sha256 FROM agent_schema_migrations WHERE version='upgrade2_tool_budget_001'").fetchone()
        present = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='agent_tool_reservations'").fetchone()
        if recorded is None and present is None:
            return {"state": "NOT_VERIFIED", "count": 0}
        if recorded != (hashlib.sha256(migration.read_bytes()).hexdigest(),) or present is None:
            raise ValueError("工具预算迁移不可核查")
        run_id = run_id if terminal else sink.config.run_id
        epoch = expected_lease_epoch if terminal else sink.config.lease_epoch
        if terminal:
            self.runs.require_terminal_lineage(db, run_id)
        else:
            self.runs._require_lease(db, run_id, sink.lease_owner, sink.config.lease_epoch)
            self.runs.require_active_lineage(db, run_id)
        run = db.execute("SELECT actor_id,space_id,conversation_id,selected_refs,scope_proof,status,cancel_requested_at,goal_revision,applied_goal_revision FROM agent_runs WHERE run_id=?", (run_id,)).fetchone()
        statuses = {"SUCCEEDED", "FAILED", "CANCELED", "INTERRUPTED"} if terminal else {"RUNNING"}
        if run is None or run[5] not in statuses or run[7:9] != (goal_revision, goal_revision) or (not terminal and run[6] is not None):
            raise ValueError("草稿运行或目标版本不可核查")
        if terminal:
            RunBroker.require_identity(identity)
            if run[:2] != (identity.actor_id, identity.space_id) or run[2] not in identity.conversation_ids or not set(json.loads(run[3])).issubset(identity.source_refs):
                raise ValueError("终态草稿本人身份或会话范围不一致")
            if identity.verify is not None:
                identity.verify()
        proof = self.scope.prove_in_transaction(db, run[2], json.loads(run[3]))
        if (proof.owner_id, proof.namespace) != run[:2] or json.loads(json.dumps(asdict(proof))) != json.loads(run[4]):
            raise ValueError("草稿来源范围已经变化")
        result = db.execute("SELECT type,payload,lease_epoch FROM agent_run_events WHERE run_id=? AND seq=?", (run_id, result_seq)).fetchone()
        if result is None or result[0] != "RESULT_RECORDED" or json.loads(result[1]).get("goal_revision") != goal_revision or result[2] != epoch:
            raise ValueError("草稿结果事件不可核查")
        rows = db.execute("SELECT seq,payload,lease_epoch FROM agent_run_events WHERE run_id=? AND type='TOOL_FINISHED' AND seq>? AND seq<? ORDER BY seq", (run_id, last_input_seq, result_seq)).fetchall()
        count = 0
        seen_calls = set()
        seen_refs = set()
        for seq, raw, event_epoch in rows:
            payload = json.loads(raw)
            tool = payload.get("tool_id")
            if tool not in TOOLS:
                continue
            if "draft_ref" not in payload:
                if terminal:
                    raise ValueError("终态草稿结束事件缺少草稿引用")
                continue
            if payload.get("goal_revision") != goal_revision or event_epoch != epoch:
                raise ValueError("草稿工具事件目标或租约代次不符")
            if set(payload) != {"tool_id", "call_id", "outcome", "goal_revision", "draft_ref"} or payload["outcome"] != "RETURNED":
                raise ValueError("草稿工具事件不可核查")
            kind, object_kind, operation = TOOLS[tool]
            ref = payload["draft_ref"]
            if not isinstance(ref, dict) or set(ref) != {"kind", "object_id", "version", "sha256", "domain_operation", "domain_request_key"} or ref["kind"] != object_kind or ref["domain_operation"] != operation or ref["domain_request_key"] != draft_domain_request_key(kind, run_id, payload["call_id"]):
                raise ValueError("草稿来源关联不可核查")
            if payload["call_id"] in seen_calls:
                raise ValueError("草稿结束事件重复")
            reference = (ref["kind"], ref["object_id"], ref["version"], ref["sha256"])
            if reference in seen_refs:
                raise ValueError("草稿引用集合重复")
            reservation = db.execute("SELECT request_digest,tool_name,lease_epoch FROM agent_tool_reservations WHERE run_id=? AND request_key=?", (run_id, payload["call_id"])).fetchone()
            starts = db.execute("SELECT seq,payload,lease_epoch FROM agent_run_events WHERE run_id=? AND type='TOOL_STARTED' AND json_extract(payload,'$.tool_id')=? AND json_extract(payload,'$.call_id')=?", (run_id, tool, payload["call_id"])).fetchall()
            if reservation is None or reservation[1:] != (tool, epoch) or len(starts) != 1 or not last_input_seq < starts[0][0] < seq or starts[0][2] != epoch or json.loads(starts[0][1]) != {"tool_id": tool, "call_id": payload["call_id"]}:
                raise ValueError("草稿工具请求不可核查")
            domain = db.execute("SELECT digest,result FROM idempotency WHERE namespace=? AND operation=? AND key=?", (run[1], operation, ref["domain_request_key"])).fetchone()
            if domain is None:
                raise ValueError("草稿领域回执不存在")
            receipt = json.loads(domain[1])
            if receipt.get("meeting_id") != ref["object_id"] or receipt.get("version") != ref["version"]:
                raise ValueError("草稿领域回执不可核查")
            object_row = db.execute("SELECT body FROM objects WHERE namespace=? AND kind=? AND id=?", (run[1], object_kind, ref["object_id"])).fetchone()
            if object_row is None:
                if terminal:
                    raise ValueError("终态草稿对象不存在")
                continue
            draft = json.loads(object_row[0])
            if draft.get("version") != ref["version"] or checksum(draft) != ref["sha256"]:
                if terminal:
                    raise ValueError("终态草稿对象版本或摘要不符")
                continue
            version = ref["version"]
            if not isinstance(version, str) or not version.isascii() or not version.isdecimal() or str(int(version)) != version or int(version) < 1:
                raise ValueError("草稿版本不可核查")
            if kind == "meeting":
                params = {"meeting_id": ref["object_id"], "meeting_version": draft["meeting_version"], "expected_version": str(int(version) - 1), **draft["details"]}
            else:
                entries = [{key: item[key] for key in ("kind", "text", "source_anchor")} for item in draft["entries"]]
                params = {"meeting_id": ref["object_id"], "meeting_version": draft["meeting_version"], "expected_version": str(int(version) - 1), "source_id": draft["source_id"], "source_version": draft["source_version"], "entries": entries}
            if domain[0] != checksum({"action": operation, "content": params}) or reservation[0] != checksum({"goal_revision": goal_revision, "scope_proof": json.loads(run[4]), "params": params}):
                if terminal:
                    raise ValueError("终态草稿领域回执或预留摘要不符")
                continue
            pins = {pin[0]: (pin[1], pin[2]) for pin in proof.source_pins}
            refs = draft["details"]["source_refs"] if kind == "meeting" else [{"source_id": draft["source_id"], "version": draft["source_version"]}]
            if not refs:
                raise ValueError("草稿缺少来源")
            for item in refs:
                source = require_current_business_source(self.scope.store, db, run[1], run[0], item["source_id"])
                if pins.get(item["source_id"]) != (item["version"], checksum(source)):
                    raise ValueError("草稿来源已经变化")
            if kind == "meeting" and (receipt.get("state") != "DRAFT" or receipt.get("review_sha256") != draft.get("review_sha256") or receipt.get("meeting_version") != draft.get("meeting_version")):
                raise ValueError("会议草稿回执不可核查")
            if kind == "minutes" and (receipt.get("state") != "DRAFT_REVIEW" or receipt.get("minute_id") != draft.get("minute_id") or receipt.get("entry_count") != len(draft.get("entries", []))):
                raise ValueError("纪要草稿回执不可核查")
            seen_calls.add(payload["call_id"])
            seen_refs.add(reference)
            count += 1
        if terminal:
            starts = db.execute("SELECT seq,payload,lease_epoch FROM agent_run_events WHERE run_id=? AND type='TOOL_STARTED' AND seq>? AND seq<? ORDER BY seq", (run_id, last_input_seq, result_seq)).fetchall()
            for _, raw, start_epoch in starts:
                payload = json.loads(raw)
                if payload.get("tool_id") not in TOOLS:
                    continue
                if start_epoch != epoch or payload.get("call_id") not in seen_calls:
                    raise ValueError("终态草稿开始事件缺少对应结束")
        if count != len(seen_refs):
            raise ValueError("草稿引用数量不一致")
        return {"state": "RECORD_PRESENT" if count else "NOT_VERIFIED", "count": count}

    def inspect_terminal_in_transaction(self, db, identity, run_id, goal_revision, result_seq, last_input_seq, expected_lease_epoch):
        return self.inspect_in_transaction(db, None, goal_revision, result_seq, last_input_seq, terminal=True, expected_lease_epoch=expected_lease_epoch, run_id=run_id, identity=identity)
