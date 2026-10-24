const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {createHash}=require('node:crypto');
const {execFileSync}=require('node:child_process');
const {_electron:electron}=require('playwright');
const {expect:baseExpect}=require('@playwright/test');
const access=require('./account-access.cjs');
const expect=baseExpect.configure({timeout:12000});
const root=path.resolve(__dirname,'../..'),validation=path.join(root,'validation');
const source=JSON.parse(fs.readFileSync(process.argv[2]));
const directory=source.application_directory,ports=source.ports;
assert.equal(path.dirname(directory),path.join(validation,'.work'));
assert(path.basename(directory).startsWith('fc04-journey-'));
const origin='http://127.0.0.1:'+ports.webui;
const frontend=path.resolve(root,process.env.UI02_CHECK_FRONTEND||'ui02-n3-dist');
const accounts=Object.fromEntries(JSON.parse(fs.readFileSync(path.join(directory,'accounts/credentials.json'))).map(row=>[row.role,row]));
const records=[],output=path.join(root,'evidence/feature-delivery/UI02',process.env.UI02_CHECK_PHASE==='RED'?'red.json':'current.json');
fs.mkdirSync(path.dirname(output),{recursive:true});
function save(status){fs.writeFileSync(output,JSON.stringify({status,application_directory:directory,ports,frontend_directory:frontend,manifest_sha256:createHash('sha256').update(fs.readFileSync(path.join(frontend,'asset-manifest.json'))).digest('hex'),visual:'NOT_RUN',user_acceptance:'NOT_RUN',records},null,2)+'\n');}
async function main(){let desktop;
  try{
    const digest=()=>JSON.parse(execFileSync(path.join(validation,'.venv/bin/python'),[path.join(validation,'fc04_state_digest.py'),directory],{cwd:root,env:{...process.env,TMPDIR:path.join(directory,'tmp')}}));
    const before=digest(),credentialDigest=createHash('sha256').update(fs.readFileSync(path.join(directory,'accounts/credentials.json'))).digest('hex'),configDigest=createHash('sha256').update(fs.readFileSync(path.join(directory,'config.json'))).digest('hex');
    desktop=await electron.launch({args:[__dirname],cwd:validation,timeout:60000,env:{...process.env,BOSS_VALIDATION_ROOT:validation,BOSS_PRODUCT_UI:'1',BOSS_EXECUTION_SCOPE:'BOSS-PRIORITY-ITERATION',BOSS_PRODUCT_FRONTEND_DIR:frontend,BOSS_APPLICATION_WORK_DIR:directory,BOSS_APPLICATION_PORTS:JSON.stringify(ports),BOSS_DESKTOP_TEST_WINDOW_HIDDEN:'1',BOSS_INITIAL_PAGE:'F01',BOSS_DEMO_ACCOUNT_INJECTION:'1',TMPDIR:path.join(directory,'tmp')}});
    const page=await desktop.firstWindow({timeout:120000});await page.waitForURL(origin+'/?bossPage=F01');
    await access.login(page,accounts,'BOSS');
    await page.getByRole('button',{name:'大鹏会话',exact:true}).click();
    await expect(page.locator('.boss-sidebar')).toHaveCount(1);
    await expect(page.locator('#main-sidebar')).toHaveCount(0);
    await expect(page.locator('.boss-hero h1')).toHaveText('大鹏会话');
    await expect(page.locator('.boss-sidebar-nav > button')).toHaveCount(11);
    await expect(page.locator('.boss-native-surface h1:visible')).toHaveCount(0);
    await expect(page.getByLabel('当前会话',{exact:true})).toBeVisible();
    records.push({check:'shared_shell_native_entry',same_window:true,single_navigation:true});
    const nativeAuth=await access.bootstrap(origin,accounts,'BOSS');
    const settingsReply=await fetch(origin+'/api/settings',{headers:{Authorization:'Bearer '+nativeAuth.api_token}});
    assert.equal(settingsReply.status,200);const nativeSettings=await settingsReply.json();
    records.push({check:'native_model_configuration',model:nativeSettings.agent.model,provider:nativeSettings.agent.provider,has_api_key:nativeSettings.agent.has_api_key,provider_status:nativeSettings.providers.map(row=>({name:row.name,configured:row.configured})),buttons:await page.locator('.boss-native-surface button[aria-label]').evaluateAll(elements=>elements.map(element=>element.getAttribute('aria-label')))});
    save('IN_PROGRESS');
    assert.equal(desktop.windows().length,1);
    const native=page.getByRole('region',{name:'大鹏会话内容',exact:true});
    await expect(native.getByRole('button',{name:/^(语音输入|Voice input)$/})).toHaveCount(0);
    const input=native.locator('textarea');await expect(input).toHaveCount(1);
    const question='请核查当前采购报告的资料来源。';
    await input.fill(question);
    await page.locator('.boss-sidebar-nav').getByRole('button',{name:'交办管理',exact:true}).click();
    await expect(page.locator('.boss-hero h1')).toContainText('交办');
    const taskResponse=await fetch(origin+'/api/boss/ui/tasks',{headers:{Authorization:'Bearer '+nativeAuth.api_token}});assert.equal(taskResponse.status,200);const taskProjection=await taskResponse.json();assert(taskProjection.tasks.length>0);const actualTask=taskProjection.tasks[0];
    const taskRow=page.locator('.boss-task-row').filter({has:page.getByText(actualTask.purpose||actualTask.task_id,{exact:true})});await expect(taskRow).toHaveCount(1);await taskRow.click();
    const selectedTask=new URL(page.url()).searchParams.get('bossTask');
    assert.equal(selectedTask,actualTask.task_id);
    await page.locator('.boss-sidebar-nav').getByRole('button',{name:'大鹏会话',exact:true}).click();await expect(input).toHaveValue(question);
    const typography=[];
    for(const size of [{width:1440,height:900},{width:1280,height:800},{width:1024,height:768}])for(const zoom of [1,2]){
      await page.setViewportSize(size);await desktop.evaluate(({BrowserWindow},factor)=>BrowserWindow.getAllWindows()[0].webContents.setZoomFactor(factor),zoom);
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>document.documentElement.clientWidth),false);
      await input.scrollIntoViewIfNeeded();await input.click();await expect(input).toBeFocused();
      await page.keyboard.press('Meta+k');const directoryDialog=page.getByRole('dialog',{name:'全部页面导航',exact:true});await expect(directoryDialog).toBeVisible();await expect(page.getByRole('dialog')).toHaveCount(1);await page.keyboard.press('Tab');assert(await directoryDialog.evaluate(element=>element.contains(document.activeElement)));await page.keyboard.press('Escape');await expect(directoryDialog).toHaveCount(0);await expect(input).toBeFocused();
      const measured=await input.evaluate(element=>{const style=getComputedStyle(element);return {font:style.fontFamily,size:style.fontSize,line:style.lineHeight,color:style.color};});
      assert.equal(measured.size,'16px');assert.equal(measured.line,'24px');typography.push({size,zoom,measured,horizontal_overflow:false});
      await page.keyboard.press('Tab');assert(await page.evaluate(()=>document.activeElement!==document.body));
    }
    await desktop.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows()[0].webContents.setZoomFactor(1));await page.setViewportSize({width:1440,height:900});
    records.push({check:'retained_native_draft_business_context_and_six_layouts',selected_task_retained:new URL(page.url()).searchParams.get('bossTask')===selectedTask,typography});save('IN_PROGRESS');
    const actualOptions=await page.getByLabel('当前会话',{exact:true}).locator('option').evaluateAll(elements=>elements.map(element=>element.value).filter(Boolean));
    if(actualOptions.length){
      await page.getByLabel('当前会话',{exact:true}).selectOption(actualOptions[0]);
      const dialog=page.getByRole('dialog',{name:'未保存会话输入',exact:true});await expect(dialog).toBeVisible();
      await dialog.getByRole('button',{name:'返回继续编辑',exact:true}).click();await expect(input).toHaveValue(question);
      records.push({check:'native_session_switch_guard',preserved_input:true,existing_session_count:actualOptions.length});
    }
    await native.getByRole('button',{name:/^(发送消息|Send message)$/}).click();
    await expect(native.getByText('SIMULATED：请在原料库存或食品品质页面选择当前依据并填写协调内容，再准备本人核查材料。',{exact:true})).toBeVisible({timeout:60000});
    await expect(input).toHaveValue('');
    const conversationUrl=page.url();assert(conversationUrl.includes('#/chat/'));
    await page.reload();await expect(page.locator('.boss-hero h1')).toHaveText('大鹏会话');
    await expect(native.getByTestId('thread-message-region').getByText(question,{exact:true})).toBeVisible();
    await expect(native.getByText('SIMULATED：请在原料库存或食品品质页面选择当前依据并填写协调内容，再准备本人核查材料。',{exact:true})).toBeVisible();
    const messageStyle=await native.getByTestId('thread-message-region').getByText(question,{exact:true}).evaluate(element=>({size:getComputedStyle(element).fontSize,line:getComputedStyle(element).lineHeight,color:getComputedStyle(element).color}));assert.equal(messageStyle.size,'16px');assert.equal(messageStyle.line,'24px');
    await page.emulateMedia({reducedMotion:'reduce'});assert(await page.evaluate(()=>matchMedia('(prefers-reduced-motion: reduce)').matches));await expect(page.getByRole('img',{name:'Boss Agent 标识',exact:true})).toBeVisible();await expect(page.getByRole('img',{name:'大鹏吉祥物',exact:true})).toBeVisible();
    records.push({check:'actual_native_transport_response_and_persisted_reload',external_api_mode:'SIMULATED_FIRST',new_external_requests:false,conversation_hash_preserved:page.url()===conversationUrl});save('IN_PROGRESS');
    await page.getByRole('button',{name:'返回业务页面',exact:true}).click();await expect(page.locator('.boss-hero h1')).toContainText('交办');
    await page.goBack();await expect(page.locator('.boss-hero h1')).toHaveText('大鹏会话');
    await page.goForward();await expect(page.locator('.boss-hero h1')).toContainText('交办');
    records.push({check:'same_session_history_back_forward',same_window:true});save('IN_PROGRESS');
    await access.logout(page);await expect(page.getByText(question,{exact:true})).toHaveCount(0);
    assert.deepEqual(await page.evaluate(()=>Object.keys(localStorage).filter(key=>key.startsWith('nanobot.webui.composerQueuedGuidance.v1:'))),[]);
    await access.login(page,accounts,'MAINTAINER');await page.locator('.boss-sidebar-nav').getByRole('button',{name:'应用设置',exact:true}).click();
    await expect(page.locator('.boss-hero h1')).toHaveText('应用设置');
    await expect(page.locator('.boss-sidebar-nav > button')).toHaveCount(6);
    await expect(page.locator('.boss-sidebar')).toHaveCount(1);await expect(page.locator('#main-sidebar')).toHaveCount(0);
    const settings=page.getByRole('region',{name:'应用设置内容',exact:true});await expect(settings.getByRole('combobox',{name:'设置分类',exact:true})).toBeVisible();
    await settings.getByRole('combobox',{name:'设置分类',exact:true}).selectOption('appearance');
    await expect(settings.locator('[data-settings-section="appearance"]')).toBeVisible();
    await settings.getByRole('combobox',{name:/^(Change language|切换语言)$/}).click();await page.getByRole('option',{name:'简体中文',exact:true}).click();
    await expect(page.getByText(question,{exact:true})).toHaveCount(0);
    const wrap=settings.getByRole('switch',{name:'代码换行',exact:true});await expect(wrap).toBeVisible();
    const initial=await wrap.getAttribute('aria-checked');await wrap.click();await expect(wrap).toHaveAttribute('aria-checked',initial==='true'?'false':'true');
    await page.reload();await expect(settings.locator('[data-settings-section="appearance"]')).toBeVisible();await expect(wrap).toHaveAttribute('aria-checked',initial==='true'?'false':'true');
    await settings.getByRole('combobox',{name:'设置分类',exact:true}).selectOption('advanced');
    const host=settings.locator('input[id="runtime-gateway.host"]');await expect(host).toBeVisible();const originalHost=await host.inputValue(),editedHost=originalHost==='localhost'?'127.0.0.1':'localhost';await host.fill(editedHost);
    await page.locator('.boss-sidebar-nav').getByRole('button',{name:'模型运行配置',exact:true}).click();
    const unsaved=page.getByRole('dialog',{name:'未保存应用设置',exact:true});await expect(unsaved).toBeVisible();await unsaved.getByRole('button',{name:'返回继续编辑',exact:true}).click();await expect(host).toHaveValue(editedHost);
    await page.locator('.boss-sidebar-nav').getByRole('button',{name:'模型运行配置',exact:true}).click();await unsaved.getByRole('button',{name:'保留编辑并离开',exact:true}).click();
    await page.locator('.boss-sidebar-nav').getByRole('button',{name:'应用设置',exact:true}).click();await expect(host).toHaveValue(editedHost);await host.fill(originalHost);
    await settings.getByRole('combobox',{name:'设置分类',exact:true}).selectOption('appearance');
    records.push({check:'native_settings_unsaved_guard_and_retained_edit',unsubmitted_configuration_changed:false,continue_editing_preserved:true,leave_and_return_preserved:true});save('IN_PROGRESS');
    const maintLayouts=[];for(const size of [{width:1440,height:900},{width:1280,height:800},{width:1024,height:768}])for(const zoom of [1,2]){
      await page.setViewportSize(size);await desktop.evaluate(({BrowserWindow},factor)=>BrowserWindow.getAllWindows()[0].webContents.setZoomFactor(factor),zoom);assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>document.documentElement.clientWidth),false);await page.keyboard.press('Tab');maintLayouts.push({size,zoom,horizontal_overflow:false});
    }
    await desktop.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows()[0].webContents.setZoomFactor(1));await page.setViewportSize({width:1440,height:900});
    const maintAuth=await access.bootstrap(origin,accounts,'MAINTAINER');
    for(const endpoint of ['/api/sessions','/api/boss/ui/tasks'])assert.equal((await fetch(origin+endpoint,{headers:{Authorization:'Bearer '+maintAuth.api_token}})).status,403);
    records.push({check:'actual_settings_local_save_reload_role_and_layouts',role:'MAINTAINER',settings_section:'appearance',private_chat_absent:true,private_endpoints_denied:true,layouts:maintLayouts});save('IN_PROGRESS');
    await page.goto(origin+'/?bossPage=F12');await expect(page.getByRole('region',{name:'当前入口不可用',exact:true})).toBeVisible();
    assert.deepEqual(digest(),before);assert.equal(createHash('sha256').update(fs.readFileSync(path.join(directory,'accounts/credentials.json'))).digest('hex'),credentialDigest);
    assert.equal(createHash('sha256').update(fs.readFileSync(path.join(directory,'config.json'))).digest('hex'),configDigest);
    const storage=await page.evaluate(()=>JSON.stringify({url:location.href,local:Object.fromEntries(Object.entries(localStorage)),session:Object.fromEntries(Object.entries(sessionStorage))}));
    for(const account of Object.values(accounts)){
      assert(!storage.includes(account.password));
      for(const file of fs.readdirSync(path.join(frontend,'assets')).filter(value=>/\.(js|css)$/.test(value)))assert(!fs.readFileSync(path.join(frontend,'assets',file),'utf8').includes(account.password));
    }
    records.push({check:'old_link_unavailable_and_existing_business_credentials_preserved',business_rows:before.length,credentials_unchanged:true});
    save('PASS');
  }finally{if(desktop)await desktop.close();}
}
main().then(()=>console.log(JSON.stringify({status:'PASS',report:output})),failure=>{let message=failure.message;for(const account of Object.values(accounts))for(const key of ['username','password'])message=message.replaceAll(account[key],'[已隐藏]');records.push({check:'failure',message});save('FAIL');console.error(JSON.stringify({status:'FAIL',report:output}));process.exitCode=1;});
