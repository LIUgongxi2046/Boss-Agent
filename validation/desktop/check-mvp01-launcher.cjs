const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {_electron:electron}=require('playwright');
const {expect}=require('@playwright/test');
const access=require('./account-access.cjs');
const root=path.resolve(__dirname,'../..'),directory=path.join(root,'validation/.work/mvp01-experience');
async function main(){let desktop;
  try{
    desktop=await electron.launch({executablePath:path.join(root,'scripts/run_mvp01.command'),args:[],cwd:root,timeout:120000,env:{...process.env,BOSS_DESKTOP_TEST_WINDOW_HIDDEN:'1'}});
    const page=await desktop.firstWindow({timeout:120000});await page.waitForURL('http://127.0.0.1:9962/');
    const accounts=Object.fromEntries(JSON.parse(fs.readFileSync(path.join(directory,'accounts/credentials.json'))).map(row=>[row.role,row]));
    await access.login(page,accounts,'BOSS');await expect(page.getByRole('region',{name:'采购成本连续体验',exact:true})).toBeVisible();
    const auth=await access.bootstrap('http://127.0.0.1:9962',accounts,'BOSS');
    const response=await fetch('http://127.0.0.1:9962/api/boss/identity',{headers:{Authorization:'Bearer '+auth.api_token}});assert.equal(response.status,200);assert.equal((await response.json()).execution_scope,'BOSS-MVP-1');
    const setup=JSON.parse(fs.readFileSync(path.join(directory,'setup.json')));assert.equal(setup.status,'READY');
    fs.writeFileSync(path.join(root,'evidence/feature-delivery/MVP01/launcher.json'),JSON.stringify({status:'PASS',launcher:'scripts/run_mvp01.command',scope:'BOSS-MVP-1',origin:'http://127.0.0.1:9962',ports:setup.ports,
      manifest_sha256:setup.manifest_sha256,directory,credential_path:path.join(directory,'accounts/credentials.json'),actual_boss_login:true,hidden_window:true,visual:'NOT_RUN',user_acceptance:'NOT_RUN'},null,2)+'\n');
  }finally{if(desktop)await desktop.close();}
}
main().then(()=>console.log('MVP01 launcher PASS'),failure=>{console.error(failure);process.exitCode=1;});
