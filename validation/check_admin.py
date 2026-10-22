import json
import os
import uuid

import httpx
from playwright.sync_api import expect, sync_playwright
from websockets.sync.client import connect

from business import ROOT, now


def main():
    os.environ["TMPDIR"] = str(ROOT / ".work/tmp")
    output = ROOT.parent / "evidence/T02" / ("admin-" + str(uuid.uuid4()))
    output.mkdir(parents=True)
    access = json.loads((ROOT / ".work/application/access.json").read_text())
    records = []
    with httpx.Client(base_url="http://127.0.0.1:8872", trust_env=False, timeout=20) as client:
        response = client.get("/webui/bootstrap", headers={"X-Nanobot-Auth": access["MAINTAINER"]})
        response.raise_for_status()
        credentials = response.json()
        for path in ("/api/sessions", "/api/boss/identity", "/api/settings"):
            response = client.get(path, headers={"Authorization": "Bearer " + credentials["api_token"]})
            records.append({"role": "MAINTAINER", "path": path, "status": response.status_code})
            assert response.status_code == (403 if path == "/api/sessions" else 200)
        assert client.get("/api/sessions").status_code == 401
        assert client.get("/webui/bootstrap", headers={"X-Nanobot-Auth": "coordinator-1"}).status_code == 401
        with connect("ws://127.0.0.1:8872/?token=" + credentials["token"]) as socket:
            assert json.loads(socket.recv())["event"] == "ready"
            socket.send(json.dumps({"type": "message", "chat_id": "ui-check", "content": "代替老板创建交办"}))
            denied = json.loads(socket.recv())
            assert denied["event"] == "error" and denied["detail"] == "access_denied"
            records.append({"role": "MAINTAINER", "transport": "WEBSOCKET", "operation": "message", "result": denied})
    with sync_playwright() as driver:
        browser = driver.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page(locale="en-US")
        mutations = []

        def websocket(socket):
            def sent(raw):
                frame = json.loads(raw)
                if frame.get("action") == "settings.runtime_config.update":
                    mutations.append(frame)
            socket.on("framesent", sent)

        page.on("websocket", websocket)
        page.goto("http://127.0.0.1:8872", wait_until="networkidle")
        page.get_by_role("textbox", name="WebUI password", exact=True).fill(access["MAINTAINER"])
        page.get_by_role("button", name="Connect", exact=True).click()
        page.get_by_role("button", name="Settings", exact=True).click()
        page.get_by_role("button", name="Advanced", exact=True).click()
        control = page.get_by_role("spinbutton", name="Tool iterations per turn", exact=True)
        before = int(control.input_value())
        value = 8 if before != 8 else 9
        control.fill(str(value))
        expect(page.get_by_role("region", name="Agent limits", exact=True).get_by_role("status")).to_have_text("Saved.", timeout=20000)
        assert len(mutations) == 1
        page.reload(wait_until="networkidle")
        expect(page.get_by_role("spinbutton", name="Tool iterations per turn", exact=True)).to_have_value(str(value), timeout=20000)
        config = json.loads((ROOT / ".work/application/config.json").read_text())
        assert config["agents"]["defaults"]["maxToolIterations"] == value
        (output / "admin-reloaded.txt").write_text(page.locator("body").aria_snapshot())
        (output / "requests.json").write_text(json.dumps({"access_checks": records, "mutations": mutations}, ensure_ascii=False, indent=2))
        report = {"at": now(), "status": "PASS", "scope": "维护身份管理配置 DOM 保存重载、HTTP 私人会话拒绝、WebSocket 业务决定拒绝、未认证与联系人伪造拒绝", "saved_max_tool_rounds": value, "next_task_adoption": "等待实际服务重启后的新任务"}
        (output / "result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
        print(json.dumps({**report, "evidence": str(output)}, ensure_ascii=False))
        browser.close()


if __name__ == "__main__":
    main()
