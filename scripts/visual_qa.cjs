/**
 * Capture real *authenticated* Boss-Agent desktop WebUI frames for review.
 * Usage (Mac, with local app running):
 *   node scripts/visual_qa.cjs --role BOSS --pages F01,F06,N02,N05
 *   node scripts/visual_qa.cjs --role MAINTAINER --pages A04,A08
 *
 * Requires Playwright Chromium installed on this Mac:
 *   cd validation/desktop && npx playwright install chromium
 *
 * No credentials or screenshots are uploaded: captures stay in .work/.
 * Do not run against real enterprise/private sources without authorization.
 */
"use strict";
const fs = require("node:fs");
const path = require("node:path");
const ROOT = path.resolve(__dirname, "..");
const { chromium } = require(path.join(ROOT, "validation", "desktop", "node_modules", "playwright"));
const args = process.argv.slice(2);
function flag(key, fallback) {
  const at = args.indexOf(key);
  return at >= 0 && args[at + 1] ? args[at + 1] : fallback;
}
const role = flag("--role", "BOSS").toUpperCase();
if (!["BOSS", "MAINTAINER"].includes(role)) throw new Error("role must be BOSS or MAINTAINER");
const pageIds = flag("--pages", role === "BOSS" ? "F01,F06,N02,N05" : "A04,A08").split(",").map(x=>x.trim()).filter(Boolean);
const viewports = [{width:1440,height:1024},{width:1280,height:800},{width:1024,height:768}];
const address = flag("--url", "http://127.0.0.1:8872");
if (!/^http:\/\/127\.0\.0\.1:\d+$/.test(address)) {
  throw new Error("Only 127.0.0.1 development WebUI is accepted");
}
const creds = path.join(ROOT,"validation",".work","application","access.json");
const cataloguePath = path.join(ROOT,"Boss-Agent-Desktop-Complete-v6","meta","页面配置.json");
const catalogue = JSON.parse(fs.readFileSync(cataloguePath,"utf8"));
for (const id of pageIds) {
  if (!catalogue[id]) throw new Error("Unknown Desktop v6 design page: " + id);
  if (["N01","D08"].includes(id)) throw new Error("Native nanobot owns authentication, not a separate Boss-Agent route");
  if (catalogue[id].technical !== (role === "MAINTAINER") && !["D06","D07"].includes(id)) {
    throw new Error("Role cannot capture this page: " + role + "/" + id);
  }
}
if (!fs.existsSync(creds)) throw new Error("Local authenticated runtime not running; no access.json at expected path");
const access = JSON.parse(fs.readFileSync(creds,"utf8"));
const secret = access[role];
if (typeof secret !== "string" || secret.length < 32) throw new Error("Invalid local role credential");
const output = path.join(ROOT,".work","visual-qa",role.toLowerCase());
fs.mkdirSync(output,{recursive:true,mode:0o700});
(async()=>{
 const browser=await chromium.launch({headless:true});
 const records=[];
 try {
   for(const pageId of pageIds){
     for(const vp of viewports){
       const context=await browser.newContext({
         viewport:vp,deviceScaleFactor:1,colorScheme:"light",
         reducedMotion:"reduce",locale:"zh-CN",
       });
       await context.addInitScript((value)=>{
         window.localStorage.setItem("nanobot-webui.bootstrap-secret",value);
       }, secret);
       const page=await context.newPage();
       const filename=pageId+"-"+vp.width+"x"+vp.height+".png";
       const screenshot=path.join(output,filename);
       let state="SUCCESS",message="",geometry=null,geometryViolations=[];
       try{
         await page.goto(address+"/?bossPage="+encodeURIComponent(pageId),{waitUntil:"domcontentloaded",timeout:15000});
         await page.locator('.boss-v6[data-role="'+role+'"]').waitFor({state:"visible",timeout:30000});
         await page.locator(".boss-meta-strip").waitFor({state:"visible",timeout:12000});
         // Allow first non-blocking render; live business values remain in frame.
         await page.waitForTimeout(450);
         geometry = await page.evaluate(() => {
           const rect = selector => {
             const element = document.querySelector(selector);
             if (!element) return null;
             const bounds = element.getBoundingClientRect();
             return {width: bounds.width, height: bounds.height};
           };
           const hero = document.querySelector(".boss-hero");
           const mascot = document.querySelector(".boss-hero-mascot");
           const logo = document.querySelector(".boss-brand img");
           return {
             sidebar: rect(".boss-sidebar"),
             topbar: rect(".boss-topbar"),
             hero: rect(".boss-hero"),
             heroRadiusPx: hero ? Number.parseFloat(getComputedStyle(hero).borderTopLeftRadius) : null,
             mascotAssetLoaded: !!mascot && mascot instanceof HTMLImageElement && mascot.naturalWidth > 0,
             brandAssetLoaded: !!logo && logo instanceof HTMLImageElement && logo.naturalWidth > 0,
             pageTitle: hero?.querySelector("h1")?.textContent || "",
           };
         });
         const expectedSidebar = vp.width <= 1050 ? 60 : 204;
         const expectedHero = pageId === "F01" ? (vp.width <= 1250 ? 124 : 146) : 122;
         const close = (actual, expected) => Math.abs(actual - expected) <= 2.5;
         if (!geometry?.sidebar || !close(geometry.sidebar.width, expectedSidebar)) {
           geometryViolations.push("sidebar_width");
         }
         if (!geometry?.topbar || !close(geometry.topbar.height, 64)) {
           geometryViolations.push("topbar_height");
         }
         if (!geometry?.hero || !close(geometry.hero.height, expectedHero)) {
           geometryViolations.push("hero_height");
         }
         if (geometry?.heroRadiusPx == null || !close(geometry.heroRadiusPx, 20)) {
           geometryViolations.push("hero_radius");
         }
         if (!geometry?.brandAssetLoaded) geometryViolations.push("logo_not_loaded");
         if (!geometry?.mascotAssetLoaded) geometryViolations.push("mascot_not_loaded");
         await page.screenshot({path:screenshot,animations:"disabled",fullPage:false});
         if (geometryViolations.length) {
           state="GEOMETRY_MISMATCH";
           message="Desktop v6 source geometry or branded media differs from reference";
         }
       } catch(e){
         state="CAPTURE_FAILED";message=String(e instanceof Error?e.message:e).slice(0,300);
       }
       records.push({
         page_id:pageId,
         page_title:catalogue[pageId].title,
         role,viewport:vp,screenshot:state==="SUCCESS"?path.relative(ROOT,screenshot):null,
         design_reference:path.join("Boss-Agent-Desktop-Complete-v6","images-1x",pageId+"-"+catalogue[pageId].title+".png"),
         state,message,geometry,geometry_violations:geometryViolations,
       });
       console.log(pageId+" "+vp.width+"x"+vp.height+": "+state);
       await context.close();
     }
   }
 }finally{
   await browser.close();
   // Never persist the secret, any token, or the raw auth file in the report.
   fs.writeFileSync(path.join(output,"capture-report.json"),JSON.stringify({
     platform:process.platform,architecture:process.arch,role,
     generated_at:new Date().toISOString(),
     notes:"Source-v6 shell geometry and branded-media diagnostic. Screenshots are NOT pixel comparison or complete product acceptance.",
     captures:records,
   },null,2)+"\n",{mode:0o600});
 }
 if(records.some(r=>r.state!=="SUCCESS"))process.exitCode=1;
})().catch(err=>{
  console.error(err instanceof Error?err.message:String(err));
  process.exitCode=1;
});
