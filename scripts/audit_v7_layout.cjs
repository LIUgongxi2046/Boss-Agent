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
const output = argument("--output", path.join(ROOT, ".work/takeover/v7-layout-audit/audit.json"));
const explicit = process.argv.slice(2).filter(value => catalogue[value]);
const pages = explicit.length ? explicit : Object.keys(catalogue);
pages.sort((left, right) => Number(Boolean(catalogue[left].technical)) - Number(Boolean(catalogue[right].technical)));
const viewports = [{ width: 1440, height: 1024 }, { width: 1280, height: 800 }];
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
    localStorage.setItem("nanobot-webui.bootstrap-secret", body.api_token);
    return body.api_token;
  }, { username: account.username, password: account.password, role });
  if (!token) throw new Error("登录结果为空");
}

async function measure(page, id) {
  await page.waitForSelector('[data-page="' + id + '"]', { timeout: 20000 });
  await page.waitForTimeout(600);
  return page.evaluate(id => {
    const root = document.querySelector('[data-page="' + id + '"]');
    if (!root) return { id, missing: true };
    const visible = element => {
      const style = getComputedStyle(element);
      const rect = element.getBoundingClientRect();
      const closedDetails = element.closest("details:not([open])");
      if (closedDetails && element.closest("details") === closedDetails && !element.matches("summary")) return false;
      if (element.closest("[hidden]")) return false;
      return style.display !== "none" && style.visibility !== "hidden" && rect.width > 1 && rect.height > 1;
    };
    const cardSelector = ".boss-panel,.boss-v7-panel,.boss-card,.boss-columns>*,.boss-n02-panel,.boss-chat-artifact,.boss-v7-card";
    const cards = [...root.querySelectorAll(cardSelector)].filter(visible);
    const overlaps = [];
    for (let i = 0; i < cards.length; i += 1) {
      for (let j = i + 1; j < cards.length; j += 1) {
        const a = cards[i], b = cards[j];
        if (a.contains(b) || b.contains(a)) continue;
        const ra = a.getBoundingClientRect(), rb = b.getBoundingClientRect();
        const width = Math.min(ra.right, rb.right) - Math.max(ra.left, rb.left);
        const height = Math.min(ra.bottom, rb.bottom) - Math.max(ra.top, rb.top);
        if (width > 4 && height > 4) {
          const area = width * height;
          const smaller = Math.min(ra.width * ra.height, rb.width * rb.height);
          if (area > 80 && area > smaller * 0.05) {
            overlaps.push({ a: (a.querySelector("h2,h3")?.textContent || a.className || "").trim().slice(0, 40),
              b: (b.querySelector("h2,h3")?.textContent || b.className || "").trim().slice(0, 40),
              width: Math.round(width), height: Math.round(height) });
          }
        }
      }
    }
    const clipped = [...root.querySelectorAll("*")].filter(element => {
      if (!visible(element)) return false;
      const style = getComputedStyle(element);
      if (!["hidden", "clip"].includes(style.overflowY) && !["hidden", "clip"].includes(style.overflow)) return false;
      return element.scrollHeight > element.clientHeight + 8 && element.clientHeight > 0 && element.children.length > 0;
    }).slice(0, 8).map(element => ({ tag: element.tagName.toLowerCase(), className: String(element.className).slice(0, 60),
      clientHeight: element.clientHeight, scrollHeight: element.scrollHeight }));
    const inScrollContainer = element => {
      let node = element.parentElement;
      while (node && node !== root.parentElement) {
        const style = getComputedStyle(node);
        if (["auto", "scroll"].includes(style.overflowX) || ["auto", "scroll"].includes(style.overflow)) return true;
        node = node.parentElement;
      }
      return false;
    };
    const outOfStage = [...root.querySelectorAll("*")].filter(element => {
      if (!visible(element)) return false;
      if (inScrollContainer(element)) return false;
      const rect = element.getBoundingClientRect();
      const stage = element.closest(".boss-stage") || root;
      const sr = stage.getBoundingClientRect();
      return rect.right > sr.right + 2 || rect.left < sr.left - 2;
    }).slice(0, 8).map(element => ({ tag: element.tagName.toLowerCase(), className: String(element.className).slice(0, 60),
      right: Math.round(element.getBoundingClientRect().right), stageRight: Math.round((element.closest(".boss-stage") || root).getBoundingClientRect().right) }));
    const compactTypes = new Set(["checkbox", "radio", "hidden", "submit", "button", "file", "color", "range"]);
    const controls = [...root.querySelectorAll("input,select,textarea")].filter(visible)
      .filter(element => !compactTypes.has((element.getAttribute("type") || "text").toLowerCase()));
    const cramped = controls.filter(element => {
      const rect = element.getBoundingClientRect();
      return rect.width < 80 || rect.height < 30;
    }).slice(0, 10).map(element => ({ tag: element.tagName.toLowerCase(), type: element.getAttribute("type") || "",
      width: Math.round(element.getBoundingClientRect().width), height: Math.round(element.getBoundingClientRect().height),
      label: (element.getAttribute("aria-label") || element.getAttribute("placeholder") || element.name || "").slice(0, 40) }));
    const unlabeled = controls.filter(element => {
      const labelled = element.labels && element.labels.length || element.getAttribute("aria-label") || element.getAttribute("placeholder");
      return !labelled;
    }).slice(0, 10).map(element => ({ tag: element.tagName.toLowerCase(), name: element.name || "", id: element.id || "" }));
    const spill = [...root.querySelectorAll("*")].filter(element => {
      if (!visible(element) || element.children.length) return false;
      const style = getComputedStyle(element);
      return element.scrollWidth > element.clientWidth + 4 && ["visible", "clip"].includes(style.overflowX) && (element.textContent || "").trim().length > 0;
    }).slice(0, 10).map(element => ({ tag: element.tagName.toLowerCase(), className: String(element.className).slice(0, 50),
      scrollWidth: element.scrollWidth, clientWidth: element.clientWidth }));
    return { id, title: (root.querySelector("h1,h2")?.textContent || "").trim(), cards: cards.length, overlaps: overlaps.slice(0, 10),
      overlapCount: overlaps.length, clipped, outOfStage, cramped, unlabeled, spill,
      horizontalOverflow: document.documentElement.scrollWidth > innerWidth + 1,
      textLength: (root.innerText || "").length };
  }, id);
}

async function main() {
  fs.mkdirSync(path.dirname(output), { recursive: true });
  fs.mkdirSync(path.join(ROOT, ".work/takeover/v7-layout-audit/browser-temporary"), { recursive: true });
  process.env.TMPDIR = path.join(ROOT, ".work/takeover/v7-layout-audit/browser-temporary");
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
      for (const viewport of viewports) {
        await page.setViewportSize(viewport);
        await page.goto(origin + "/?bossPage=" + id);
        await page.waitForSelector('[data-page="' + id + '"]', { timeout: 20000 });
        await page.waitForTimeout(800);
        records.push({ viewport, ...(await measure(page, id)) });
      }
    }
  } finally {
    await browser.close();
  }
  fs.writeFileSync(output, JSON.stringify({ at: new Date().toISOString(), records }, null, 1));
  const bad = records.filter(row => row.overlapCount || row.outOfStage.length || row.horizontalOverflow || row.cramped.length || row.unlabeled.length || row.spill.length);
  console.log("pages", pages.length, "records", records.length, "flagged", bad.length);
  for (const row of bad.slice(0, 60)) {
    console.log(row.id, row.viewport.width + "x" + row.viewport.height, "overlap", row.overlapCount, "outside", row.outOfStage.length,
      "overflow", row.horizontalOverflow, "cramped", row.cramped.length, "unlabeled", row.unlabeled.length, "spill", row.spill.length);
  }
}

main().catch(error => { console.error(error); process.exit(1); });
