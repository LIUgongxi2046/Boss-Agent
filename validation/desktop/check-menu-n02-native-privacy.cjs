const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {once}=require('node:events');
const {spawn}=require('node:child_process');
const {randomUUID,createHash}=require('node:crypto');
const {_electron:electron}=require('playwright');
const {expect:baseExpect}=require('@playwright/test');
const access=require('./account-access.cjs');
const expect=baseExpect.configure({timeout:15000});
const root=path.resolve(__dirname,'../..'),validation=path.join(root,'validation'),frontend=path.join(root,'menu-n02-n3-dist');
const directory=path.join(validation,'.work','menu-n02-native-privacy-'+randomUUID()),accounts=access.provision(directory);
const ports={business:10731,webui:10732,gateway:20731},origin='http://127.0.0.1:10733';
const records=[],output=path.join(root,'evidence/menu-delivery/N02/native-privacy.json');
const hash=text=>createHash('sha256').update(text).digest('hex');
function save(status){fs.mkdirSync(path.dirname(output),{recursive:true});fs.writeFileSync(output,JSON.stringify({status,application_directory:directory,ports,frontend_directory:frontend,manifest_sha256:hash(fs.readFileSync(path.join(frontend,'asset-manifest.json'))),external_api_mode:'SIMULATED_FIRST',visual:'NOT_RUN',user_acceptance:'NOT_RUN',scope:'N02_NATIVE_DRAFT_AND_QUEUE_PRIVACY',records},null,2)+'\n');}
async function main(){let desktop,socket,proxy;
  try{
    proxy=spawn(path.join(validation,'.venv/bin/python'),[path.join(__dirname,'menu_n02_native_proxy.py'),String(ports.webui),'10733'],{cwd:root,env:{...process.env,TMPDIR:path.join(directory,'tmp')},stdio:['ignore',fs.openSync(path.join(directory,'proxy.stdout.log'),'w'),fs.openSync(path.join(directory,'proxy.stderr.log'),'w')]});
    desktop=await electron.launch({args:[__dirname],cwd:validation,timeout:60000,env:{...process.env,BOSS_VALIDATION_ROOT:validation,BOSS_PRODUCT_UI:'1',BOSS_EXECUTION_SCOPE:'BOSS-PRIORITY-ITERATION',BOSS_PRODUCT_FRONTEND_DIR:frontend,BOSS_APPLICATION_WORK_DIR:directory,BOSS_APPLICATION_PORTS:JSON.stringify(ports),BOSS_DESKTOP_TEST_WINDOW_HIDDEN:'1',TMPDIR:path.join(directory,'tmp')}});
    const page=await desktop.firstWindow({timeout:120000});await page.waitForURL('http://127.0.0.1:'+ports.webui+'/');await desktop.evaluate(async({BrowserWindow},url)=>BrowserWindow.getAllWindows()[0].loadURL(url),origin+'/');await page.waitForURL(origin+'/');
    const identities={};for(const role of ['BOSS','MAINTAINER'])identities[role]=await access.bootstrap(origin,accounts,role);
    async function read(route,role='BOSS'){const response=await fetch(origin+route,{headers:{Authorization:'Bearer '+identities[role].api_token}});assert.equal(response.status,200);return response.json();}
    socket=new WebSocket(identities.MAINTAINER.ws_url+'?token='+encodeURIComponent(identities.MAINTAINER.token));const responses=new Map();socket.addEventListener('message',event=>{const value=JSON.parse(event.data);if(value.event==='webui_response')responses.set(value.request_id,value);});await once(socket,'open');
    async function command(action,payload){const key=randomUUID();socket.send(JSON.stringify({type:'webui_request',request_id:key,action,payload}));await expect.poll(()=>responses.has(key),{message:action}).toBe(true);const response=responses.get(key);assert.equal(response.ok,true,JSON.stringify(response.error));return response.result;}
    const config=await read('/api/boss/ui/admin/runtime-configuration','MAINTAINER'),values={max_tool_rounds:6,max_output_tokens:700,tool_scope:['todayRead','morningListRead','morningDetailRead','morningSourceRead']};
    const draft=await command('boss.runtime.save',{client_request_id:randomUUID(),expected_version:config.draft?.version??'0',values}),checked=await command('boss.runtime.validate',{client_request_id:randomUUID(),expected_version:draft.version,expected_content_sha256:draft.content_sha256});
    await command('boss.runtime.activate',{client_request_id:randomUUID(),expected_version:checked.version,expected_content_sha256:checked.content_sha256,expected_active_version:config.current.version});
    await access.login(page,accounts,'BOSS');const meeting=(await read('/api/boss/ui/meetings')).meeting;await expect(page.getByLabel('业务日期',{exact:true})).toBeEnabled();await page.getByLabel('业务日期',{exact:true}).fill(meeting.starts_at.slice(0,10));await page.getByRole('button',{name:'更新当前事项',exact:true}).click();
    await page.getByLabel('晨间问题',{exact:true}).fill('请整理当前日期需要本人处理的事项');await page.getByRole('button',{name:'发送任务',exact:true}).click();await page.waitForURL(/bossPage=NATIVE/);
    const bindingId=new URL(page.url()).searchParams.get('morningBinding');let binding;await expect.poll(async()=>{binding=(await read('/api/boss/ui/morning/binding?client_request_id='+bindingId)).result;if(!binding.last_request_id)return 'PENDING';return (await read('/api/boss/ui/morning/request?client_request_id='+binding.last_request_id)).request_state;},{timeout:60000}).toBe('SUCCEEDED');
    const native=page.getByRole('region',{name:'大鹏会话内容',exact:true}),editor=native.locator('textarea');await expect(native.getByRole('button',{name:/^(发送消息|Send message)$/})).toBeVisible();
    assert.equal((await fetch(origin+'/_n02/hold',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({chat_id:binding.chat_id})})).status,200);
    await editor.fill('请继续核查当前来源');await native.getByRole('button',{name:/^(发送消息|Send message)$/}).click();await expect.poll(async()=>(await (await fetch(origin+'/_n02/state')).json()).held!==null).toBe(true);
    const queuedText='请保留本次尚未发送的资料核查说明';await editor.fill(queuedText);await editor.press('Enter');await expect(native.locator('[data-queued-prompt-row]')).toHaveCount(1);await expect(editor).toHaveValue('');
    const storage=await page.evaluate(()=>JSON.stringify({url:location.href,local:Object.fromEntries(Object.entries(localStorage)),session:Object.fromEntries(Object.entries(sessionStorage))}));assert(!storage.includes(queuedText));assert(!storage.includes('nanobot.webui.composerQueuedGuidance.v1:'));
    await native.getByRole('button',{name:/^(停止响应|Stop response)$/}).click();await page.getByRole('button',{name:'返回业务页面',exact:true}).click();let dialog=page.getByRole('dialog',{name:'未保存会话输入',exact:true});await expect(dialog).toBeVisible();await dialog.getByRole('button',{name:'返回继续编辑',exact:true}).click();await expect(native.locator('[data-queued-prompt-row]')).toHaveCount(1);
    await page.getByRole('button',{name:'返回业务页面',exact:true}).click();await page.getByRole('dialog',{name:'未保存会话输入',exact:true}).getByRole('button',{name:'放弃输入并离开',exact:true}).click();await page.waitForURL(/bossPage=F01/);assert.equal((await fetch(origin+'/_n02/release',{method:'POST'})).status,200);
    const trace=await (await fetch(origin+'/_n02/state')).json();assert(!trace.messages.some(message=>message.content_sha256===hash(queuedText)));await page.getByRole('button',{name:'打开当前晨间会话',exact:true}).click();await expect(native.locator('[data-queued-prompt-row]')).toHaveCount(0);await expect(editor).toHaveValue('');
    records.push({check:'actual_delayed_native_output_memory_only_queue_and_explicit_discard',chat_id:binding.chat_id,queue_in_browser_storage:false,queued_message_sent:false,discarded_queue_restored:false});save('IN_PROGRESS');
    const attachment=path.join(root,'data/simulation/supply-quality-v1.yaml');await native.locator('input[type=file]').setInputFiles(attachment);await expect(native.getByText(path.basename(attachment),{exact:true})).toBeVisible();await expect(editor).toHaveValue('');
    await page.getByRole('button',{name:'新建会话',exact:true}).click();dialog=page.getByRole('dialog',{name:'未保存会话输入',exact:true});await expect(dialog).toBeVisible();await dialog.getByRole('button',{name:'返回继续编辑',exact:true}).click();await expect(native.getByText(path.basename(attachment),{exact:true})).toBeVisible();
    await page.getByRole('button',{name:'新建会话',exact:true}).click();await page.getByRole('dialog',{name:'未保存会话输入',exact:true}).getByRole('button',{name:'放弃输入并离开',exact:true}).click();await expect(native.getByText(path.basename(attachment),{exact:true})).toHaveCount(0);await expect(editor).toHaveValue('');
    const after=await (await fetch(origin+'/_n02/state')).json();assert.equal(after.messages.filter(message=>message.chat_id===binding.chat_id).length,3);
    records.push({check:'actual_selected_file_attachment_only_navigation_guard_and_discard',source_file:'data/simulation/supply-quality-v1.yaml',source_sha256:hash(fs.readFileSync(attachment)),attachment_sent:false,discarded_attachment_restored:false});save('PASS');
  }finally{if(socket)socket.close();if(proxy&&proxy.exitCode===null){const current=await (await fetch(origin+'/_n02/state')).json();if(current.held)await fetch(origin+'/_n02/release',{method:'POST'});}if(desktop)await desktop.close();if(proxy&&proxy.exitCode===null){const ended=once(proxy,'exit');proxy.kill('SIGTERM');await ended;}}
}
main().then(()=>console.log(JSON.stringify({status:'PASS',report:output})),failure=>{let message=failure.message;for(const account of Object.values(accounts))for(const key of ['username','password'])message=message.replaceAll(account[key],'[已隐藏]');records.push({check:'failure',message});save('FAIL');console.error(JSON.stringify({status:'FAIL',report:output}));process.exitCode=1;});
