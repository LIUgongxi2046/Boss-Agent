"""Grounded agriculture-specific readiness views for FR-14 through FR-23.

Field names and metric labels are transcribed from the user's approved
Desktop v6 HTML sources (not fabricated business results). Data availability
comes only from the current ControlStore and its versioned sources.
"""
from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import parse_qs

from aiohttp import web

from business import checksum, now
from boss_execution_scope import NAMESPACE

CATALOGUE_PATH = Path(__file__).resolve().parents[1] / "Boss-Agent-Desktop-Complete-v7/meta/页面配置.json"
CATALOGUE = json.loads(CATALOGUE_PATH.read_text(encoding="utf-8")) if CATALOGUE_PATH.exists() else {}

SECTORS = {
    "F14": ("原料与饲料", ["原料", "产品", "法人", "期间"],
            ["行情价格", "合同价格", "入库成本", "领用成本"]),
    "F15": ("水产季节", ["区域", "品种", "阶段", "比较周期"],
            ["订单", "渠道库存", "投苗投喂", "回访分子分母"]),
    "F16": ("苗种批次", ["养户反馈", "苗种批次", "养殖批次"],
            ["批次来源", "投苗依据", "专业反馈"]),
    "F17": ("动保与技服", ["区域", "批次", "专业责任人"],
            ["现场问题", "用药依据", "回访证据"]),
    "F18": ("生猪合作", ["合作主体", "批次", "周期", "结算状态"],
            ["存栏", "转群", "出栏重量", "出栏价格"]),
    "F19": ("禽类与反刍", ["用途", "阶段", "客户", "观察期"],
            ["供料数量", "体重", "出栏", "适用单位"]),
    "F20": ("公司水产养殖", ["自营法人", "养殖单元", "设备", "批次"],
            ["养殖单元", "设备记录", "批次证据"]),
    "F21": ("食品与品质", ["客诉", "原料批次", "加工批次", "查询范围"],
            ["客诉证据", "质量追溯", "批次关系"]),
    "F22": ("海外业务", ["国别", "法人", "本地期间", "集团期间", "币种", "时区"],
            ["订单", "工段能力", "交付缺口", "回款范围"]),
    "F23": ("研发应用", ["研发项目", "试验版本", "专业评审", "决定问题"],
            ["试验依据", "版本状态", "专业评审"]),
    "V19-BEEF": ("禽类与反刍 · 肉用牛羊",
                 ["牛或羊", "用途", "生长阶段", "客户", "观察期"],
                 ["供料量", "生长表现", "出栏", "适用单位"]),
    "V19-EGG": ("禽类与反刍 · 蛋禽",
                ["蛋禽阶段", "客户", "日龄", "观察期"],
                ["供料", "产蛋量", "合格蛋重", "适用单位"]),
    "V19-MILK": ("禽类与反刍 · 奶畜",
                 ["动物", "客户", "泌乳阶段", "观察期"],
                 ["供料量", "产奶表现", "计量单位", "观察期"]),
}


class BossSectorAPI:
    def __init__(self, store, namespace=NAMESPACE):
        self.store, self.namespace = store, namespace

    def serve(self, role, query_string):
        if role != "BOSS":
            return (401 if role is None else 403), {"error": "FORBIDDEN"}
        params = parse_qs(query_string, keep_blank_values=True)
        if ("page" not in params or len(params["page"]) != 1 or not params["page"][0]
                or set(params) - {"page", "filters", "overview_reference"}):
            return 400, {"error": "INVALID_SCOPE"}
        page = params["page"][0]
        if page not in SECTORS:
            return 404, {"error": "UNKNOWN_SECTOR"}
        applied = {}
        if "filters" in params:
            try:
                parsed = json.loads(params["filters"][0])
            except json.JSONDecodeError:
                return 400, {"error": "INVALID_FILTERS"}
            if not isinstance(parsed, dict) or not all(
                    isinstance(key, str) and isinstance(value, str) for key, value in parsed.items()):
                return 400, {"error": "INVALID_FILTERS"}
            applied = {key: value for key, value in parsed.items() if value}
        overview = None
        if "overview_reference" in params:
            try:
                overview = json.loads(params["overview_reference"][0])
            except json.JSONDecodeError:
                return 400, {"error": "INVALID_OVERVIEW_REFERENCE"}
            if not isinstance(overview, dict):
                return 400, {"error": "INVALID_OVERVIEW_REFERENCE"}
        title, design_filters, kpis = SECTORS[page]
        with self.store.connect() as db:
            self.store.active(db, self.namespace)
            base = self.store.get(db, self.namespace, "initial", "snapshot")
            clock = self.store.get(db, self.namespace, "clock", "current")
            # Water-feed external sales are related to F14. They do *not*
            # include the actual raw-material market prices, contracts,
            # warehouse receipts or formula cost expected by FR-14.
            matching = []
            if page == "F14":
                row = db.execute(
                    "SELECT body FROM objects WHERE namespace=? AND kind='document' AND id='finance-note'",
                    (self.namespace,),
                ).fetchone()
                if row is not None:
                    doc = json.loads(row[0])
                    if (not doc.get("withdrawn") and
                            doc.get("access_scope") == base["owner_id"] and
                            doc.get("source_type") == "SIMULATED"):
                        matching.append({
                            "source_id": doc["source_id"],
                            "version": doc["version"],
                            "source_type": "SIMULATED",
                            "published_at": doc.get("published_at"),
                            "related_scope": "region-1 EXTERNAL_SALES water-feed comparison",
                            "not_evidence_for": "raw-material quotation, contract, inventory or consumption cost",
                        })
            pack_row = db.execute(
                "SELECT body FROM objects WHERE namespace=? AND kind='document' AND id=?",
                (self.namespace, "sector-" + page.lower() + "-a"),
            ).fetchone()
            pack = json.loads(pack_row[0]) if pack_row else None
        design = CATALOGUE.get(page) or {}
        timezone = base["boss_profile"].get("timezone", "Asia/Shanghai")
        today = clock["at"][:10]
        contacts = [{"contact_id": contact["contact_id"], "version": "1",
                     "display_name": contact["name"], "organization": contact["organization"],
                     "responsibility": contact["responsibility"],
                     "eligible": contact["valid_from"] <= today <= contact["valid_until"]}
                    for contact in base["contacts"]]
        facts = pack.get("sector_facts") if pack else None
        pack_source = ({"source_id": pack["source_id"], "version": pack["version"], "source_type": "SIMULATED",
                        "published_at": pack.get("published_at"), "related_scope": f"{page} 模拟指标",
                        "validity_state": "VALID", "author_display_name": "李文"} if pack else None)
        sources = ([pack_source] if pack_source else []) + [
            {"source_id": doc["source_id"], "version": doc["version"], "source_type": "SIMULATED",
             "published_at": doc.get("published_at"), "related_scope": doc["related_scope"],
             "validity_state": "VALID", "author_display_name": doc.get("author_display_name")}
            for doc in matching]
        coverage = [{"label": label,
                     "value": "模拟指标已生成" if facts else "尚未提供",
                     "state": "SIMULATED" if facts else "SOURCE_NOT_AVAILABLE"}
                    for label in (design.get("right") or [])]
        if facts:
            missing = ["明细与指标来自模拟资料包；后续动作尚未提供"]
        else:
            missing = ["当前专题的正式模拟明细尚未生成", "指标计算、来源核对与后续动作待接入"]
            if matching:
                missing.insert(0, "已有相关外销资料，但不足以计算本页指标")
        records, sections, relations, workflow = [], [], [], []
        if facts:
            pack_source_ids = [pack["source_id"]]
            for row in facts.get("rows", []):
                dims = row.get("dims", {})
                if any(key in dims and dims[key] != value for key, value in applied.items()):
                    continue
                records.append({"id": row["id"], "values": row["values"],
                                "source_ids": pack_source_ids, "version": "1", "state": "SIMULATED"})
            sections = [{**row, "state": "SIMULATED", "source_ids": pack_source_ids}
                        for row in facts.get("sections", [])]
            relations = [{**row, "source_ids": pack_source_ids}
                         for row in facts.get("relations", [])]
            workflow = [{**row, "source_ids": row.get("source_ids") or pack_source_ids}
                        for row in facts.get("workflow", [])]
        return 200, {
            "projection": "sector-workspace", "page_id": page, "title": title,
            "source_type": "SIMULATED", "namespace": self.namespace,
            "dataset_version": base["dataset_version"], "read_at": now(),
            "query_id": f"{page}-{checksum({'filters': applied, 'overview': overview})[:16]}",
            "business_clock": clock["at"], "overview_reference": overview,
            "design_filters": design_filters, "filter_options": {},
            "applied_filters": applied,
            "metrics": ([{"id": f"{page}-kpi-{index}", "label": metric["label"],
                          "value": metric["points"][-1]["value"], "unit": metric["unit"],
                          "period": facts["period"], "source_ids": [pack["source_id"]],
                          "state": "SIMULATED", "definition_version": "1",
                          "comparability": "同一模拟资料包与指标定义版本"}
                         for index, metric in enumerate(facts["metrics"])] if facts else
                        [{"id": f"{page}-kpi-{index}", "label": label, "value": None, "unit": None,
                          "period": None, "source_ids": [], "state": "SOURCE_NOT_AVAILABLE",
                          "definition_version": "1", "comparability": "当前没有可比较的正式明细"}
                         for index, label in enumerate(kpis)]),
            "trend": ({"metric_id": facts["metrics"][0]["label"], "unit": facts["metrics"][0]["unit"],
                       "points": [{"period": point["period"], "value": point["value"],
                                   "source_ids": [pack["source_id"]]}
                                  for point in facts["metrics"][0]["points"]]}
                      if facts and facts["metrics"] else None),
            "records": records, "sections": sections, "relations": relations, "workflow": workflow,
            "sources": sources, "coverage": coverage, "missing_fields": missing,
            "availability": "SIMULATED_METRICS_ONLY" if facts else "SOURCE_NOT_AVAILABLE", "contacts": contacts,
            "followup_actions": [], "resource_options": [], "timezones": [timezone],
            "owner_timezone": timezone, "related_source_refs": matching,
            "sector_specific_dataset_available": bool(facts),
            "sector_kpi_calculations_supported": bool(facts),
            "data_gap": ("已有关联水产饲料外销经营资料，但不足以计算本页指标。" if matching
                         else "尚无本专题经过核验的有效模拟业务明细。"),
            "business_scope": "selection dataset; not a full enterprise ERP",
        }
