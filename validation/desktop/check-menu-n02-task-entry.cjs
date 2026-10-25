const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {once}=require('node:events');
const {spawn,execFileSync}=require('node:child_process');
const {randomUUID,createHash}=require('node:crypto');
const {_electron:electron}=require('playwright');
const {expect:baseExpect}=require('@playwright/test');
const access=require('./account-access.cjs');
const expect=baseExpect.configure({timeout:20000});
const root=path.resolve(__dirname,'../..'),validation=path.join(root,'validation'),frontend=path.join(root,'menu-n02-n3-dist');
const directory=path.join(validation,'.work','menu-n02-task-entry-'+randomUUID()),accounts=access.provision(directory);
const ports={business:10811,webui:10812,gateway:20811},proxyPort=10813,origin='http://127.0.0.1:'+proxyPort;
const output=path.join(root,'evidence/menu-delivery/N02/task-entry-ui.json'),records=[],sockets=[];
let stage='START';
function save(status){fs.mkdirSync(path.dirname(output),{recursive:true});fs.writeFileSync(output,JSON.stringify({status,scope:'N02_F06_ACTUAL_TASK_ENTRY',application_directory:directory,ports,proxy_port:proxyPort,manifest_sha256:createHash('sha256').update(fs.readFileSync(path.join(frontend,'asset-manifest.json'))).digest('hex'),external_api_mode:'SIMULATED_FIRST',visual:'NOT_RUN',user_acceptance:'NOT_RUN',records},null,2)+'\n');}
async function main(){let desktop,proxy,page;
  try{
    proxy=spawn(path.join(validation,'.venv/bin/python'),[path.join(__dirname,'menu_n02_native_proxy.py'),String(ports.webui),String(proxyPort)],{cwd:root,env:{...process.env,TMPDIR:path.join(directory,'tmp')},stdio:['ignore',fs.openSync(path.join(directory,'proxy.stdout.log'),'w'),fs.openSync(path.join(directory,'proxy.stderr.log'),'w')]});
    desktop=await electron.launch({args:[__dirname],cwd:validation,timeout:60000,env:{...process.env,BOSS_VALIDATION_ROOT:validation,BOSS_PRODUCT_UI:'1',BOSS_EXECUTION_SCOPE:'BOSS-PRIORITY-ITERATION',BOSS_PRODUCT_FRONTEND_DIR:frontend,BOSS_APPLICATION_WORK_DIR:directory,BOSS_APPLICATION_PORTS:JSON.stringify(ports),BOSS_DESKTOP_TEST_WINDOW_HIDDEN:'1',TMPDIR:path.join(directory,'tmp')}});
    page=await desktop.firstWindow({timeout:120000});await page.waitForURL('http://127.0.0.1:'+ports.webui+'/');
    await desktop.evaluate(async({BrowserWindow},url)=>BrowserWindow.getAllWindows()[0].loadURL(url),origin+'/');await page.waitForURL(origin+'/');
    async function connect(role){
      const identity=await access.bootstrap(origin,accounts,role),socket=new WebSocket(identity.ws_url+'?token='+encodeURIComponent(identity.token)),events=[];sockets.push(socket);
      socket.addEventListener('message',event=>events.push(JSON.parse(event.data)));await once(socket,'open');await expect.poll(()=>events.some(event=>event.event==='ready')).toBe(true);
      return {identity,socket,events,async command(action,payload){const request_id=randomUUID();socket.send(JSON.stringify({type:'webui_request',request_id,action,payload}));await expect.poll(()=>events.some(event=>event.request_id===request_id)).toBe(true);const response=events.find(event=>event.request_id===request_id);assert.equal(response.ok,true,action+': '+JSON.stringify(response.error));return response.result;}};
    }
    const boss=await connect('BOSS'),maintainer=await connect('MAINTAINER');
    async function read(route,connection=boss){const response=await fetch(origin+route,{headers:{Authorization:'Bearer '+connection.identity.api_token}});assert.equal(response.status,200,route);return response.json();}
    async function trace(){return (await fetch(origin+'/_n02/state')).json();}
    async function arm(action){const response=await fetch(origin+'/_n02/drop-response',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action})});assert.equal(response.status,200);}
    async function count(action){return (await trace()).requests.filter(item=>item.action===action).length;}
    const configuration=await read('/api/boss/ui/admin/runtime-configuration',maintainer),values={max_tool_rounds:12,max_output_tokens:700,tool_scope:['bossDashboardRead','bossTasksRead','bossMeetingsRead','bossEvidenceRead','bossWorkspaceRead','conversationRead','query_metrics'],workspace_read_mode:'WORKSPACE_PROJECTIONS',workspace_projections:['notifications','travel','calendar','research']};
    const draft=await maintainer.command('boss.runtime.save',{client_request_id:randomUUID(),expected_version:configuration.draft?.version??'0',values});
    const checked=await maintainer.command('boss.runtime.validate',{client_request_id:randomUUID(),expected_version:draft.version,expected_content_sha256:draft.content_sha256});
    await maintainer.command('boss.runtime.activate',{client_request_id:randomUUID(),expected_version:checked.version,expected_content_sha256:checked.content_sha256,expected_active_version:configuration.current.version});
    const source=await read('/api/boss/ui/evidence?source=finance-note');
    async function create(purpose){return boss.command('boss.assignment.create',{client_request_id:randomUUID(),purpose,coordinator_id:'coordinator-1',due_at:'2026-10-25T17:00:00+08:00',timezone:'Asia/Shanghai',evidence_requirements:[source.source_id],related_meeting_id:'meeting-1',related_event_ids:['event-1'],source_refs:[source.source_id],content_version:'1'});}
    const selected=await create(source.content),other=await create('核查 '+source.source_id+' 的当前版本 '+source.version),before=await read('/api/boss/ui/tasks'),outbox=await read('/api/boss/ui/workspace/outbox');
    assert.equal((await read('/api/sessions')).sessions.length,0);
    await access.login(page,accounts,'BOSS');await page.getByRole('button',{name:'聊天交办',exact:true}).click();await page.getByRole('button',{name:'准备交办',exact:true}).click();await page.waitForURL(/bossPage=F06/);
    await page.locator('.boss-task-row').filter({hasText:source.content}).click();
    let entry=page.getByRole('region',{name:'任务会话入口',exact:true});await expect(entry).toContainText(selected.task_id);await expect(entry.getByRole('button',{name:'新建当前任务会话',exact:true})).toBeEnabled();
    stage='D06_BEFORE_PREPARATION';await page.getByLabel('交办目的',{exact:true}).fill(source.content);
    await entry.getByRole('button',{name:'新建当前任务会话',exact:true}).click();let dialog=page.getByRole('dialog').filter({hasText:'未保存修改（D06）'});await expect(dialog).toBeVisible();assert.equal(await count('boss.conversation.task.prepare'),0);
    await dialog.getByRole('button',{name:'返回继续编辑',exact:true}).click();await expect(page.getByLabel('交办目的',{exact:true})).toHaveValue(source.content);
    await entry.getByRole('button',{name:'新建当前任务会话',exact:true}).click();await expect(dialog).toBeVisible();
    stage='PREPARE_RESPONSE_INTERRUPTION';await arm('boss.conversation.task.prepare');await dialog.getByRole('button',{name:'放弃草稿并离开',exact:true}).click();
    await expect.poll(async()=>(await trace()).dropped?.action).toBe('boss.conversation.task.prepare');const prepareDrop=(await trace()).dropped;assert.equal(prepareDrop.transaction_response_ok,true);
    await expect(entry.getByRole('button',{name:'读取原任务会话记录',exact:true})).toBeEnabled({timeout:40000});assert.equal(await count('boss.conversation.task.prepare'),1);assert.equal(await count('boss.conversation.task.bind'),0);assert.equal((await read('/api/sessions')).sessions.length,0);
    assert.equal(new URL(page.url()).searchParams.get('taskConversationRequest'),prepareDrop.client_request_id);
    await page.reload();entry=page.getByRole('region',{name:'任务会话入口',exact:true});await expect(entry).toContainText('尚未绑定会话');await expect(entry.getByRole('button',{name:'继续原任务会话',exact:true})).toBeEnabled();assert.equal(await count('boss.conversation.task.prepare'),1);
    records.push({check:'f06_actual_selection_d06_and_prepared_response_interruption',task_id:selected.task_id,task_version:selected.version,client_request_id:prepareDrop.client_request_id,preparation_submission_count:1,automatic_chat_count:0,draft_preserved_on_cancel:true,refresh_queried_original_only:true});save('IN_PROGRESS');
    stage='BIND_RESPONSE_INTERRUPTION';await arm('boss.conversation.task.bind');await entry.getByRole('button',{name:'继续原任务会话',exact:true}).click();
    await expect.poll(async()=>(await trace()).dropped?.action).toBe('boss.conversation.task.bind');const bindDrop=(await trace()).dropped;assert.equal(bindDrop.client_request_id,prepareDrop.client_request_id);await expect(entry.getByRole('button',{name:'读取原任务会话记录',exact:true})).toBeEnabled({timeout:40000});
    const pointer=new URL(page.url()).searchParams.get('taskConversationChat');assert(pointer);const original=await read('/api/boss/ui/conversation/task-entry?client_request_id='+prepareDrop.client_request_id);assert.equal(original.entry.binding_state,'BOUND');assert.equal(original.entry.context.chat_id,pointer);assert.equal(original.entry.current_use_verified,false);
    assert.equal((await read('/api/sessions')).sessions.length,1);assert.equal((await read('/api/boss/ui/runtime-records',maintainer)).runs.length,0);
    await page.reload();entry=page.getByRole('region',{name:'任务会话入口',exact:true});await expect(entry).toContainText('已有绑定记录');await expect(entry.getByRole('button',{name:'继续原任务会话',exact:true})).toBeEnabled();await entry.getByRole('button',{name:'继续原任务会话',exact:true}).click();await page.waitForURL(/bossPage=N02/);
    const fixed=page.getByLabel('固定任务上下文',{exact:true});await expect(fixed).toContainText(selected.task_id);await expect(fixed).not.toContainText(other.task_id);assert.equal(await count('boss.conversation.task.prepare'),1);assert.equal(await count('boss.conversation.task.bind'),1);assert.equal((await trace()).messages.length,0);assert.equal((await read('/api/boss/ui/runtime-records',maintainer)).runs.length,0);
    records.push({check:'bound_response_interruption_reload_and_current_read_before_open',chat_id:pointer,preparation_id:original.entry.preparation_id,preparation_sha256:original.entry.preparation_sha256,binding_submission_count:1,automatic_message_count:0,automatic_runtime_count:0,original_binding_reused:true});save('IN_PROGRESS');
    stage='CURRENT_TASK_INPUT';const region=page.getByRole('region',{name:'聊天交办内容',exact:true});await region.getByRole('textbox',{name:/^本次消息/}).fill('查看当前任务');await region.getByRole('button',{name:'提交需求',exact:true}).click();
    await expect.poll(async()=>(await trace()).messages.length).toBe(1);const turn=(await trace()).messages[0];assert.equal(turn.chat_id,pointer);boss.socket.send(JSON.stringify({type:'attach',chat_id:pointer}));
    let receipt;await expect.poll(async()=>{receipt=await boss.command('boss.conversation.request',{chat_id:pointer,turn_id:turn.turn_id});return receipt.request_state;},{timeout:60000}).toBe('SUCCEEDED');
    const runtime=(await read('/api/boss/ui/runtime-records?run_id='+receipt.run_id,maintainer)).runs[0];assert.equal(runtime.conversation_context.task_entry.preparation_sha256,original.entry.preparation_sha256);assert.deepEqual(runtime.conversation_context.task_entry.task_reference,original.entry.task_reference);assert.deepEqual(runtime.conversation_context.task_entry.source_references,original.entry.source_references);
    const actualTask=runtime.tool_results.find(step=>step.tool_id==='conversationRead');assert.equal(actualTask.task_id,selected.task_id);assert.equal(actualTask.task_version,selected.version);assert(!runtime.tool_results.some(step=>step.task_id===other.task_id));
    const sourceButton=region.locator('[data-task-entry-source="'+source.source_id+'"]').getByRole('button',{name:'核查任务来源原文',exact:true});await sourceButton.click();await page.waitForURL(/bossPage=D01/);assert.equal(new URL(page.url()).searchParams.get('bossSource'),source.source_id);await page.getByRole('button',{name:'返回原会话',exact:true}).click();await page.waitForURL(/bossPage=N02/);await expect(sourceButton).toBeFocused();
    await fixed.getByRole('button',{name:'返回关联任务',exact:true}).click();await page.waitForURL(/bossPage=F06/);assert.equal(new URL(page.url()).searchParams.get('bossTask'),selected.task_id);await page.getByRole('button',{name:'返回原会话',exact:true}).click();await page.waitForURL(/bossPage=N02/);await expect(fixed.getByRole('button',{name:'返回关联任务',exact:true})).toBeFocused();
    await page.reload();await expect(page.getByLabel('固定任务上下文',{exact:true})).toContainText(selected.task_id);assert.equal((await read('/api/boss/ui/runtime-records',maintainer)).runs.length,1);
    const after=await read('/api/boss/ui/tasks'),afterOutbox=await read('/api/boss/ui/workspace/outbox');assert.equal(after.tasks.length,before.tasks.length);assert.equal(afterOutbox.sent_messages.length,outbox.sent_messages.length);
    records.push({check:'actual_ui_question_consumes_fixed_task_and_returns_to_formal_task_and_source',chat_id:pointer,run_id:runtime.run_id,task_id:actualTask.task_id,task_version:actualTask.task_version,current_source_reference_count:original.entry.source_references.length,created_additional_task:false,sent_message:false,refresh_preserved_binding:true,source_and_task_return_focus_restored:true});save('IN_PROGRESS');
    stage='LATE_TASK_SELECTION_AND_EDIT';await page.getByLabel('固定任务上下文',{exact:true}).getByRole('button',{name:'返回关联任务',exact:true}).click();await page.waitForURL(/bossPage=F06/);
    async function gate(route,action){const response=await fetch(origin+'/_n02/'+route,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(action?{action}:{})});assert.equal(response.status,200);}
    entry=page.getByRole('region',{name:'任务会话入口',exact:true});await gate('hold-action','boss.conversation.task.prepare');await entry.getByRole('button',{name:'新建当前任务会话',exact:true}).click();
    await expect.poll(async()=>(await trace()).action_held?.action).toBe('boss.conversation.task.prepare');
    await page.locator('.boss-task-row').filter({hasText:'核查 '+source.source_id+' 的当前版本 '+source.version}).click();
    await expect.poll(()=>new URL(page.url()).searchParams.get('bossTask')).toBe(other.task_id);await gate('release-action');
    await expect(entry.locator('[data-task-conversation-original]')).toContainText(selected.task_id);await expect(entry.getByRole('button',{name:'继续原任务会话',exact:true})).toBeDisabled();
    assert.equal((await read('/api/sessions')).sessions.length,1);assert.equal(new URL(page.url()).searchParams.get('bossTask'),other.task_id);
    await entry.getByRole('button',{name:'返回原任务核查',exact:true}).click();await expect(entry.getByRole('button',{name:'继续原任务会话',exact:true})).toBeEnabled();
    await gate('hold-action','boss.conversation.task.bind');await entry.getByRole('button',{name:'继续原任务会话',exact:true}).click();await expect.poll(async()=>(await trace()).action_held?.action).toBe('boss.conversation.task.bind');
    await page.getByLabel('交办目的',{exact:true}).fill(source.content);await gate('release-action');dialog=page.getByRole('dialog').filter({hasText:'未保存修改（D06）'});await expect(dialog).toBeVisible();
    assert.equal(new URL(page.url()).searchParams.get('bossPage'),'F06');await dialog.getByRole('button',{name:'返回继续编辑',exact:true}).click();await expect(page.getByLabel('交办目的',{exact:true})).toHaveValue(source.content);
    const secondChat=new URL(page.url()).searchParams.get('taskConversationChat');assert(secondChat&&secondChat!==pointer);await entry.getByRole('button',{name:'读取原任务会话记录',exact:true}).click();await expect(entry.getByRole('button',{name:'继续原任务会话',exact:true})).toBeEnabled();
    await entry.getByRole('button',{name:'继续原任务会话',exact:true}).click();await expect(dialog).toBeVisible();await dialog.getByRole('button',{name:'放弃草稿并离开',exact:true}).click();await page.waitForURL(/bossPage=N02/);await expect(page.getByLabel('固定任务上下文',{exact:true})).toContainText(selected.task_id);
    assert.equal((await read('/api/sessions')).sessions.length,2);assert.equal((await trace()).messages.length,1);assert.equal((await read('/api/boss/ui/runtime-records',maintainer)).runs.length,1);assert.equal(await count('boss.conversation.task.prepare'),2);assert.equal(await count('boss.conversation.task.bind'),2);
    records.push({check:'actual_late_preparation_preserves_new_task_selection_and_late_binding_preserves_draft',original_task_id:selected.task_id,selected_other_task_id:other.task_id,new_chat_id:secondChat,late_response_replaced_selection:false,late_edit_preserved_on_cancel:true,explicit_discard_opened_original_binding:true,additional_task_created:false,automatic_runtime_count:0});save('IN_PROGRESS');
    stage='INDEPENDENT_CHAT_AND_INVALIDATION';await page.getByRole('button',{name:'新建会话',exact:true}).click();await expect(page.getByLabel('固定任务上下文',{exact:true})).toHaveCount(0);await page.getByRole('button',{name:'历史会话',exact:true}).click();await page.getByRole('combobox',{name:'当前会话',exact:true}).selectOption('websocket:'+pointer);await expect(page.getByLabel('固定任务上下文',{exact:true})).toContainText(selected.task_id);
    const cancelled=await boss.command('boss.assignment.cancel',{client_request_id:randomUUID(),task_id:selected.task_id,task_version:selected.version,reason:'验证本人取消后原会话持续核查固定任务版本'});assert(cancelled);
    await expect(region.getByRole('button',{name:'重新核查任务上下文',exact:true})).toBeVisible();const historical=await read('/api/boss/ui/conversation/task-entry?client_request_id='+prepareDrop.client_request_id);assert.equal(historical.entry.task_reference.version,selected.version);assert.equal(historical.entry.current_use_verified,false);
    await region.getByRole('textbox',{name:/^本次消息/}).fill('查看当前任务');await region.getByRole('button',{name:'提交需求',exact:true}).click();await expect.poll(async()=>(await trace()).messages.length).toBe(2);const failedTurn=(await trace()).messages[1];let failed;await expect.poll(async()=>{failed=await boss.command('boss.conversation.request',{chat_id:pointer,turn_id:failedTurn.turn_id});return failed.request_state;}).toBe('FAILED');assert.equal(failed.run_id,null);assert.equal((await read('/api/boss/ui/runtime-records',maintainer)).runs.length,1);
    const storage=await page.evaluate(()=>JSON.stringify({url:location.href,local:Object.fromEntries(Object.entries(localStorage)),session:Object.fromEntries(Object.entries(sessionStorage))}));assert(!storage.includes(source.content));
    records.push({check:'new_chat_clears_context_and_changed_task_rejects_before_runtime',chat_id:pointer,original_task_version:selected.version,original_receipt_retained:true,independent_chat_inherited_task:false,failed_run_id:null,additional_runtime_count:0,private_body_in_ordinary_storage:false});
    const schema=JSON.parse(execFileSync(path.join(validation,'.venv/bin/python'),[path.join(validation,'check_menu_n02_runtime.py'),directory],{cwd:root,env:{...process.env,PYTHONDONTWRITEBYTECODE:'1',TMPDIR:path.join(directory,'tmp')},encoding:'utf8'}));assert.equal(schema.status,'PASS');records.push({check:'actual_bound_task_runtime_current_strict_schema',...schema});save('PASS');
  }catch(failure){
    if(page&&!page.isClosed()){
      const entry=page.getByRole('region',{name:'任务会话入口',exact:true});
      const context=page.locator('.boss-n02-context');
      records.push({check:'failure_dom_state',url:page.url(),task_entry_count:await entry.count(),task_entry_text:await entry.count()?await entry.textContent():null,context_text:await context.count()?await context.textContent():null});
    }
    throw failure;
  }finally{
    for(const socket of sockets)socket.close();
    if(desktop){await desktop.evaluate(({BrowserWindow})=>{for(const window of BrowserWindow.getAllWindows())window.destroy();});await desktop.close();}
    if(proxy)proxy.kill('SIGTERM');
  }
}
main().then(()=>console.log(JSON.stringify({status:'PASS',report:output})),failure=>{records.push({check:'failure',stage,error_type:failure.name,message:failure.message});save('FAIL');console.error(JSON.stringify({status:'FAIL',report:output,stage,error_type:failure.name,message:failure.message}));process.exitCode=1;});
