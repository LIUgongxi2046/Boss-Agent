import hashlib
import json
import os
import secrets
import sqlite3
import subprocess
import sys
import uuid
from decimal import Decimal
from pathlib import Path

import httpx

from business import ROOT, checksum, initial_materials, now


def main():
    run_id = str(uuid.uuid4())
    work = ROOT / ".work" / run_id
    work.mkdir(parents=True)
    output = ROOT.parent / "evidence/T02" / run_id
    output.mkdir(parents=True)
    env = dict(os.environ, BOSS_PROBE_TOKEN=secrets.token_urlsafe(32), MAINTAINER_PROBE_TOKEN=secrets.token_urlsafe(32), TMPDIR=str(ROOT / ".work/tmp"))
    db_path = work / "business.sqlite"
    log = (output / "service.log").open("w")
    command = [sys.executable, str(ROOT / "service.py"), "--database", str(db_path), "--port", "8875"]
    records = []
    process = subprocess.Popen(command, env=env, stdout=log, stderr=log)
    base = "http://127.0.0.1:8875"
    client = httpx.Client(base_url=base, timeout=10, trust_env=False)

    def call(role, method, route, payload=None, expected=200):
        headers = {"Authorization": f"Bearer {env[role + '_PROBE_TOKEN']}"} if role else {}
        response = client.request(method, route, headers=headers, json=payload)
        records.append({"at": now(), "role": role, "method": method, "route": route, "input": payload, "status": response.status_code, "response": response.json() if response.headers.get("content-type", "").startswith("application/json") else response.text})
        (output / "requests.json").write_text(json.dumps(records, ensure_ascii=False, indent=2))
        assert response.status_code == expected, records[-1]
        return records[-1]["response"]

    def ready():
        # 由标准 HTTP 客户端执行连接重试，仅等待本地进程监听。
        transport = httpx.HTTPTransport(retries=8)
        with httpx.Client(transport=transport, timeout=3, trust_env=False) as probe:
            response = probe.get(base + "/health", headers={"Authorization": "Bearer " + env["BOSS_PROBE_TOKEN"]})
            response.raise_for_status()

    try:
        ready()
        first = call("MAINTAINER", "POST", "/datasets", {"namespace": "local-a"})
        second = call("MAINTAINER", "POST", "/datasets", {"namespace": "local-b"})
        assert first["snapshot_sha256"] == second["snapshot_sha256"] == checksum(initial_materials())
        envelope = {"request_id": "query-1", "owner_id": "boss-1", "execution_namespace": "local-a", "dataset_id": "selection", "dataset_version": "1", "session_id": "session-1"}
        query = {"envelope": envelope, "question": "查询当前与基准期间经营指标", "metric_ids": ["sales_quantity", "revenue", "cost", "gross_profit", "gross_margin", "gross_profit_per_tonne"], "region_id": "region-1", "product_ids": ["product-1", "product-2"], "period_start": "2026-10-01", "period_end": "2026-10-10", "comparison_start": "2026-09-01", "comparison_end": "2026-09-10", "currency": "CNY", "trade_scope": "EXTERNAL_SALES", "definition_version": "1"}
        result = call("BOSS", "POST", "/operations/query_metrics", query)
        # 独立路径读取已保存明细，按需求预期检查业务工具结果。
        with sqlite3.connect(db_path) as db:
            snapshot = json.loads(db.execute("SELECT body FROM objects WHERE namespace='local-a' AND kind='initial'").fetchone()[0])
        totals = {period: {field: sum(Decimal(row[field]) for row in snapshot["details"] if row["period"] == period) for field in ("quantity_tonnes", "revenue_cny", "cost_cny")} for period in ("BASE", "CURRENT")}
        assert totals["BASE"] == {"quantity_tonnes": 10000, "revenue_cny": 40000000, "cost_cny": 36000000}
        assert totals["CURRENT"] == {"quantity_tonnes": 12000, "revenue_cny": 48000000, "cost_cny": 44160000}
        actual = {(v["period_scope"], v["metric_id"]): Decimal(v["value"]) for v in result["values"]}
        assert actual["CURRENT", "gross_profit"] == 3840000
        assert actual["BASE", "gross_margin"] == 10 and actual["CURRENT", "gross_margin"] == 8
        assert actual["BASE", "gross_profit_per_tonne"] == 400 and actual["CURRENT", "gross_profit_per_tonne"] == 320
        change = {m: (actual["CURRENT", m] / actual["BASE", m] - 1) * 100 for m in ("sales_quantity", "revenue", "gross_profit", "gross_profit_per_tonne")}
        assert list(change.values()) == [20, 20, -4, -20]
        evidence = call("BOSS", "POST", "/operations/read_evidence", {"envelope": envelope, "query_id": result["query_id"], "source_ids": ["finance-note"], "detail_refs": result["detail_refs"]})
        assert len(evidence["original_records"]) == 9
        product = call("BOSS", "POST", "/operations/query_metrics", {**query, "product_ids": ["product-1"]})
        assert len(product["detail_refs"]) == 4
        call("BOSS", "POST", "/operations/query_metrics", {**query, "region_id": "unavailable"}, 400)
        content = {"content_version": "1", "coordinator_id": "coordinator-1", "purpose": "提交当前会议关联的毛利变化解释、措施和证据", "due_at": "2026-10-25T17:00:00+08:00", "timezone": "Asia/Shanghai", "evidence_requirements": ["原因明细", "措施及证据"], "related_meeting_id": "meeting-1", "related_event_ids": ["event-1"], "source_refs": ["finance-note"]}
        auth = call("BOSS", "POST", "/authorizations", {"namespace": "local-a", "action": "create_assignment", "payload": content})
        request = {"envelope": envelope, **content, **auth, "idempotency_key": "create-1"}
        task = call("BOSS", "POST", "/operations/create_assignment", request)
        assert call("BOSS", "POST", "/operations/create_assignment", request) == task
        call("BOSS", "POST", "/operations/create_assignment", {**request, "purpose": "未经授权的内容"}, 403)
        changed_content = {**content, "purpose": "另一个获准模拟任务"}
        changed_auth = call("BOSS", "POST", "/authorizations", {"namespace": "local-a", "action": "create_assignment", "payload": changed_content})
        call("BOSS", "POST", "/operations/create_assignment", {**request, **changed_content, **changed_auth}, 409)
        call("BOSS", "POST", "/operations/query_metrics", {**query, "envelope": {**envelope, "owner_id": "coordinator-1"}}, 403)
        send_content = {"task_id": task["task_id"], "task_version": "1", "recipient_id": "coordinator-1", "body": content["purpose"], "content_version": "1"}
        send_auth = call("BOSS", "POST", "/authorizations", {"namespace": "local-a", "action": "send_assignment", "payload": send_content})
        send = {"envelope": envelope, **send_content, **send_auth, "idempotency_key": "send-1"}
        sent = call("BOSS", "POST", "/operations/send_assignment", send)
        assert call("BOSS", "POST", "/operations/send_assignment", send) == sent
        read = {"envelope": {**envelope, "session_id": "session-2"}, "task_id": task["task_id"]}
        saved = call("BOSS", "POST", "/operations/read_assignment", read)
        assert saved["status"] == "WAITING_FEEDBACK" and saved["completion_authorization_id"] is None
        call("MAINTAINER", "POST", "/operations/create_assignment", request, 403)
        call("MAINTAINER", "POST", "/authorizations", {"namespace": "local-a", "action": "send_assignment", "payload": send_content}, 403)
        call("MAINTAINER", "GET", "/spaces/local-a/context", expected=403)
        call("MAINTAINER", "PUT", "/spaces/local-a/memory", {"version": "1", "text": "无权修改"}, 403)
        call(None, "POST", "/operations/read_assignment", read, 401)
        call(None, "GET", "/spaces/local-a/context", expected=401)
        call("BOSS", "PUT", "/spaces/local-a/memory", {"version": "1", "text": "简报优先显示待决定事项", "confirmation_state": "CONFIRMED"})
        call("MAINTAINER", "PUT", "/spaces/local-a/configuration", {"version": "1", "max_tool_rounds": 8})
        current = call("BOSS", "GET", "/spaces/local-a/context")
        assert current["memory"]["version"] == "2" and current["configuration"]["max_tool_rounds"] == 8
        call("MAINTAINER", "PUT", "/spaces/local-a/configuration", {"version": "1", "max_tool_rounds": 4}, 409)
        assert call("MAINTAINER", "POST", "/spaces/local-a/events", {"event_id": "event-1"})["state"] == "DELIVERED"
        assert call("MAINTAINER", "POST", "/spaces/local-a/events", {"event_id": "event-1"})["state"] == "SUPPRESSED"
        call("MAINTAINER", "PUT", "/spaces/local-a/schedule", {"version": "1", "enabled": False})
        assert call("MAINTAINER", "POST", "/spaces/local-a/events", {"event_id": "event-2"})["state"] == "SUPPRESSED"
        call("BOSS", "PUT", "/spaces/local-a/memory", {"version": "2", "confirmation_state": "DELETED"})
        process.terminate()
        assert process.wait(timeout=10) == 0
        process = subprocess.Popen(command, env=env, stdout=log, stderr=log)
        ready()
        assert call("BOSS", "POST", "/operations/read_assignment", read) == saved
        assert len(call("BOSS", "GET", "/spaces/local-a/objects/outbox")) == 1
        assert len(call("BOSS", "GET", "/spaces/local-a/objects/notification")) == 1
        restored = call("BOSS", "GET", "/spaces/local-a/context")
        assert restored["memory"] is None and restored["configuration"]["max_tool_rounds"] == 8
        assert call("MAINTAINER", "POST", "/spaces/local-a/events", {"event_id": "event-3"})["state"] == "SUPPRESSED"
        reset = call("MAINTAINER", "POST", "/spaces/local-a/reset", {"namespace": "local-c"})
        assert reset["snapshot_sha256"] == first["snapshot_sha256"]
        call("BOSS", "POST", "/operations/create_assignment", request, 409)
        assert call("BOSS", "GET", "/spaces/local-c/objects/task") == []
        report = {"status": "PASS", "scope": "真实 HTTP 与 SQLite 模拟业务服务检查；不代表模型、上游页面或桌面验收", "run_id": run_id, "requests": len(records), "snapshot_sha256": first["snapshot_sha256"], "numeric_changes": {k: str(v) for k, v in change.items()}, "checks": ["相同初始快照", "明细复算", "产品维度查询", "原始依据", "授权创建与发送", "独立重读", "重复写入", "内容越权拒绝", "维护越权拒绝", "未认证拒绝", "记忆版本与删除", "配置版本与冲突", "事件重复抑制", "暂停", "实际进程重启", "重置隔离"], "finished_at": now(), "code_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT / "business.py", ROOT / "service.py", Path(__file__))}}
        (output / "result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
        print(json.dumps(report, ensure_ascii=False, indent=2))
    finally:
        process.terminate()
        process.wait(timeout=10)
        client.close()
        log.close()


if __name__ == "__main__":
    main()
