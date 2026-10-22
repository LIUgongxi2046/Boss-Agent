import argparse
import asyncio
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

from nanobot.cron.service import CronService
from nanobot.cron.types import CronSchedule

from business import ROOT, Store, now


async def worker(work, phase):
    store = Store(work / "business.sqlite")
    records = []
    fired = asyncio.Event()

    async def execute(job):
        result = store.notify("cron-check", "fixed-event")
        records.append({"at": now(), "pid": os.getpid(), "job_id": job.id, "result": result})
        (work / f"{phase}-callbacks.json").write_text(json.dumps(records, ensure_ascii=False, indent=2))
        fired.set()
        return json.dumps(result, ensure_ascii=False)

    service = CronService(work / "cron/jobs.json", on_job=execute, max_sleep_ms=100)
    await service.start()
    try:
        if phase == "execute":
            store.initialize("cron-check")
            job = service.add_job("T02 实际调度", CronSchedule(kind="every", every_ms=500), "处理已授权模拟事件", session_key="cron-check", origin_channel="websocket", origin_chat_id="cron-check")
            await asyncio.wait_for(fired.wait(), 5)
            service.enable_job(job.id, False)
            assert records[0]["result"]["state"] == "DELIVERED"
            assert await service.run_job(job.id, force=True)
            assert records[1]["result"]["state"] == "SUPPRESSED"
            (work / "job-id.json").write_text(json.dumps({"id": job.id}))
        else:
            job_id = json.loads((work / "job-id.json").read_text())["id"]
            job = next(job for job in service.list_jobs(include_disabled=True) if job.id == job_id)
            assert job.enabled is False
            await asyncio.sleep(1.2)
            assert records == []
            service.enable_job(job_id, True)
            await asyncio.wait_for(fired.wait(), 5)
            assert records[0]["result"]["state"] == "SUPPRESSED"
            assert service.remove_job(job_id)
            count = len(records)
            await asyncio.sleep(1.2)
            assert len(records) == count
    finally:
        service.stop()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=["execute", "restart"])
    parser.add_argument("--work", type=Path)
    args = parser.parse_args()
    if args.phase:
        asyncio.run(worker(args.work, args.phase))
        return
    run_id = "cron-" + str(uuid.uuid4())
    work = ROOT / ".work" / run_id
    output = ROOT.parent / "evidence/T02" / run_id
    work.mkdir(parents=True)
    output.mkdir(parents=True)
    for phase in ("execute", "restart"):
        with (output / f"{phase}.log").open("w") as log:
            subprocess.run([sys.executable, __file__, "--phase", phase, "--work", str(work)], check=True, stdout=log, stderr=log, timeout=15)
        (output / f"{phase}-callbacks.json").write_bytes((work / f"{phase}-callbacks.json").read_bytes())
    report = {"status": "PASS", "at": now(), "scope": "上游 CronService 真实计时触发、重复抑制、暂停保存、独立进程恢复与取消", "processes": [json.loads((output / f"{phase}-callbacks.json").read_text())[0]["pid"] for phase in ("execute", "restart")], "model_request_sent": False, "business_clock": "NOT_RUN", "multiple_process_ownership": "NOT_RUN", "desktop_lifecycle": "NOT_RUN"}
    assert len(set(report["processes"])) == 2
    (output / "result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps({**report, "evidence": str(output)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
