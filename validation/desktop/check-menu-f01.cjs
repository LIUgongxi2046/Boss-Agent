const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {randomUUID,createHash}=require('node:crypto');
const {_electron:electron}=require('playwright');
const {expect:baseExpect}=require('@playwright/test');
const access=require('./account-access.cjs');
const expect=baseExpect.configure({timeout:12000});
const root=path.resolve(__dirname,'../..'),validation=path.join(root,'validation');
const phase=process.env.MENU_F01_PHASE||'GREEN';
const frontend=path.resolve(root,phase==='RED'?'ui02-n3-dist':'menu-f01-n3-dist');
const directory=path.join(validation,'.work','menu-f01-'+phase.toLowerCase()+'-'+randomUUID());
const ports={business:10511,webui:10512,gateway:20511},origin='http://127.0.0.1:'+ports.webui;
const accounts=access.provision(directory),records=[];
const output=path.join(root,'evidence/menu-delivery/F01',phase.toLowerCase()+'.json');
fs.mkdirSync(path.dirname(output),{recursive:true});
function save(status){fs.writeFileSync(output,JSON.stringify({status,phase,application_directory:directory,frontend_directory:frontend,ports,
  manifest_sha256:createHash('sha256').update(fs.readFileSync(path.join(frontend,'asset-manifest.json'))).digest('hex'),
  external_api_mode:'SIMULATED_FIRST',visual:'NOT_RUN',user_acceptance:'NOT_RUN',records},null,2)+'\n');}
async function main(){let desktop;
  try{
    desktop=await electron.launch({args:[__dirname],cwd:validation,timeout:60000,env:{...process.env,BOSS_VALIDATION_ROOT:validation,
      BOSS_PRODUCT_UI:'1',BOSS_EXECUTION_SCOPE:'BOSS-PRIORITY-ITERATION',BOSS_PRODUCT_FRONTEND_DIR:frontend,
      BOSS_APPLICATION_WORK_DIR:directory,BOSS_APPLICATION_PORTS:JSON.stringify(ports),BOSS_DESKTOP_TEST_WINDOW_HIDDEN:'1',TMPDIR:path.join(directory,'tmp')}});
    const page=await desktop.firstWindow({timeout:120000});await page.waitForURL(origin+'/');
    await access.login(page,accounts,'BOSS');
    await expect(page.locator('.boss-sidebar').getByRole('button',{name:'今日工作',exact:true})).toBeVisible();
    await expect(page.getByRole('heading',{name:'现在就交给大鹏',exact:true})).toBeVisible();
    await expect(page.getByRole('heading',{name:'我的当前事项',exact:true})).toBeVisible();
    for(const title of ['当前需我关注','来源与依据'])await expect(page.getByRole('heading',{name:title,exact:true})).toBeVisible();
    assert.equal(await page.locator('.boss-f01-categories > button').count(),3);
    records.push({check:'original_f01_regions',status:'PASS'});save('PASS');
  }finally{if(desktop)await desktop.close();}
}
main().then(()=>console.log(JSON.stringify({status:'PASS',report:output})),failure=>{
  let message=failure.message;for(const account of Object.values(accounts))for(const key of ['username','password'])message=message.replaceAll(account[key],'[已隐藏]');
  records.push({check:'failure',message});save('FAIL');console.error(JSON.stringify({status:'FAIL',report:output}));process.exitCode=1;
});
