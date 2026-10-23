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
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
HOST = "http://127.0.0.1:8872"
EVENTS = {"webui_response", "message", "delta", "stream_end", "turn_end", "recovery_state", "retry_status", "context_compaction"}


async def check():
    schema_path = ROOT / "specs/runtime-events.schema.json"
    schema = json.loads(schema_path.read_text())
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    access = json.loads((ROOT / "validation/.work/application/access.json").read_text())
    counts = Counter()
    observations = []
    async with httpx.AsyncClient(base_url=HOST, trust_env=False, timeout=15) as http:
        bootstrap = await http.get("/webui/bootstrap", headers={"X-Nanobot-Auth": access["BOSS"]})
        bootstrap.raise_for_status()
        boot = bootstrap.json()
        headers = {"Authorization": "Bearer " + boot["api_token"]}
        identity = await http.get("/api/boss/identity", headers=headers)
        identity.raise_for_status()
        assert identity.json()["role"] == "BOSS"
        dashboard = await http.get("/api/boss/ui/dashboard", headers=headers)
        dashboard.raise_for_status()
        assert dashboard.json()["source_type"] == "SIMULATED"

        async def business_state():
            state = {}
            for kind in ("task", "outbox"):
                response = await http.get("http://127.0.0.1:8871/spaces/ui-check/objects/" + kind,
                                          headers={"Authorization": "Bearer " + access["BOSS"]})
                response.raise_for_status()
                state[kind] = hashlib.sha256(response.content).hexdigest()
            return state

        before = await business_state()
        address = "ws://127.0.0.1:8872" + boot["ws_path"] + "?token=" + quote(boot["token"], safe="")
        async with websockets.connect(address, proxy=None, open_timeout=15, max_size=1_000_000) as ws:
            ready = json.loads(await asyncio.wait_for(ws.recv(), timeout=15))
            assert ready["event"] == "ready" and ready["chat_id"]
            chat_id = ready["chat_id"]
            turn_id = str(uuid.uuid4())
            await ws.send(json.dumps({
                "type": "message", "chat_id": chat_id, "turn_id": turn_id, "webui": True,
                "content": "只读查询获准SIMULATED资料。调用query_metrics比较region-1的product-1、product-2，2026-10-01至2026-10-10与2026-09-01至2026-09-10，CNY、EXTERNAL_SALES、definition_version=1，查询收入和毛利率并读取依据。不得创建交办或发送消息，缺少原因明确说明未知。",
            }, ensure_ascii=False))
            async with asyncio.timeout(150):
                while True:
                    frame = json.loads(await ws.recv())
                    name = frame["event"]
                    counts[name] += 1
                    if name.startswith("reasoning"):
                        raise RuntimeError("普通业务通道出现内部推理事件")
                    if name in EVENTS:
                        errors = list(validator.iter_errors(frame))
                        if errors:
                            output = ROOT / "evidence/T09/w3-20261023/runtime-event-schema-check.json"
                            output.parent.mkdir(parents=True, exist_ok=True)
                            output.write_text(json.dumps({
                                "status": "SCHEMA_MISMATCH", "event": name,
                                "schema_sha256": hashlib.sha256(schema_path.read_bytes()).hexdigest(),
                                "frame_fields": sorted(frame),
                                "frame_field_types": {key: type(value).__name__ for key, value in frame.items()},
                                "frame_sha256": hashlib.sha256(json.dumps(frame, sort_keys=True).encode()).hexdigest(),
                                "private_body_recorded": False, "business_write_requested": False,
                                "at": datetime.now(timezone.utc).isoformat(),
                            }, ensure_ascii=False, indent=2) + "\n")
                            raise RuntimeError("Runtime事件Schema不匹配：" + name + "；路径=" + str(list(errors[0].absolute_schema_path)))
                        observations.append({
                            "event": name, "fields": sorted(frame),
                            "sha256": hashlib.sha256(json.dumps(frame, sort_keys=True).encode()).hexdigest(),
                            "chat_matches": frame.get("chat_id", chat_id) == chat_id,
                            "turn_matches": frame.get("turn_id", turn_id) == turn_id,
                            "tool_event_count": len(frame.get("tool_events", [])),
                        })
                    if name == "turn_end" and frame.get("turn_id") == turn_id:
                        assert frame.get("outcome", "completed") == "completed"
                        assert not frame.get("failure_kind")
                        break
            assert counts["turn_end"] == 1 and counts["stream_end"] > 0
        assert await business_state() == before
    return {
        "status": "PASS_OBSERVED_EVENTS_ONLY", "at": datetime.now(timezone.utc).isoformat(),
        "commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "schema_sha256": hashlib.sha256(schema_path.read_bytes()).hexdigest(),
        "event_counts": dict(counts), "observations": observations,
        "business_state_unchanged": True, "private_body_recorded": False,
        "unobserved_event_types": sorted(EVENTS - set(counts)),
        "full_A06_A07_A16_accepted": False,
    }


if __name__ == "__main__":
    result = asyncio.run(check())
    output = ROOT / "evidence/T09/w3-20261023/runtime-events.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({key: value for key, value in result.items() if key != "observations"}, ensure_ascii=False))
