# 为当前验收实例补充模拟业务数据：消息草稿与会议纪要草稿。
# 只写入 SIMULATED 数据，不发送消息、不确认纪要、不创建外部请求。
from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "validation"))

from boss_command_api import BossCommandAPI
from controls import ControlStore

WORK = Path(os.environ.get("BOSS_APPLICATION_WORK_DIR", ROOT / "validation/.work/application-acceptance")).resolve()
STORE = ControlStore(WORK / "business.sqlite")
API = BossCommandAPI(STORE)
MARKER_ID = "demo-seed-1"

DRAFTS = [
    ("coordinator-1", "请在本周内完成华东区域交付缺口核查，并附批次回访记录。"),
    ("finance-1", "请核对本月水产季节订单与回款范围，确认后回复。"),
    ("contact-2", "会前材料已更新，请查看当前版本并准备需要讨论的问题。"),
]

MINUTES = [
    ("OPINION", "历史纪要显示协调人已完成经营原始明细准备。", "historical-1 由 coordinator-1 统筹准备经营原始明细"),
    ("DECISION", "经营事件 event-1 继续保持 OPEN，等待本人完成决定。", "关联经营事件 event-1 保持 OPEN"),
    ("ASSIGNMENT_DRAFT", "由协调人继续跟进完成决定所需材料。", "尚未收到本人完成决定"),
]


def execute(action: str, payload: dict) -> None:
    status, body = API.execute("BOSS", action, payload)
    detail = body.get("result", body) if isinstance(body, dict) else body
    print(action, status, str(detail)[:180])
    if status != 200:
        raise SystemExit("seed failed: " + str(detail)[:300])


def main() -> None:
    with STORE.connect() as db:
        marker = db.execute("SELECT 1 FROM objects WHERE namespace=? AND kind='demo_seed' AND id=?",
                            ("ui-check", MARKER_ID)).fetchone()
        application = db.execute("SELECT 1 FROM objects WHERE namespace=? AND kind='application'",
                                 ("ui-check",)).fetchone()
    if application is None:
        status, body = API.execute("MAINTAINER", "boss.simulation.application.seed", {
            "client_request_id": str(uuid.uuid4()), "application_id": "application-1",
            "applicant_contact_id": "coordinator-1", "amount_cny": "3000.00",
            "title": "华东区域交付缺口补充材料",
            "description": "请批准补充批次回访记录与库存明细，用于核查交付缺口。",
            "attachment_text": "模拟附件：华东区域批次回访记录，库存明细与交付缺口说明。",
        })
        print("boss.simulation.application.seed", status, str(body)[:180])
        if status != 200:
            raise SystemExit("application seed failed")
    if marker is not None:
        print("demo seed already present")
        return
    for recipient, body in DRAFTS:
        execute("boss.message.draft.save", {
            "client_request_id": str(uuid.uuid4()), "draft_id": None, "expected_version": "0",
            "recipient_id": recipient, "related_task_id": None, "body": body,
            "attachment_refs": [{"source_id": "finance-note", "version": "1"}],
            "visibility": "RECIPIENT_ONLY",
        })
    execute("boss.minutes.save", {
        "client_request_id": str(uuid.uuid4()), "meeting_id": "meeting-1", "meeting_version": "1",
        "source_id": "meeting-minutes", "source_version": "1", "expected_version": "0",
        "entries": [{"kind": kind, "text": text, "source_anchor": anchor} for kind, text, anchor in MINUTES],
    })
    with STORE.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        STORE.put(db, "ui-check", "demo_seed", MARKER_ID, {"seed_id": MARKER_ID, "source_type": "SIMULATED"})
    print("demo seed written")


if __name__ == "__main__":
    main()
