from dataclasses import dataclass
import json
import re

from aiohttp import web
from jsonschema import Draft202012Validator, FormatChecker

from business import SPEC, checksum, encode, require
from boss_bi_queries import BIQueryAPI
from fc02_agent import Fc02Context, Fc02Tool, bind_query, bind_scoped_followup
from public_bi_scenarios import loaded_scenarios, dimension_options
from conversation_agent import ConversationReadTool


METRICS = {"单吨毛利": "gross_profit_per_tonne", "毛利率": "gross_margin", "毛利": "gross_profit",
    "销售收入": "revenue", "收入": "revenue", "成本": "cost", "销售吨数": "sales_quantity", "销量": "sales_quantity"}
LABELS = {"region_id": "区域", "product_ids": "产品范围", "metric_ids": "指标", "legal_entity_id": "法人主体",
    "period_start": "查询期间开始日期", "period_end": "查询期间结束日期", "comparison_start": "比较期间开始日期",
    "comparison_end": "比较期间结束日期", "currency": "币种", "quantity_unit": "数量单位", "trade_scope": "交易范围",
    "definition_version": "指标定义版本", "business_basis": "业务口径", "settlement_state": "结算状态"}
DATE_RANGE = re.compile(r"(?P<label>比较期间|对比期间|基准期间|查询期间|当前期间|期间|比较|对比)?\s*(?:改为|调整为|从)?\s*(?P<start>\d{4}-\d{2}-\d{2})\s*(?:至|到|~|—|–|\.\.)\s*(?P<end>\d{4}-\d{2}-\d{2})")


def mentioned(text, value):
    return re.search(r"(?<![A-Za-z0-9_-])" + re.escape(value) + r"(?![A-Za-z0-9_-])", text, re.IGNORECASE) is not None


@dataclass(frozen=True)
class QueryPlan:
    binding: object = None
    pending_scope: str | None = None
    required_inputs: tuple[str, ...] = ()
    references: tuple = ()
    parent: object = None


class ConversationQueries:
    def __init__(self, store, conversation):
        self.store, self.conversation, self.api = store, conversation, BIQueryAPI(store)

    def plan(self, text, query, pending_scope=None):
        followup = any(word in text for word in ("继续", "改为", "调整", "只看", "仅看", "补充", "沿用"))
        metric_words = sorted([*METRICS, *METRICS.values()], key=len, reverse=True)
        metrics = re.findall("|".join(r"(?<![A-Za-z0-9_])" + re.escape(word) + r"(?![A-Za-z0-9_])"
            if word.isascii() else re.escape(word) for word in metric_words), text)
        requested = bool(metrics) or any(word in text for word in ("查询", "计算", "比较", "对比"))
        requested = requested or bool(followup and re.search(r"product-|region-|entity-|期间|口径|指标", text))
        if not requested:
            return QueryPlan()
        view = self.conversation.read("BOSS", query)
        choices = [(run["run_id"], ref) for run in view["runs"] for ref in run["artifacts"] if ref["kind"] == "query"]
        explicit = [(run_id, ref) for run_id, ref in choices if mentioned(text, ref["id"])]
        selected = explicit[-1] if explicit else choices[-1] if followup and choices and "重新" not in text else None
        parent = self.conversation.artifact("BOSS", {**query, "run_id": selected[0], "kind": "query", "id": selected[1]["id"]}) if selected else None
        base = {key: value for key, value in parent["data"]["context_snapshot"].items()
            if key not in {"envelope", "question", "parent_query_id", "query_mode"}} if parent else json.loads(pending_scope) if pending_scope and "重新" not in text else {}
        scenarios = loaded_scenarios(self.store, "BOSS")["scenarios"]
        scenario_ids = [item["scenario_id"] for item in scenarios if mentioned(text, item["scenario_id"])]
        require(len(scenario_ids) <= 1, "请明确当前唯一经营资料范围", web.HTTPBadRequest)
        scenario_id = scenario_ids[0] if scenario_ids else base.get("scenario_id")
        dimensions = dimension_options(self.store, "BOSS", self.api.dimensions("BOSS", scenario_id))
        available = dimensions["available_dimensions"]
        updates, required = {}, []
        if scenario_id is not None:
            updates["scenario_id"] = scenario_id
        for field, values in available.items():
            if field == "definition_version":
                continue
            selected_values = [value for value in values if mentioned(text, value)]
            if selected_values:
                if field in {"product_id", "region_id"}:
                    updates["product_ids" if field == "product_id" else "region_id"] = selected_values if field == "product_id" else selected_values[0]
                    if field == "region_id" and len(selected_values) > 1:
                        updates["region_ids"] = selected_values
                else:
                    require(len(selected_values) == 1, "当前经营条件包含多个不兼容值，请明确" + LABELS.get(field, field), web.HTTPBadRequest)
                    updates[field] = selected_values[0]
        for token, field, dimension in (("region", "region_id", "region_id"), ("product", "product_ids", "product_id"), ("entity", "legal_entity_id", "legal_entity_id")):
            identifiers = re.findall(r"(?<![A-Za-z0-9_-])" + token + r"-[A-Za-z0-9_-]+", text)
            if any(value not in available[dimension] for value in identifiers):
                required.append("请提供当前正式维度中的" + LABELS[field])
        if any(word in text for word in ("全部当前产品", "全部产品", "所有产品")):
            updates["product_ids"] = available["product_id"]
        if any(word in text for word in ("全部区域", "所有区域")):
            updates.update(region_id=available["region_id"][0], region_ids=available["region_id"])
        if metrics:
            updates["metric_ids"] = list(dict.fromkeys(METRICS.get(word, word) for word in metrics))
        metric_choice = re.search(r"指标(?:改为|调整为|为|[:：])\s*([^，,。；;]+)", text)
        if metric_choice:
            terms = re.split(r"、|和|及|与|\+", metric_choice[1].strip())
            if any(term.strip() not in metric_words for term in terms):
                required.append("请明确当前正式支持的指标：" + "、".join(dict.fromkeys(METRICS)))
        for field, label in LABELS.items():
            if field in {"region_id", "product_ids", "metric_ids", "period_start", "period_end", "comparison_start", "comparison_end"}:
                continue
            value = re.search("(?:" + re.escape(field) + "|" + re.escape(label) + r")(?:改为|调整为|为|版本|[:：=])?\s*([A-Za-z0-9_.-]+)", text)
            if value:
                updates[field] = value[1]
        for pair in DATE_RANGE.finditer(text):
            label = pair["label"] or ""
            before = label.startswith(("比较", "对比", "基准"))
            updates["comparison_start" if before else "period_start"] = pair["start"]
            updates["comparison_end" if before else "period_end"] = pair["end"]
        if "当前已保存期间" in text:
            updates["period_start"], updates["period_end"] = dimensions["periods"]["CURRENT"]
        if "已保存比较期间" in text:
            updates["comparison_start"], updates["comparison_end"] = dimensions["periods"]["BASE"]
        if any(word in text for word in ("本月", "本周", "上月", "上周")):
            required.append("请明确查询期间和比较期间的实际起止日期")
        if "使用当前获准口径" in text:
            for field in ("legal_entity_id", "currency", "quantity_unit", "trade_scope", "definition_version", "business_basis", "settlement_state"):
                if field not in updates and field not in base and len(available[field]) == 1:
                    updates[field] = available[field][0]
        for phrase, field, value in (("已结算", "settlement_state", "SETTLED"), ("未结算", "settlement_state", "UNSETTLED"),
                ("全部结算状态", "settlement_state", "ALL"), ("外销", "trade_scope", "EXTERNAL_SALES"),
                ("内部领用", "trade_scope", "INTERNAL_CONSUMPTION"), ("人民币", "currency", "CNY"), ("吨数单位", "quantity_unit", "tonne")):
            if phrase in text:
                updates[field] = value
        if parent is not None and not updates and "沿用当前查询范围" not in text:
            required.append("请明确本次经营条件，或明确沿用当前查询范围")
        scope = {**base, **updates}
        required.extend("请补充" + LABELS[field] for field in LABELS if field not in scope)
        valid_fields = {key: value for key, value in scope.items() if key in SPEC["io_schema"]["$defs"]["scoped_query_input"]["properties"]
            and key not in {"envelope", "question", "parent_query_id", "query_mode"}}
        require(valid_fields == scope, "继承经营条件超出正式范围", web.HTTPConflict)
        if required:
            return QueryPlan(pending_scope=encode(scope), required_inputs=tuple(dict.fromkeys(required)))
        parameters = {**scope, "query_mode": "SCOPED", "question": text}
        if parent:
            env = parent["data"]["envelope"]
            context = Fc02Context("BOSS", env["owner_id"], env["execution_namespace"], env["dataset_id"], env["dataset_version"],
                env["request_id"], query["session_id"], True, (), frozenset())
            binding = bind_scoped_followup(self.store, context, parent["id"], text, updates)
        else:
            binding = bind_query(parameters)
        schema = Fc02Tool(self.store, lambda: None, "query_metrics").parameters
        require(not list(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(json.loads(binding.parameters_json))),
                "当前经营条件不符合正式查询Schema", web.HTTPBadRequest)
        refs = tuple(("document", item["source_id"], item["version"]) for item in dimensions["source_options"])
        return QueryPlan(binding=binding, references=refs, parent=parent)


class ConversationQueryTool(ConversationReadTool):
    def __init__(self, delegate, scope):
        require(isinstance(delegate, Fc02Tool) and delegate.name == "query_metrics"
                and delegate.store.path.resolve() == scope.store.path.resolve(), "会话查询需要同库正式Fc02Tool", web.HTTPForbidden)
        self.delegate, self.scope = delegate, scope

    async def execute(self, **params):
        require(not list(Draft202012Validator(self.parameters, format_checker=FormatChecker()).iter_errors(params)),
                "会话查询参数不符合正式Schema", web.HTTPBadRequest)
        context = self.scope.current()
        require((self.name, checksum(params)) in context.allowed_calls, "查询参数超出本次明确范围", web.HTTPForbidden)
        result = await self.delegate.execute(**params)
        require(self.scope.current() == context, "查询期间当前范围已经变化", web.HTTPConflict)
        return result
