import json
import os

from playwright.sync_api import sync_playwright

from business import ROOT


os.environ["TMPDIR"] = str(ROOT / ".work/tmp")
with sync_playwright() as driver:
    browser = driver.chromium.launch(channel="chrome", headless=True)
    page = browser.new_page(locale="en-US")
    page.goto("http://127.0.0.1:8872", wait_until="networkidle")
    access = json.loads((ROOT / ".work/application/access.json").read_text())
    page.get_by_role("textbox", name="WebUI password", exact=True).fill(access["BOSS"])
    page.get_by_role("button", name="Connect", exact=True).click()
    page.get_by_role("button", name="New topic", exact=True).wait_for()
    page.get_by_role("status", name="Connected", exact=True).wait_for()
    page.get_by_role("region", name="Conversation workbench", exact=True).wait_for()
    page.locator("main").get_by_role("textbox").wait_for()
    print(page.locator("body").aria_snapshot())
    browser.close()
