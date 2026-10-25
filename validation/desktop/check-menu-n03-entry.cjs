const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {randomUUID,createHash}=require('node:crypto');
const {_electron:electron}=require('playwright');
const {expect}=require('@playwright/test');
const access=require('./account-access.cjs');
const root=path.resolve(__dirname,'../..'),validation=path.join(root,'validation'),frontend=path.join(root,'menu-n03-n3-dist');
const space=fs.statfsSync(root);assert(space.bavail*space.bsize>=200*1024*1024,'入口检查需要至少200MiB可用空间');
const directory=path.join(validation,'.work','menu-n03-entry-'+randomUUID());
const accounts=access.provision(directory),ports={business:10831,webui:10832,gateway:20831};
fs.mkdirSync(path.join(directory,'tmp'),{recursive:true});
const output=path.join(root,'evidence/menu-delivery/N03/entry.json');
async function main(){
  let application;
  try{
    application=await electron.launch({args:[__dirname],cwd:validation,timeout:60000,env:{...process.env,BOSS_VALIDATION_ROOT:validation,BOSS_PRODUCT_UI:'1',BOSS_EXECUTION_SCOPE:'BOSS-PRIORITY-ITERATION',BOSS_INITIAL_PAGE:'N03',BOSS_PRODUCT_FRONTEND_DIR:frontend,BOSS_APPLICATION_WORK_DIR:directory,BOSS_APPLICATION_PORTS:JSON.stringify(ports),BOSS_DESKTOP_TEST_WINDOW_HIDDEN:'1',PYTHONDONTWRITEBYTECODE:'1',TMPDIR:path.join(directory,'tmp')}});
    const page=await application.firstWindow({timeout:120000});
    await page.waitForURL('http://127.0.0.1:'+ports.webui+'/?bossPage=N03');
    await access.login(page,accounts,'BOSS');
    await expect(page.locator('.boss-v6[data-page="N03"]')).toBeVisible();
    const expected=['经营关注范围','十个经营专题','经营提醒与来源'];
    const observed=await page.locator('.boss-content h2').allTextContents();
    const missing=expected.filter(title=>!observed.includes(title));
    const status=missing.length?'REQUIREMENT_FAILURE':'PASS';
    fs.mkdirSync(path.dirname(output),{recursive:true});
    fs.writeFileSync(output,JSON.stringify({status,scope:'MENU_N03_REQUIRED_OVERVIEW_ENTRY',checkpoints:['MENU-N03.C01','MENU-N03.C02'],application_directory:directory,ports,manifest_sha256:createHash('sha256').update(fs.readFileSync(path.join(frontend,'asset-manifest.json'))).digest('hex'),expected_headings:expected,observed_headings:observed,missing_headings:missing,visual:'NOT_RUN',user_acceptance:'NOT_RUN'},null,2)+'\n');
    console.log(JSON.stringify({status,report:output,missing_headings:missing}));
    assert.deepEqual(missing,[],'经营关注必须提供原加载页面的三个业务区域');
  }finally{if(application){await application.evaluate(({BrowserWindow})=>{for(const window of BrowserWindow.getAllWindows())window.destroy();});await application.close();}}
}
void main();
