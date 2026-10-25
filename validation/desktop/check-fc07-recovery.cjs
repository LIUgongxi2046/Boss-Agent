const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {execFileSync,spawn}=require('node:child_process');
const {once}=require('node:events');
const {randomUUID}=require('node:crypto');
const {_electron:electron}=require('playwright');
const {expect}=require('@playwright/test');
const access=require('./account-access.cjs');
const root=path.resolve(__dirname,'../..'),validation=path.join(root,'validation');
const frontend=process.env.BOSS_PRODUCT_FRONTEND_DIR;assert(frontend&&path.isAbsolute(frontend));
const id='fc07-recovery-'+randomUUID(),directory=path.join(validation,'.work',id),ports={business:10081,webui:10082,gateway:20081},proxyPort=10083;
const origin='http://127.0.0.1:'+proxyPort,output=path.join(root,'evidence/feature-delivery/FC07',id+'.json'),records=[];
fs.mkdirSync(path.dirname(output),{recursive:true});
function save(status){fs.writeFileSync(output,JSON.stringify({status,run_id:id,frontend_directory:frontend,application_directory:directory,ports,proxy_port:proxyPort,visual:'NOT_RUN',external_api_mode:'SIMULATED_FIRST',user_acceptance:'NOT_RUN',records},null,2)+'\n');}
async function main(){let desktop,proxy;
  try{
    execFileSync(path.join(validation,'.venv/bin/python'),[path.join(root,'scripts/prepare_mvp01.py'),'--directory',directory,'--frontend',frontend,'--ports',JSON.stringify(ports)],{cwd:root,env:{...process.env,TMPDIR:path.join(validation,'.work/tmp')},timeout:120000});
    const accounts=Object.fromEntries(JSON.parse(fs.readFileSync(path.join(directory,'accounts/credentials.json'))).map(row=>[row.role,row]));
    proxy=spawn(path.join(validation,'.venv/bin/python'),[path.join(__dirname,'fc03_morning_proxy.py'),String(ports.webui),String(proxyPort)],{cwd:root,env:{...process.env,TMPDIR:path.join(directory,'tmp')},stdio:['ignore',fs.openSync(path.join(directory,'proxy.stdout.log'),'w'),fs.openSync(path.join(directory,'proxy.stderr.log'),'w')]});
    const environment={...process.env,BOSS_VALIDATION_ROOT:validation,BOSS_PRODUCT_UI:'1',BOSS_PRODUCT_FRONTEND_DIR:frontend,BOSS_APPLICATION_WORK_DIR:directory,BOSS_APPLICATION_PORTS:JSON.stringify(ports),BOSS_DESKTOP_TEST_WINDOW_HIDDEN:'1',TMPDIR:path.join(directory,'tmp')};delete environment.BOSS_EXECUTION_SCOPE;
    desktop=await electron.launch({args:[__dirname],cwd:validation,env:environment,timeout:60000});const page=await desktop.firstWindow({timeout:120000});await page.waitForURL('http://127.0.0.1:'+ports.webui+'/');
    await desktop.evaluate(async({BrowserWindow},url)=>BrowserWindow.getAllWindows()[0].loadURL(url),origin+'/?bossPage=F06');await access.login(page,accounts,'BOSS');
    await page.locator('button.boss-search').click();const navigation=page.getByRole('dialog',{name:'全部页面导航',exact:true});await navigation.getByPlaceholder('搜索页面编号或名称',{exact:true}).fill('F06');await navigation.getByRole('button',{name:/^F06 · /}).click();
    const create=page.locator('.boss-panel').filter({has:page.getByRole('heading',{name:'创建交办',exact:true})});
    await expect(create).toBeVisible();records.push({check:'current_controls',url:page.url(),controls:await create.locator('select,input,textarea').evaluateAll(elements=>elements.map(element=>({tag:element.tagName,label:element.labels?.[0]?.textContent,type:element.getAttribute('type')})))});save('IN_PROGRESS');
    await create.getByRole('combobox',{name:/^唯一负责人/}).selectOption('coordinator-1');await create.getByLabel('期限（Asia/Shanghai）',{exact:true}).fill('2026-10-25T17:00');
    await create.locator('textarea').fill('核查当前采购资料并提供负责人反馈');await create.locator('input.boss-single-input').fill('当前原文与负责人署名反馈');await create.getByRole('button',{name:'核对并创建',exact:true}).click();
    let dialog=page.getByRole('dialog');await dialog.getByRole('checkbox').check();await dialog.getByRole('button',{name:'确认并提交',exact:true}).click();await expect(dialog).toHaveCount(0);
    const detail=page.locator('.boss-panel').filter({has:page.getByRole('heading',{name:'交办详情与模拟发送',exact:true})});await detail.locator('textarea').fill('请核查当前采购原文并提交署名进展');
    const armed=await fetch(origin+'/_morning/arm',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'boss.assignment.send'})});assert.equal(armed.status,200);
    await detail.getByRole('button',{name:'核对并模拟发送',exact:true}).click();dialog=page.getByRole('dialog');await dialog.getByRole('checkbox').check();await dialog.getByRole('button',{name:'确认并提交',exact:true}).click();
    async function state(){return (await fetch(origin+'/_morning/state')).json();}
    await expect.poll(async()=>(await state()).dropped_actions.includes('boss.assignment.send')).toBe(true);
    await expect.poll(async()=>(await state()).connections>1).toBe(true);
    const trace=await state(),forwarded=trace.events.filter(row=>row.event==='actual_request_forwarded'&&row.action==='boss.assignment.send');records.push({check:'actual_send_interrupted',transport:trace.events});save('IN_PROGRESS');
    assert.equal(forwarded.length,1,'连接恢复不得重发本人发送动作');const key=forwarded[0].client_request_id;
    assert.equal(new URL(page.url()).searchParams.get('assignmentRequest'),key,'未知发送须保留原编号以供刷新恢复');
    await page.reload();dialog=page.getByRole('dialog');await expect(dialog).toBeVisible();await expect(dialog.getByRole('button',{name:'确认并提交',exact:true})).toBeDisabled();await page.keyboard.press('Escape');await expect(dialog).toBeVisible();await dialog.getByRole('button',{name:'核查原请求结果',exact:true}).focus();await page.keyboard.press('Tab');await expect(dialog.getByRole('button',{name:'核查原请求结果',exact:true})).toBeFocused();
    await dialog.getByRole('button',{name:'核查原请求结果',exact:true}).click();await expect(dialog).toHaveCount(0);
    const auth=await access.bootstrap(origin,accounts,'BOSS'),response=await fetch(origin+'/api/boss/ui/tasks',{headers:{Authorization:'Bearer '+auth.api_token}});assert.equal(response.status,200);const tasks=await response.json();
    assert.equal(tasks.tasks.length,1);assert.equal(tasks.tasks[0].status,'WAITING_FEEDBACK');assert.equal(tasks.linked_messages.length,1);
    records.push({check:'readonly_recovery_after_reload',client_request_id:key,task_id:tasks.tasks[0].task_id,status:tasks.tasks[0].status,message_count:1});save('IN_PROGRESS');
    async function read(route){const response=await fetch(origin+route,{headers:{Authorization:'Bearer '+auth.api_token}});assert.equal(response.status,200);return response.json();}
    async function rpc(role,action,payload){const identity=await access.bootstrap(origin,accounts,role),socket=new WebSocket(origin.replace('http:','ws:')+identity.ws_path+'?token='+encodeURIComponent(identity.token));try{
      await new Promise((resolve,reject)=>{const timeout=setTimeout(()=>reject(new Error('实际维护连接尚未就绪')),15000);socket.addEventListener('message',event=>{if(JSON.parse(event.data).event==='ready'){clearTimeout(timeout);resolve();}});});
      const requestId=randomUUID(),reply=new Promise((resolve,reject)=>{const timeout=setTimeout(()=>reject(new Error('实际操作尚未取得回执')),30000);socket.addEventListener('message',event=>{const body=JSON.parse(event.data);if(body.request_id===requestId){clearTimeout(timeout);resolve(body);}});});socket.send(JSON.stringify({type:'webui_request',request_id:requestId,action,payload}));const body=await reply;assert.equal(body.ok,true,JSON.stringify({action,error:body.error}));return body.result;
    }finally{socket.close();}}
    async function armAction(action){const response=await fetch(origin+'/_morning/arm',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action})});assert.equal(response.status,200);}
    const supply=await read('/api/boss/ui/supply-quality?interface_id=SI09'),report=supply.supply[0].cost_reports.find(row=>row.cost_type==='INBOUND_RECEIPT'),originRecord=supply.records.find(row=>row.record_id===report.current.report_id);
    assert(originRecord);const coordinateInput={interface_id:'SI09',origin_entity_type:'material_cost_report',origin_record_id:originRecord.record_id,origin_version:originRecord.version,review_sha256:supply.review_sha256,purpose:'核查当前采购报告的来源版本并保存本人确认',coordinator_id:'coordinator-1',due_at:'2026-10-25T17:00:00+08:00',timezone:'Asia/Shanghai',evidence_requirements:['当前成本报告及来源版本']};
    await rpc('BOSS','boss.fc01.prepare',{client_request_id:id+'-source-prepare',coordinate_input:coordinateInput});
    const sourceTask=await rpc('BOSS','boss.fc01.coordinate',{client_request_id:id+'-source-task',preparation_request_id:id+'-source-prepare',coordinate_input:coordinateInput});
    const sourcePayload=JSON.parse(execFileSync(path.join(validation,'.venv/bin/python'),[path.join(validation,'fc01_cost_token_input.py')],{cwd:root,encoding:'utf8',env:{...process.env,PYTHONDONTWRITEBYTECODE:'1'}}));
    sourcePayload.client_request_id=id+'-source-revise';sourcePayload.records=sourcePayload.records.filter(row=>row.data.report_id===originRecord.record_id);assert.equal(sourcePayload.records.length,1);sourcePayload.records[0].expected_version=originRecord.version;
    await rpc('MAINTAINER','boss.simulation.supply_quality.import',sourcePayload);
    await page.goto(origin+'/?bossPage=F06&bossTask='+sourceTask.task_id);const review=page.getByRole('region',{name:'核查交办来源',exact:true});await expect(review.getByText('此前版本 1 · 当前版本 2',{exact:false})).toBeVisible();
    await review.getByLabel('本次核查依据',{exact:true}).fill('本人已经核查同一原文的新版本及当前使用范围');await review.getByRole('checkbox').check();await armAction('boss.assignment.sources.confirm');await review.getByRole('button',{name:'本人确认当前来源',exact:true}).click();
    await expect.poll(async()=>(await state()).dropped_actions.includes('boss.assignment.sources.confirm')).toBe(true);await expect(review.getByRole('button',{name:'查询原请求回执',exact:true})).toBeEnabled();const sourceKey=new URL(page.url()).searchParams.get('sourceReviewRequest');assert(sourceKey);
    await page.reload();await review.getByRole('button',{name:'查询原请求回执',exact:true}).click();await expect(review.getByText('已保存核查依据：本人已经核查同一原文的新版本及当前使用范围',{exact:true})).toBeVisible();
    const sourceResult=await read('/api/boss/ui/assignment-source-review?task_id='+sourceTask.task_id);assert.equal(sourceResult.binding_state,'CURRENT');assert.equal(sourceResult.task.version,'2');assert.equal(sourceResult.history.length,1);
    await page.locator('button.boss-search').click();const taskNavigation=page.getByRole('dialog',{name:'全部页面导航',exact:true});await taskNavigation.getByPlaceholder('搜索页面编号或名称',{exact:true}).fill('N05');await taskNavigation.getByRole('button',{name:/^N05 · /}).click();await page.getByRole('tab',{name:/^本人承诺/}).click();
    const commitment=page.locator('.boss-commitments');await commitment.getByLabel('承诺目标',{exact:true}).fill('本人核查当前来源并保存原编号记录');await commitment.getByLabel('本人原定期限（北京时间）',{exact:true}).fill('2026-10-25T17:00');await commitment.getByLabel('完成核查证据要求',{exact:true}).fill('当前经营原文');await commitment.getByLabel('承诺依据来源 ID',{exact:true}).fill('finance-note');await commitment.getByLabel('承诺依据版本',{exact:true}).fill('1');await commitment.getByRole('button',{name:'读取本人承诺依据',exact:true}).click();await expect(commitment.locator('blockquote')).toBeVisible();await commitment.getByRole('button',{name:'本人核对并创建承诺',exact:true}).click();dialog=page.getByRole('dialog');await dialog.getByRole('checkbox').check();await armAction('boss.commitment.create');await dialog.getByRole('button',{name:'确认并提交',exact:true}).click();
    await expect.poll(async()=>(await state()).dropped_actions.includes('boss.commitment.create')).toBe(true);const commitmentKey=new URL(page.url()).searchParams.get('commitmentRequest');assert(commitmentKey);await page.reload();dialog=page.getByRole('dialog');await expect(dialog.getByRole('button',{name:'确认并提交',exact:true})).toBeDisabled();await dialog.getByRole('button',{name:'核查原请求结果',exact:true}).click();await expect(dialog).toHaveCount(0);
    const final=await read('/api/boss/ui/tasks');assert.equal(final.self_commitments.length,1);assert.equal(final.self_commitments[0].status,'ACTIVE');assert.equal(final.linked_messages.length,1);const transport=await state();for(const originalKey of [key,sourceKey,commitmentKey])assert.equal(transport.events.filter(event=>event.event==='actual_request_forwarded'&&event.client_request_id===originalKey).length,1);
    records.push({check:'source_confirmation_and_commitment_original_receipts',source_task_id:sourceTask.task_id,source_request:sourceKey,source_version:'2',source_history_count:1,commitment_request:commitmentKey,commitment_id:final.self_commitments[0].commitment_id,commitment_count:1,original_approved_source:'finance-note',transport:transport.events});save('PASS');
  }finally{if(desktop)await desktop.close();if(proxy&&proxy.exitCode===null){const ended=once(proxy,'exit');proxy.kill('SIGTERM');await ended;}}
}
main().then(()=>console.log(JSON.stringify({status:'PASS',report:output})),failure=>{records.push({check:'failure',message:failure.message});save('FAIL');console.error(JSON.stringify({status:'FAIL',report:output}));process.exitCode=1;});
