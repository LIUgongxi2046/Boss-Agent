"use strict";

const fs = require("node:fs");
const path = require("node:path");
const os = require("node:os");
const ROOT = path.resolve(__dirname, "..");
const { chromium } = require(path.join(ROOT, "validation/desktop/node_modules/playwright"));
const catalogue = JSON.parse(fs.readFileSync(path.join(ROOT, "Boss-Agent-Desktop-Complete-v7/meta/页面配置.json"), "utf8"));

function argument(name, fallback) {
  const index = process.argv.indexOf(name);
  return index >= 0 ? process.argv[index + 1] : fallback;
}

const origin = argument("--origin", "http://127.0.0.1:8872");
const accounts = argument("--accounts", path.join(ROOT, "validation/.work/application-acceptance/accounts/credentials.json"));
const output = argument("--output", path.join(ROOT, ".work/takeover/v7-product-dom/product.json"));
const explicit = process.argv.slice(2).filter(value => catalogue[value]);
const pages = explicit.length ? explicit : Object.keys(catalogue);
pages.sort((left, right) => Number(Boolean(catalogue[left].technical)) - Number(Boolean(catalogue[right].technical)));
const viewports = [{ width: 1440, height: 1024 }, { width: 1280, height: 800 }, { width: 1024, height: 768 }];
const executablePath = process.env.BOSS_PRODUCT_CHROMIUM || path.join(os.homedir(), "Library/Caches/ms-playwright/chromium_headless_shell-1228/chrome-headless-shell-mac-x64/chrome-headless-shell");

const credentials = JSON.parse(fs.readFileSync(accounts, "utf8"));
const users = Object.fromEntries(credentials.map(item => [item.role, item]));

async function signIn(page, role) {
  const account = users[role];
  if (!account) throw new Error("缺少 " + role + " 账号");
  await page.goto(origin + "/");
  const token = await page.evaluate(async ({ username, password, role }) => {
    const response = await fetch("/webui/bootstrap", { headers: { "X-Boss-Username": username, "X-Boss-Password": password, "X-Boss-Role": role }, cache: "no-store" });
    if (!response.ok) throw new Error("登录失败 HTTP " + response.status);
    const body = await response.json();
    if (!body.api_token) throw new Error("缺少访问令牌");
    localStorage.setItem("nanobot-webui.bootstrap-secret", body.api_token);
    return body.api_token;
  }, { username: account.username, password: account.password, role });
  if (!token) throw new Error("登录结果为空");
}

async function measure(page, id) {
  await page.waitForSelector('[data-page="' + id + '"]', { timeout: 20000 });
  await page.waitForTimeout(300);
  return page.evaluate(id => {
    const box = element => {
      const bounds = element.getBoundingClientRect();
      const style = getComputedStyle(element);
      return { x: bounds.x, y: bounds.y, width: bounds.width, height: bounds.height,
        display: style.display, gridTemplateColumns: style.gridTemplateColumns, gap: style.gap,
        padding: style.padding, fontSize: style.fontSize, lineHeight: style.lineHeight,
        borderRadius: style.borderRadius };
    };
    const root = document.querySelector('[data-page="' + id + '"]');
    const stage = root?.querySelector(".boss-stage");
    const headings = [...(root?.querySelectorAll("h1,h2,h3") || [])].map(item => ({ text: item.textContent.trim(), tag: item.tagName.toLowerCase(), ...box(item) }));
    const panels = [...(root?.querySelectorAll(".boss-panel") || [])].map(item => ({ title: item.querySelector("h2")?.textContent.trim() || "",
      ...box(item) }));
    const columns = [...(root?.querySelectorAll(".boss-columns") || [])].map(item => ({ ...box(item),
      children: [...item.children].map(child => ({ width: Math.round(child.getBoundingClientRect().width), ...box(child) })) }));
    return { id, title: document.title, stage: stage ? box(stage) : null, columns, panels, headings,
      horizontalOverflow: document.documentElement.scrollWidth > innerWidth,
      text: (root?.innerText || "").slice(0, 20000) };
  }, id);
}

async function main() {
  fs.mkdirSync(path.dirname(output), { recursive: true });
  fs.mkdirSync(path.join(ROOT, ".work/takeover/v7-product-dom/browser-temporary"), { recursive: true });
  process.env.TMPDIR = path.join(ROOT, ".work/takeover/v7-product-dom/browser-temporary");
  const browser = await chromium.launch({ headless: true, executablePath });
  const records = [];
  try {
    const context = await browser.newContext();
    const page = await context.newPage();
    let signedRole = null;
    for (const id of pages) {
      const role = catalogue[id].technical ? "MAINTAINER" : "BOSS";
      if (signedRole !== role) {
        await signIn(page, role);
        signedRole = role;
      }
      await page.setViewportSize(viewports[0]);
      await page.goto(origin + "/?bossPage=" + id);
      await page.waitForSelector('[data-page="' + id + '"]', { timeout: 20000 });
      await page.waitForTimeout(1000);
      for (const viewport of viewports) {
        await page.setViewportSize(viewport);
        await page.waitForTimeout(400);
        const observed = await measure(page, id);
        records.push({ id, role, viewport, observedAt: new Date().toISOString(), ...observed });
      }
      process.stdout.write(id + " " + role + "\n");
    }
    fs.writeFileSync(output, JSON.stringify({ origin, accounts, visualInspection: false, records }, null, 2) + "\n");
    process.stdout.write(output + "\n");
  } finally {
    await browser.close();
  }
}

main().catch(error => { console.error(error); process.exit(1); });
