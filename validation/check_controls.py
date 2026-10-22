import asyncio
import concurrent.futures
import json
import os
import secrets
import subprocess
import sys
import uuid

import httpx
from nanobot.cron.service import CronService
from nanobot.cron.types import CronSchedule

from business import ROOT, encode, now
from controls import ControlStore


async def scheduling(client, call, work):
    namespace = "rules-check"
    call("MAINTAINER", "POST", "/datasets", {"namespace": namespace})
    root = "/spaces/" + namespace
    rules = {"version": "1", "cooldown_seconds": 1800, "quiet_start": 22, "quiet_end": 7, "timezone": "Asia/Shanghai", "important_escalation": False}
    call("BOSS", "POST", root + "/controls/rules", rules)
    event = {"event_id": "business-event", "version": "1", "state": "OPEN", "impact": "NORMAL", "due_at": "2026-10-22T09:00:00+08:00"}
    call("MAINTAINER", "POST", root + "/controls/event", event)
    store = ControlStore(work / "business.sqlite")
    tick = asyncio.Event()
    executions = []

    async def due(job):
        results = store.dispatch_due(namespace)
        executions.append({"at": now(), "job_id": job.id, "results": results})
        tick.set()
        return encode(results)

    async def next_tick(expected):
        tick.clear()
        await asyncio.wait_for(tick.wait(), 5)
        actual = executions[-1]["results"][0]
        assert (actual["reason"] or actual["state"]) == expected, actual

    cron = CronService(work / "cron/jobs.json", on_job=due, max_sleep_ms=100)
    await cron.start()
    try:
        cron.add_job("获准业务时钟", CronSchedule(kind="every", every_ms=200), "按当前规则调度事件", session_key=namespace, origin_channel="websocket", origin_chat_id=namespace)
        await next_tick("DELIVERED")
        await next_tick("DUPLICATE_EVENT")
        event["version"] = "2"
        call("MAINTAINER", "POST", root + "/controls/event", event)
        await next_tick("COOLDOWN")
        call("MAINTAINER", "POST", root + "/controls/clock", {"at": "2026-10-22T22:00:00+08:00"})
        await next_tick("QUIET_HOURS")
        event.update(version="3", impact="IMPORTANT")
        call("MAINTAINER", "POST", root + "/controls/event", event)
        await next_tick("QUIET_HOURS")
        call("BOSS", "POST", root + "/controls/rules", {**rules, "version": "2", "important_escalation": True})
        await next_tick("DELIVERED")
        call("BOSS", "POST", root + "/controls/reminder", {"event_id": "business-event", "state": "SNOOZED", "until": "2026-10-22T22:30:00+08:00"})
        event["version"] = "4"
        call("MAINTAINER", "POST", root + "/controls/event", event)
        await next_tick("BOSS_SNOOZED")
        call("BOSS", "POST", root + "/controls/reminder", {"event_id": "business-event", "state": "CLOSED"})
        await next_tick("BOSS_CLOSED")
        call("MAINTAINER", "POST", root + "/controls/clock", {"at": "2026-10-23T08:00:00+08:00"})
        event.update(version="5", state="RECOVERED", impact="NORMAL")
        call("MAINTAINER", "POST", root + "/controls/event", event)
        call("BOSS", "POST", root + "/controls/reminder", {"event_id": "business-event", "state": "ACKNOWLEDGED"})
        await next_tick("DELIVERED")
        call("MAINTAINER", "PUT", root + "/schedule", {"version": "1", "enabled": False})
        await next_tick("PLAN_PAUSED_OR_CANCELED")
        call("MAINTAINER", "PUT", root + "/schedule", {"version": "2", "enabled": True, "canceled": True})
        await next_tick("PLAN_PAUSED_OR_CANCELED")
        notifications = call("BOSS", "GET", root + "/objects/notification")
        assert len(notifications) == 3
        return executions
    finally:
        cron.stop()


def main():
    run_id = "controls-" + str(uuid.uuid4())
    work = ROOT / ".work" / run_id
    output = ROOT.parent / "evidence/T02" / run_id
    work.mkdir(parents=True)
    output.mkdir(parents=True)
    env = dict(os.environ, BOSS_PROBE_TOKEN=secrets.token_urlsafe(32), MAINTAINER_PROBE_TOKEN=secrets.token_urlsafe(32), TMPDIR=str(ROOT / ".work/tmp"))
    records = []
    with (output / "service.log").open("w") as log, httpx.Client(base_url="http://127.0.0.1:8873", timeout=10, trust_env=False) as client:
        process = subprocess.Popen([sys.executable, str(ROOT / "service.py"), "--database", str(work / "business.sqlite"), "--port", "8873"], env=env, stdout=log, stderr=log)

        def call(role, method, route, payload=None, expected=200):
            headers = {"Authorization": "Bearer " + env[role + "_PROBE_TOKEN"]} if role in {"BOSS", "MAINTAINER"} else {"Authorization": "Bearer coordinator-1"}
            response = client.request(method, route, json=payload, headers=headers)
            value = response.json() if response.headers.get("content-type", "").startswith("application/json") else response.text
            display = {"calendar_id": value["calendar_id"], "private_body_visible": bool(value["private_body"])} if route.endswith("private_calendar") and response.status_code == 200 else value
            records.append({"at": now(), "role": role, "method": method, "route": route, "input": payload, "status": response.status_code, "result": display})
            (output / "requests.json").write_text(json.dumps(records, ensure_ascii=False, indent=2))
            assert response.status_code == expected, records[-1]
            return value

        try:
            with httpx.Client(transport=httpx.HTTPTransport(retries=8), trust_env=False) as ready:
                ready.get("http://127.0.0.1:8873/health", headers={"Authorization": "Bearer " + env["BOSS_PROBE_TOKEN"]}).raise_for_status()
            baseline = call("MAINTAINER", "POST", "/datasets", {"namespace": "controls-check"})
            envelope = {"request_id": run_id, "owner_id": "boss-1", "execution_namespace": "controls-check", "dataset_id": "selection", "dataset_version": "1", "session_id": "control-session"}
            root = "/spaces/controls-check"
            content = {"content_version": "1", "coordinator_id": "coordinator-1", "purpose": "提交当前会议关联的毛利变化解释、措施和证据", "due_at": "2026-10-25T17:00:00+08:00", "timezone": "Asia/Shanghai", "evidence_requirements": ["原因明细", "措施及证据"], "related_meeting_id": "meeting-1", "related_event_ids": ["event-1"], "source_refs": ["finance-note"]}
            auth = call("BOSS", "POST", "/authorizations", {"namespace": "controls-check", "action": "create_assignment", "payload": content})
            task = call("BOSS", "POST", "/operations/create_assignment", {"envelope": envelope, **content, **auth, "idempotency_key": "create-1"})
            payload = {"task_id": task["task_id"], "task_version": "1", "recipient_id": "coordinator-1", "body": content["purpose"], "content_version": "1"}
            auth = call("BOSS", "POST", "/authorizations", {"namespace": "controls-check", "action": "send_assignment", "payload": payload})
            call("BOSS", "POST", "/operations/send_assignment", {"envelope": envelope, **payload, **auth, "idempotency_key": "send-1"})
            feedback = {"task_id": task["task_id"], "task_version": "2", "author_contact_id": "coordinator-1", "kind": "PROGRESS", "content": "正在准备获准模拟明细"}
            progress = call("MAINTAINER", "POST", root + "/controls/feedback", feedback)["task"]
            assert progress["status"] == "IN_PROGRESS" and progress["completion_authorization_id"] is None
            extension = call("MAINTAINER", "POST", root + "/controls/feedback", {**feedback, "task_version": "3", "kind": "EXTENSION_REQUEST", "proposed_due_at": "2026-10-26T17:00:00+08:00"})
            assert extension["task"]["due_at"] == content["due_at"]
            decision = {"task_id": task["task_id"], "task_version": "4", "feedback_id": extension["feedback"]["feedback_id"], "due_at": "2026-10-26T17:00:00+08:00"}
            auth = call("BOSS", "POST", "/authorizations", {"namespace": "controls-check", "action": "extend_assignment", "payload": decision})
            call("MAINTAINER", "POST", root + "/controls/decide", {**decision, **auth}, 403)
            extended = call("BOSS", "POST", root + "/controls/decide", {**decision, **auth})
            assert extended["due_at"] == decision["due_at"] and extended["status"] == "IN_PROGRESS"
            result = call("MAINTAINER", "POST", root + "/controls/feedback", {**feedback, "task_version": "5", "kind": "RESULT_SUBMITTED", "evidence_refs": ["finance-note"], "content": "获准模拟措施及证据已经提交"})
            assert result["task"]["status"] == "RESULT_SUBMITTED" and result["task"]["completion_authorization_id"] is None
            decision = {"task_id": task["task_id"], "task_version": "6", "feedback_id": result["feedback"]["feedback_id"]}
            auth = call("BOSS", "POST", "/authorizations", {"namespace": "controls-check", "action": "complete_assignment", "payload": decision})
            completed = call("BOSS", "POST", root + "/controls/decide", {**decision, **auth})
            assert completed["status"] == "COMPLETED_CONFIRMED" and completed["completion_authorization_id"] == auth["authorization_id"]
            revoked = call("BOSS", "POST", "/authorizations", {"namespace": "controls-check", "action": "create_assignment", "payload": content})
            call("BOSS", "POST", root + "/controls/revoke", revoked)
            call("BOSS", "POST", "/operations/create_assignment", {"envelope": envelope, **content, **revoked, "idempotency_key": "revoked"}, 403)
            call("BOSS", "POST", root + "/controls/private_calendar", {})
            call("MAINTAINER", "POST", root + "/controls/private_calendar", {}, 403)
            call("CONTACT", "GET", "/health", expected=401)
            search = call("BOSS", "POST", root + "/controls/search", {"query": "毛利"})
            assert len(search["results"]) == 1
            call("BOSS", "POST", root + "/controls/withdraw", {"source_id": "finance-note", "version": "1"})
            assert call("BOSS", "POST", root + "/controls/search", {"query": "毛利"})["results"] == []
            assert call("BOSS", "POST", root + "/controls/reference_status", {"task_id": task["task_id"]})["sources"][0]["state"] == "WITHDRAWN"
            call("MAINTAINER", "POST", root + "/controls/reference_status", {"task_id": task["task_id"]}, 403)
            query = {"envelope": envelope, "question": "检查撤销资料后的查询", "metric_ids": ["gross_profit"], "region_id": "region-1", "product_ids": ["product-1"], "period_start": "2026-10-01", "period_end": "2026-10-10", "comparison_start": "2026-09-01", "comparison_end": "2026-09-10", "currency": "CNY", "trade_scope": "EXTERNAL_SALES", "definition_version": "1"}
            call("BOSS", "POST", "/operations/query_metrics", query, 410)
            call("MAINTAINER", "POST", root + "/controls/clock", {"at": "invalid-date"}, 400)
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                changes = list(pool.map(lambda text: client.put(root + "/memory", headers={"Authorization": "Bearer " + env["BOSS_PROBE_TOKEN"]}, json={"version": "1", "text": text, "confirmation_state": "CONFIRMED"}), ["优先查看本人决定", "优先查看现金事项"]))
            assert sorted(response.status_code for response in changes) == [200, 409]
            executions = asyncio.run(scheduling(client, call, work))
            (output / "scheduler.json").write_text(json.dumps(executions, ensure_ascii=False, indent=2))
            with ControlStore(work / "business.sqlite").connect() as db:
                original = json.loads(db.execute("SELECT body FROM objects WHERE namespace='controls-check' AND kind='initial'").fetchone()[0])
                assert original["event"]["status"] == "OPEN"
            report = {"status": "PASS", "at": now(), "requests": len(records), "scope": "反馈、老板延期与完成、授权撤销、私人正文权限、联系人拒绝、资料摄取检索撤销、并发版本及上游实际调度采用业务时钟和提醒规则", "baseline": baseline, "concurrent_statuses": sorted(response.status_code for response in changes), "completed_task": completed}
            (output / "result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
            print(json.dumps({**report, "evidence": str(output)}, ensure_ascii=False))
        finally:
            process.terminate()
            process.wait(timeout=10)


if __name__ == "__main__":
    main()
