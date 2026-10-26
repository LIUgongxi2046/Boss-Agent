"""Deterministic simulated sector metric pack for F14-F23.

The pack is seeded once per execution space as versioned SIMULATED source
documents. Values are generated from a fixed seed; they are not real business
results and carry no claim beyond the explicit simulated range.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta

from business import now
from boss_sector_api import CATALOGUE, SECTORS

PACK_VERSION = "4"
DEFINITION = "SECTOR-PACK-1"
UNIT_MAP = {
    "F14": ["CNY/吨", "CNY/吨", "CNY/吨", "CNY/吨"],
    "F15": ["吨", "吨", "万尾", "%"],
    "F16": ["批次", "头", "%"],
    "F17": ["次", "%", "天"],
    "F18": ["头", "CNY", "头", "CNY/头"],
    "F19": ["吨", "公斤", "头", "头/日"],
    "F20": ["亩", "吨", "CNY"],
    "F21": ["件", "批次", "%"],
    "F22": ["CNY", "吨", "吨", "CNY"],
    "F23": ["项", "%", "分"],
    "V19-BEEF": ["吨", "公斤", "头", "头/日"],
    "V19-EGG": ["吨", "枚", "枚", "克"],
    "V19-MILK": ["吨", "公斤", "公斤", "天"],
}
PERIODS = ["2026-08", "2026-09", "2026-10"]
FILTER_CHOICES = {
    "区域": ["华东", "华南"], "品种": ["草鱼", "对虾"], "阶段": ["苗期", "育肥期"],
    "客户": ["客户A", "客户B"], "观察期": ["2026-09", "2026-10"], "批次": ["批次-1", "批次-2"],
    "专业责任人": ["coordinator-1", "finance-1"], "用途": ["肉禽", "蛋禽"], "日龄": ["21天", "35天"],
    "比较周期": ["2026-09", "2026-10"], "国别": ["越南", "印度尼西亚"], "法人": ["entity-1"],
    "本地期间": ["2026-09", "2026-10"], "集团期间": ["2026-09", "2026-10"], "币种": ["USD", "CNY"],
    "时区": ["Asia/Ho_Chi_Minh", "Asia/Shanghai"], "研发项目": ["研发-1", "研发-2"],
    "试验版本": ["v1"], "专业评审": ["待评审", "已评审"], "决定问题": ["扩大试验", "维持范围"],
}
TEXT_FIELDS = {"天气观察": ["晴间多云 · 模拟", "多云转雨 · 模拟"], "适用单位": ["公斤/头 · 模拟", "公斤/头 · 模拟"]}


def _number(page, label, period, unit):
    digest = hashlib.sha256((page + "|" + label + "|" + period + "|" + DEFINITION).encode()).digest()
    value = int.from_bytes(digest[:4], "big")
    if unit == "%":
        return str(round(1 + value % 8800 / 100, 2))
    if unit == "CNY":
        return str(10000 + value % 90000)
    if unit.startswith("CNY/"):
        return str(100 + value % 900)
    if unit in ("公斤", "枚", "克", "分", "天", "头/日"):
        return str(10 + value % 990)
    return str(round(20 + value % 9800 / 10, 1))


def _rows(page):
    design = CATALOGUE.get(page) or {}
    filters = design.get("filters") or []
    fields = design.get("fields") or []
    _, _, kpis = SECTORS[page]
    kpi_units = UNIT_MAP.get(page, [""] * len(kpis))
    unit_by_label = {label: kpi_units[index] if index < len(kpi_units) else ""
                     for index, label in enumerate(kpis)}
    rows = []
    for index in range(6):
        values, dims = {}, {}
        for label in filters:
            choices = FILTER_CHOICES.get(label, ["范围A", "范围B"])
            dims[label] = choices[index % len(choices)]
            values[label] = dims[label]
        for label in fields:
            if label in TEXT_FIELDS:
                choices = TEXT_FIELDS[label]
                values[label] = choices[index % len(choices)]
            elif label in dims:
                values[label] = dims[label]
            else:
                values[label] = _number(page, label, PERIODS[-1], unit_by_label.get(label, ""))
        rows.append({"id": page.lower() + "-row-" + str(index + 1), "values": values,
                     "dims": dims, "version": "1", "state": "SIMULATED"})
    return rows


def _sections(page):
    design = CATALOGUE.get(page) or {}
    kinds = ["FACT", "OPINION", "INFERENCE"]
    return [{"title": title,
             "text": "模拟资料范围：" + page + " · " + title + "；当前仅有指标与模拟明细，关系与后续动作尚未提供。",
             "claim_kind": kinds[index % 3] if page == "F23" else None}
            for index, title in enumerate(design.get("sections") or [])]


def _relations(page):
    labels = {"F16": ["繁育", "检验", "交付", "运输", "接收", "放养", "回访"],
              "F20": ["事件与观察", "observed_at", "received_at", "测量方法", "当前措施", "批次关系"]}.get(page, [])
    return [{"id": page.lower() + "-rel-" + str(index + 1), "label": label, "state": "SIMULATED",
             "description": "模拟关联证据：" + label + "；仅用于界面范围展示。", "source_ids": []}
            for index, label in enumerate(labels)]


def _workflow(page):
    if page != "F17":
        return []
    stages = ["观察", "采样检测", "专业确认", "执行反馈", "复查"]
    states = ["complete", "complete", "current", "waiting", "waiting"]
    return [{"title": stage, "description": "模拟阶段：" + stage, "state": states[index],
             "author": "coordinator-1" if stage == "专业确认" else None,
             "source_ids": [], "confirmed_at": None}
            for index, stage in enumerate(stages)]


def _page_facts(page):
    _, _, kpis = SECTORS[page]
    units = UNIT_MAP.get(page, [""] * len(kpis))
    metrics = []
    for index, label in enumerate(kpis):
        unit = units[index] if index < len(units) else ""
        points = [{"period": period, "value": _number(page, label, period, unit)} for period in PERIODS]
        metrics.append({"label": label, "unit": unit, "points": points})
    design = CATALOGUE.get(page) or {}
    filter_options = {
        label: [{"id": choice, "label": choice} for choice in FILTER_CHOICES.get(label, ["范围A", "范围B"])]
        for label in (design.get("filters") or [])
    }
    return {"metrics": metrics, "rows": _rows(page), "sections": _sections(page),
            "relations": _relations(page), "workflow": _workflow(page),
            "filter_options": filter_options, "period": PERIODS[-1], "periods": PERIODS}


def _document(page, snapshot):
    clock = datetime.fromisoformat(snapshot["business_clock"])
    published = (clock - timedelta(days=2)).isoformat()
    valid_from = (clock - timedelta(days=10)).isoformat()
    facts = _page_facts(page)
    return {
        "source_id": "sector-" + page.lower() + "-a", "version": "1",
        "source_type": "SIMULATED", "author_contact_id": "finance-1",
        "access_scope": snapshot["owner_id"], "published_at": published,
        "valid_from": valid_from, "valid_until": None, "validity_state": "VALID",
        "original_locator": "sector-pack:" + page, "sector_page": page,
        "sector_facts": facts, "simulation_definition": DEFINITION,
        "content": "专题 " + page + " 模拟资料：按固定种子生成 " + str(len(facts["metrics"])) + " 项指标，覆盖 2026-08 至 2026-10；不是真实企业经营结果。",
    }


def ensure_sector_pack(store, db, snapshot):
    existing = db.execute("SELECT body FROM objects WHERE namespace=? AND kind='sector_pack' AND id='current'",
                          ("ui-check",)).fetchone()
    if existing is not None:
        marker = json.loads(existing[0])
        if marker.get("version") == PACK_VERSION and marker.get("dataset_version") == snapshot["dataset_version"]:
            return marker
    documents = [_document(page, snapshot) for page in SECTORS]
    for document in documents:
        store.put(db, "ui-check", "document", document["source_id"], document)
    marker = {"version": PACK_VERSION, "definition": DEFINITION,
              "dataset_version": snapshot["dataset_version"],
              "document_ids": [document["source_id"] for document in documents],
              "generated_at": now(), "source_type": "SIMULATED"}
    store.put(db, "ui-check", "sector_pack", "current", marker)
    return marker
