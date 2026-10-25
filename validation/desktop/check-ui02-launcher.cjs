const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {createHash}=require('node:crypto');
const {execFileSync}=require('node:child_process');
const {_electron:electron}=require('playwright');
const {expect}=require('@playwright/test');
const access=require('./account-access.cjs');
const root=path.resolve(__dirname,'../..'),validation=path.join(root,'validation'),directory=path.join(validation,'.work/ui02-experience');
const frontend=path.join(root,'ui02-n3-dist'),output=path.join(root,'evidence/feature-delivery/UI02/launcher.json');
const accounts=Object.fromEntries(JSON.parse(fs.readFileSync(path.join(directory,'accounts/credentials.json'))).map(row=>[row.role,row]));
const records=[];
function save(status){fs.writeFileSync(output,JSON.stringify({status,application_directory:directory,ports:{business:10411,webui:10412,gateway:20411},frontend_directory:frontend,manifest_sha256:createHash('sha256').update(fs.readFileSync(path.join(frontend,'asset-manifest.json'))).digest('hex'),visual:'NOT_RUN',user_acceptance:'NOT_RUN',records},null,2)+'\n');}
async function main(){let desktop;
  try{
    const digest=()=>JSON.parse(execFileSync(path.join(validation,'.venv/bin/python'),[path.join(validation,'fc04_state_digest.py'),directory],{cwd:root,env:{...process.env,TMPDIR:path.join(directory,'tmp')}}));
    const before=digest(),credentialDigest=createHash('sha256').update(fs.readFileSync(path.join(directory,'accounts/credentials.json'))).digest('hex');
    const environment={...process.env,BOSS_DESKTOP_TEST_WINDOW_HIDDEN:'1'};delete environment.BOSS_UI02_WORK_DIRECTORY;delete environment.BOSS_UI02_PORTS;
    desktop=await electron.launch({executablePath:path.join(root,'scripts/run_ui02.command'),args:[],cwd:root,timeout:120000,env:environment});const page=await desktop.firstWindow({timeout:120000});await page.waitForURL('http://127.0.0.1:10412/?bossPage=F01');
    for(const role of ['BOSS','MAINTAINER']){
      if(role==='MAINTAINER')await page.getByRole('button',{name:'技术维护',exact:true}).click();
      await page.getByRole('button',{name:'测试账号注入',exact:true}).click();await expect(page.getByLabel('账号',{exact:true})).toHaveValue(accounts[role].username);await expect(page.getByLabel('密码',{exact:true})).toHaveValue(accounts[role].password);await expect(page.locator('.boss-v6[data-role]')).toHaveCount(0);
      await page.getByRole('button',{name:/^(登录|重新认证)$/}).click();await expect(page.locator('.boss-v6[data-role="'+role+'"]')).toBeVisible();await page.locator('.boss-sidebar-nav').getByRole('button',{name:role==='BOSS'?'大鹏会话':'应用设置',exact:true}).click();await expect(page.locator('.boss-native-surface')).toBeVisible();records.push({check:'actual_default_launcher_and_explicit_role_authentication',role,account_filled_without_login:true,same_window:desktop.windows().length===1});await access.logout(page);
    }
    assert.deepEqual(digest(),before);assert.equal(createHash('sha256').update(fs.readFileSync(path.join(directory,'accounts/credentials.json'))).digest('hex'),credentialDigest);records.push({check:'independent_default_business_and_credentials_preserved',business_rows:before.length,credentials_unchanged:true,user_experience_directory_used:false});save('PASS');
  }finally{if(desktop)await desktop.close();}
}
main().then(()=>console.log(JSON.stringify({status:'PASS',report:output})),failure=>{let message=failure.message;for(const account of Object.values(accounts))for(const field of ['username','password'])message=message.replaceAll(account[field],'[已隐藏]');records.push({check:'failure',message});save('FAIL');console.error(JSON.stringify({status:'FAIL',report:output}));process.exitCode=1;});
