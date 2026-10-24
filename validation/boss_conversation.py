import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from aiohttp import web
from jsonschema import Draft202012Validator

from business import require
from boss_simulation_api import _context
from boss_source_policy import source_validity
from boss_supply_quality import external_adoption

SCHEMA = json.loads((Path(__file__).resolve().parents[1] / "specs/conversation.schema.json").read_text())


def validate(name, value):
    require(not list(Draft202012Validator({**SCHEMA, "$ref": "#/$defs/" + name}).iter_errors(value)), "会话输入输出不符合Schema", web.HTTPBadRequest)
    return value


def owner_role(role):
    require(role in ("BOSS", "MAINTAINER"), "本人身份尚未认证", web.HTTPUnauthorized)
    require(role == "BOSS", "会话及消息仅限本人访问", web.HTTPForbidden)


def optional(db, ns, kind, identifier):
    row = db.execute("SELECT body FROM objects WHERE namespace=? AND kind=? AND id=?", (ns, kind, identifier)).fetchone()
    return json.loads(row[0]) if row else None


def recorded_conversation_context(run):
    return validate("RecordedConversationContext", {field: run["conversation_context"][field]
        for field in ("input_sha256", "allowed_call_refs", "references")})


def references(run):
    found = {}
    selected = run.get("morning_context", {}).get("selected_item_ref", {})
    for row in run["tool_results"] + run.get("owner_task_links", []) + [run.get("assignment_context", {}), selected]:
        for field, kind, version in (("query_id", "query", None), ("task_id", "task", row.get("task_version", row.get("version"))),
                                     ("list_id", "morning_list", row.get("list_version")), ("message_id", "message", None), ("draft_id", "message_draft", row.get("version"))):
            if row.get(field):
                found[kind, row[field]] = validate("Reference", {"kind": kind, "id": row[field], "recorded_version": version, "adoption_state": "REQUIRES_CURRENT_READ"})
    return list(found.values())


class ConversationAPI:
    def __init__(self, store):
        from boss_conversation_references import ConversationReferences
        self.store = store
        self.context_references = ConversationReferences(store)

    def _run(self, db, context, query):
        run = self.store.get(db, context["namespace"], "runtime_run", query["run_id"])
        require(run["namespace"] == context["namespace"] and all(run[field] == context[field] for field in ("dataset_id", "dataset_version"))
                and run["session_id"] == query["session_id"] and run["chat_id"] == query["chat_id"], "运行不属于当前会话及资料范围", web.HTTPForbidden)
        return run

    def read(self, role, query):
        owner_role(role)
        validate("Context", query)
        with self.store.connect() as db:
            db.execute("BEGIN")
            return self.project_in_transaction(role, db, query)

    def project_in_transaction(self, role, db, query):
        owner_role(role)
        validate("Context", query)
        context = _context(db)
        runs = []
        for identifier, in db.execute("SELECT id FROM objects WHERE namespace=? AND kind='runtime_run' AND json_extract(body,'$.session_id')=? AND json_extract(body,'$.chat_id') IS ? ORDER BY json_extract(body,'$.started_at'),id", (context["namespace"], query["session_id"], query["chat_id"])).fetchall():
            run = self._run(db, context, {**query, "run_id": identifier})
            record = {field: run[field] for field in ("run_id", "session_id", "request_id", "chat_id", "turn_id", "configuration_version", "configuration_id", "status", "stop_reason", "started_at", "finished_at")}
            record["runtime"] = {field: run["runtime"][field] for field in ("provider", "model_id", "api_type", "max_tool_rounds", "max_output_tokens", "timeout", "config_sha256")}
            record["tool_steps"] = [{field: step[field] for field in ("tool_id", "tool_call_id", "iteration", "status", "task_status", "version", "task_version", "source_id") if field in step} for step in run["tool_results"]]
            record["tool_errors"] = [{field: step[field] for field in ("tool_id", "tool_call_id", "error_type") if field in step} for step in run.get("tool_errors", [])]
            record["artifacts"] = references(run)
            record["origin_references"] = {}
            record["context_references"] = self.context_references.project_in_transaction(db, context, run)
            if "conversation_context" in run:
                record["origin_references"]["conversation_context"] = recorded_conversation_context(run)
            for field, allowed in (("morning_context", ("date", "timezone", "snapshot_sha256", "order_version")),
                                   ("assignment_context", ("task_id", "task_version", "review_sha256")),
                                   ("reminder_context", ("projection", "projection_sha256"))):
                if field in run:
                    record["origin_references"][field] = {key: run[field][key] for key in allowed if key in run[field]}
            if "selected_item_ref" in run.get("morning_context", {}):
                selected = run["morning_context"]["selected_item_ref"]
                record["origin_references"]["morning_context"]["selected_item_ref"] = {
                    key: selected[key] for key in ("list_id", "list_version", "item_id", "object_id", "version", "source_refs") if key in selected}
            record["external_model_invoked"] = run.get("external_model_invoked")
            record["source_type"] = run.get("source_type", "RUNTIME_RECORD")
            runs.append(record)
        return validate("View", {"projection": "conversation", "source_type": "RUNTIME_RECORD", **query, "runs": runs,
            "coverage_state": "PARTIAL" if runs else "UNAVAILABLE", "missing_sources": ["NATIVE_TRANSCRIPT_AND_UNSENT_INPUT_OWNED_BY_NATIVE_SESSION"],
            "business_authorization_granted": False, "business_mutation_performed": False})

    def artifact(self, role, query):
        owner_role(role)
        validate("ArtifactInput", query)
        with self.store.connect() as db:
            db.execute("BEGIN")
            context = _context(db)
            run = self._run(db, context, query)
            recorded_context = recorded_conversation_context(run)["references"] if "conversation_context" in run else []
            require(any(ref["kind"] == query["kind"] and ref["id"] == query["id"] for ref in references(run) + recorded_context), "产物没有关联当前会话及运行", web.HTTPForbidden)
            ns, identifier, kind = context["namespace"], query["id"], query["kind"]
            initial = self.store.get(db, ns, "initial", "snapshot")
            evidence = None
            if kind == "query":
                result = self.store.get(db, ns, "query", identifier)
                require(all(result["envelope"][field] == context[field] for field in ("owner_id", "dataset_id", "dataset_version"))
                        and result["envelope"]["execution_namespace"] == ns, "查询产物归属不符", web.HTTPForbidden)
                evidence = self.store.read_evidence(db, ns, initial, {"query_id": identifier, "source_ids": [row["source_id"] for row in result["sources"]], "detail_refs": result["detail_refs"]})
            elif kind == "task":
                result = self.store.get(db, ns, "task", identifier)
                require(result["execution_namespace"] == ns and result.get("owner_id", initial["owner_id"]) == initial["owner_id"], "关联交办归属不符", web.HTTPForbidden)
                self.store.require_current_assignment_sources(db, ns, initial, result)
            elif kind == "morning_list":
                from boss_morning import MorningAPI
                stored, current, _ = MorningAPI(self.store)._current(db, context, identifier)
                result = {"result": stored["result"], "current_order": {"version": current["order_version"], "state": current["order_state"], "item_ids": [item["item_id"] for item in current["items"]]}}
            else:
                kinds = ("message_draft",) if kind == "message_draft" else ("message_outbox", "outbox")
                matches = [json.loads(row[0]) for row in db.execute("SELECT body FROM objects WHERE namespace=? AND id=? AND kind IN (" + ",".join("?" for _ in kinds) + ")", (ns, identifier, *kinds)).fetchall()]
                require(len(matches) == 1, "关联消息没有唯一当前记录", web.HTTPNotFound)
                row = matches[0]
                result = self._message(db, context, row)
            return validate("ArtifactResult", {"source_type": "SIMULATED", **{field: query[field] for field in ("run_id", "session_id", "chat_id", "kind", "id")},
                "data": result, "evidence": evidence, "business_authorization_granted": False, "business_mutation_performed": False})

    def _message(self, db, context, row):
        ns = context["namespace"]
        require(row.get("owner_id", context["owner_id"]) == context["owner_id"] and row.get("execution_namespace", ns) == ns, "消息归属不符", web.HTTPForbidden)
        initial = self.store.get(db, ns, "initial", "snapshot")
        clock = self.store.get(db, ns, "clock", "current")["at"]
        attachments = []
        for ref in row.get("attachment_refs", []):
            found = db.execute("SELECT body FROM objects WHERE namespace=? AND kind='document' AND id=? AND json_extract(body,'$.access_scope')=? AND json_extract(body,'$.source_id')=? AND json_extract(body,'$.source_type')='SIMULATED'", (ns, ref["source_id"], context["owner_id"], ref["source_id"])).fetchone()
            doc = json.loads(found[0]) if found else None
            allowed = doc is not None
            state = source_validity(doc, clock) if allowed else "MISSING_OR_FORBIDDEN"
            if state == "VALID" and (doc["version"] != ref["version"] or external_adoption(db, ns, initial, clock, doc)["state"] == "NEEDS_REIMPORT"):
                state = "NEEDS_REVIEW"
            attachments.append({"source_id": ref["source_id"], "version": ref["version"], "current_version": doc["version"] if allowed else None, "status": state,
                **{field: doc.get(field) if allowed and state == "VALID" else None for field in ("author_contact_id", "published_at", "observed_at", "original_locator")}})
        current = all(item["status"] == "VALID" for item in attachments)
        result = {field: row[field] for field in ("draft_id", "version", "status", "message_id", "draft_version", "recipient_id", "related_task_id", "task_id", "content_sha256", "visibility", "send_state", "message_status", "delivery_state", "reply_state", "sent_at", "updated_at", "authorization_id", "external_channel_invoked") if field in row}
        result.update(body=row.get("body") if current else None, attachment_refs=attachments, adoption_state="CURRENT" if current else "NEEDS_REVIEW")
        if row.get("task_id") or row.get("related_task_id"):
            task_id = row.get("task_id") or row["related_task_id"]
            task = self.store.get(db, ns, "task", task_id)
            require(task["execution_namespace"] == ns and task.get("owner_id", initial["owner_id"]) == initial["owner_id"], "消息关联交办归属不符", web.HTTPForbidden)
            result["current_task"] = {field: task[field] for field in ("task_id", "version", "status")}
        return result

    def messages(self, role):
        owner_role(role)
        with self.store.connect() as db:
            db.execute("BEGIN")
            context = _context(db)
            ns = context["namespace"]
            def rows(kind):
                return [json.loads(row[0]) for row in db.execute("SELECT body FROM objects WHERE namespace=? AND kind=? ORDER BY id", (ns, kind)).fetchall()]
            drafts = [self._message(db, context, row) for row in rows("message_draft")]
            sent = [self._message(db, context, row) for row in rows("message_outbox") + rows("outbox")]
            by_id = {row["message_id"]: row for row in sent}
            replies = []
            for row in rows("message_reply"):
                require(row["reply_to"] in by_id, "回复缺少原始消息", web.HTTPConflict)
                replies.append({field: row[field] for field in ("reply_id", "reply_to", "author_contact_id", "source_type", "received_at", "related_task_id", "task_completion_confirmed", "task_feedback_id", "task_status_after_reply") if field in row}
                               | {"text": row["text"] if by_id[row["reply_to"]]["adoption_state"] == "CURRENT" else None})
            initial = self.store.get(db, ns, "initial", "snapshot")
            today = datetime.fromisoformat(self.store.get(db, ns, "clock", "current")["at"]).astimezone(ZoneInfo(initial["boss_profile"]["timezone"])).date().isoformat()
            contacts = [{field: contact[field] for field in ("contact_id", "name", "organization", "responsibility", "valid_from", "valid_until")}
                        | {"is_current": contact["valid_from"] <= today <= contact["valid_until"]} for contact in initial["contacts"]]
            return validate("Messages", {"projection": "conversation-messages", "source_type": "SIMULATED", "scope": "OWNER_MESSAGE_HISTORY", "drafts": drafts, "sent_messages": sent,
                "replies": replies, "contacts": contacts, "business_authorization_granted": False, "business_mutation_performed": False})
