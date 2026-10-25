import asyncio
import hashlib
import json
import subprocess
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import httpx
import websockets

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "validation/.work/application"
HOST = "http://127.0.0.1:8872"
INPUTS = ("validation/application.py", "validation/boss_agent_read_tools.py", "validation/boss_research.py",
          "validation/boss_source_policy.py", "validation/boss_prompt_config.py", "validation/business.py", "validation/uv.lock")


async def check():
    hashes = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in INPUTS}
    access = json.loads((WORK / "access.json").read_text())
    before_events = json.loads((WORK / "diagnostics/events.json").read_text())
    before_calls = sum(row.get("name") == "bossWorkspaceRead" for row in before_events)
    before_transport = len(json.loads((WORK / "diagnostics/http-requests.json").read_text()))
    counts = Counter()
    async with httpx.AsyncClient(base_url=HOST, trust_env=False, timeout=15) as http:
        bootstrap = await http.get("/webui/bootstrap", headers={"X-Nanobot-Auth": access["BOSS"]})
        bootstrap.raise_for_status()
        boot = bootstrap.json()
        headers = {"Authorization": "Bearer " + boot["api_token"]}
        research = await http.get("/api/boss/ui/workspace/research", headers=headers)
        research.raise_for_status()
        report = research.json()["report"]
        original = await http.get("/api/boss/ui/evidence", headers=headers, params={"source": "finance-note"})
        original.raise_for_status()
        source = original.json()
        assert source["source_type"] == "SIMULATED"
        dashboard = await http.get("/api/boss/ui/dashboard", headers=headers)
        dashboard.raise_for_status()

        async def business_state():
            result = {}
            for kind in ("task", "outbox"):
                response = await http.get("http://127.0.0.1:8871/spaces/ui-check/objects/" + kind,
                                          headers={"Authorization": "Bearer " + access["BOSS"]})
                response.raise_for_status()
                result[kind] = hashlib.sha256(response.content).hexdigest()
            return result

        before_state = await business_state()
        address = "ws://127.0.0.1:8872" + boot["ws_path"] + "?token=" + quote(boot["token"], safe="")
        async with websockets.connect(address, proxy=None, open_timeout=15, max_size=1_000_000) as ws:
            ready = json.loads(await asyncio.wait_for(ws.recv(), 15))
            assert ready["event"] == "ready"
            request_id = str(uuid.uuid4())
            await ws.send(json.dumps({"type": "webui_request", "request_id": request_id,
                "action": "boss.research.prepare", "payload": {
                    "client_request_id": "w3-research-" + request_id,
                    "expected_version": report["version"] if report else "0",
                    "question": source["content"].split("；", 1)[0],
                    "period": "", "country": "", "business_relation": "",
                    "cutoff_date": dashboard.json()["business_clock"][:10],
                }}, ensure_ascii=False))
            async with asyncio.timeout(15):
                while True:
                    receipt = json.loads(await ws.recv())
                    if receipt.get("request_id") == request_id:
                        assert receipt["ok"] is True
                        break
            turn_id = str(uuid.uuid4())
            await ws.send(json.dumps({"type": "message", "chat_id": ready["chat_id"],
                "turn_id": turn_id, "webui": True,
                "content": "调用bossWorkspaceRead读取本人当前已准备的研究来源。依据有效来源说明一项原文事实，标明source_id和version；来源缺少或不再有效时明确说明。只读，不创建交办、不发送消息。"}, ensure_ascii=False))
            async with asyncio.timeout(150):
                while True:
                    frame = json.loads(await ws.recv())
                    counts[frame["event"]] += 1
                    if frame["event"].startswith("reasoning"):
                        raise RuntimeError("普通业务通道出现内部推理事件")
                    if frame["event"] == "turn_end" and frame.get("turn_id") == turn_id:
                        assert frame.get("outcome", "completed") == "completed"
                        assert not frame.get("failure_kind")
                        break
        assert await business_state() == before_state
        current = await http.get("/api/boss/ui/workspace/research", headers=headers)
        current.raise_for_status()
        current_view = current.json()
    observed = json.loads((WORK / "diagnostics/events.json").read_text())
    calls = [row for row in observed if row.get("name") == "bossWorkspaceRead"]
    assert len(calls) > before_calls
    assert calls[-1]["status"] == current_view["current_reference_state"]
    assert all(hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == value for name, value in hashes.items())
    transport = json.loads((WORK / "diagnostics/http-requests.json").read_text())[before_transport:]
    return {
        "status": "PASS_PUBLIC_RESEARCH_TOOL_ONLY", "at": datetime.now(timezone.utc).isoformat(),
        "commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "source_sha256": hashes, "source_type": "SIMULATED",
        "research_preparation_written": True, "research_version": current_view["report"]["version"],
        "actual_read_tool_calls": len(calls) - before_calls,
        "current_reference_state": current_view["current_reference_state"],
        "current_references": [{"source_id": item["source_id"], "version": item["version"]}
                               for item in current_view["report"]["matched_sources"]],
        "model_requests": sum(row["type"] == "request" for row in transport),
        "response_ids": sorted({row["response_id"] for row in transport if row.get("response_id")}),
        "event_counts": dict(counts), "task_and_outbox_unchanged": True,
        "private_body_recorded": False, "cost_total": None,
        "event_schema_validation": "NOT_RUN_SEE_REV01", "full_A15_A16_accepted": False,
    }


if __name__ == "__main__":
    result = asyncio.run(check())
    output = ROOT / "evidence/T09/w3-20261023/public-research-runtime.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False))
