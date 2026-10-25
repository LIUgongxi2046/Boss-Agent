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
const digest=()=>JSON.parse(execFileSync(path.join(validation,'.venv/bin/python'),[path.join(validation,'fc07_state_digest.py'),source.application_directory],{cwd:root,env:{...process.env,TMPDIR:path.join(source.application_directory,'tmp')}}));
async function main(){let desktop;
  try{
    const before=digest();assert(before.some(row=>row.kind==='task'));
    desktop=await electron.launch({executablePath:path.join(root,'scripts/run_fc07.command'),args:[],cwd:root,timeout:120000,env:{...process.env,BOSS_DESKTOP_TEST_WINDOW_HIDDEN:'1',BOSS_FC07_WORK_DIRECTORY:source.application_directory,BOSS_FC07_PORTS:JSON.stringify(source.ports)}});
    const page=await desktop.firstWindow({timeout:120000}),origin='http://127.0.0.1:'+source.ports.webui;await page.waitForURL(origin+'/');
    const accounts=Object.fromEntries(JSON.parse(fs.readFileSync(path.join(source.application_directory,'accounts/credentials.json'))).map(row=>[row.role,row]));await access.login(page,accounts,'BOSS');await expect(page.getByRole('region',{name:'采购成本连续体验',exact:true})).toBeVisible();
    const auth=await access.bootstrap(origin,accounts,'MAINTAINER'),response=await fetch(origin+'/api/boss/ui/admin/runtime-configuration',{headers:{Authorization:'Bearer '+auth.api_token}});assert.equal(response.status,200);const state=await response.json();assert(['read_assignment','assignmentSourcesRead','bossSupplyQualityPrepare'].every(name=>state.current.tool_scope.includes(name)));
    const after=digest();assert.deepEqual(after,before);const setup=JSON.parse(fs.readFileSync(path.join(source.application_directory,'fc07-setup.json')));assert.equal(setup.scope_id,'BOSS-PRIORITY-ITERATION');assert.equal(setup.mvp_database_preserved,true);
    const manifest=path.join(root,'fc07-n3-dist/asset-manifest.json');assert.equal(setup.manifest_sha256,createHash('sha256').update(fs.readFileSync(manifest)).digest('hex'));
    fs.writeFileSync(path.join(root,'evidence/feature-delivery/FC07/launcher.json'),JSON.stringify({status:'PASS',launcher:'scripts/run_fc07.command',scope:'BOSS-PRIORITY-ITERATION',application_directory:source.application_directory,ports:source.ports,
      manifest_sha256:setup.manifest_sha256,actual_boss_login:true,configuration_version:state.current.version,current_tool_scope:state.current.tool_scope,existing_business_rows_unchanged:before.length,independent_validation_directory:true,visual:'NOT_RUN',user_acceptance:'NOT_RUN'},null,2)+'\n');
  }finally{if(desktop)await desktop.close();}
}
main().then(()=>console.log('FC07 launcher PASS'),failure=>{console.error(failure);process.exitCode=1;});
