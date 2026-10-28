import calendar
import json
from copy import deepcopy
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import yaml

from boss_command_api import BossCommandAPI
from boss_sector_api import CATALOGUE, SECTORS, query_id_for
from boss_sector_pack import PACK_VERSION, DEFINITION
from boss_supply_quality import SupplyQualityAPI, IMPORT_ACTION
from business import checksum, encode

ROOT = Path(__file__).resolve().parents[1]
NS = "ui-check"
REVISION = "COMPREHENSIVE-20261028-1"
BASELINE = json.loads((ROOT / "specs/public-business-baseline.json").read_text())
PEOPLE = [
    ("coordinator-1", "林知远", "总经理办公室", "业务统筹与秘书协调"),
    ("finance-1", "许清和", "财务管理中心", "财务分析与资金计划"),
    ("contact-2", "沈嘉宁", "江洲水产合作社", "客户采购与养殖反馈"),
    ("purchasing-1", "周启航", "采购管理中心", "玉米豆粕采购与供应保障"),
    ("aquatic-1", "顾雨桐", "水产业务部", "季节订单与渠道库存"),
    ("seed-1", "陆景川", "种苗事业部", "苗种批次与交付跟踪"),
    ("health-1", "温予安", "动物健康中心", "专业采样与技术服务"),
    ("pig-1", "江承泽", "生猪事业部", "合作农场与批次结算"),
    ("poultry-1", "宋语晴", "禽畜事业部", "肉禽蛋禽奶畜与反刍业务"),
    ("farm-1", "程沐阳", "养殖运营中心", "自营养殖与设备记录"),
    ("quality-1", "叶书宁", "食品品质中心", "客诉追溯与专业复查"),
    ("overseas-1", "方明澈", "国际业务中心", "海外订单与回款"),
    ("research-1", "苏念慈", "中央研究院", "研发试验与专家评审"),
    ("customer-1", "贺云舟", "青禾食品有限公司", "食品客户与订单验收"),
]

# 每项分别保存三个月的业务数值，单位与业务对象共同定义。
SERIES = {
    "F14": [("行情价格", "CNY/吨", [3120, 3180, 3360]), ("合同价格", "CNY/吨", [3080, 3130, 3210]), ("入库成本", "CNY/吨", [3110, 3160, 3250]), ("领用成本", "CNY/吨", [3130, 3180, 3320])],
    "F15": [("订单", "吨", [52000, 55000, 49500]), ("渠道库存", "吨", [7800, 8200, 10200]), ("投苗投喂", "万尾", [9200, 9600, 8640]), ("回访分子分母", "%", [82, 86, 75])],
    "F16": [("批次来源", "批次", [36, 40, 44]), ("投苗依据", "万尾", [18000, 20000, 22000]), ("专业反馈", "%", [94, 95, 91])],
    "F17": [("现场问题", "件", [18, 16, 22]), ("用药依据", "%", [100, 100, 100]), ("回访证据", "天", [2, 2, 3])],
    "F18": [("存栏", "头", [48000, 49200, 50100]), ("转群", "头", [6800, 7200, 7500]), ("出栏重量", "公斤/头", [122, 123, 124]), ("出栏价格", "CNY/公斤", [15.8, 15.2, 14.6])],
    "F19": [("供料数量", "吨", [42000, 43500, 45000]), ("体重", "公斤/羽", [2.5, 2.55, 2.6]), ("出栏", "羽", [460000, 475000, 490000]), ("适用单位", "日龄", [42, 42, 42])],
    "F20": [("养殖单元", "亩", [3600, 3600, 3600]), ("设备记录", "次", [180, 186, 210]), ("批次证据", "批次", [24, 26, 28])],
    "F21": [("客诉证据", "件", [8, 6, 9]), ("质量追溯", "批次", [260, 280, 310]), ("批次关系", "%", [98, 99, 100])],
    "F22": [("订单", "CNY", [1080000000, 1140000000, 1240000000]), ("工段能力", "吨", [270000, 280000, 290000]), ("交付缺口", "吨", [12000, 10000, 18000]), ("回款范围", "CNY", [890000000, 920000000, 980000000])],
    "F23": [("试验依据", "项", [12, 14, 16]), ("版本状态", "%", [80, 85, 87.5]), ("专业评审", "分", [78, 81, 84])],
    "V19-BEEF": [("供料量", "吨", [2800, 2900, 3050]), ("生长表现", "公斤/头/日", [1.15, 1.18, 1.20]), ("出栏", "头", [640, 660, 690]), ("适用单位", "日龄", [480, 480, 480])],
    "V19-EGG": [("供料", "吨", [4100, 4200, 4300]), ("产蛋量", "枚", [31800000, 32400000, 33000000]), ("合格蛋重", "克/枚", [59, 59.5, 60]), ("适用单位", "日龄", [260, 260, 260])],
    "V19-MILK": [("供料量", "吨", [3600, 3650, 3700]), ("产奶表现", "公斤/头/日", [32, 32.5, 33]), ("计量单位", "公斤", [4800000, 4875000, 4950000]), ("观察期", "天", [30, 30, 30])],
}
TOPIC_NOTES = {
    "F14": "周启航报告豆粕行情3360元/吨，合同3210元/吨，入库3250元/吨，领用3320元/吨。可用库存6400吨，日耗800吨，覆盖8天；待检900吨和在途1200吨分别记录。成本变化原因需要核对合同生效与领用批次。",
    "F15": "顾雨桐报告华南草鱼育肥订单49500吨，渠道库存10200吨，回访90户、计划120户，覆盖75%。订单减少与库存增加同时出现，尚未确认天气或客户需求的贡献。沈嘉宁负责提供养户记录。",
    "F16": "陆景川记录育苗批次FZ-M1020，经检验、运输、签收关联养殖批次FZ-A1022；本月44批次、投苗22000万尾。抽样40个池塘，其中36个具备完整接收与回访记录，其余4个待补充。",
    "F17": "温予安记录现场问题22件，其中18件已经采样，4件等待客户补充现场材料。专业记录与业务协调分别保存，尚未作出用药或确诊决定；下一次复查安排在业务日期次日下午。",
    "F18": "江承泽报告合作农场期初49200头，转入7500头，出栏6500头，其他转出100头，期末50100头；每头出栏124公斤、价格14.6元/公斤。两个批次尚未结算，不能将预计结果当作已结算利润。",
    "F19": "宋语晴记录肉禽供料45000吨，平均体重2.6公斤/羽，出栏490000羽，观察日龄42天。蛋禽、奶畜和肉用牛羊分别采用各自的计量单位与观察条件。",
    "F20": "程沐阳记录自营养殖3600亩、28个在养批次。设备巡检210次，3次增氧异常已经登记人工检查，设备资料不表示远程控制已经执行。费用归属为丰泽水产养殖有限公司。",
    "F21": "叶书宁收到9件客诉；已保存310批次追溯关系，当前模拟加工批次FZ-F1021关联客户贺云舟。库存与交付分别追踪，检验尚未完成，专业核查与老板交办保持各自状态。",
    "F22": "方明澈报告订单12.4亿元人民币、工段能力290000吨、交付缺口18000吨、已收到回款9.8亿元人民币。越南当地时间与北京时间相差一小时，金额全部采用人民币结算；未提供外币折算与汇率，不推算外币金额。",
    "F23": "苏念慈负责16项试验，其中14项完成版本审查。对虾试验采用试验组120池、对照组120池，观察30天；专家评审84分。试验样本用于演练，不能推定真实推广效果。",
}
TASKS = [
    ("F14", "核查豆粕合同与领用成本差异", -1, "RESULT_SUBMITTED", "周启航已提交合同和入库记录，等待本人核查领用批次。"),
    ("F15", "补充草鱼订单减少的客户回访资料", 0, "IN_PROGRESS", "顾雨桐已完成90户回访，剩余30户计划今日完成。"),
    ("F16", "补齐苗种签收与养殖批次关系", 1, "WAITING_FEEDBACK", "陆景川负责核对4个池塘的签收和投苗记录。"),
    ("F17", "协调技服采样与专业复查", 1, "IN_PROGRESS", "温予安已完成18件采样，4件等待现场材料。"),
    ("F18", "核查合作农场未结算批次", -2, "WAITING_FEEDBACK", "江承泽需要提供两个批次的饲料、转群及费用凭证。"),
    ("F19", "复核禽畜四种用途的统计单位", 2, "RESULT_SUBMITTED", "宋语晴已按用途提交独立统计表。"),
    ("F20", "安排养殖设备异常人工检查", 0, "IN_PROGRESS", "程沐阳正在核查3次异常巡检及人工处理记录。"),
    ("F21", "跟进食品客诉与批次检验", 1, "WAITING_FEEDBACK", "叶书宁负责联系贺云舟补充检验资料，尚无质量放行结论。"),
    ("F22", "协调越南订单交付缺口", 0, "IN_PROGRESS", "方明澈已经整理18000吨缺口，等待生产排期。"),
    ("F23", "核查对虾试验对照与样本范围", 3, "OPEN", "苏念慈需要提供两组各120池的原始观察记录。"),
    ("F14", "汇总原料到货计划", 2, "WAITING_FEEDBACK", "周启航负责提供未来八天到货计划。"),
    ("F22", "核对海外回款与订单范围", 2, "RESULT_SUBMITTED", "许清和与方明澈已提交人民币回款范围。"),
]


def _at(clock, days=0, hour=17):
    return (clock + timedelta(days=days)).replace(hour=hour, minute=0, second=0, microsecond=0).isoformat()


def _months(clock):
    first = clock.replace(day=1)
    previous = (first - timedelta(days=1)).replace(day=1)
    older = (previous - timedelta(days=1)).replace(day=1)
    return [value.strftime("%Y-%m") for value in (older, previous, first)]


def _shift_times(value, delta):
    fields = {"quoted_at", "expires_at", "period_start", "period_end", "followup_at", "due_at", "starts_at", "ends_at", "valid_from", "valid_until"}
    if isinstance(value, dict):
        for key, item in value.items():
            if key in fields and isinstance(item, str):
                shifted = datetime.fromisoformat(item) + delta
                value[key] = shifted.isoformat() if "T" in item else shifted.date().isoformat()
            else:
                _shift_times(item, delta)
    elif isinstance(value, list):
        for item in value:
            _shift_times(item, delta)


def _document(identifier, title, content, clock, author="finance-1"):
    return {"source_id": identifier, "title": title, "version": "1", "source_type": "SIMULATED",
            "author_contact_id": author, "author_display_name": next(person[1] for person in PEOPLE if person[0] == author),
            "access_scope": "boss-1", "published_at": _at(clock, -6, 8), "observed_at": _at(clock, -6, 8),
            "valid_from": _at(clock, -10, 0), "valid_until": None, "validity_state": "VALID",
            "original_locator": "simulation:" + REVISION + "/" + identifier,
            "content": "丰泽农牧集团业务演练资料；人物与业务记录均为模拟。\n" + content}


def _save_document(store, db, document):
    existing = db.execute("SELECT body FROM objects WHERE namespace=? AND kind='document' AND id=?", (NS, document["source_id"])).fetchone()
    if existing:
        previous = json.loads(existing[0])
        store.put(db, NS, "document_history", document["source_id"] + ":" + previous["version"], previous)
        document["version"] = str(int(previous["version"]) + 1)
    store.put(db, NS, "document", document["source_id"], document)
    db.execute("DELETE FROM knowledge WHERE namespace=? AND source_id=?", (NS, document["source_id"]))
    db.execute("INSERT INTO knowledge VALUES(?,?,?)", (NS, document["source_id"], document["content"]))


def _sectors(store, db, snapshot, clock):
    months = _months(clock)
    for page, series in SERIES.items():
        labels = CATALOGUE.get(page, {}).get("fields", [])
        choices = {"区域": "华南", "品种": "草鱼", "阶段": "育肥期", "比较周期": months[-1],
                   "原料": "豆粕", "产品": "水产饲料", "法人": "entity-1", "期间": months[-1],
                   "国别": "越南", "币种": "CNY", "时区": "Asia/Ho_Chi_Minh", "本地期间": months[-1], "集团期间": months[-1],
                   "批次": "FZ-M1020", "专业责任人": "温予安", "用途": "肉禽", "客户": "青禾食品有限公司", "观察期": months[-1],
                   "研发项目": "对虾营养试验", "试验版本": "v3", "专业评审": "已评审", "决定问题": "继续验证",
                   "合作主体": "青田合作农场", "周期": months[-1], "结算状态": "未结算", "养户反馈": "江洲水产合作社",
                   "苗种批次": "FZ-M1020", "养殖批次": "FZ-A1022", "自营法人": "丰泽水产养殖有限公司", "养殖单元": "江洲养殖区",
                   "设备": "增氧机A03", "客诉": "青禾食品品质回访", "原料批次": "FZ-R1020", "加工批次": "FZ-F1021", "查询范围": "当前批次"}
        filters = CATALOGUE.get(page, {}).get("filters", [])
        dims = {label: choices.get(label, "当前业务范围") for label in filters}
        current = {label: str(values[-1]) for label, _, values in series}
        values = {label: current.get(label, {"库存质量": "已检可用6400吨；待检900吨", "覆盖天数": "8", "天气观察": "模拟观察：多云；尚无因果结论", "繁育": "FZ-M1020", "检验": "已保存批次报告", "运输": "冷链运输记录", "接收": "江洲合作社已签收", "放养": "FZ-A1022", "回访": "36/40个池塘资料完整", "样本分母": "试验120池；对照120池", "对照组": "同周期对照组", "观察期": "30天", "效果指标": "专业评审84分；适用范围待复核"}.get(label, TOPIC_NOTES.get(page, "按当前用途独立统计"))) for label in labels}
        values.update({label: value for label, value in current.items()})
        note = TOPIC_NOTES.get(page, "宋语晴按独立用途统计，数值只代表模拟观察记录。")
        facts = {"periods": months, "period": months[-1],
                 "metrics": [{"label": label, "unit": unit, "points": [{"period": month, "value": str(value)} for month, value in zip(months, numbers)]} for label, unit, numbers in series],
                 "rows": [{"id": page.lower() + "-current", "values": values, "dims": dims, "version": "1", "state": "SIMULATED"}],
                 "filter_options": {label: [{"id": value, "label": value}] for label, value in dims.items()},
                 "sections": [{"title": title, "text": note, "claim_kind": "FACT"} for title in CATALOGUE.get(page, {}).get("sections", [])],
                 "relations": [], "workflow": []}
        if page in {"F16", "F20", "F21"}:
            facts["relations"] = [{"id": page + "-evidence", "label": "当前批次关联记录", "state": "SIMULATED", "description": note, "source_ids": ["sector-" + page.lower() + "-a"]}]
        if page == "F17":
            facts["workflow"] = [{"title": title, "description": note, "state": state, "author": "温予安", "source_ids": ["sector-f17-a"], "confirmed_at": None} for title, state in [("观察", "complete"), ("采样检测", "current"), ("专业确认", "waiting"), ("执行反馈", "waiting"), ("复查", "waiting")]]
        doc = _document("sector-" + page.lower() + "-a", SECTORS[page][0] + "经营资料", note + "\n各月指标：" + encode(facts["metrics"]), clock)
        doc.update(sector_page=page, sector_scope={"legal_entity_ids": ["entity-1"], "region_ids": ["region-1"]}, sector_facts=facts, simulation_definition=DEFINITION)
        _save_document(store, db, doc)
    store.put(db, NS, "sector_pack", "current", {"version": PACK_VERSION, "definition": DEFINITION,
              "dataset_version": snapshot["dataset_version"], "document_ids": ["sector-" + page.lower() + "-a" for page in SERIES],
              "generated_at": clock.isoformat(), "source_type": "SIMULATED"})


def populate(store, business_at):
    clock = datetime.fromisoformat(business_at)
    if clock.tzinfo is None:
        raise ValueError("业务时钟必须包含时区")
    with store.connect() as db:
        marker = db.execute("SELECT body FROM objects WHERE namespace=? AND kind='comprehensive_simulation' AND id=?", (NS, REVISION)).fetchone()
        if marker:
            current = store.get(db, NS, "initial", "snapshot")
            db.execute("UPDATE spaces SET snapshot=? WHERE namespace=? AND snapshot<>?", (checksum(current), NS, checksum(current)))
            return json.loads(marker[0])
        original = {(ns, kind, identifier): body for ns, kind, identifier, body in db.execute("SELECT namespace,kind,id,body FROM objects")}
        original_spaces = dict(db.execute("SELECT namespace,snapshot FROM spaces"))
        original_audit = db.execute("SELECT COALESCE(MAX(id),0) FROM audit").fetchone()[0]
    from controls import ControlStore
    staged = ControlStore(store.path.parent / ("simulation-build-" + uuid4().hex + ".sqlite"))
    with store.connect() as source, staged.connect() as target:
        source.backup(target)
    try:
        result = _populate(staged, business_at)
        with staged.connect() as source, store.connect() as target:
            target.execute("BEGIN IMMEDIATE")
            changed = [(ns, kind, identifier, body) for ns, kind, identifier, body in source.execute("SELECT namespace,kind,id,body FROM objects") if original.get((ns, kind, identifier)) != body]
            for ns, kind, identifier, body in changed:
                current = target.execute("SELECT body FROM objects WHERE namespace=? AND kind=? AND id=?", (ns, kind, identifier)).fetchone()
                if (current[0] if current else None) != original.get((ns, kind, identifier)):
                    raise ValueError("业务资料在生成期间发生变化，请重新执行")
                store.put(target, ns, kind, identifier, json.loads(body))
                if kind == "document":
                    target.execute("DELETE FROM knowledge WHERE namespace=? AND source_id=?", (ns, identifier))
                    target.execute("INSERT INTO knowledge VALUES(?,?,?)", (ns, identifier, json.loads(body)["content"]))
            for ns, snapshot_hash in source.execute("SELECT namespace,snapshot FROM spaces"):
                if snapshot_hash != original_spaces.get(ns):
                    target.execute("UPDATE spaces SET snapshot=? WHERE namespace=?", (snapshot_hash, ns))
            for row in source.execute("SELECT namespace,operation,key,digest,result FROM idempotency"):
                existing = target.execute("SELECT digest,result FROM idempotency WHERE namespace=? AND operation=? AND key=?", row[:3]).fetchone()
                if existing is None:
                    target.execute("INSERT INTO idempotency VALUES(?,?,?,?,?)", row)
                elif tuple(existing) != tuple(row[3:]):
                    raise ValueError("业务请求在生成期间发生变化，请重新执行")
            for row in source.execute("SELECT namespace,operation,input,output,created_at FROM audit WHERE id>?", (original_audit,)):
                target.execute("INSERT INTO audit(namespace,operation,input,output,created_at) VALUES(?,?,?,?,?)", row)
        return result
    finally:
        staged.path.unlink()
        for suffix in ("-wal", "-shm"):
            journal = Path(str(staged.path) + suffix)
            if journal.exists():
                journal.unlink()


def _populate(store, business_at):
    clock = datetime.fromisoformat(business_at)
    if clock.tzinfo is None:
        raise ValueError("业务时钟必须包含时区")
    with store.connect() as db:
        marker = db.execute("SELECT body FROM objects WHERE namespace=? AND kind='comprehensive_simulation' AND id=?", (NS, REVISION)).fetchone()
        if marker:
            return json.loads(marker[0])
        snapshot = store.get(db, NS, "initial", "snapshot")
        original_clock = datetime.fromisoformat(store.get(db, NS, "clock", "current")["at"])
        if original_clock > clock:
            raise ValueError("业务日期早于当前时钟")
        seed_clock = max(original_clock, clock - timedelta(days=6))
        if seed_clock > original_clock:
            store.control_clock(db, NS, {"at": seed_clock.isoformat()})
        snapshot["contacts"] = [{"contact_id": identifier, "name": name, "organization": "丰泽农牧集团·" + organization,
                                 "responsibility": role, "valid_from": (clock - timedelta(days=365)).date().isoformat(),
                                 "valid_until": (clock + timedelta(days=365)).date().isoformat()} for identifier, name, organization, role in PEOPLE]
        snapshot["business_clock"] = clock.isoformat()
        snapshot["company_display_name"] = BASELINE["company_display_name"]
        snapshot["simulation_revision"] = REVISION
        snapshot["simulation_application_ids"] = ["simulation-application-" + str(index) for index in range(4)]
        months = _months(clock)
        snapshot["periods"] = {key: [month + "-01", month + "-" + str(calendar.monthrange(int(month[:4]), int(month[5:]))[1])] for key, month in zip(("BASE", "CURRENT"), months[-2:])}
        # 仅在未建立经营查询时生成新明细，已有查询继续保留其原始资料。
        if not db.execute("SELECT 1 FROM objects WHERE namespace=? AND kind IN ('query','query_source_binding') LIMIT 1", (NS,)).fetchone():
            margin = (Decimal(BASELINE["products"][0]["2025"]["revenue_cny"]) - Decimal(BASELINE["products"][0]["2025"]["cost_cny"])) / Decimal(BASELINE["products"][0]["2025"]["revenue_cny"])
            for period, volume in (("BASE", Decimal("55000")), ("CURRENT", Decimal("49500"))):
                for row in [item for item in snapshot["details"] if item["period"] == period]:
                    quantity = volume / 4
                    revenue = quantity * Decimal("4200")
                    row.update(quantity_tonnes=str(quantity), revenue_cny=str(revenue), cost_cny=str((revenue * (1 - margin) + (quantity * 140 if period == "CURRENT" else 0)).quantize(Decimal("0.01"))))
        snapshot["meeting"].update(title="月度经营与交付协调会议", starts_at=_at(clock, 0, 14), ends_at=_at(clock, 0, 16), preparation_due_at=_at(clock, 0, 12))
        snapshot["event"].update(due_at=_at(clock, 0), description="越南交付缺口与原料供应协调")
        snapshot["historical_task"].update(due_at=_at(clock, 1))
        snapshot["private_calendar"].update(starts_at=_at(clock, 0, 19), ends_at=_at(clock, 0, 20), private_body="模拟私人安排：家庭晚餐")
        store.put(db, NS, "initial", "snapshot", snapshot)
        db.execute("UPDATE spaces SET snapshot=? WHERE namespace=?", (checksum(snapshot), NS))
        _sectors(store, db, snapshot, clock)
        public = _document("public-business-baseline", "历史年度经营基准与产品结构", "公开报告历史基准，保留2024与2025原始期间；模拟经营沿用丰泽农牧集团名称。\n" + encode(BASELINE), clock)
        public["public_provenance"] = {"url": BASELINE["source_url"], "page": BASELINE["financial_page"], "published_on": BASELINE["published_on"]}
        _save_document(store, db, public)
        directory = _document("simulation-business-directory", "经营演练人员与业务索引", "\n".join(name + "，" + org + "，" + role for _, name, org, role in PEOPLE) + "\n" + "\n".join(SECTORS[page][0] + "：sector-" + page.lower() + "-a；" + note for page, note in TOPIC_NOTES.items()), clock)
        _save_document(store, db, directory)
        _save_document(store, db, _document("simulation-meeting-material", "经营会议议题与准备要求", "会议讨论原料覆盖8天、草鱼订单下降、越南交付缺口18000吨和未结算生猪批次。林知远统筹，许清和准备资金范围，周启航准备到货计划，方明澈准备海外排期。待本人决定是否增加跨区域产能协调。", clock))
        snapshot["meeting"]["material_ids"] = list(dict.fromkeys(snapshot["meeting"]["material_ids"] + ["public-business-baseline", "simulation-business-directory", "simulation-meeting-material"]))
        store.put(db, NS, "initial", "snapshot", snapshot)
        db.execute("UPDATE spaces SET snapshot=? WHERE namespace=?", (checksum(snapshot), NS))
        # 当前会议已经被本人修改时保留其正文及版本。
        if not db.execute("SELECT 1 FROM objects WHERE namespace=? AND kind='meeting' AND id='meeting-1'", (NS,)).fetchone():
            store.put(db, NS, "meeting", "meeting-1", snapshot["meeting"])
        for index, (title, day, hour, participants, material) in enumerate([
            ("越南产能与回款专题会议", 1, 10, ["coordinator-1", "overseas-1", "finance-1"], "sector-f22-a"),
            ("食品客诉与专业复查会议", 2, 15, ["coordinator-1", "quality-1", "health-1"], "sector-f21-a"),
            ("对虾研发试验评审会议", 3, 10, ["coordinator-1", "research-1", "aquatic-1"], "sector-f23-a"),
        ], 1):
            meeting_id = "simulation-meeting-" + str(index)
            store.put(db, NS, "meeting", meeting_id, {"meeting_id": meeting_id, "owner_id": "boss-1", "title": title,
                      "starts_at": _at(clock, day, hour), "ends_at": _at(clock, day, hour + 1), "timezone": "Asia/Shanghai", "participant_ids": participants,
                      "material_ids": [material], "historical_commitment_ids": [], "version": "1", "state": "DRAFT", "source_type": "SIMULATED"})
    api = BossCommandAPI(store)

    def execute(role, action, key, **payload):
        status, result = api.execute(role, action, {"client_request_id": REVISION + "-" + key, **payload})
        if status != 200:
            raise RuntimeError(action + " 执行失败：" + str(status) + " " + encode(result))
        return result

    task_ids = []
    for index, (page, purpose, days, state, feedback) in enumerate(TASKS):
        with store.connect() as db:
            source = store.get(db, NS, "document", "sector-" + page.lower() + "-a")
        due = max(datetime.fromisoformat(_at(clock, days)), seed_clock + timedelta(hours=8)).isoformat()
        task = execute("BOSS", "boss.sector.coordinate.create", "task-" + str(index), page_id=page, execution_namespace=NS,
                       dataset_version=snapshot["dataset_version"], query_id=query_id_for(page, {}, None), action_code="交办", filters={}, overview_reference=None,
                       source_refs=[{"source_id": source["source_id"], "version": source["version"]}], purpose=purpose, timezone="Asia/Shanghai",
                       coordinator_id="coordinator-1", coordinator_version="1", due_at=due, expected_output=feedback, evidence_requirements="带日期与作者的原始业务记录及处理建议")
        task_ids.append(task["task_id"])
        if state == "OPEN":
            continue
        sent = execute("BOSS", "boss.assignment.send", "send-" + str(index), task_id=task["task_id"], task_version="1", recipient_id="coordinator-1", body=purpose + "。请统筹相应业务责任人并按期反馈。", content_version="1")
        if state in {"IN_PROGRESS", "RESULT_SUBMITTED"}:
            execute("MAINTAINER", "boss.simulation.feedback", "feedback-" + str(index), task_id=task["task_id"], task_version=sent["task_version"], author_contact_id="coordinator-1", kind="PROGRESS" if state == "IN_PROGRESS" else "RESULT_SUBMITTED", content=feedback, evidence_refs=[source["source_id"]])
    for index, purpose in enumerate(["决定原料到货与跨区域产能协调安排", "审阅海外回款及交付资料", "确认研发试验后续评审范围"]):
        execute("BOSS", "boss.commitment.create", "commitment-" + str(index), purpose=purpose, due_at=_at(clock, index), timezone="Asia/Shanghai", importance="IMPORTANT", evidence_requirements=["当前有效经营资料与会议记录"], source_refs=[{"source_id": "public-business-baseline", "version": "1"}])
    for index, (title, applicant, amount, content) in enumerate([
        ("华南客户回访费用申请", "aquatic-1", "12000.00", "回访剩余30户客户，交通与现场资料费用12000元。"),
        ("食品客诉检验费用申请", "quality-1", "8600.00", "送检当前批次，检验及冷链样本运输合计8600元。"),
        ("越南产能协调差旅申请", "overseas-1", "26000.00", "两名业务人员开展产能与交付协调，差旅预算26000元。"),
        ("对虾试验观察费用申请", "research-1", "48000.00", "两组各120池观察30天，记录整理与采样预算48000元。"),
    ]):
        execute("MAINTAINER", "boss.simulation.application.seed", "application-" + str(index), application_id="simulation-application-" + str(index), applicant_contact_id=applicant, amount_cny=amount, title=title, description=content, attachment_text=content + " 本申请为模拟业务，等待本人决定。")
    with store.connect() as db:
        research_exists = db.execute("SELECT 1 FROM objects WHERE namespace=? AND kind='research' AND id='research-current'", (NS,)).fetchone() is not None
        secretary_exists = db.execute("SELECT 1 FROM objects WHERE namespace=? AND kind='secretary_configuration' AND id='current'", (NS,)).fetchone() is not None
        minutes_exists = db.execute("SELECT 1 FROM objects WHERE namespace=? AND kind='minutes' AND id='meeting-1'", (NS,)).fetchone() is not None
        meeting = store.get(db, NS, "meeting", "meeting-1")
        minute_source = store.get(db, NS, "document", "meeting-minutes")
        overseas_source = store.get(db, NS, "document", "sector-f22-a")
    if not research_exists:
        execute("BOSS", "boss.research.prepare", "research", expected_version="0", question="饲料", period="2025年度历史基准与当前模拟经营", country="中国、越南", business_relation="经营分析", cutoff_date=clock.date().isoformat(), source_refs=[{"source_id": "public-business-baseline", "version": "1"}], execution_namespace=NS)
    if not secretary_exists:
        execute("MAINTAINER", "boss.technical.secretary.save", "secretary", expected_version="0", recipient_id="coordinator-1", channel="EMAIL", address="lin.zhiyuan@example.test")
    if not minutes_exists:
        execute("BOSS", "boss.minutes.save", "minutes", meeting_id="meeting-1", meeting_version=meeting["version"], source_id="meeting-minutes", source_version=minute_source["version"], expected_version="0",
                entries=[{"kind": "ASSIGNMENT_DRAFT", "text": "林知远统筹经营会议资料，尚待本人核查。", "source_anchor": "historical-1"},
                         {"kind": "OPINION", "text": "越南交付缺口和原料覆盖需要进一步核查，不推定完成。", "source_anchor": "event-1"}])
    for index, person in enumerate(("overseas-1", "quality-1", "research-1")):
        execute("BOSS", "boss.people.prepare", "people-" + str(index), brief_id=None, expected_version="0", contact_id=person, purpose="核查当前业务材料、关联任务及会议待决定事项", meeting_id="meeting-1", source_refs=[{"source_id": "simulation-business-directory", "version": "1"}])
    draft = execute("BOSS", "boss.message.draft.save", "message", draft_id=None, expected_version="0", recipient_id="overseas-1", related_task_id=None,
                    body="方明澈，请提供越南18000吨交付缺口的排产选项、人民币回款凭证和客户交期。", attachment_refs=[{"source_id": "sector-f22-a", "version": overseas_source["version"]}], visibility="RECIPIENT_ONLY")
    with store.connect() as db:
        saved_draft = store.get(db, NS, "message_draft", draft["draft_id"])
    sent = execute("BOSS", "boss.message.send", "message-send", draft_id=draft["draft_id"], expected_version=draft["version"], recipient_id="overseas-1", expected_content_sha256=saved_draft["content_sha256"])
    execute("MAINTAINER", "boss.simulation.message.reply", "message-reply", message_id=sent["message_id"], author_contact_id="overseas-1", text="模拟反馈：18000吨缺口涉及越南订单，已整理现有排期及人民币回款凭证，跨区域产能选项仍待核查。")
    execute("BOSS", "boss.travel.review", "travel", travel_id=None, expected_version="0", origin="广州", destination="湛江养殖基地", starts_at=_at(clock, 4, 8), ends_at=_at(clock, 4, 18), timezone="Asia/Shanghai", host_contact_id="farm-1", buffer_minutes=60, transport_refs=[{"source_id": "simulation-business-directory", "version": "1"}])
    with store.connect() as db:
        clock_record = store.get(db, NS, "clock", "current")
        if datetime.fromisoformat(clock_record["at"]) < clock:
            store.control_clock(db, NS, {"at": clock.isoformat()})
    supply = deepcopy(yaml.safe_load((ROOT / "data/simulation/supply-quality-v1.yaml").read_text())["initial_request"])
    supply["client_request_id"] = REVISION + "-supply"
    _shift_times(supply, clock.replace(hour=9, minute=0, second=0, microsecond=0) - datetime.fromisoformat("2026-10-22T09:00:00+08:00"))
    for record in supply["records"]:
        record["source"].update(observed_at=_at(clock, -1), valid_from=_at(clock, -10, 0), valid_until=_at(clock, 30))
        if record["entity_type"] == "contact":
            record["data"].update(name="温予安", organization="丰泽农牧集团·动物健康中心", responsibility="模拟专业资料作者")
        if record["entity_type"] == "material_quote":
            record["data"].update(origin="华南豆粕到厂", coverage="模拟豆粕单项报价，CNY/吨")
            record["data"]["price"] = "3180" if record["data"]["quote_id"] == "sim-quote-base-1" else "3360"
        if record["entity_type"] == "material_contract":
            record["data"].update(quantity="8500", unit_price="3210")
        if record["entity_type"] == "inventory_lot" and record["data"]["material_id"] is not None:
            quantities = {"sim-stock-available-1": ("6400", "6400"), "sim-stock-pending-1": ("900", "0"), "sim-stock-transit-1": ("1200", "0")}
            quantity, available = quantities[record["data"]["inventory_id"]]
            record["data"].update(quantity=quantity, available_quantity=available, unit_cost="3250")
        if record["entity_type"] == "production_batch" and record["data"]["batch_type"] == "RAW_MATERIAL":
            record["data"]["quantity"] = "8500"
        if record["entity_type"] == "material_consumption":
            record["data"].update(quantity="800", daily_quantity="800", unit_cost="3320", assumption="模拟日耗800吨；可用库存6400吨，覆盖8天；库存余额不重复扣减。")
    SupplyQualityAPI(store).execute("MAINTAINER", IMPORT_ACTION, supply)
    with store.connect() as db:
        result = {"source_type": "SIMULATED", "revision": REVISION, "dataset_version": snapshot["dataset_version"],
                  "business_clock": clock.isoformat(), "contacts": len(PEOPLE), "topics": len(SERIES), "task_ids": task_ids, "external_delivery": False,
                  "public_baseline_sha256": checksum(BASELINE)}
        store.put(db, NS, "comprehensive_simulation", REVISION, result)
    return result
