import re

from aiohttp import web
from jsonschema import Draft202012Validator

from business import encode, require
from boss_page_api import BossPageAPI
from boss_business_overview import BusinessOverviewAPI
from runtime_page_read_tools import _BossPageReadTool
from conversation_agent.domain import ConversationPlan
from conversation_agent.queries import ConversationQueries, METRICS, mentioned


BUSINESS_READ = "businessOverviewRead"
BUSINESS_TOOLS = frozenset({BUSINESS_READ, "query_metrics", "bossEvidenceRead"})
PIN_FIELDS = ("store_reference", "preparation_id", "client_request_id", "preparation_sha256", "applied_scope",
    "scope_sha256", "topic_reference", "topic_sha256", "snapshot_sha256", "source_references", "business_at", "return_reference")


def entry_pin(view):
    if view["binding_state"] == "UNBOUND":
        require(view["entry"] is None and view["current_use_verified"] is False, "经营入口未绑定状态无效", web.HTTPConflict)
        return None
    entry = view["entry"]
    require(view["binding_state"] == "BOUND" and view["current_use_verified"] is True
        and entry["binding_state"] == "BOUND" and entry["current_use_verified"] is True,
        "经营入口缺少当前正式证明", web.HTTPConflict)
    return encode({field: entry[field] for field in PIN_FIELDS})


class BusinessOverviewReadTool(_BossPageReadTool):
    name = BUSINESS_READ
    description = "读取本会话正式绑定的经营总览或选定专题，保持已应用范围、来源、用途和缺口；不产生本人授权或专业操作。"

    def __init__(self, store, scope, entry):
        super().__init__(BossPageAPI(store), "BOSS")
        self.scope, self.entry = scope, entry

    @property
    def parameters(self):
        return {"type": "object", "additionalProperties": False, "required": ["projection"],
            "properties": {"projection": {"const": "current", "enum": ["current"], "description": "由服务端采用当前会话绑定的总览、专题与用途"}}}

    async def execute(self, **params):
        require(not list(Draft202012Validator(self.parameters).iter_errors(params)), "经营读取参数无效", web.HTTPBadRequest)
        context = self.scope.current()
        view = self.entry.read("BOSS", {"session_id": context.session_id, "chat_id": context.chat_id})
        require(entry_pin(view) is not None, "经营读取需要正式绑定", web.HTTPForbidden)
        entry = view["entry"]
        if entry["topic_reference"] is None:
            result = view["overview"]
        else:
            with self._api.store.connect() as db:
                topic = self.entry.overview.topic_in_transaction(db, view["overview"], entry["topic_reference"])
            result = {"source_type": "SIMULATED", "applied_scope": entry["applied_scope"], "snapshot_sha256": entry["snapshot_sha256"],
                      "topic": topic, "sources": view["overview"]["sources"], "business_at": view["overview"]["business_at"],
                      "read_at": view["overview"]["read_at"], "business_authorization_granted": False, "business_mutation_performed": False}
            result["topic_reference"] = entry["topic_reference"]
        return encode(result)


def plan_business(store, conversation, text, query, view, pending_scope=None):
    entry, overview = view["entry"], view["overview"]
    topic = entry["topic_reference"]
    calls = [(BUSINESS_READ, encode({"projection": "current"}))]
    references = [tuple(ref[field] for field in ("kind", "id", "version")) for ref in view["references"]]
    required, bindings, checks, pending = [], (), (), None
    with store.connect() as db:
        selected_topic = BusinessOverviewAPI(store).topic_in_transaction(db, overview, topic) if topic else None
    if selected_topic is not None:
        if selected_topic["availability"] != "PARTIAL":
            required.extend(selected_topic["missing_fields"])
        other = [row["page_id"] for row in overview["topics"] if mentioned(text, row["page_id"]) and row["page_id"] != topic["page_id"]]
        require(not other, "讨论专题与原始绑定不符，请明确重新应用范围", web.HTTPConflict)
        if any(mentioned(text, use) and use != topic["use"] for use in ("BROILER", "EGG", "MILK", "BEEF")):
            required.append("专题用途变化需要明确重新应用范围，并使用新的经营会话入口")
    if re.search(r"关注条件\s*(改为|调整为|[:：=])", text):
        required.append("关注条件变化需要明确重新应用范围，并使用新的经营会话入口")
    for condition in re.findall(r"(?:只看|仅看|筛选|过滤)\s*([^，,。；;]+)", text):
        remaining = re.sub(r"(?:product|region|entity)-[A-Za-z0-9_-]+", "", condition)
        remaining = re.sub(r"产品|区域|法人主体|法人|范围|[\s、和及与]", "", remaining)
        if remaining:
            required.append("请明确当前正式支持的产品、区域或法人编号；当前筛选条件无法采用")
    query_requested = any(word in text for word in (*METRICS, *METRICS.values(), "查询", "计算", "比较", "对比", "指标改为"))
    query_requested = query_requested or bool(re.search(r"继续|改为|调整|只看|仅看|补充|沿用", text) and re.search(r"product-|region-|entity-|期间|口径|指标", text))
    if query_requested and "关联外销" not in text and any(word in text for word in
            ("库存", "配方", "苗种", "动保", "生猪", "禽类", "蛋禽", "奶畜", "牛羊", "养殖", "食品", "品质", "海外", "研发", "用药", "设备")):
        required.append("当前经营外销指标不能解释该专业事项，请采用明确专题及其有效专业资料")
    if query_requested:
        handoff = overview["query_handoff"]
        sales_reference = selected_topic is None or (topic["page_id"] == "F14" and "关联外销" in text and selected_topic["related_sales_source_refs"])
        if not sales_reference:
            required.append("当前专题没有对应的指标查询范围；经营外销参考需要采用明确的总览指标入口")
        elif handoff is None:
            required.append("当前查询条件不足：" + overview["query_handoff_unavailable_reason"])
        elif not required:
            planned = ConversationQueries(store, conversation).plan(text, query, pending_scope, applied_parameters=handoff)
            required.extend(planned.required_inputs)
            pending = planned.pending_scope
            if planned.binding is not None:
                calls.append(("query_metrics", planned.binding.parameters_json))
                bindings = (planned.binding,)
                references.extend(ref for ref in planned.references if ref not in references)
                if planned.parent is not None:
                    from conversation_agent.domain import artifact_digest
                    parent = planned.parent
                    checks = ((encode({field: parent[field] for field in ("run_id", "kind", "id")}), artifact_digest(parent)),)
    selected_sources = [ref for ref in entry["source_references"] if mentioned(text, ref["id"])]
    if any(word in text for word in ("来源", "原文")):
        if not selected_sources:
            required.append("请明确当前绑定来源编号")
        allowed = {ref["source_id"] for row in selected_topic["records"] for ref in row["source_refs"]} if selected_topic else {ref["id"] for ref in entry["source_references"]}
        for ref in selected_sources:
            if ref["status"] != "VALID" or ref["id"] not in allowed:
                required.append("当前专题没有可采用的该来源原文：" + ref["id"])
            else:
                calls.append(("bossEvidenceRead", encode({"source": ref["id"]})))
    if any(word in text for word in ("发送", "确认完成", "保存", "准备会议", "交办给")):
        required.append("会议、交办及其他写入需要正式共享流程和匹配当前对象的本人决定")
    require(len(calls) <= 10, "本次经营读取超过已验证工具步骤，请明确需要的来源", web.HTTPBadRequest)
    return ConversationPlan(tuple(calls), tuple(references), tuple(dict.fromkeys(required)), checks, bindings, pending)
