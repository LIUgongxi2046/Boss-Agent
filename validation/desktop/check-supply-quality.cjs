const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {execFileSync} = require('node:child_process');
const {createHash, randomUUID} = require('node:crypto');
const {_electron: electron} = require('playwright');
const {expect} = require('@playwright/test');
const accountAccess = require('./account-access.cjs');

const root = path.resolve(__dirname, '../..');
const validation = path.join(root, 'validation');
const runId = 'supply-quality-' + randomUUID();
const directory = path.join(validation, '.work', runId);
const accounts = accountAccess.provision(directory);
const output = path.join(root, 'evidence/T11/w3-local-20261023', runId + '.json');
const ports = process.env.BOSS_APPLICATION_PORTS ? JSON.parse(process.env.BOSS_APPLICATION_PORTS) : {business:8971, webui:8972, gateway:18971};
const origin = 'http://127.0.0.1:'+ports.webui;
const frontend = process.env.BOSS_PRODUCT_FRONTEND_DIR === undefined ? path.join(root,'.work/product/nanobot/nanobot/web/dist') : process.env.BOSS_PRODUCT_FRONTEND_DIR;
const digest = value => createHash('sha256').update(value).digest('hex');
const records = [], frames = [], sockets = [], errors = [];
const inputs = ['validation/boss_page_api.py','validation/boss_command_api.py','validation/boss_workspace_api.py',
  'validation/boss_supply_quality.py','validation/boss_supply_quality_views.py','validation/boss_source_access.py',
  'validation/check_supply_quality_state.py','app/webui/BossSupplyQualityView.tsx','app/webui/BossSupplyQualityPanel.tsx',
  'app/webui/MaintainerSupplyQuality.tsx','app/webui/BossDesktop.tsx','specs/openapi.yaml',
  'specs/simulated-supply-quality.schema.json','specs/supply-quality-results.schema.json',
  'validation/desktop/check-supply-quality.cjs','validation/product_fc01.py','app/webui/boss-v6.css',path.relative(root,path.join(frontend,'asset-manifest.json'))]
  .map(file=>({path:file,sha256:digest(fs.readFileSync(path.join(root,file)))}));
function save(status){fs.writeFileSync(output,JSON.stringify({status,run_id:runId,at:new Date().toISOString(),
  application_directory:path.relative(root,directory),frontend_directory:frontend,inputs,ports,records,external_api_mode:'SIMULATED_FIRST',
  model_requested:false,external_delivery_requested:false,visual_acceptance:'NOT_RUN',full_A11_A21_A23_accepted:false},null,2));}
function note(check,values){records.push({check,...values});save('IN_PROGRESS');}
function state(){return JSON.parse(execFileSync(path.join(validation,'.venv/bin/python'),[
  'validation/check_supply_quality_state.py','--application-directory',directory],{cwd:root,encoding:'utf8'}));}
async function main(){
  let desktop=null,page,paused=null;
  async function start(){
    desktop=await electron.launch({args:[__dirname],cwd:validation,timeout:60000,
      env:{...process.env,BOSS_VALIDATION_ROOT:validation,BOSS_PRODUCT_UI:'1',BOSS_APPLICATION_WORK_DIR:directory,
        BOSS_APPLICATION_PORTS:JSON.stringify(ports),BOSS_DESKTOP_TEST_WINDOW_HIDDEN:'1',TMPDIR:path.join(validation,'.work/tmp')}});
    page=await desktop.firstWindow({timeout:120000});
    page.on('pageerror',error=>errors.push({name:error.name}));
    page.on('websocket',socket=>socket.on('framesent',event=>{
      const frame=JSON.parse(String(event.payload));if(frame.type==='webui_request')frames.push(frame);
    }));
    await page.waitForURL(origin+'/');
  }
  async function stop(){for(const socket of sockets.splice(0))socket.close();if(desktop){await desktop.close();desktop=null;}}
  async function navigate(id){
    await page.locator('button.boss-search').click();
    const dialog=page.getByRole('dialog',{name:'全部页面导航',exact:true});
    await dialog.getByPlaceholder('搜索页面编号或名称',{exact:true}).fill(id);
    await dialog.getByRole('button',{name:new RegExp('^'+id+' · ')}).click();
  }
  async function rpc(role){
    const auth=await accountAccess.bootstrap(origin,accounts,role);
    const socket=new WebSocket(origin.replace('http:','ws:')+auth.ws_path+'?token='+encodeURIComponent(auth.token));sockets.push(socket);
    await new Promise(resolve=>socket.addEventListener('message',event=>{if(JSON.parse(event.data).event==='ready')resolve();}));
    return {token:auth.api_token,async command(action,payload){
      const id=randomUUID();
      const result=new Promise(resolve=>{const listener=event=>{const frame=JSON.parse(event.data);if(frame.request_id===id){socket.removeEventListener('message',listener);resolve(frame);}};socket.addEventListener('message',listener);});
      socket.send(JSON.stringify({type:'webui_request',request_id:id,action,payload}));return result;
    }};
  }
  async function read(token,route,status=200){
    const response=await fetch(origin+'/api/boss/ui/'+route,{headers:token?{Authorization:'Bearer '+token}:{}});
    assert.equal(response.status,status);return status===200?response.json():null;
  }
  function commandFrame(action){const frame=frames.filter(frame=>frame.action===action).at(-1);assert.ok(frame);return frame;}
  const importAction='boss.simulation.supply_quality.import',coordinate='boss.supply_quality.coordinate';
  try{
    await start();
    await accountAccess.login(page,accounts,'MAINTAINER');await navigate('A03');
    const panel=page.getByRole('region',{name:'采购与品质模拟资料维护',exact:true});
    await panel.waitFor();assert.equal(frames.filter(frame=>frame.action===importAction).length,0);
    const before=state();assert.equal(before.task_count,0);
    let initial;
    for(const [choice,outcome,status] of [['empty_request','EMPTY',200],['failed_request','FAILED',502],['timeout_request','TIMED_OUT',504],['initial_request','SUCCESS',200]]){
      await panel.getByLabel('输入种类',{exact:true}).selectOption(choice);
      await panel.getByRole('button',{name:'载入待检查输入',exact:true}).click();
      const payload=JSON.parse(await panel.getByLabel('完整输入JSON',{exact:true}).inputValue());
      if(choice==='initial_request')initial=payload;
      await expect(panel.getByRole('button',{name:'确认保存模拟资料操作',exact:true})).toBeDisabled();
      await panel.getByRole('checkbox',{name:'确认当前输入及模拟状态，仅保存当前资料操作',exact:true}).check();
      await panel.getByRole('button',{name:'确认保存模拟资料操作',exact:true}).click();
      await panel.getByText('已保存的原请求状态：'+outcome,{exact:true}).waitFor();
      const maint=await rpc('MAINTAINER');
      const receipt=await read(maint.token,'supply-quality-receipt?'+new URLSearchParams({action:importAction,client_request_id:payload.client_request_id}));
      assert.equal(receipt.outcome,'RECORDED');assert.equal(receipt.result.state,outcome);
      const replay=await maint.command(importAction,payload);assert.equal(replay.ok,status===200);
      if(status!==200)assert.equal(replay.error.status,status);
      note('public_gui_explicit_simulated_import',{outcome,http_status:status,client_request_id:payload.client_request_id,record_count:receipt.result.record_count,receipt_sha256:digest(JSON.stringify(receipt)),same_request_replay:true});
    }
    assert.equal(state().task_count,0);
    await panel.getByRole('button',{name:'载入待检查输入',exact:true}).click();
    await navigate('A02');
    await page.getByRole('dialog',{name:'未保存修改（D06）',exact:true}).getByRole('button',{name:'返回继续编辑',exact:true}).click();
    await expect(panel.getByLabel('完整输入JSON',{exact:true})).not.toHaveValue('');
    await navigate('A02');await page.getByRole('button',{name:'放弃草稿并离开',exact:true}).click();await navigate('A03');
    await expect(panel.getByLabel('完整输入JSON',{exact:true})).toHaveValue('');
    await accountAccess.logout(page);await accountAccess.login(page,accounts,'BOSS');
    let boss=await rpc('BOSS');
    const supply=await read(boss.token,'supply-quality?interface_id=SI09');
    assert.equal(supply.supply[0].available_quantity,'20');assert.equal(supply.supply[0].coverage_days,'10');
    assert.equal(supply.supply[0].actual_cost_change,null);assert.equal(supply.supply[0].hypothetical_plan_quote_difference,'2000');
    const quality=await read(boss.token,'supply-quality?interface_id=SI10');assert.equal(quality.trace.processing_totals.length,1);
    assert.equal(quality.trace.processing_totals[0].loss_quantity,'0.5');
    await navigate('F14');await page.getByRole('heading',{name:'原料与库存协调',exact:true}).waitFor();
    await expect(page.getByText('20 tonne',{exact:true}).first()).toBeVisible();
    const filters=page.getByRole('region',{name:'采购品质资料范围查询',exact:true});
    await filters.getByLabel('原料编号',{exact:true}).fill('sim-material-1');
    const filteredResponse=page.waitForResponse(response=>new URL(response.url()).pathname==='/api/boss/ui/simulation-query');
    await filters.getByLabel('原料编号',{exact:true}).press('Enter');
    const filtered=await filteredResponse;assert.equal(filtered.status(),200);
    const filteredBody=await filtered.json();assert.ok(filteredBody.records.length>0);
    const filteredRegion=filters.getByRole('region',{name:'当前筛选结果',exact:true});
    await expect(filteredRegion.locator('details')).toHaveCount(filteredBody.records.length);
    await filters.getByLabel('原料编号',{exact:true}).fill('sim-unknown-material');
    await expect(filteredRegion).toHaveCount(0);
    await filters.getByRole('button',{name:'查询当前范围资料',exact:true}).click();
    await expect(filters.getByRole('region',{name:'当前筛选结果',exact:true}).locator('details')).toHaveCount(0);
    await filters.getByLabel('期间开始',{exact:true}).fill('2026-10-01');
    await filters.getByRole('button',{name:'查询当前范围资料',exact:true}).click();
    await expect(filters.getByRole('alert')).toHaveText('期间需要完整起止日期。');
    note('public_supply_filters',{interface_id:'SI09',matched_count:filteredBody.records.length,unknown_material_empty:true,incomplete_period_rejected:true,keyboard_submit:true});
    const stockDetail=page.getByRole('region',{name:'业务原始记录',exact:true}).locator('details').filter({has:page.locator('summary').filter({hasText:'sim-stock-available-1'})});
    await stockDetail.locator('summary').click();
    const evidenceResponse=page.waitForResponse(response=>new URL(response.url()).pathname==='/api/boss/ui/evidence'&&new URL(response.url()).searchParams.get('source')==='sim-business:inventory_lot:sim-stock-available-1');
    await stockDetail.getByRole('button',{name:'打开当前原始记录',exact:true}).click();
    const evidence=await evidenceResponse;assert.equal(evidence.status(),200);assert.equal(new URL(page.url()).searchParams.get('bossPage'),'D01');
    note('public_gui_current_source_viewer',{source_id:'sim-business:inventory_lot:sim-stock-available-1',http_status:200,body_sha256:digest(JSON.stringify(await evidence.json()))});
    await navigate('F14');await page.getByRole('heading',{name:'原料与库存协调',exact:true}).waitFor();
    await page.getByLabel('协调目的',{exact:true}).fill('当前模拟采购库存来源核查');
    await navigate('F21');await page.getByRole('button',{name:'返回继续编辑',exact:true}).click();
    await expect(page.getByLabel('协调目的',{exact:true})).toHaveValue('当前模拟采购库存来源核查');
    await navigate('F21');await page.getByRole('button',{name:'放弃草稿并离开',exact:true}).click();
    await page.getByRole('heading',{name:'批次追溯与品质核查',exact:true}).waitFor();
    await page.getByLabel('协调依据',{exact:true}).selectOption('production_event:sim-production-event-1');
    await page.getByLabel('协调目的',{exact:true}).fill('汇总当前SIMULATED批次核查资料');
    await page.getByLabel('截止时间（Asia/Shanghai）',{exact:true}).fill('2026-10-24T17:00');
    await page.getByLabel('证据要求（每行一项，最多八项）',{exact:true}).fill('当前模拟资料与待核查清单');
    await page.getByRole('checkbox',{name:'本人确认当前依据、负责人、期限与证据要求',exact:true}).check();
    paused=JSON.parse(fs.readFileSync(path.join(directory,'instance.json'),'utf8')).pid;assert.ok(Number.isInteger(paused));process.kill(paused,'SIGSTOP');
    await page.getByRole('button',{name:'本人确认创建协调任务',exact:true}).click();
    await expect.poll(()=>frames.filter(frame=>frame.action===coordinate).length).toBe(1);
    const pending=commandFrame(coordinate).payload;
    await navigate('F14');await page.getByRole('button',{name:'放弃草稿并离开',exact:true}).click();
    await navigate('F21');await page.getByText(new RegExp('请求编号：'+pending.client_request_id)).waitFor();
    process.kill(paused,'SIGCONT');paused=null;
    await expect.poll(async()=>state().task_count).toBe(1);
    await page.getByRole('button',{name:'重新读取当前资料',exact:true}).click();
    const afterCreate=await read(boss.token,'supply-quality?interface_id=SI10');
    assert.equal(afterCreate.coordination_links.length,1);const taskId=afterCreate.coordination_links[0].task_id;
    await expect.poll(async()=>await page.getByRole('button',{name:'查看交办列表',exact:true}).count()).toBe(1);
    if(await page.getByRole('button',{name:'核查原请求回执',exact:true}).count())await page.getByRole('button',{name:'核查原请求回执',exact:true}).click();
    await page.getByRole('button',{name:'查看交办列表',exact:true}).click();
    assert.equal(new URL(page.url()).searchParams.get('bossTask'),taskId);
    await page.getByRole('heading',{name:'交办详情与模拟发送',exact:true}).waitFor();
    const task=(await read(boss.token,'tasks')).tasks.find(task=>task.task_id===taskId);assert.equal(task.status,'OPEN');
    const sent=await boss.command('boss.assignment.send',{client_request_id:'supply-send-'+randomUUID(),task_id:taskId,task_version:task.version,recipient_id:'coordinator-1',body:'请汇总当前模拟来源与待核查清单。',content_version:'1'});assert.equal(sent.ok,true);
    const maint=await rpc('MAINTAINER');
    const feedback=await maint.command('boss.simulation.feedback',{client_request_id:'supply-feedback-'+randomUUID(),task_id:taskId,task_version:sent.result.task_version,author_contact_id:'coordinator-1',kind:'RESULT_SUBMITTED',content:'已汇总模拟资料，专业事项继续待核查。',evidence_refs:task.source_refs});assert.equal(feedback.ok,true);
    const completed=await boss.command('boss.assignment.complete',{client_request_id:'supply-complete-'+randomUUID(),task_id:taskId,task_version:feedback.result.task.version,feedback_id:feedback.result.feedback_id});assert.equal(completed.ok,true);assert.equal(completed.result.status,'COMPLETED_CONFIRMED');
    note('public_gui_coordination_original_request_and_actual_task_lifecycle',{task_id:taskId,client_request_id:pending.client_request_id,unknown_request_retained_across_pages:true,task_selected_by_navigation:true,final_task_state:completed.result.status,external_delivery:false});
    await navigate('F21');await page.getByRole('heading',{name:'批次追溯与品质核查',exact:true}).waitFor();
    for(const [width,height] of [[1024,768],[1280,800],[1440,1024]])for(const zoom of [1,2]){
      await desktop.evaluate(({BrowserWindow},{width,height,zoom})=>{const window=BrowserWindow.getAllWindows()[0];window.setContentSize(width,height);window.webContents.setZoomFactor(zoom);},{width,height,zoom});
      await expect.poll(()=>page.evaluate(()=>window.innerWidth)).toBe(Math.round(width/zoom));
      const dimensions=await page.locator('.boss-v6').evaluate(element=>({width:document.documentElement.clientWidth,scroll:document.documentElement.scrollWidth,role:element.dataset.role}));
      note('public_supply_dom_bounds',{native_width:width,native_height:height,zoom,...dimensions});
      if(dimensions.scroll>dimensions.width+1)note('overflow_elements',{elements:await page.locator('.boss-v6 *').evaluateAll(elements=>elements.filter(element=>element.getClientRects().length&&element.getBoundingClientRect().right>document.documentElement.clientWidth+1).slice(0,20).map(element=>({tag:element.tagName,class:element.className,width:element.getBoundingClientRect().width,right:element.getBoundingClientRect().right,whiteSpace:getComputedStyle(element).whiteSpace,overflowX:getComputedStyle(element).overflowX})))});
      assert.ok(dimensions.scroll<=dimensions.width+1);
      await navigate('F14');await page.getByRole('heading',{name:'原料与库存协调',exact:true}).waitFor();
      await navigate('F21');await page.getByRole('heading',{name:'批次追溯与品质核查',exact:true}).waitFor();
    }
    await page.context().setOffline(true);await page.getByRole('button',{name:'重新读取当前资料',exact:true}).click();
    await page.getByRole('alert').filter({hasText:'Failed to fetch'}).waitFor();assert.equal(await page.getByRole('region',{name:'业务原始记录'}).count(),0);
    await page.context().setOffline(false);await page.getByRole('button',{name:'重新读取当前资料',exact:true}).click();await page.getByRole('region',{name:'业务原始记录'}).waitFor();
    assert.equal((await boss.command(importAction,initial)).error.status,403);
    await read(maint.token,'supply-quality?interface_id=SI09',403);await read(null,'supply-quality?interface_id=SI09',401);
    await read(boss.token,'supply-quality?interface_id=SI09&namespace=ui-check',400);
    const originalState=state();assert.equal(originalState.production_events[0].state,'PROFESSIONAL_REVIEW_PENDING');assert.equal(originalState.inventory.find(row=>row.id==='sim-stock-finished-1').quality_state,'HOLD');assert.equal(originalState.counts.runtime_run,0);
    await stop();await start();await accountAccess.login(page,accounts,'BOSS');boss=await rpc('BOSS');
    assert.deepEqual(state(),originalState);
    const restarted=await read(boss.token,'supply-quality?interface_id=SI10');assert.equal(restarted.coordination_links[0].task_id,taskId);
    await navigate('F21');await page.getByRole('heading',{name:'批次追溯与品质核查',exact:true}).waitFor();
    note('actual_restart_preserves_business_and_professional_states',{state:originalState,source_type:'SIMULATED',external_service_invoked:false});
    const currentMaint=await rpc('MAINTAINER');
    const professional=initial.records.find(row=>row.entity_type==='professional_record');
    const change={...initial,client_request_id:'supply-current-source-'+randomUUID(),records:[{...professional,expected_version:'1',data:{...professional.data,state:'PROFESSIONALLY_CONFIRMED',conclusion:'PASS_REPORTED'}}]};
    assert.equal((await currentMaint.command(importAction,change)).ok,true);
    const source='sim-business:production_event:sim-production-event-1';
    await read(boss.token,'evidence?'+new URLSearchParams({source}),409);
    const knowledge=await read(boss.token,'workspace/knowledge?q=SIMULATED');assert.ok(knowledge.results.every(row=>row.source_id!==source));
    await accountAccess.logout(page);await accountAccess.login(page,accounts,'MAINTAINER');await navigate('A03');
    const withdrawalPanel=page.getByRole('region',{name:'采购与品质模拟资料维护',exact:true});
    await withdrawalPanel.getByLabel('输入种类',{exact:true}).selectOption('withdraw');await withdrawalPanel.getByRole('button',{name:'载入待检查输入',exact:true}).click();
    const withdrawal={client_request_id:'supply-withdraw-'+randomUUID(),entity_type:'inventory_lot',record_id:'sim-stock-available-1',expected_version:'1',reason:'SIMULATED来源撤销检查'};
    await withdrawalPanel.getByLabel('完整输入JSON',{exact:true}).fill(JSON.stringify(withdrawal,null,2));
    await withdrawalPanel.getByRole('checkbox',{name:'确认当前输入及模拟状态，仅保存当前资料操作',exact:true}).check();await withdrawalPanel.getByRole('button',{name:'确认保存模拟资料操作',exact:true}).click();
    await withdrawalPanel.getByText('已保存的原请求状态：WITHDRAWN',{exact:true}).waitFor();
    const withdrawalAuth=await rpc('MAINTAINER');const withdrawalReceipt=await read(withdrawalAuth.token,'supply-quality-receipt?'+new URLSearchParams({action:'boss.simulation.supply_quality.withdraw',client_request_id:withdrawal.client_request_id}));
    assert.equal(withdrawalReceipt.result.record_state,'WITHDRAWN');
    await accountAccess.logout(page);await accountAccess.login(page,accounts,'BOSS');boss=await rpc('BOSS');
    await read(boss.token,'evidence?'+new URLSearchParams({source:withdrawalReceipt.result.source_id}),410);
    const afterWithdraw=await read(boss.token,'supply-quality?interface_id=SI09');assert.ok(afterWithdraw.source_statuses.some(row=>row.record_id==='inventory_lot:sim-stock-available-1'&&row.data===null&&row.source_refs.some(reference=>reference.status==='WITHDRAWN')));
    note('public_current_dependency_and_gui_withdrawal',{dependency_changed_source:source,body_http_status:409,withdrawn_source:withdrawalReceipt.result.source_id,withdrawn_body_http_status:410,current_body_reused:false,withdrawal_via_authenticated_gui:true});
    await accountAccess.logout(page);await read(boss.token,'supply-quality?interface_id=SI10',401);
    assert.deepEqual(errors,[]);assert.equal(frames.filter(frame=>frame.action===coordinate).length,1);
    note('public_roles_logout_and_renderer',{renderer_errors:errors.length,coordination_request_count:1,model_requests:0,final_state:state()});
    save('PASS_PUBLIC_SIMULATED_SUPPLY_QUALITY_COORDINATION_RECEIPTS_SOURCE_ADOPTION_AND_RESTART');
  }finally{if(paused)process.kill(paused,'SIGCONT');await stop();}
}
main().then(()=>console.log(JSON.stringify({status:'PASS',report:path.relative(root,output)})),error=>{
  records.push({check:'failure',name:error.name,message:String(error.message).slice(0,1400)});save('FAIL');console.error(JSON.stringify({status:'FAIL',report:path.relative(root,output)}));process.exitCode=1;
});
