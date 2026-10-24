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
const root=path.resolve(__dirname,'../..'),validation=path.join(root,'validation'),frontend=path.join(root,'menu-f01-n3-dist');
const directory=path.join(validation,'.work','menu-f01-native-'+randomUUID()),accounts=access.provision(directory);
const ports={business:10531,webui:10532,gateway:20531},proxyPort=10533,origin='http://127.0.0.1:'+proxyPort;
const records=[],output=path.join(root,'evidence/menu-delivery/F01/native.json');fs.mkdirSync(path.dirname(output),{recursive:true});
function save(status){fs.writeFileSync(output,JSON.stringify({status,application_directory:directory,ports,frontend_directory:frontend,
  manifest_sha256:createHash('sha256').update(fs.readFileSync(path.join(frontend,'asset-manifest.json'))).digest('hex'),external_api_mode:'SIMULATED_FIRST',visual:'NOT_RUN',user_acceptance:'NOT_RUN',records},null,2)+'\n');}
async function main(){let desktop,socket,proxy;
  try{
    proxy=spawn(path.join(validation,'.venv/bin/python'),[path.join(__dirname,'fc03_morning_proxy.py'),String(ports.webui),String(proxyPort)],{cwd:root,env:{...process.env,TMPDIR:path.join(directory,'tmp')},
      stdio:['ignore',fs.openSync(path.join(directory,'proxy.stdout.log'),'w'),fs.openSync(path.join(directory,'proxy.stderr.log'),'w')]});
    desktop=await electron.launch({args:[__dirname],cwd:validation,timeout:60000,env:{...process.env,BOSS_VALIDATION_ROOT:validation,
      BOSS_PRODUCT_UI:'1',BOSS_EXECUTION_SCOPE:'BOSS-PRIORITY-ITERATION',BOSS_PRODUCT_FRONTEND_DIR:frontend,BOSS_APPLICATION_WORK_DIR:directory,
      BOSS_APPLICATION_PORTS:JSON.stringify(ports),BOSS_DESKTOP_TEST_WINDOW_HIDDEN:'1',TMPDIR:path.join(directory,'tmp')}});
    const page=await desktop.firstWindow({timeout:120000});await page.waitForURL('http://127.0.0.1:'+ports.webui+'/');
    await desktop.evaluate(async({BrowserWindow},url)=>BrowserWindow.getAllWindows()[0].loadURL(url),origin+'/');await page.waitForURL(origin+'/');const errors=[];page.on('pageerror',error=>errors.push(error.message));
    const identities={};for(const role of ['BOSS','MAINTAINER'])identities[role]=await access.bootstrap(origin,accounts,role);
    async function read(route,role='BOSS',status=200){const response=await fetch(origin+route,{headers:{Authorization:'Bearer '+identities[role].api_token}});assert.equal(response.status,status,route);return response.json();}
    socket=new WebSocket(identities.MAINTAINER.ws_url+'?token='+encodeURIComponent(identities.MAINTAINER.token));const responses=new Map();socket.addEventListener('message',event=>{const body=JSON.parse(event.data);if(body.event==='webui_response')responses.set(body.request_id,body);});await once(socket,'open');
    async function command(action,payload,status=200){const id=randomUUID();socket.send(JSON.stringify({type:'webui_request',request_id:id,action,payload}));await expect.poll(()=>responses.has(id)).toBe(true);const body=responses.get(id);assert.equal(body.ok,status===200,JSON.stringify(body.error));if(status!==200)assert.equal(body.error.status,status);return body.result;}
    const config=await read('/api/boss/ui/admin/runtime-configuration','MAINTAINER'),values={max_tool_rounds:6,max_output_tokens:700,tool_scope:['todayRead','morningListRead','morningDetailRead','morningSourceRead']};
    const draft=await command('boss.runtime.save',{client_request_id:'native-save-'+randomUUID(),expected_version:config.draft?.version??'0',values});
    const checked=await command('boss.runtime.validate',{client_request_id:'native-validate-'+randomUUID(),expected_version:draft.version,expected_content_sha256:draft.content_sha256});
    await command('boss.runtime.activate',{client_request_id:'native-activate-'+randomUUID(),expected_version:checked.version,expected_content_sha256:checked.content_sha256,expected_active_version:config.current.version});
    const meeting=(await read('/api/boss/ui/meetings')).meeting,date=meeting.starts_at.slice(0,10);
    await access.login(page,accounts,'BOSS');await expect(page.getByLabel('业务日期',{exact:true})).toBeEnabled();await page.getByLabel('业务日期',{exact:true}).fill(date);await page.getByRole('button',{name:'更新当前事项',exact:true}).click();
    const question='请整理本日需要本人决定、协调和知晓的事项';await page.getByLabel('晨间问题',{exact:true}).fill(question);
    assert.equal((await fetch(origin+'/_morning/hold-binding',{method:'POST'})).status,200);
    await page.getByRole('button',{name:'发送任务',exact:true}).click();await expect.poll(async()=>(await (await fetch(origin+'/_morning/state')).json()).held_binding!==null).toBe(true);
    const canceledBindingId=new URL(page.url()).searchParams.get('morningBinding');assert(canceledBindingId);
    await page.getByRole('button',{name:'取消会话交接',exact:true}).click();assert.equal((await fetch(origin+'/_morning/release-binding',{method:'POST'})).status,200);
    await expect(page.locator('.boss-f01')).toContainText('会话交接已取消');await expect(page.getByLabel('晨间问题',{exact:true})).toHaveValue(question);await expect(page.locator('.boss-hero h1')).toHaveText('今日工作');await expect(page.locator('.boss-f01')).toBeVisible();
    assert.equal((await read('/api/boss/ui/morning/binding?client_request_id='+canceledBindingId)).result.last_request_id,null);assert.equal((await read('/api/boss/ui/morning/history')).requests.length,0);
    assert(!(await (await fetch(origin+'/_morning/state')).json()).events.some(row=>row.action==='boss.morning.cancel'));
    records.push({check:'actual_binding_handoff_cancellation_keeps_question_and_sends_no_message',binding_id:canceledBindingId,original_query_cancel_requested:false,question_sent:false});save('IN_PROGRESS');
    await page.getByLabel('IANA 时区',{exact:true}).fill('UTC');await page.getByRole('button',{name:'更新当前事项',exact:true}).click();await expect(page.getByRole('button',{name:'发送任务',exact:true})).toBeEnabled();
    await page.getByLabel('IANA 时区',{exact:true}).fill(meeting.timezone);await page.getByRole('button',{name:'更新当前事项',exact:true}).click();await expect(page.getByRole('button',{name:'发送任务',exact:true})).toBeEnabled();
    await fetch(origin+'/_morning/arm',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'boss.morning.bind'})});
    await page.getByRole('button',{name:'发送任务',exact:true}).click();
    await expect.poll(async()=>(await (await fetch(origin+'/_morning/state')).json()).dropped_actions.includes('boss.morning.bind')).toBe(true);
    const originalBindingId=new URL(page.url()).searchParams.get('morningBinding');assert(originalBindingId);
    await page.getByRole('button',{name:'读取原会话绑定与结果',exact:true}).click();
    const bound=(await read('/api/boss/ui/morning/binding?client_request_id='+originalBindingId)).result;assert.equal(bound.last_request_id,null);
    assert.equal((await read('/api/boss/ui/morning/history')).requests.length,0);await expect(page.getByLabel('晨间问题',{exact:true})).toHaveValue(question);
    await page.getByRole('button',{name:'发送任务',exact:true}).click();await page.waitForURL(/bossPage=NATIVE/);
    const native=page.getByRole('region',{name:'大鹏会话内容',exact:true}),messages=native.getByTestId('thread-message-region');
    await expect(messages.getByText(question,{exact:true})).toBeVisible({timeout:60000});
    const bindingId=new URL(page.url()).searchParams.get('morningBinding');assert.equal(bindingId,originalBindingId);
    async function lastResult(id,previous){let binding,result;await expect.poll(async()=>{binding=(await read('/api/boss/ui/morning/binding?client_request_id='+id)).result;if(!binding?.last_request_id||binding.last_request_id===previous)return 'PENDING';result=await read('/api/boss/ui/morning/request?client_request_id='+binding.last_request_id);return result.request_state;},{timeout:90000}).toBe('SUCCEEDED');return {binding,result};}
    const first=await lastResult(bindingId);await expect(messages).toContainText('SIMULATED · 晨间清单');const listId=first.result.receipt.result.list_id;
    const secondQuestion='请继续说明当前清单的资料覆盖缺口';await native.locator('textarea').fill(secondQuestion);await native.getByRole('button',{name:/^(发送消息|Send message)$/}).click();
    const second=await lastResult(bindingId,first.binding.last_request_id);assert.equal(second.binding.session_id,first.binding.session_id);assert.equal(second.result.receipt.result.list_id,listId);assert.notEqual(second.result.run_id,first.result.run_id);
    await expect(messages.getByText(secondQuestion,{exact:true})).toBeVisible();
    const beforeStopHistory=(await read('/api/boss/ui/morning/history')).requests;
    await native.locator('textarea').fill('请继续核查当前来源与准备事项');await native.getByRole('button',{name:/^(发送消息|Send message)$/}).click();
    await native.getByRole('button',{name:/^(停止响应|Stop response)$/}).click();
    let stopped;await expect.poll(async()=>{const binding=(await read('/api/boss/ui/morning/binding?client_request_id='+bindingId)).result;if(binding.last_request_id===second.binding.last_request_id)return 'PENDING';stopped=await read('/api/boss/ui/morning/request?client_request_id='+binding.last_request_id);return stopped.request_state;},{timeout:60000}).toBe('CANCELED');
    assert.equal((await read('/api/boss/ui/morning/history')).requests.length,beforeStopHistory.length+1);assert.equal(stopped.receipt.result.list_id,listId);
    records.push({check:'actual_native_stop_cancels_current_turn_without_new_query',request_id:stopped.client_request_id,run_id:stopped.run_id,state:stopped.request_state,extra_stop_query:false,preserved_list_id:listId});save('IN_PROGRESS');
    await page.getByRole('button',{name:'返回业务页面',exact:true}).click();await expect(page.locator('.boss-hero h1')).toHaveText('今日工作');
    const list=await read('/api/boss/ui/morning/list?list_id='+listId),selected=list.result.items.find(item=>item.kind==='meeting');assert(selected);
    const row=page.locator('.boss-f01-table tbody tr').filter({has:page.getByRole('button',{name:selected.title,exact:true})});await row.getByRole('button',{name:selected.title,exact:true}).click();
    const detail=page.locator('.boss-f01-aside section').filter({has:page.getByRole('heading',{name:'当前事项详情',exact:true})});await expect(detail).toContainText(selected.object_id);
    const selectedQuestion='继续讨论当前选中事项的依据和准备要求';await page.getByLabel('晨间问题',{exact:true}).fill(selectedQuestion);await detail.getByRole('button',{name:'继续讨论',exact:true}).click();await page.waitForURL(/bossPage=NATIVE/);
    const selectedBindingId=new URL(page.url()).searchParams.get('morningBinding');assert.notEqual(selectedBindingId,bindingId);
    const selectedRun=await lastResult(selectedBindingId);assert.equal(selectedRun.binding.item_id,selected.item_id);assert.equal(selectedRun.result.receipt.result.list_id,listId);
    const runtime=(await read('/api/boss/ui/runtime-records?run_id='+selectedRun.result.run_id,'MAINTAINER')).runs[0];
    assert.equal(runtime.morning_context.selected_item_ref.item_id,selected.item_id);assert.deepEqual(runtime.morning_context.selected_item_ref.source_refs,selected.source_refs);
    assert(!JSON.stringify(runtime).includes(selectedQuestion));assert.equal(runtime.usage,null);assert.equal(runtime.cost_total,null);
    const conversation=page.url();await page.reload();await expect(messages.getByText(selectedQuestion,{exact:true})).toBeVisible();
    await page.getByRole('button',{name:'返回业务页面',exact:true}).click();await expect(detail).toContainText(selected.object_id);await expect(page.getByLabel('晨间问题',{exact:true})).toHaveValue('');
    await page.getByRole('button',{name:'打开当前晨间会话',exact:true}).click();await expect(messages.getByText(selectedQuestion,{exact:true})).toBeVisible();assert.equal(new URL(page.url()).hash,new URL(conversation).hash);
    const storage=await page.evaluate(()=>JSON.stringify({url:location.href,local:Object.fromEntries(Object.entries(localStorage)),session:Object.fromEntries(Object.entries(sessionStorage))}));for(const text of [question,secondQuestion,selectedQuestion])assert(!storage.includes(text));
    const trace=await (await fetch(origin+'/_morning/state')).json();assert.equal(trace.events.filter(row=>row.event==='actual_request_forwarded'&&row.action==='boss.morning.bind'&&row.client_request_id===bindingId).length,1);
    await command('boss.morning.bind',{client_request_id:'native-maint-denied-'+randomUUID(),chat_id:first.binding.chat_id,date,timezone:meeting.timezone},401);
    const currentConfig=await read('/api/boss/ui/admin/runtime-configuration','MAINTAINER');
    const limited=await command('boss.runtime.save',{client_request_id:'native-limited-'+randomUUID(),expected_version:currentConfig.draft.version,values:{...values,max_tool_rounds:4}});
    const limitedCheck=await command('boss.runtime.validate',{client_request_id:'native-limited-check-'+randomUUID(),expected_version:limited.version,expected_content_sha256:limited.content_sha256});
    await command('boss.runtime.activate',{client_request_id:'native-limited-activate-'+randomUUID(),expected_version:limitedCheck.version,expected_content_sha256:limitedCheck.content_sha256,expected_active_version:currentConfig.current.version});
    await native.locator('textarea').fill('请重新核查当前事项的资料范围');await native.getByRole('button',{name:/^(发送消息|Send message)$/}).click();
    let failed;await expect.poll(async()=>{const current=(await read('/api/boss/ui/morning/binding?client_request_id='+selectedBindingId)).result;if(current.last_request_id===selectedRun.binding.last_request_id)return 'PENDING';failed=await read('/api/boss/ui/morning/request?client_request_id='+current.last_request_id);return failed.request_state;},{timeout:60000}).toBe('FAILED');
    assert.equal(failed.run_id,null);assert.equal(failed.receipt.result.list_id,listId);
    await page.getByRole('button',{name:'返回业务页面',exact:true}).click();await expect(page.locator('.boss-f01')).toContainText('晨间运行状态 FAILED');
    const diagnosticDirectory=path.join(validation,'.work','desktop-'+path.basename(directory),'diagnostics');
    for(const name of fs.readdirSync(diagnosticDirectory).filter(name=>name.endsWith('.log'))){const content=fs.readFileSync(path.join(diagnosticDirectory,name),'utf8');for(const text of [question,secondQuestion,selectedQuestion])assert(!content.includes(text));for(const account of Object.values(accounts))assert(!content.includes(account.password));}
    for(const name of fs.readdirSync(path.join(frontend,'assets')).filter(name=>/\.(js|css)$/.test(name))){const content=fs.readFileSync(path.join(frontend,'assets',name),'utf8');for(const account of Object.values(accounts))assert(!content.includes(account.password));}
    assert.deepEqual(errors,[]);records.push({check:'actual_native_two_turns_current_item_runtime_history_and_return',first_binding_id:bindingId,selected_binding_id:selectedBindingId,session_id:first.binding.session_id,list_id:listId,item_id:selected.item_id,run_ids:[first.result.run_id,second.result.run_id,selectedRun.result.run_id],renderer_errors:errors,private_input_in_ordinary_storage:false,binding_interrupted_after_actual_save:true,binding_replayed:false,first_question_sent_after_explicit_recovery:true});
    records.push({check:'native_context_failure_preserves_original_list_and_maintainer_denied',state:failed.request_state,run_id:failed.run_id,domain_list_id:failed.receipt.result.list_id,private_input_or_password_in_technical_logs:false,password_in_assets:false});save('PASS');
  }finally{if(socket)socket.close();if(desktop)await desktop.close();if(proxy&&proxy.exitCode===null){const ended=once(proxy,'exit');proxy.kill('SIGTERM');await ended;}}
}
main().then(()=>console.log(JSON.stringify({status:'PASS',report:output})),failure=>{let message=failure.message;for(const account of Object.values(accounts))for(const key of ['username','password'])message=message.replaceAll(account[key],'[已隐藏]');records.push({check:'failure',message});save('FAIL');console.error(JSON.stringify({status:'FAIL',report:output}));process.exitCode=1;});
