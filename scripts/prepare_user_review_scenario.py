import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "validation"))

from boss_command_api import BossCommandAPI
from boss_page_api import BossPageAPI
from boss_sector_pack import ensure_sector_pack
from controls import ControlStore


def prepare(directory):
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    database = directory / "business.sqlite"
    if database.exists():
        raise FileExistsError("验收资料目录已经存在，请使用新的独立目录")
    store = ControlStore(database)
    store.initialize("ui-check")
    with store.connect() as db:
        ensure_sector_pack(store, db, store.get(db, "ui-check", "initial", "snapshot"))
    api = BossCommandAPI(store)

    def execute(role, action, key, **payload):
        status, result = api.execute(role, action, {"client_request_id": "user-review-" + key, **payload})
        if status != 200:
            raise RuntimeError(f"{action} 执行失败：{status} {result}")
        return result

    execute("MAINTAINER", "boss.technical.secretary.save", "secretary",
            expected_version="0", recipient_id="coordinator-1", channel="EMAIL", address="secretary@example.test")
    execute("MAINTAINER", "boss.simulation.application.seed", "application",
            application_id="application-1", applicant_contact_id="finance-1", amount_cny="3000.00",
            title="华东客户回访费用申请", description="申请三千元开展客户回访，核查近期交付情况与采购安排。",
            attachment_text="模拟申请材料：客户回访交通费用两千元，资料整理费用一千元，申请合计三千元。")
    for index, (purpose, person, due) in enumerate([
        ("确认华东区域下周供货安排", "coordinator-1", "2026-10-23T17:00:00+08:00"),
        ("核查本月采购成本变化", "coordinator-1", "2026-10-24T17:00:00+08:00"),
    ]):
        task = execute("BOSS", "boss.assignment.create", f"task-{index}", purpose=purpose,
                       coordinator_id=person, due_at=due, timezone="Asia/Shanghai",
                       evidence_requirements=["经营原始明细及处理建议"], related_meeting_id="meeting-1",
                       related_event_ids=["event-1"], source_refs=["finance-note"], content_version="1")
        execute("BOSS", "boss.assignment.send", f"send-{index}", task_id=task["task_id"],
                task_version=task["version"], recipient_id=person, body=purpose+"，请按约定时间反馈。", content_version="1")
    execute("BOSS", "boss.commitment.create", "commitment", purpose="确认下周经营会议的重点议题",
            due_at="2026-10-23T16:00:00+08:00", timezone="Asia/Shanghai", importance="IMPORTANT",
            evidence_requirements=["会议议题与经营材料"], source_refs=[{"source_id": "finance-note", "version": "1"}])
    execute("BOSS", "boss.research.prepare", "research", expected_version="0", question="毛利率",
            period="", country="", business_relation="", cutoff_date="2026-12-31",
            source_refs=[{"source_id": "finance-note", "version": "1"}], execution_namespace="ui-check")
    execute("BOSS", "boss.people.prepare", "people", brief_id=None, expected_version="0",
            contact_id="coordinator-1", purpose="讨论客户回访与下周供货安排", meeting_id="meeting-1",
            source_refs=[{"source_id": "meeting-minutes", "version": "1"}])
    pages = BossPageAPI(store)
    status, library = pages.serve("BOSS", "/api/boss/ui/owner/meeting-library")
    if status != 200 or any(not any(record["kind"] == kind for record in library["records"])
                            for kind in ("meeting", "document", "approval", "research", "people")):
        raise RuntimeError("模拟资料目录尚未覆盖全部业务分类")
    return {"source_type": "SIMULATED", "library_records": len(library["records"]), "external_delivery": False}


def main():
    parser = argparse.ArgumentParser(description="准备独立用户验收模拟资料，不创建登录账号")
    parser.add_argument("--directory", type=Path, required=True)
    args = parser.parse_args()
    directory = args.directory.resolve()
    if directory.parent != (ROOT / "validation/.work").resolve():
        raise ValueError("资料目录必须位于 validation/.work 的直接子目录")
    result = prepare(directory)
    print("模拟资料准备完成，目录记录数量：", result["library_records"])


if __name__ == "__main__":
    main()
