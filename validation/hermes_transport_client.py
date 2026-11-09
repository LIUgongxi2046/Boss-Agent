from urllib.parse import urlsplit
from urllib.parse import quote
import json

import httpx

from hermes_meeting_brief_public import validate_safe_section_audit


class HermesTransportClient:
    def __init__(self, endpoint: str, capability: str, run_id: str):
        url = urlsplit(endpoint)
        if url.scheme != "http" or url.hostname != "127.0.0.1" or not url.port or url.username or url.password or url.path not in ("", "/") or url.query or url.fragment:
            raise ValueError("通信入口必须是本机地址")
        if not isinstance(capability, str) or len(capability) < 32 or not capability.isascii() or not isinstance(run_id, str) or not run_id:
            raise ValueError("通信凭据或运行编号无效")
        self.run_id = run_id
        self.waiting_state = None
        self.waiting_interrupt = None
        self.client = httpx.Client(base_url=endpoint, headers={"Authorization": "Bearer " + capability}, timeout=15, trust_env=False)

    def request(self):
        response = self.client.get("/internal/v1/request")
        response.raise_for_status()
        body = response.json()
        if not isinstance(body, dict) or set(body) != {"protocol_version", "run_id", "goal", "goal_revision", "selected_refs"} or type(body["protocol_version"]) is not int or body["protocol_version"] != 1 or body["run_id"] != self.run_id or not isinstance(body["goal"], str) or not body["goal"].strip() or type(body["goal_revision"]) is not int or body["goal_revision"] <= 0 or not isinstance(body["selected_refs"], list) or any(not isinstance(ref, str) or not ref for ref in body["selected_refs"]):
            raise ValueError("运行请求响应无效")
        return body

    def prepare_domain_intent(self, action, params, request_key, *, tool_name=None):
        tools = {"meetingConfirm": "boss.meeting.confirm", "meetingCancel": "boss.meeting.cancel", "meetingHeld": "boss.meeting.held"}
        if tool_name is not None and tools.get(tool_name) != action:
            raise ValueError("会议工具名称与操作不一致")
        path = "/internal/v1/tools/domain-intent" + ("/" + tool_name if tool_name is not None else "")
        response = self.client.post(path, json={"protocol_version": 1, "request_key": request_key, "action": action, "params": params})
        response.raise_for_status()
        body = response.json()
        if not isinstance(body, dict) or set(body) != {"protocol_version", "intent_id", "status"} or type(body["protocol_version"]) is not int or body["protocol_version"] != 1 or not isinstance(body["intent_id"], str) or not body["intent_id"] or body["status"] != "WAITING_CONFIRMATION":
            raise ValueError("业务意图响应无效")
        self._accept_waiting("WAITING_CONFIRMATION")
        return body

    def read_decision_receipt(self, intent_id, call_id):
        response = self.client.post("/internal/v1/tools/decision-receipt", json={"protocol_version": 1, "intent_id": intent_id, "call_id": call_id})
        response.raise_for_status()
        body = response.json()
        if not isinstance(body, dict) or set(body) != {"protocol_version", "intent_id", "receipt"} or type(body["protocol_version"]) is not int or body["protocol_version"] != 1 or body["intent_id"] != intent_id or not isinstance(body["receipt"], dict) or body["receipt"].get("status") not in {"SUCCEEDED", "REJECTED"} or body["receipt"].get("intent_id") != intent_id:
            raise ValueError("本人决定回执响应无效")
        return body["receipt"]

    def read_meeting_context(self, call_id):
        response = self.client.post("/internal/v1/tools/meeting-context", json={"protocol_version": 1, "call_id": call_id})
        response.raise_for_status()
        body = response.json()
        if not isinstance(body, dict) or set(body) != {"protocol_version", "result"} or type(body["protocol_version"]) is not int or body["protocol_version"] != 1:
            raise ValueError("会议读取响应无效")
        result = body["result"]
        if not isinstance(result, dict) or set(result) != {"source_type", "meeting", "draft"} or result["source_type"] != "SIMULATED" or not isinstance(result["meeting"], dict) or set(result["meeting"]) != {"meeting_id", "version", "state", "title", "starts_at", "ends_at", "timezone", "participant_ids", "source_refs"}:
            raise ValueError("会议读取内容无效")
        meeting = result["meeting"]
        if any(not isinstance(meeting[key], str) or not meeting[key] for key in ("meeting_id", "version", "state", "starts_at", "timezone")) or any(meeting[key] is not None and (not isinstance(meeting[key], str) or not meeting[key]) for key in ("title", "ends_at")) or not isinstance(meeting["participant_ids"], list) or any(not isinstance(item, str) or not item for item in meeting["participant_ids"]) or not isinstance(meeting["source_refs"], list) or not meeting["source_refs"] or any(not isinstance(item, dict) or set(item) != {"source_id", "version", "source_sha256"} or any(not isinstance(item[key], str) or not item[key] for key in item) for item in meeting["source_refs"]):
            raise ValueError("会议基本信息无效")
        draft = result["draft"]
        if draft is not None and (not isinstance(draft, dict) or set(draft) != {"confirmation_parameters", "details", "impact", "source_refs"} or not isinstance(draft["confirmation_parameters"], dict) or set(draft["confirmation_parameters"]) != {"meeting_id", "meeting_version", "draft_version", "review_sha256"} or not isinstance(draft["details"], dict) or not isinstance(draft["impact"], dict) or not isinstance(draft["source_refs"], list)):
            raise ValueError("会议草稿读取内容无效")
        return result

    def read_meeting_projection(self, kind, call_id):
        if kind not in {"catalog", "arrangement"} or not isinstance(call_id, str) or not call_id or len(call_id) > 80:
            raise ValueError("会议读取请求无效")
        response = self.client.post("/internal/v1/tools/meeting-projection/" + kind, json={"protocol_version": 1, "call_id": call_id})
        response.raise_for_status()
        body = response.json()
        if not isinstance(body, dict) or set(body) != {"protocol_version", "result"} or type(body["protocol_version"]) is not int or body["protocol_version"] != 1 or not isinstance(body["result"], dict):
            raise ValueError("会议读取响应无效")
        result = body["result"]
        expected = {"source_type", "meeting", "documents", "library", "business_at"} if kind == "catalog" else {"source_type", "meeting", "draft", "contacts", "sources", "revisions", "business_at", "invitation_sent", "scope"}
        if set(result) != expected or result["source_type"] != "SIMULATED" or not isinstance(result["meeting"], dict) or not isinstance(result["business_at"], str):
            raise ValueError("会议读取内容无效")
        if kind == "catalog":
            library = result["library"]
            if not isinstance(result["documents"], list) or not isinstance(library, dict) or set(library) != {"source_type", "records", "insights", "scope", "business_clock"} or library["source_type"] != "SIMULATED" or library["scope"] != "SELECTED_MEETING_SOURCES" or library["business_clock"] != result["business_at"] or not isinstance(library["records"], list) or not isinstance(library["insights"], list):
                raise ValueError("会议目录范围无效")
            if any(not isinstance(item, dict) or not {"source_id", "version", "source_sha256", "source_type", "author_contact_id", "published_at", "original_locator"} <= set(item) or item["source_type"] != "SIMULATED" or any(not isinstance(item[key], str) or not item[key] for key in ("source_id", "version", "source_sha256")) for item in result["documents"]):
                raise ValueError("会议资料信息无效")
            if any(not isinstance(item, dict) or not isinstance(item.get("source_refs"), list) or not isinstance(item.get("actions"), list) for item in library["records"]) or any(not isinstance(item, dict) or item.get("target_kind") != "meeting" for item in library["insights"]):
                raise ValueError("会议目录内容无效")
        if kind == "arrangement" and (result["scope"] != "SELECTED_MEETING_SOURCES" or any(not isinstance(result[key], list) for key in ("contacts", "sources", "revisions")) or result["invitation_sent"] is not None):
            raise ValueError("会议安排范围无效")
        if kind == "arrangement" and ("preparation_due_at" not in result["meeting"] or result["meeting"]["preparation_due_at"] is not None and not isinstance(result["meeting"]["preparation_due_at"], str)):
            raise ValueError("会议准备时间无效")
        return result

    def prepare_meeting_brief(self, params, request_key):
        response = self.client.post("/internal/v1/tools/meeting-brief-prepare", json={"protocol_version": 1, "request_key": request_key, "params": params})
        response.raise_for_status()
        body = response.json()
        if not isinstance(body, dict) or set(body) != {"protocol_version", "result"} or type(body["protocol_version"]) is not int or body["protocol_version"] != 1 or not isinstance(body["result"], dict):
            raise ValueError("会议简报回执无效")
        result = body["result"]
        fields = {"source_type", "brief_id", "meeting_id", "version", "state", "source_count", "missing_count", "historical_commitment_count", "message_sent", "meeting_occurred", "brief", "source_materials", "content_checks"}
        if set(result) != fields or result["source_type"] != "SIMULATED" or result["meeting_id"] != params["meeting_id"] or result["state"] not in {"NEEDS_REVIEW", "READY_FOR_REVIEW"} or result["message_sent"] is not False or type(result["meeting_occurred"]) is not bool or any(not isinstance(result[key], str) or not result[key] for key in ("brief_id", "meeting_id", "version")) or any(type(result[key]) is not int or result[key] < 0 for key in ("source_count", "missing_count", "historical_commitment_count")):
            raise ValueError("会议简报回执内容无效")
        brief = result["brief"]
        if not isinstance(brief, dict) or any(brief.get(key) != result[key] for key in ("brief_id", "meeting_id", "version", "state", "source_type", "message_sent", "meeting_occurred")) or brief.get("meeting_version") != params["meeting_version"] or not isinstance(brief.get("compiled"), dict):
            raise ValueError("会议简报内容无效")
        compiled = brief["compiled"]
        if any(not isinstance(compiled.get(key), list) for key in ("sources", "commitments", "missing_items")) or result["source_count"] != len(compiled["sources"]) or result["missing_count"] != len(compiled["missing_items"]) or result["historical_commitment_count"] != len(compiled["commitments"]):
            raise ValueError("会议简报内容数量无效")
        materials = result["source_materials"]
        if not isinstance(materials, list) or len(materials) != len(compiled["sources"]) or any(not isinstance(item, dict) or set(item) != {"source_id", "version", "source_sha256", "content"} or any(not isinstance(item[key], str) for key in item) or any(item[key] != reference.get(key) for key in ("source_id", "version", "source_sha256")) for item, reference in zip(materials, compiled["sources"])):
            raise ValueError("会议简报来源内容无效")
        if result["content_checks"] != {kind: "NOT_VERIFIED" for kind in ("AGENDA", "CONSENSUS", "CONFLICT", "DECISION")}:
            raise ValueError("会议简报内容核查状态无效")
        return result

    def save_meeting_draft(self, params, request_key):
        response = self.client.post("/internal/v1/tools/meeting-draft", json={"protocol_version": 1, "request_key": request_key, "params": params})
        response.raise_for_status()
        body = response.json()
        if not isinstance(body, dict) or set(body) != {"protocol_version", "draft"} or type(body["protocol_version"]) is not int or body["protocol_version"] != 1:
            raise ValueError("会议草稿响应无效")
        draft = body["draft"]
        if not isinstance(draft, dict) or set(draft) != {"status", "confirmation_parameters", "details", "impact", "source_refs"} or draft["status"] != "DRAFT" or not isinstance(draft["confirmation_parameters"], dict) or set(draft["confirmation_parameters"]) != {"meeting_id", "meeting_version", "draft_version", "review_sha256"} or not isinstance(draft["details"], dict) or not isinstance(draft["impact"], dict) or not isinstance(draft["source_refs"], list):
            raise ValueError("会议草稿内容无效")
        return draft

    def save_formal_meeting_draft(self, params, request_key):
        response = self.client.post("/internal/v1/tools/meeting-draft-formal", json={"protocol_version": 1, "request_key": request_key, "params": params})
        response.raise_for_status()
        body = response.json()
        if not isinstance(body, dict) or set(body) != {"protocol_version", "draft"} or type(body["protocol_version"]) is not int or body["protocol_version"] != 1 or not isinstance(body["draft"], dict):
            raise ValueError("会议草稿回执无效")
        draft = body["draft"]
        if set(draft) != {"meeting_id", "meeting_version", "version", "state", "review_sha256", "meeting_changed", "invitation_sent"} or draft["state"] != "DRAFT" or draft["meeting_changed"] is not False or draft["invitation_sent"] is not False or any(not isinstance(draft[key], str) or not draft[key] for key in ("meeting_id", "meeting_version", "version", "review_sha256")):
            raise ValueError("会议草稿回执内容无效")
        return draft

    def minutes_tool(self, params, request_key):
        writing = params is not None
        body = {"protocol_version": 1, "request_key": request_key}
        if writing:
            body["params"] = params
        response = self.client.post("/internal/v1/tools/minutes-draft" if writing else "/internal/v1/tools/minutes-context", json=body)
        response.raise_for_status()
        result = response.json()
        if not isinstance(result, dict) or set(result) != {"protocol_version", "result"} or type(result["protocol_version"]) is not int or result["protocol_version"] != 1 or not isinstance(result["result"], dict):
            raise ValueError("纪要工具响应无效")
        content = result["result"]
        if writing:
            if set(content) != {"details", "confirmation_parameters"} or not isinstance(content["details"], dict) or not isinstance(content["confirmation_parameters"], dict):
                raise ValueError("纪要草稿响应无效")
        elif set(content) != {"source_type", "meeting_id", "meeting_version", "minutes", "assignment_context"} or content["source_type"] != "SIMULATED" or not isinstance(content["meeting_id"], str) or not isinstance(content["meeting_version"], str) or (content["minutes"] is not None and (not isinstance(content["minutes"], dict) or set(content["minutes"]) != {"details", "confirmation_parameters"})) or (content["assignment_context"] is not None and (not isinstance(content["assignment_context"], dict) or set(content["assignment_context"]) != {"related_meeting_id", "related_event_ids", "source_refs", "content_version", "eligible_coordinator_ids"})):
            raise ValueError("纪要读取响应无效")
        return content

    def emit(self, origin_event_id, event_type, payload):
        response = self.client.post("/internal/v1/events", json={"protocol_version": 1, "origin_event_id": origin_event_id, "type": event_type, "payload": payload})
        response.raise_for_status()
        body = response.json()
        if not isinstance(body, dict) or set(body) != {"protocol_version", "event"} or type(body["protocol_version"]) is not int or body["protocol_version"] != 1 or not isinstance(body["event"], dict) or body["event"].get("run_id") != self.run_id:
            raise ValueError("运行事件响应无效")
        return body["event"]

    def pending_input(self):
        response = self.client.get("/internal/v1/inputs")
        response.raise_for_status()
        body = response.json()
        if not isinstance(body, dict) or set(body) != {"protocol_version", "input"} or type(body["protocol_version"]) is not int or body["protocol_version"] != 1:
            raise ValueError("补充输入响应无效")
        item = body["input"]
        if item is not None and (not isinstance(item, dict) or set(item) != {"input_id", "input_seq", "goal_revision", "content"} or not isinstance(item["input_id"], str) or not item["input_id"] or type(item["input_seq"]) is not int or item["input_seq"] <= 0 or type(item["goal_revision"]) is not int or item["goal_revision"] <= 1 or not isinstance(item["content"], str) or not item["content"].strip()):
            raise ValueError("补充输入内容无效")
        return item

    def input_context(self):
        response = self.client.get("/internal/v1/input-context")
        response.raise_for_status()
        body = response.json()
        if not isinstance(body, dict) or set(body) != {"protocol_version", "run_id", "goal", "goal_revision", "inputs", "requirements"} or type(body["protocol_version"]) is not int or body["protocol_version"] != 1 or body["run_id"] != self.run_id or not isinstance(body["goal"], str) or not body["goal"].strip() or type(body["goal_revision"]) is not int or not isinstance(body["inputs"], list) or body["goal_revision"] != len(body["inputs"]) + 1:
            raise ValueError("补充输入上下文无效")
        requirements = body["requirements"]
        if not isinstance(requirements, dict) or set(requirements) != {"goal_revision", "state", "required_outputs"} or type(requirements["goal_revision"]) is not int or requirements["goal_revision"] != body["goal_revision"] or requirements["state"] not in {"CONFIRMED", "PENDING_CONFIRMATION", "UNAVAILABLE"}:
            raise ValueError("运行成果要求无效")
        outputs = requirements["required_outputs"]
        if requirements["state"] == "CONFIRMED":
            if not isinstance(outputs, list) or not outputs or any(not isinstance(item, str) or not item for item in outputs) or len(outputs) != len(set(outputs)):
                raise ValueError("运行成果选择无效")
        elif outputs is not None:
            raise ValueError("待确认的成果选择无效")
        for index, item in enumerate(body["inputs"], 1):
            if not isinstance(item, dict) or set(item) != {"input_id", "input_seq", "goal_revision", "content", "applied"} or not isinstance(item["input_id"], str) or not item["input_id"] or type(item["input_seq"]) is not int or item["input_seq"] != index or type(item["goal_revision"]) is not int or item["goal_revision"] != index + 1 or not isinstance(item["content"], str) or not item["content"].strip() or type(item["applied"]) is not bool:
                raise ValueError("补充输入记录无效")
        return body

    def prepare_inputs(self):
        context = self.input_context()
        for item in context["inputs"]:
            if item["applied"]:
                continue
            event = self.acknowledge_input(item["input_seq"])
            if event.get("payload") != {"input_id": item["input_id"], "input_seq": item["input_seq"], "goal_revision": item["goal_revision"]}:
                raise ValueError("补充输入回执与内容不匹配")
        current = self.input_context()
        expected = [{**item, "applied": True} for item in context["inputs"]]
        if current["goal"] != context["goal"] or current["goal_revision"] != context["goal_revision"] or current["inputs"] != expected or current["requirements"] != context["requirements"]:
            raise ValueError("准备期间补充输入已经变化")
        return current

    def prepare_turn(self):
        context = self.input_context()
        if context["requirements"]["state"] != "CONFIRMED":
            raise ValueError("当前目标的成果要求尚未确认")
        context = self.prepare_inputs()
        request = self.request()
        if request["goal"] != context["goal"] or request["goal_revision"] != context["goal_revision"]:
            raise ValueError("准备期间运行目标已经变化")
        prompt = json.dumps({"goal": context["goal"], "additional_inputs": [item["content"] for item in context["inputs"]], "required_outputs": context["requirements"]["required_outputs"]}, ensure_ascii=False)
        return {"goal_revision": context["goal_revision"], "prompt": prompt}

    def bi_definitions(self):
        response = self.client.get("/internal/v1/tools/bi-definitions")
        response.raise_for_status()
        body = response.json()
        if not isinstance(body, dict) or set(body) != {"protocol_version", "definitions"} or type(body["protocol_version"]) is not int or body["protocol_version"] != 1 or not isinstance(body["definitions"], list):
            raise ValueError("经营工具定义响应无效")
        definitions = body["definitions"]
        if len(definitions) != 2 or any(not isinstance(item, dict) or set(item) != {"name", "description", "parameters"} or not isinstance(item["description"], str) or not isinstance(item["parameters"], dict) for item in definitions) or {item["name"] for item in definitions} != {"query_metrics", "read_evidence"}:
            raise ValueError("经营工具定义不可核查")
        return definitions

    def create_child(self, request_key, description):
        from uuid import UUID
        if not isinstance(request_key, str) or not request_key.strip() or len(request_key) > 128 or not isinstance(description, str) or not description.strip() or len(description) > 2000:
            raise ValueError("委派请求无效")
        response = self.client.post("/internal/v1/children", json={"protocol_version": 1, "request_key": request_key, "description": description})
        response.raise_for_status()
        body = response.json()
        if not isinstance(body, dict) or set(body) != {"protocol_version", "child"} or type(body["protocol_version"]) is not int or body["protocol_version"] != 1 or not isinstance(body["child"], dict) or set(body["child"]) != {"run_id", "parent_run_id", "parent_goal_revision", "goal_revision"} or body["child"]["parent_run_id"] != self.run_id or type(body["child"]["parent_goal_revision"]) is not int or body["child"]["parent_goal_revision"] < 1 or type(body["child"]["goal_revision"]) is not int or body["child"]["goal_revision"] != 1 or not isinstance(body["child"]["run_id"], str) or str(UUID(body["child"]["run_id"])) != body["child"]["run_id"]:
            raise ValueError("委派回执不可核查")
        return body["child"]

    def dispatch_child(self, child_id, request_key):
        from uuid import UUID
        if not isinstance(child_id, str) or str(UUID(child_id)) != child_id or not isinstance(request_key, str) or not request_key.strip() or len(request_key) > 128:
            raise ValueError("委派派发请求无效")
        response = self.client.post("/internal/v1/children/" + child_id + "/dispatch", json={"protocol_version": 1, "request_key": request_key}, timeout=None)
        response.raise_for_status()
        body = response.json()
        if not isinstance(body, dict) or set(body) != {"protocol_version", "dispatch"} or type(body["protocol_version"]) is not int or body["protocol_version"] != 1 or not isinstance(body["dispatch"], dict) or body["dispatch"].get("run_id") != child_id:
            raise ValueError("委派派发回执不可核查")
        return body["dispatch"]

    def child_result(self, child_id, request_key=None):
        from uuid import UUID, uuid4
        if request_key is None:
            request_key = str(uuid4())
        if not isinstance(child_id, str) or str(UUID(child_id)) != child_id or not isinstance(request_key, str) or not request_key.strip() or len(request_key) > 128:
            raise ValueError("子运行编号无效")
        response = self.client.get("/internal/v1/children/" + child_id + "/result", params={"request_key": request_key})
        response.raise_for_status()
        body = response.json()
        if not isinstance(body, dict) or set(body) != {"protocol_version", "child_result"} or type(body["protocol_version"]) is not int or body["protocol_version"] != 1 or not isinstance(body["child_result"], dict) or set(body["child_result"]) != {"run_id", "status", "result"} or body["child_result"]["run_id"] != child_id:
            raise ValueError("委派结果响应不可核查")
        return body["child_result"]

    def call_bi_tool(self, tool_name, arguments, call_id):
        if tool_name not in ("query_metrics", "read_evidence") or not isinstance(arguments, dict) or not isinstance(call_id, str) or not 1 <= len(call_id) <= 80:
            raise ValueError("经营工具请求无效")
        response = self.client.post("/internal/v1/tools/bi", json={"protocol_version": 1, "call_id": call_id,
                                    "tool_name": tool_name, "arguments": arguments})
        response.raise_for_status()
        body = response.json()
        if not isinstance(body, dict) or set(body) != {"protocol_version", "result"} or type(body["protocol_version"]) is not int or body["protocol_version"] != 1 or not isinstance(body["result"], dict):
            raise ValueError("经营工具响应无效")
        return body["result"]

    def read_evidence(self, source, call_id):
        if not isinstance(source, str) or not 1 <= len(source) <= 100 or not isinstance(call_id, str) or not call_id or len(call_id) > 80:
            raise ValueError("来源读取请求无效")
        response = self.client.post("/internal/v1/tools/read-evidence", json={"protocol_version": 1, "call_id": call_id, "source": source})
        response.raise_for_status()
        body = response.json()
        if not isinstance(body, dict) or set(body) != {"protocol_version", "result"} or type(body["protocol_version"]) is not int or body["protocol_version"] != 1 or not isinstance(body["result"], dict):
            raise ValueError("来源读取响应无效")
        result = body["result"]
        if result.get("source_id") != source or result.get("source_type") != "SIMULATED" or any(not isinstance(result.get(key), str) or not result[key] for key in ("version", "read_at")) or not isinstance(result.get("source_sha256"), str) or len(result["source_sha256"]) != 64 or any(char not in "0123456789abcdef" for char in result["source_sha256"]) or not isinstance(result.get("content"), str) or any(key not in result for key in ("published_at", "author_contact_id", "original_locator")):
            raise ValueError("来源读取内容无效")
        return result

    def read_documents(self, call_id):
        response = self.client.post("/internal/v1/tools/read-documents", json={"protocol_version": 1, "call_id": call_id})
        response.raise_for_status()
        body = response.json()
        if not isinstance(body, dict) or set(body) != {"protocol_version", "result"} or type(body["protocol_version"]) is not int or body["protocol_version"] != 1 or not isinstance(body["result"], dict):
            raise ValueError("来源读取响应无效")
        return body["result"]

    def read_context(self, kind, call_id):
        if kind not in {"memory", "method"} or not isinstance(call_id, str) or not call_id or len(call_id) > 80:
            raise ValueError("上下文工具请求无效")
        response = self.client.post("/internal/v1/tools/context/" + kind, json={"protocol_version": 1, "call_id": call_id})
        response.raise_for_status()
        body = response.json()
        if not isinstance(body, dict) or set(body) != {"protocol_version", "result"} or type(body["protocol_version"]) is not int or body["protocol_version"] != 1 or not isinstance(body["result"], dict):
            raise ValueError("运行上下文响应无效")
        if kind == "method":
            result = body["result"]
            if set(result) != {"content", "reference", "business_authorization_granted", "goal_revision"} or not isinstance(result["content"], str) or not result["content"].strip() or result["business_authorization_granted"] is not False or type(result["goal_revision"]) is not int or result["goal_revision"] < 1 or not isinstance(result["reference"], dict) or not isinstance(result["reference"].get("method"), dict) or set(result["reference"]["method"]) != {"sop_id", "name", "version", "content_sha256"}:
                raise ValueError("运行方法响应无效")
        return body["result"]

    def create_meeting_brief(self, arguments):
        response = self.client.post("/internal/v1/tools/meeting-brief", json={"protocol_version": 1, "arguments": arguments})
        response.raise_for_status()
        body = response.json()
        if not isinstance(body, dict) or set(body) != {"protocol_version", "artifact"} or type(body["protocol_version"]) is not int or body["protocol_version"] != 1 or not isinstance(body["artifact"], dict) or body["artifact"].get("run_id") != self.run_id:
            raise ValueError("成果工具回执无效")
        if "section_audit" in body["artifact"]:
            validate_safe_section_audit(body["artifact"]["section_audit"])
        return body["artifact"]

    def create_runtime_meeting_brief(self, arguments):
        response = self.client.post("/internal/v1/tools/runtime-meeting-brief", json={"protocol_version": 1, "arguments": arguments})
        response.raise_for_status()
        body = response.json()
        if not isinstance(body, dict) or set(body) != {"protocol_version", "artifact"} or type(body["protocol_version"]) is not int or body["protocol_version"] != 1 or not isinstance(body["artifact"], dict) or body["artifact"].get("run_id") != self.run_id or "storage_key" in body["artifact"]:
            raise ValueError("会议成果回执无效")
        if "section_audit" in body["artifact"]:
            validate_safe_section_audit(body["artifact"]["section_audit"])
        return body["artifact"]

    def record_result(self, origin_event_id, goal_revision, text, citations):
        response = self.client.post("/internal/v1/result", json={"protocol_version": 1, "origin_event_id": origin_event_id,
                                    "goal_revision": goal_revision, "text": text, "citations": citations})
        response.raise_for_status()
        body = response.json()
        if not isinstance(body, dict) or set(body) != {"protocol_version", "event", "citation_checks"} or type(body["protocol_version"]) is not int or body["protocol_version"] != 1 or not isinstance(body["event"], dict) or body["event"].get("run_id") != self.run_id or body["event"].get("type") != "RESULT_RECORDED" or not isinstance(body["citation_checks"], list) or body["citation_checks"] != [{**citation, "locator_verification": "NOT_VERIFIED"} for citation in citations]:
            raise ValueError("运行结果回执无效")
        return body["event"]

    def authorize_model_execution(self):
        response = self.client.post("/internal/v1/model-execution", json={"protocol_version": 1})
        response.raise_for_status()
        body = response.json()
        if body != {"protocol_version": 1, "authorized": True}:
            raise ValueError("模型执行授权响应无效")

    def reserve_workspace_file_tool(self, name, call_id, arguments_sha256):
        response = self.client.post("/internal/v1/tools/workspace-file-reserve", json={"protocol_version": 1,
            "tool_name": name, "call_id": call_id, "arguments_sha256": arguments_sha256})
        response.raise_for_status()
        if response.json() != {"protocol_version": 1, "run_id": self.run_id, "call_id": call_id, "reserved": True}:
            raise ValueError("文件工具预留响应无效")

    def finish_workspace_file_tool(self, name, call_id, outcome):
        response = self.client.post("/internal/v1/tools/workspace-file-finish", json={"protocol_version": 1,
            "tool_name": name, "call_id": call_id, "outcome": outcome})
        response.raise_for_status()
        if response.json() != {"protocol_version": 1, "run_id": self.run_id, "call_id": call_id, "recorded": True}:
            raise ValueError("文件工具回执响应无效")

    def wait_for_requirements(self, goal_revision):
        response = self.client.post("/internal/v1/requirements/wait", json={"protocol_version": 1, "goal_revision": goal_revision})
        response.raise_for_status()
        body = response.json()
        if not isinstance(body, dict) or set(body) != {"protocol_version", "run_id", "status", "requirements"} or type(body["protocol_version"]) is not int or body["protocol_version"] != 1 or body["run_id"] != self.run_id or body["status"] != "WAITING_INPUT" or not isinstance(body["requirements"], dict) or body["requirements"].get("goal_revision") != goal_revision or body["requirements"].get("state") not in {"PENDING_CONFIRMATION", "UNAVAILABLE"}:
            raise ValueError("成果要求等待回执无效")
        self._accept_waiting("WAITING_INPUT")
        return body

    def request_additional_input(self, question, goal_revision, call_id):
        if not isinstance(question, str) or not question.strip() or len(question) > 2000 or type(goal_revision) is not int or goal_revision < 1 or not isinstance(call_id, str) or not call_id or len(call_id) > 80:
            raise ValueError("补充事项请求无效")
        response = self.client.post("/internal/v1/tools/input-required", json={"protocol_version": 1, "call_id": call_id, "goal_revision": goal_revision, "question": question})
        response.raise_for_status()
        body = response.json()
        if not isinstance(body, dict) or set(body) != {"protocol_version", "run_id", "status", "goal_revision", "event_id"} or type(body["protocol_version"]) is not int or body["protocol_version"] != 1 or body["run_id"] != self.run_id or body["status"] != "WAITING_INPUT" or body["goal_revision"] != goal_revision or not isinstance(body["event_id"], str) or not body["event_id"]:
            raise ValueError("补充事项响应无效")
        self._accept_waiting("WAITING_INPUT")
        return body

    def _accept_waiting(self, state):
        if state not in {"WAITING_INPUT", "WAITING_CONFIRMATION"} or self.waiting_state is not None:
            raise ValueError("等待回执状态不可核查")
        if self.waiting_interrupt is not None and self.waiting_interrupt() is not True:
            raise ValueError("等待状态无法中止当前引擎循环")
        self.waiting_state = state

    def citation_checks(self, event_id):
        if not isinstance(event_id, str) or not event_id or len(event_id) > 128:
            raise ValueError("运行结果事件编号无效")
        response = self.client.get("/internal/v1/results/" + quote(event_id, safe="") + "/citation-checks")
        response.raise_for_status()
        body = response.json()
        if not isinstance(body, dict) or set(body) != {"protocol_version", "event_id", "citation_checks"} or type(body["protocol_version"]) is not int or body["protocol_version"] != 1 or body["event_id"] != event_id or not isinstance(body["citation_checks"], list) or any(not isinstance(item, dict) or set(item) != {"source_id", "locator", "locator_verification"} or not isinstance(item["source_id"], str) or not isinstance(item["locator"], str) or item["locator_verification"] != "NOT_VERIFIED" for item in body["citation_checks"]):
            raise ValueError("运行结果引用核查响应无效")
        return body["citation_checks"]

    def document_result(self, call_id):
        if not isinstance(call_id, str) or not call_id or len(call_id) > 80:
            raise ValueError("工具请求编号无效")
        response = self.client.get("/internal/v1/tools/read-documents/" + quote(call_id, safe=""))
        response.raise_for_status()
        body = response.json()
        if not isinstance(body, dict) or set(body) != {"protocol_version", "result"} or type(body["protocol_version"]) is not int or body["protocol_version"] != 1 or not isinstance(body["result"], dict):
            raise ValueError("来源读取响应无效")
        return body["result"]

    def acknowledge_input(self, input_seq):
        response = self.client.post("/internal/v1/inputs/ack", json={"protocol_version": 1, "input_seq": input_seq})
        response.raise_for_status()
        body = response.json()
        if not isinstance(body, dict) or set(body) != {"protocol_version", "event"} or type(body["protocol_version"]) is not int or body["protocol_version"] != 1 or not isinstance(body["event"], dict) or body["event"].get("run_id") != self.run_id or body["event"].get("type") != "INPUT_APPLIED":
            raise ValueError("补充输入回执无效")
        return body["event"]

    def close(self):
        self.client.close()
