"use strict";

const fs = require("node:fs");
const path = require("node:path");
const crypto = require("node:crypto");
const {pathToFileURL, fileURLToPath} = require("node:url");
const ROOT = path.resolve(__dirname, "..");
const {chromium} = require(path.join(ROOT, "validation/desktop/node_modules/playwright"));
const DESIGN = path.join(ROOT, "Boss-Agent-Desktop-Complete-v7");
const OUTPUT = path.join(ROOT, ".work/takeover/v7-reference-dom");
fs.mkdirSync(path.join(OUTPUT, "browser-temporary"), {recursive: true});
process.env.TMPDIR = path.join(OUTPUT, "browser-temporary");
const catalogue = JSON.parse(fs.readFileSync(path.join(DESIGN, "meta/页面配置.json"), "utf8"));
const pages = process.argv.slice(2);
const selected = pages.length ? pages : Object.keys(catalogue);
if (selected.some(id => !catalogue[id])) throw new Error("页面编号不属于当前设计目录");

async function main() {
  const browser = await chromium.launch({channel: "chrome", headless: true});
  const records = [];
  try {
    const context = await browser.newContext();
    await context.route("**/*", route => {
      if (!route.request().url().startsWith("file://")) throw new Error("设计核查只允许本地文件");
      return route.continue();
    });
    const page = await context.newPage();
    const errors = [];
    page.on("pageerror", error => errors.push(error.message));
    for (const id of selected) {
      const filename = path.join(DESIGN, "pages", id + "-" + catalogue[id].title + ".html");
      for (const viewport of [{width:1440,height:1024}, {width:1280,height:800}, {width:1024,height:768}]) {
        await page.setViewportSize(viewport);
        await page.goto(pathToFileURL(filename).href);
        await page.evaluate(() => document.fonts.ready);
        const observed = await page.evaluate(() => {
          const box = element => {
            const bounds = element.getBoundingClientRect();
            const style = getComputedStyle(element);
            return {x:bounds.x,y:bounds.y,width:bounds.width,height:bounds.height,
              display:style.display,gridTemplateColumns:style.gridTemplateColumns,gap:style.gap,
              padding:style.padding,fontSize:style.fontSize,lineHeight:style.lineHeight,
              borderRadius:style.borderRadius,background:style.backgroundColor};
          };
          const stage = document.querySelector(".stage-body");
          return {
            title:document.title,
            scripts:[...document.scripts].filter(item => item.src).map(item => item.src),
            styles:[...document.querySelectorAll('link[rel="stylesheet"]')].map(item => item.href),
            stage:stage ? box(stage) : null,
            grids:[...document.querySelectorAll(".v6-grid,.editorgrid,.v7-chatcolumns,.sheet-row,.dialog-grid")].map(element => ({
              ...box(element), className:element.className,
              columns:[...element.children].map(column => ({...box(column),
                titles:[...column.querySelectorAll("h2,.card-title")].map(item => item.textContent.trim())})),
            })),
            panels:[...document.querySelectorAll(".v6-panel,.v7-sectionwide,.v7-sidebox,.card.pad")].map(element => ({
              title:element.querySelector("h2,.v7-sideheading,.card-title")?.textContent.trim() || "",
              ...box(element),
              fields:[...element.querySelectorAll("label")].map(item => item.textContent.trim()),
              actions:[...element.querySelectorAll("button")].map(item => item.textContent.trim()),
            })),
            headings:[...(stage?.querySelectorAll("h2,h3,.card-title") || [])].map(item => ({text:item.textContent.trim(),...box(item)})),
            horizontalOverflow:document.documentElement.scrollWidth > innerWidth,
          };
        });
        if (errors.length) throw new Error(JSON.stringify({id, errors}));
        const dependencies=[...observed.scripts,...observed.styles].map(url=>({path:fileURLToPath(url),sha256:crypto.createHash("sha256").update(fs.readFileSync(fileURLToPath(url))).digest("hex")}));
        records.push({id, viewport, sourceSha256:crypto.createHash("sha256").update(fs.readFileSync(filename)).digest("hex"), dependencies, ...observed});
      }
      process.stdout.write(id + "\n");
    }
    const output = path.join(OUTPUT, pages.length ? "reference-" + pages.join("-") + ".json" : "reference.json");
    fs.writeFileSync(output, JSON.stringify({design:DESIGN, browser:browser.version(), observedAt:new Date().toISOString(),
      visualInspection:false, authenticatedApplication:false, records}, null, 2) + "\n");
    process.stdout.write(output + "\n");
  } finally {
    await browser.close();
  }
}

main();
