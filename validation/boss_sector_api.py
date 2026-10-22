"""Grounded agriculture-specific readiness views for FR-14 through FR-23.

Field names and metric labels are transcribed from the user's approved
Desktop v6 HTML sources (not fabricated business results). Data availability
comes only from the current ControlStore and its versioned sources.
"""
from __future__ import annotations

from urllib.parse import parse_qs

from aiohttp import web

from business import now

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
    def __init__(self, store, namespace="ui-check"):
        self.store, self.namespace = store, namespace

    def serve(self, role, query_string):
        if role != "BOSS":
            return (401 if role is None else 403), {"error": "FORBIDDEN"}
        params = parse_qs(query_string, keep_blank_values=True)
        if set(params) != {"page"} or len(params["page"]) != 1:
            return 400, {"error": "INVALID_SCOPE"}
        page = params["page"][0]
        if page not in SECTORS:
            return 404, {"error": "UNKNOWN_SECTOR"}
        title, filters, kpis = SECTORS[page]
        with self.store.connect() as db:
            self.store.active(db, self.namespace)
            base = self.store.get(db, self.namespace, "initial", "snapshot")
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
                    import json
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
        return 200, {
            "page_id": page, "title": title, "design_filters": filters,
            "kpi_labels": kpis,
            "metrics": [
                {"label": label, "value": None, "unit": None,
                 "data_status": "SOURCE_NOT_AVAILABLE"}
                for label in kpis
            ],
            "related_source_refs": matching,
            "sector_specific_dataset_available": False,
            "sector_kpi_calculations_supported": False,
            "data_gap": ("已有关联水产饲料外销经营资料，但不足以计算本页的原料价格、合同和领用成本。"
                         if matching else "尚无本专题经过核验的有效模拟业务明细。"),
            "business_scope": "selection dataset; not a full enterprise ERP",
            "source_type": "SIMULATED", "namespace": self.namespace,
            "dataset_version": base["dataset_version"],
            "read_at": now(),
        }
