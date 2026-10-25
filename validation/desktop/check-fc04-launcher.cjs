const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {execFileSync}=require('node:child_process');
const {createHash}=require('node:crypto');
const {_electron:electron}=require('playwright');
const {expect}=require('@playwright/test');
const access=require('./account-access.cjs');
const root=path.resolve(__dirname,'../..'),validation=path.join(root,'validation'),source=JSON.parse(fs.readFileSync(process.argv[2]));
assert.equal(path.dirname(source.application_directory),path.join(validation,'.work'));
const digest=()=>JSON.parse(execFileSync(path.join(validation,'.venv/bin/python'),[path.join(validation,'fc04_state_digest.py'),source.application_directory],{cwd:root,env:{...process.env,TMPDIR:path.join(source.application_directory,'tmp')}}));
async function main(){let desktop;
  try{
    const before=digest();assert(before.some(row=>row.kind==='owner_plan'));
    desktop=await electron.launch({executablePath:path.join(root,'scripts/run_fc04.command'),args:[],cwd:root,timeout:120000,env:{...process.env,BOSS_DESKTOP_TEST_WINDOW_HIDDEN:'1',BOSS_FC04_WORK_DIRECTORY:source.application_directory,BOSS_FC04_PORTS:JSON.stringify(source.ports)}});
    const page=await desktop.firstWindow({timeout:120000}),origin='http://127.0.0.1:'+source.ports.webui;await page.waitForURL(origin+'/?bossPage=F02');
    const accounts=Object.fromEntries(JSON.parse(fs.readFileSync(path.join(source.application_directory,'accounts/credentials.json'))).map(row=>[row.role,row]));await access.login(page,accounts,'BOSS');await expect(page.getByRole('heading',{name:'经营通知与提醒',exact:true})).toBeVisible();
    const boss=await access.bootstrap(origin,accounts,'BOSS'),response=await fetch(origin+'/api/boss/ui/owner-plans',{headers:{Authorization:'Bearer '+boss.api_token}});assert.equal(response.status,200);const plans=await response.json();assert.equal(plans.plans[0].state,'CANCELED');
    const after=digest();assert.deepEqual(after,before);const manifest=path.join(root,'fc04-n3-dist/asset-manifest.json');
    fs.writeFileSync(path.join(root,'evidence/feature-delivery/FC04/launcher.json'),JSON.stringify({status:'PASS',launcher:'scripts/run_fc04.command',scope:'BOSS-PRIORITY-ITERATION',application_directory:source.application_directory,ports:source.ports,
      manifest_sha256:createHash('sha256').update(fs.readFileSync(manifest)).digest('hex'),actual_boss_login:true,first_page:'F02',existing_business_rows_unchanged:before.length,automatic_configuration_changes:false,automatic_business_rule_or_event_creation:false,
      retained_owner_plan_state:plans.plans[0].state,independent_validation_directory:true,visual:'NOT_RUN',user_acceptance:'NOT_RUN'},null,2)+'\n');
  }finally{if(desktop)await desktop.close();}
}
main().then(()=>console.log('FC04 launcher PASS'),failure=>{console.error(failure);process.exitCode=1;});
