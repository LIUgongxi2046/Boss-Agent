import json
import os
import uuid
from pathlib import Path

import httpx
from playwright.sync_api import expect, sync_playwright

from business import ROOT, now


def main():
    os.environ["TMPDIR"] = str(ROOT / ".work/tmp")
    output = ROOT.parent / "evidence/T02" / ("ui-business-" + str(uuid.uuid4()))
    output.mkdir(parents=True)
    access = json.loads((ROOT / ".work/application/access.json").read_text())
    requests = []
    with httpx.Client(base_url="http://127.0.0.1:8871", headers={"Authorization": "Bearer " + access["BOSS"]}, trust_env=False, timeout=10) as service:
        def call(route, payload):
            response = service.post(route, json=payload)
            requests.append({"at": now(), "route": route, "input": payload, "status": response.status_code, "result": response.json()})
            (output / "business-requests.json").write_text(json.dumps(requests, ensure_ascii=False, indent=2))
            response.raise_for_status()
            return response.json()

        with sync_playwright() as driver:
            browser = driver.chromium.launch(channel="chrome", headless=True)
            page = browser.new_page(locale="en-US")
            frames = []

            def websocket(socket):
                def received(raw):
                    frame = json.loads(raw)
                    if frame.get("event") not in {"reasoning_delta", "reasoning_end"}:
                        frames.append(frame)
                        (output / "ui-events.json").write_text(json.dumps(frames, ensure_ascii=False, indent=2))
                socket.on("framereceived", received)

            page.on("websocket", websocket)
            page.goto("http://127.0.0.1:8872", wait_until="networkidle")
            page.get_by_role("textbox", name="WebUI password", exact=True).fill(access["BOSS"])
            page.get_by_role("button", name="Connect", exact=True).click()
            composer = page.get_by_role("region", name="Conversation workbench", exact=True).get_by_role("textbox")
            composer.wait_for()

            def turn(text):
                before = len(frames)
                composer.fill(text)
                composer.press("Enter")
                (output / f"turn-{before}-submitted.txt").write_text(page.locator("body").aria_snapshot())
                page.get_by_role("button", name="Stop response", exact=True).wait_for(state="visible", timeout=10000)
                page.get_by_role("button", name="Stop response", exact=True).wait_for(state="hidden", timeout=120000)
                (output / f"turn-{before}-completed.txt").write_text(page.locator("body").aria_snapshot())
                composer.wait_for()
                assert any(frame.get("event") == "stream_end" for frame in frames[before:]), "本次模型运行缺少结束事件"

            turn("查询 region-1 的 product-1 和 product-2，2026-10-01 至 2026-10-10 对比 2026-09-01 至 2026-09-10，CNY、EXTERNAL_SALES、definition_version=1，查询全部六个经营指标并读取原始依据。")
            (output / "query.txt").write_text(page.locator("body").aria_snapshot())
            content = {"content_version": "1", "coordinator_id": "coordinator-1", "purpose": "提交当前会议关联的毛利变化解释、措施和证据", "due_at": "2026-10-25T17:00:00+08:00", "timezone": "Asia/Shanghai", "evidence_requirements": ["原因明细", "措施及证据"], "related_meeting_id": "meeting-1", "related_event_ids": ["event-1"], "source_refs": ["finance-note"]}
            call("/authorizations", {"namespace": "ui-check", "action": "create_assignment", "payload": content})
            turn("本人授权创建以下交办：" + json.dumps(content, ensure_ascii=False))
            tasks = service.get("/spaces/ui-check/objects/task")
            tasks.raise_for_status()
            assert len(tasks.json()) == 1
            task = tasks.json()[0]
            send = {"task_id": task["task_id"], "task_version": "1", "recipient_id": "coordinator-1", "body": content["purpose"], "content_version": "1"}
            call("/authorizations", {"namespace": "ui-check", "action": "send_assignment", "payload": send})
            turn("本人授权按以下内容模拟发送：" + json.dumps(send, ensure_ascii=False))
            turn("重新读取任务 " + task["task_id"] + "，给出当前正式状态和消息关联。")
            expect(page.locator("main")).to_contain_text("WAITING_FEEDBACK")
            page.reload(wait_until="networkidle")
            expect(page.locator("main")).to_contain_text(task["task_id"], timeout=20000)
            expect(page.locator("main")).to_contain_text("WAITING_FEEDBACK")
            (output / "assignment-reloaded.txt").write_text(page.locator("body").aria_snapshot())
            formal = service.get("/spaces/ui-check/objects/task").json()[0]
            outbox = service.get("/spaces/ui-check/objects/outbox").json()
            assert formal["status"] == "WAITING_FEEDBACK" and len(outbox) == 1 and len(formal["message_ids"]) == 1
            (output / "result.json").write_text(json.dumps({"at": now(), "status": "PASS", "scope": "原生用户端 DOM 共同任务、刷新重读与独立正式状态核查", "task": formal, "outbox": outbox}, ensure_ascii=False, indent=2))
            print(json.dumps({"evidence": str(output), "status": "PASS"}, ensure_ascii=False))
            browser.close()


if __name__ == "__main__":
    main()
