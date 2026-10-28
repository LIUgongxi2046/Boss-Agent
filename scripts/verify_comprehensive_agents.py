import argparse
import asyncio
import json
import sqlite3
from pathlib import Path
from time import monotonic
from uuid import uuid4

import httpx
from websockets.asyncio.client import connect

ROOT = Path(__file__).resolve().parents[1]


async def receive(socket, predicate):
    async with asyncio.timeout(330):
        async for value in socket:
            event = json.loads(value)
            if predicate(event):
                return event
    raise RuntimeError("Agent 连接已经结束")


async def rpc(socket, action, payload):
    identifier = str(uuid4())
    await socket.send(json.dumps({"type": "webui_request", "request_id": identifier, "action": action, "payload": payload}))
    result = await receive(socket, lambda event: event.get("request_id") == identifier)
    if not result.get("ok"):
        raise RuntimeError(action + "：" + json.dumps(result.get("error"), ensure_ascii=False))
    return result["result"]


def saved_run(directory, chat_id):
    with sqlite3.connect(directory / "business.sqlite") as db:
        rows = db.execute("SELECT body FROM objects WHERE kind='runtime_run' AND json_extract(body,'$.chat_id')=? ORDER BY rowid DESC", (chat_id,)).fetchall()
    if not rows:
        raise ValueError("Agent 没有保存运行记录")
    return json.loads(rows[0][0])


async def verify(args):
    accounts = json.loads((args.directory / "accounts/credentials.json").read_text())
    account = next(row for row in accounts if row["role"] == "BOSS")
    async with httpx.AsyncClient(base_url=args.origin, timeout=30) as http:
        bootstrap = await http.get("/webui/bootstrap", headers={"X-Boss-Username": account["username"], "X-Boss-Password": account["password"], "X-Boss-Role": "BOSS"})
        bootstrap.raise_for_status()
        identity = bootstrap.json()
        headers = {"Authorization": "Bearer " + identity["api_token"]}

        async def read(path):
            response = await http.get(path, headers=headers)
            response.raise_for_status()
            return response.json()

        tasks = (await read("/api/boss/ui/tasks"))["tasks"]
        cases = [("ordinary", "请读取今日工作、会议和任务，说明需要本人关注的三项事项，引用原始资料。", None)]
        cases += [("sector-" + page, "请用 bossSectorRead 读取 " + page + "，说明当前指标、单位、主要变化、记录作者及待核查事项。仅作查询分析。", None)
                  for page in [*("F" + str(index) for index in range(14, 24)), "V19-EGG", "V19-MILK", "V19-BEEF"]]
        cases += [("morning", "请读取今天需要本人处理的事项，说明当前业务日期、责任人和期限，保留依据。", "morning"),
                  ("business-overview", "请核查当前已应用经营范围，说明三项主要经营关注、指标和依据。", "business")]
        cases += [("business-" + use, "请分析当前绑定的畜禽用途，说明本用途的经营数值、单位与来源，核查其他用途的数据是否与本用途混用。", "business-" + use) for use in ("EGG", "MILK", "BEEF")]
        for state in ("OPEN", "WAITING_FEEDBACK", "IN_PROGRESS", "RESULT_SUBMITTED"):
            task = next(row for row in tasks if row["status"] == state)
            cases.append(("task-" + state, "请读取当前绑定任务，说明目的、责任人、业务期限、当前反馈及需要本人决定的内容。", task))
        cases += [("public-baseline", "请使用 bossEvidenceRead 读取 public-business-baseline，比较2024和2025的营业收入、成本和饲料产品毛利率，使用原始期间并注明它们是历史公开基准。", None),
                  ("meeting-library", "请读取当前会议资料目录，说明全部会议安排、参会人和原始资料，不要遗漏后续会议。", None),
                  ("research", "请读取当前研究原文，说明研究问题、采用资料、原始期间及尚待核查内容。", None),
                  ("people", "请读取会面资料与当前任务，核查方明澈的职责、会议准备和待反馈事项。", None)]
        if args.case:
            if set(args.case) - {row[0] for row in cases}:
                raise ValueError("指定场景没有对应的实际验证入口")
            cases = [row for row in cases if row[0] in args.case]
        results = []
        args.output.parent.mkdir(parents=True, exist_ok=True)
        for name, question, binding in cases:
            started = monotonic()
            bootstrap = await http.get("/webui/bootstrap", headers={"X-Boss-Username": account["username"], "X-Boss-Password": account["password"], "X-Boss-Role": "BOSS"})
            bootstrap.raise_for_status()
            identity = bootstrap.json()
            # 浏览器 WebSocket 不发送协议级 ping，验证连接采用相同传输行为。
            async with connect(identity["ws_url"] + "?token=" + identity["token"], max_size=16 * 1024 * 1024, ping_interval=None) as socket:
                await receive(socket, lambda event: event.get("event") == "ready")
                await socket.send(json.dumps({"type": "new_chat"}))
                attached = await receive(socket, lambda event: event.get("event") == "attached")
                chat_id = attached["chat_id"]
                if binding == "morning":
                    await rpc(socket, "boss.morning.bind", {"client_request_id": str(uuid4()), "chat_id": chat_id, "date": "2026-10-28", "timezone": "Asia/Shanghai"})
                elif isinstance(binding, str) and (binding == "business" or binding.startswith("business-")):
                    scope = {"legal_entity_id": "entity-1", "region_id": None, "period_start": "2026-10-01", "period_end": "2026-10-31", "timezone": "Asia/Shanghai", "attention": "ALL"}
                    overview = await rpc(socket, "boss.business_overview.read", scope)
                    topic = {"page_id": "F19", "use": binding.removeprefix("business-")} if binding.startswith("business-") else None
                    preparation = await rpc(socket, "boss.conversation.business.prepare", {"client_request_id": str(uuid4()), "applied_scope": scope, "snapshot_sha256": overview["snapshot_sha256"], "topic_reference": topic})
                    await rpc(socket, "boss.conversation.business.bind", {"client_request_id": preparation["client_request_id"], "preparation_id": preparation["preparation_id"], "preparation_sha256": preparation["preparation_sha256"], "chat_id": chat_id})
                    await rpc(socket, "boss.conversation.business.read", {"chat_id": chat_id, "adopt_selection": True})
                elif isinstance(binding, dict):
                    preparation = await rpc(socket, "boss.conversation.task.prepare", {"client_request_id": str(uuid4()), "task_id": binding["task_id"], "task_version": binding["version"]})
                    await rpc(socket, "boss.conversation.task.bind", {"client_request_id": preparation["client_request_id"], "preparation_id": preparation["preparation_id"], "preparation_sha256": preparation["preparation_sha256"], "chat_id": chat_id})
                    await rpc(socket, "boss.conversation.task.read", {"chat_id": chat_id})
                turn_id = str(uuid4())
                await socket.send(json.dumps({"type": "message", "chat_id": chat_id, "turn_id": turn_id, "content": question + "\n回答控制在300字以内；使用丰泽农牧集团名称。", "webui": True}, ensure_ascii=False))
                terminal = await receive(socket, lambda event: event.get("event") == "turn_end" and event.get("turn_id") == turn_id)
                row = saved_run(args.directory, chat_id)
                assert row["status"] == "SUCCEEDED", (name, row["status"], row.get("stop_reason"))
                assert row.get("external_model_invoked") is True, (name, "没有实际模型请求")
                assert row["model_requests"] and all(request["http_status"] == 200 for request in row["model_requests"])
                assert row["model_requests"][-1]["finish_reasons"] == ["stop"]
                assert len(row["model_requests"]) <= row["runtime"]["max_tool_rounds"]
                assert not row.get("tool_errors"), (name, row.get("tool_errors"))
                assert row.get("tool_results"), (name, "没有实际工具调用")
                result = {"case": name, "chat_id": chat_id, "run_id": row["run_id"], "status": row["status"],
                          "external_model_invoked": row["external_model_invoked"], "model": row["runtime"]["model_id"],
                          "model_requests": len(row["model_requests"]), "tools": [item["tool_id"] for item in row["tool_results"]],
                          "tool_errors": row.get("tool_errors", []), "elapsed_seconds": round(monotonic() - started, 2), "terminal": terminal.get("outcome")}
                results.append(result)
                args.output.write_text(json.dumps({"source_type": "SIMULATED", "model_mode": "LIVE", "results": results}, ensure_ascii=False, indent=2))
                print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="通过实际认证、原生会话和真实模型验证仿真业务问题")
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--origin", default="http://127.0.0.1:9082")
    parser.add_argument("--output", type=Path, default=ROOT / ".work/simulation-20261028/live-agents.json")
    parser.add_argument("--case", action="append")
    asyncio.run(verify(parser.parse_args()))
