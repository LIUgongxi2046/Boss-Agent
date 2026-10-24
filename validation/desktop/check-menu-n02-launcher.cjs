const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {createHash,randomUUID}=require('node:crypto');
const {execFileSync}=require('node:child_process');
const {_electron:electron}=require('playwright');
const {expect:baseExpect}=require('@playwright/test');
const expect=baseExpect.configure({timeout:15000});
const root=path.resolve(__dirname,'../..'),validation=path.join(root,'validation'),directory=path.join(validation,'.work','menu-n02-launcher-check-'+randomUUID());
const frontend=path.join(root,'menu-n02-n3-dist'),ports={business:10791,webui:10792,gateway:20791},origin='http://127.0.0.1:'+ports.webui;
const output=path.join(root,'evidence/menu-delivery/N02/launcher.json'),records=[];
function save(status){fs.writeFileSync(output,JSON.stringify({status,scope:'N02_ACTUAL_LAUNCHER_AND_CONTROLLED_ACCOUNT_FILL',application_directory:directory,ports,frontend_directory:frontend,manifest_sha256:createHash('sha256').update(fs.readFileSync(path.join(frontend,'asset-manifest.json'))).digest('hex'),visual:'NOT_RUN',user_acceptance:'NOT_RUN',records},null,2)+'\n');}
async function main(){let desktop;
  try{
    const initialization=JSON.parse(execFileSync(path.join(validation,'.venv/bin/python'),[path.join(root,'scripts/prepare_menu_n02.py'),'--directory',directory,'--frontend',frontend,'--ports',JSON.stringify(ports)],{cwd:root,env:{...process.env,PYTHONDONTWRITEBYTECODE:'1',TMPDIR:path.join(validation,'.work/tmp')},encoding:'utf8'}));assert.equal(initialization.existing_data_reused,false);
    const setup=JSON.parse(fs.readFileSync(path.join(directory,'setup.json')));assert.equal(setup.feature_id,'MENU-N02');assert.equal(setup.status,'READY');assert.deepEqual(setup.ports,ports);records.push({check:'fresh_isolated_initializer_uses_actual_registered_tools',configuration_version:setup.configuration_version,tool_scope:setup.runtime_configuration_values.tool_scope});save('IN_PROGRESS');
    const credentialFile=path.join(directory,'accounts/credentials.json'),beforeCredential=fs.statSync(credentialFile),digest=()=>JSON.parse(execFileSync(path.join(validation,'.venv/bin/python'),[path.join(validation,'fc04_state_digest.py'),directory],{cwd:root,env:{...process.env,PYTHONDONTWRITEBYTECODE:'1',TMPDIR:path.join(directory,'tmp')},encoding:'utf8'}));const before=digest();
    desktop=await electron.launch({executablePath:path.join(root,'scripts/run_menu_n02.command'),args:[],cwd:root,timeout:120000,env:{...process.env,BOSS_DESKTOP_TEST_WINDOW_HIDDEN:'1',BOSS_MENU_N02_WORK_DIRECTORY:directory,BOSS_MENU_N02_PORTS:JSON.stringify(ports),PYTHONDONTWRITEBYTECODE:'1'}});
    const page=await desktop.firstWindow({timeout:120000});await page.waitForURL(origin+'/?bossPage=N02');
    for(const role of ['BOSS','MAINTAINER']){
      if(role==='MAINTAINER')await page.getByRole('button',{name:'技术维护',exact:true}).click();
      await page.getByRole('button',{name:'测试账号注入',exact:true}).click();await expect(page.getByLabel('账号',{exact:true})).toHaveValue(role==='BOSS'?'boss':'maintainer');const password=await page.getByLabel('密码',{exact:true}).inputValue();assert(password.length>=24);await expect(page.locator('.boss-v6[data-role]')).toHaveCount(0);
      const ordinary=await page.evaluate(()=>JSON.stringify({url:location.href,local:Object.fromEntries(Object.entries(localStorage)),session:Object.fromEntries(Object.entries(sessionStorage))}));assert(!ordinary.includes(password));
      await page.getByRole('button',{name:/^(登录|重新认证)$/}).click();await expect(page.locator('.boss-v6[data-role="'+role+'"]')).toBeVisible();assert.equal(desktop.windows().length,1);
      if(role==='BOSS'){await expect(page.locator('.boss-hero h1')).toHaveText('聊天交办');await expect(page.getByRole('region',{name:'聊天交办内容',exact:true})).toBeVisible();await expect(page.getByRole('button',{name:'提交需求',exact:true})).toBeDisabled();}
      records.push({check:'controlled_main_window_role_account_fill_requires_explicit_login',role,account_filled_without_login:true,ordinary_storage_contains_password:false,same_window:true});await page.getByTitle('退出当前身份',{exact:true}).click();await expect(page.getByLabel('账号',{exact:true})).toBeEnabled();
    }
    assert.deepEqual(digest(),before);const afterCredential=fs.statSync(credentialFile);assert.equal(afterCredential.size,beforeCredential.size);assert.equal(afterCredential.mtimeMs,beforeCredential.mtimeMs);assert.deepEqual(JSON.parse(fs.readFileSync(path.join(directory,'setup.json'))),setup);records.push({check:'existing_prepared_data_config_and_credential_file_preserved',business_rows:before.length,credential_file_unchanged:true,setup_unchanged:true,protected_user_instances_used:false});save('PASS');
  }finally{if(desktop)await desktop.close();}
}
main().then(()=>console.log(JSON.stringify({status:'PASS',report:output})),failure=>{records.push({check:'failure',error_type:failure.name});save('FAIL');console.error(JSON.stringify({status:'FAIL',error_type:failure.name,report:output}));process.exitCode=1;});
