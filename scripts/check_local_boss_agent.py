#!/usr/bin/env python3
"""Local read-only Boss-Agent smoke: real DeepSeek through nanobot WebUI.

Run only when the developer's Mac is running scripts/run_boss_local.sh.
Requires local BOSS credentials, never prints tokens or model response bodies.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import httpx
import websockets

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "validation" / ".work" / "application"
REPORT = ROOT / "validation" / ".work" / "local-agent-smoke.json"
HOST = "http://127.0.0.1:8872"


def local_socket_uri(bootstrap):
    token = bootstrap.get("token")
    path = bootstrap.get("ws_path")
    if not isinstance(token, str) or not token:
        raise ValueError("WebSocket token missing")
    if not isinstance(path, str) or not path.startswith("/") or "?" in path or "#" in path:
        raise ValueError("WebSocket path invalid")
    return "ws://127.0.0.1:8872" + path + "?token=" + quote(token, safe="")


async def smoke():
    access = json.loads((WORK / "access.json").read_text(encoding="utf-8"))
    secret = access["BOSS"]
    async with httpx.AsyncClient(base_url=HOST, timeout=15) as http:
        boot = await http.get("/webui/bootstrap", headers={"X-Nanobot-Auth": secret})
        boot.raise_for_status()
        data = boot.json()
        api_token = data["api_token"]
        headers = {"Authorization": "Bearer " + api_token}
        identity = await http.get("/api/boss/identity", headers=headers)
        identity.raise_for_status()
        if identity.json().get("role") != "BOSS":
            raise PermissionError("BOSS identity required")
        dash = await http.get("/api/boss/ui/dashboard", headers=headers)
        dash.raise_for_status()
        scope = dash.json()
        if scope.get("source_type") != "SIMULATED":
            raise ValueError("Only simulated data allowed")
        metrics = await http.get(
            "/api/boss/ui/metrics", headers=headers,
            params={"products": "product-1,product-2"},
        )
        metrics.raise_for_status()
        values = metrics.json().get("result", {})
        if len(values.get("values", [])) != 12 or not values.get("sources"):
            raise ValueError("Metric tool and evidence unavailable")

    event_counts = {}
    completed = False
    failed = False
    tool_events = 0
    async with websockets.connect(
        local_socket_uri(data),
        open_timeout=15, ping_interval=20, max_size=1_000_000,
    ) as ws:
        ready = json.loads(await asyncio.wait_for(ws.recv(), timeout=15))
        if ready.get("event") != "ready" or not ready.get("chat_id"):
            raise ValueError("WebSocket did not provide a chat ID")
        chat_id = ready["chat_id"]
        turn_id = str(uuid.uuid4())
        prompt = (
            "只读查询，不得创建交办或发送任何消息。请在 SIMULATED 数据中对比 "
            "region-1 的 product-1、product-2 CURRENT 与 BASE 的收入、"
            "毛利率，读取来源，缺少原因依据时请说明未知。"
        )
        await ws.send(json.dumps({
            "type": "message", "chat_id": chat_id, "turn_id": turn_id,
            "content": prompt, "webui": True,
        }, ensure_ascii=False))
        deadline = asyncio.get_running_loop().time() + 150
        while asyncio.get_running_loop().time() < deadline:
            frame = json.loads(await asyncio.wait_for(ws.recv(), timeout=35))
            name = frame.get("event", "unknown")
            if not isinstance(name, str):
                name = "unknown"
            event_counts[name] = event_counts.get(name, 0) + 1
            if "tool" in name.lower() or "activity" in name.lower():
                tool_events += 1
            if frame.get("turn_id") not in (None, turn_id):
                continue
            if name == "turn_end":
                failed = bool(frame.get("error")) or frame.get("stop_reason") in (
                    "error", "cancelled", "max_iterations",
                )
                completed = not failed
                break
            if name == "error":
                failed = True
                break
    if not completed or failed:
        raise RuntimeError("Actual model turn did not finish")
    return {
        "status": "PASS_LOCAL_READ_AND_MODEL_SESSION",
        "at": datetime.now(timezone.utc).isoformat(),
        "provider": "deepseek",
        "requested_model": "deepseek-flash",
        "protocol": "authenticated_nanobot_websocket",
        "data_source": "SIMULATED",
        "dataset_version": scope.get("dataset_version"),
        "metric_rows": len(values["values"]),
        "model_turn_completed": completed,
        "tool_event_count": tool_events,
        "event_type_counts": event_counts,
        "business_write_verified": False,
        "visual_acceptance": "NOT_RUN",
        "product_acceptance": "NOT_RUN",
    }


def main():
    try:
        report = asyncio.run(smoke())
    except Exception as error:
        print("本地 Agent 联调未通过：" + type(error).__name__ +
              "；不输出任何私密请求或响应。", file=sys.stderr)
        raise SystemExit(2) from None
    REPORT.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(REPORT, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
