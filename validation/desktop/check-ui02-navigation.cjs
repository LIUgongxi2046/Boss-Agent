const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {createHash}=require('node:crypto');
const {_electron:electron}=require('playwright');
const {expect:baseExpect}=require('@playwright/test');
const access=require('./account-access.cjs');
const expect=baseExpect.configure({timeout:15000});
const root=path.resolve(__dirname,'../..'),validation=path.join(root,'validation');
const source=JSON.parse(fs.readFileSync(process.argv[2])),directory=source.application_directory,ports=source.ports;
assert.equal(path.dirname(directory),path.join(validation,'.work'));assert(path.basename(directory).startsWith('fc04-journey-'));
const frontend=path.join(root,'ui02-n3-dist'),origin='http://127.0.0.1:'+ports.webui;
const accounts=Object.fromEntries(JSON.parse(fs.readFileSync(path.join(directory,'accounts/credentials.json'))).map(row=>[row.role,row]));
const records=[],output=path.join(root,'evidence/feature-delivery/UI02/navigation.json');
const expected={BOSS:['F01','F03','F14','F21','F02','F06','N05','N06','N08','N09','NATIVE'],MAINTAINER:['A03','A04','A08','A13','A15','NATIVE']};
function save(status){fs.writeFileSync(output,JSON.stringify({status,application_directory:directory,ports,frontend_directory:frontend,manifest_sha256:createHash('sha256').update(fs.readFileSync(path.join(frontend,'asset-manifest.json'))).digest('hex'),visual:'NOT_RUN',user_acceptance:'NOT_RUN',records},null,2)+'\n');}
async function main(){let desktop;
  try{
    desktop=await electron.launch({executablePath:path.join(root,'scripts/run_ui02.command'),args:[],cwd:root,timeout:120000,env:{...process.env,BOSS_DESKTOP_TEST_WINDOW_HIDDEN:'1',BOSS_UI02_WORK_DIRECTORY:directory,BOSS_UI02_PORTS:JSON.stringify(ports)}});
    const page=await desktop.firstWindow({timeout:120000});await page.waitForURL(origin+'/?bossPage=F01');
    for(const role of ['BOSS','MAINTAINER']){
      await access.login(page,accounts,role);const nav=page.locator('.boss-sidebar-nav');
      const labels=await nav.locator('button').evaluateAll(elements=>elements.map(element=>element.getAttribute('title')));assert.equal(labels.length,expected[role].length);
      const routes=[];
      for(const label of labels){
        const button=nav.getByRole('button',{name:label,exact:true});await button.click();await expect(button).toHaveAttribute('aria-current','page');
        const id=new URL(page.url()).searchParams.get('bossPage');routes.push(id);await expect(page.locator('.boss-hero h1')).toBeVisible();
        await expect(page.locator('.boss-sidebar')).toHaveCount(1);await expect(page.locator('#main-sidebar')).toHaveCount(0);
        await expect(page.locator(id==='NATIVE'?'.boss-native-surface':'.boss-content')).toBeVisible();
      }
      assert.deepEqual(routes,expected[role]);
      await page.keyboard.press('Meta+k');const dialog=page.getByRole('dialog',{name:'全部页面导航',exact:true});await expect(dialog).toBeVisible();await expect(dialog.locator('.boss-directory-list > button')).toHaveCount(expected[role].length);await page.keyboard.press('Escape');await expect(dialog).toHaveCount(0);
      records.push({check:'all_delivered_routes_directory_and_single_shell',role,routes,same_window:desktop.windows().length===1});save('IN_PROGRESS');
      await access.logout(page);
    }
    save('PASS');
  }finally{if(desktop)await desktop.close();}
}
main().then(()=>console.log(JSON.stringify({status:'PASS',report:output})),failure=>{let message=failure.message;for(const account of Object.values(accounts))for(const field of ['username','password'])message=message.replaceAll(account[field],'[已隐藏]');records.push({check:'failure',message});save('FAIL');console.error(JSON.stringify({status:'FAIL',report:output}));process.exitCode=1;});
