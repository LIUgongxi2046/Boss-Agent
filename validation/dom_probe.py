import json
import os
import uuid
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

from business import now

ROOT = Path(__file__).resolve().parent


def main():
    os.environ["TMPDIR"] = str(ROOT / ".work/tmp")
    output = ROOT.parent / "evidence/T02" / ("dom-" + str(uuid.uuid4()))
    output.mkdir(parents=True)
    records, request_ids = [], set()

    def sent(raw):
        frame = json.loads(raw)
        if frame.get("action") == "settings.runtime_config.update":
            request_ids.add(frame["request_id"])
            records.append({"direction": "sent", "at": now(), "request": frame})

    def received(raw):
        frame = json.loads(raw)
        if frame.get("event") == "webui_response" and frame.get("request_id") in request_ids:
            result = frame.get("result", {})
            records.append({"direction": "received", "at": now(), "request_id": frame["request_id"], "ok": frame["ok"], "error": frame.get("error"), "runtime_config": result.get("runtime_config"), "requires_restart": result.get("requires_restart")})

    def connected(socket):
        socket.on("framesent", sent)
        socket.on("framereceived", received)
    with sync_playwright() as driver:
        browser = driver.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page(locale="en-US")
        page.on("websocket", connected)
        response = page.request.get("http://127.0.0.1:8872/api/settings")
        assert response.status == 401
        page.goto("http://127.0.0.1:8872", wait_until="networkidle")
        secret = json.loads((ROOT / ".work/upstream-instance/access.json").read_text())["NANOBOT_WEBUI_SECRET"]
        page.get_by_role("textbox", name="WebUI password", exact=True).fill(secret)
        page.get_by_role("button", name="Connect", exact=True).click()
        page.get_by_role("textbox", name="WebUI password", exact=True).wait_for(state="hidden")
        page.get_by_role("button", name="Settings", exact=True).click()
        page.get_by_role("button", name="Models", exact=True).wait_for()
        page.get_by_role("button", name="Advanced", exact=True).click()
        control = page.get_by_role("spinbutton", name="Tool iterations per turn", exact=True)
        before = int(control.input_value())
        target = 8 if before != 8 else 9
        control.fill(str(target))
        expect(page.get_by_role("region", name="Agent limits", exact=True).get_by_role("status")).to_have_text("Saved.", timeout=15000)
        replies = [record for record in records if record["direction"] == "received"]
        assert len(replies) == 1 and replies[0]["ok"] is True
        (output / "websocket-requests.json").write_text(json.dumps(records, ensure_ascii=False, indent=2))
        (output / "unauthenticated.json").write_text(json.dumps({"method": "GET", "path": "/api/settings", "status": response.status, "at": now()}))
        (output / "admin-saved.txt").write_text(page.locator("body").aria_snapshot())
        page.reload(wait_until="networkidle")
        expect(page.get_by_role("spinbutton", name="Tool iterations per turn", exact=True)).to_have_value(str(target))
        config = json.loads((ROOT / ".work/upstream-instance/config.json").read_text())
        assert config["agents"]["defaults"]["maxToolIterations"] == target
        (output / "admin-reloaded.txt").write_text(page.locator("body").aria_snapshot())
        page.get_by_role("button", name="Back to chat", exact=True).click()
        page.get_by_role("button", name="Restart later", exact=True).click()
        page.get_by_role("button", name="New topic", exact=True).wait_for()
        (output / "user-chat.txt").write_text(page.locator("body").aria_snapshot())
        report = {"at": now(), "status": "PASS", "scope": "上游登录、管理配置保存与刷新重读、用户聊天入口 DOM；业务模型任务未执行", "url": "http://127.0.0.1:8872", "before": before, "saved": target, "file_reloaded": target, "model_request_sent": False, "next_model_task_adoption": "NOT_RUN", "desktop": "NOT_RUN"}
        (output / "result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
        print(json.dumps({**report, "evidence": str(output)}, ensure_ascii=False))
        browser.close()


if __name__ == "__main__":
    main()
