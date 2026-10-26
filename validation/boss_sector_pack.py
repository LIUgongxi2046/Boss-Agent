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
from boss_sector_api import SECTORS

PACK_VERSION = "1"
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


def _page_facts(page):
    _, _, kpis = SECTORS[page]
    units = UNIT_MAP.get(page, [""] * len(kpis))
    metrics = []
    for index, label in enumerate(kpis):
        unit = units[index] if index < len(units) else ""
        points = [{"period": period, "value": _number(page, label, period, unit)} for period in PERIODS]
        metrics.append({"label": label, "unit": unit, "points": points})
    return {"metrics": metrics, "period": PERIODS[-1], "periods": PERIODS}


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
