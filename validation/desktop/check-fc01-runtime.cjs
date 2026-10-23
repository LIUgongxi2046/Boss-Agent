const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {randomUUID,createHash}=require('node:crypto');
const {_electron:electron}=require('playwright');
const {expect}=require('@playwright/test');
const access=require('./account-access.cjs');
const root=path.resolve(__dirname,'../..');
const runId='fc01-runtime-'+randomUUID();
const directory=path.join(root,'validation/.work',runId);
const accounts=access.provision(directory);
const ports={business:9371,webui:9372,gateway:19371};
const origin='http://127.0.0.1:'+ports.webui;
const frontend=process.env.BOSS_PRODUCT_FRONTEND_DIR;
assert(frontend&&path.isAbsolute(frontend));
const report=path.join(root,'evidence/T11/w3-local-20261023',runId+'.json');
const checks=[],sockets=[];
const hash=file=>createHash('sha256').update(fs.readFileSync(file)).digest('hex');
function save(status){fs.writeFileSync(report,JSON.stringify({status,run_id:runId,ports,application_directory:directory,
  frontend_directory:frontend,build_manifest_sha256:hash(path.join(frontend,'asset-manifest.json')),
  inputs:['validation/product_fc01.py','validation/application.py','validation/role_channel.py','specs/runtime-records.schema.json','app/webui/BossSupplyQualityPanel.tsx','app/webui/boss-v6.css'].map(file=>({path:file,sha256:hash(path.join(root,file))})),
  external_api_mode:'SIMULATED_FIRST',external_model_requested:false,visual:'NOT_RUN',checks},null,2));}
async function main(){
  let desktop;
  try{
    desktop=await electron.launch({args:[__dirname],cwd:path.join(root,'validation'),timeout:60000,env:{...process.env,
      BOSS_VALIDATION_ROOT:path.join(root,'validation'),BOSS_PRODUCT_UI:'1',BOSS_APPLICATION_WORK_DIR:directory,
      BOSS_APPLICATION_PORTS:JSON.stringify(ports),BOSS_DESKTOP_TEST_WINDOW_HIDDEN:'1',TMPDIR:path.join(root,'validation/.work/tmp')}});
    const page=await desktop.firstWindow({timeout:120000});await page.waitForURL(origin+'/');
    const errors=[];page.on('pageerror',error=>errors.push(error.name));
    async function navigate(id){await page.locator('button.boss-search').click();const dialog=page.getByRole('dialog',{name:'全部页面导航',exact:true});
      await dialog.getByPlaceholder('搜索页面编号或名称',{exact:true}).fill(id);await dialog.getByRole('button',{name:new RegExp('^'+id+' · ')}).click();}
    async function rpc(role){const auth=await access.bootstrap(origin,accounts,role);
      const socket=new WebSocket(origin.replace('http:','ws:')+auth.ws_path+'?token='+encodeURIComponent(auth.token));sockets.push(socket);
      await new Promise(resolve=>socket.addEventListener('message',event=>{if(JSON.parse(event.data).event==='ready')resolve();}));
      return {token:auth.api_token,async command(action,payload){const id=randomUUID();const response=new Promise(resolve=>{const listener=event=>{const frame=JSON.parse(event.data);if(frame.request_id===id){socket.removeEventListener('message',listener);resolve(frame);}};socket.addEventListener('message',listener);});socket.send(JSON.stringify({type:'webui_request',request_id:id,action,payload}));return response;}};}
    async function read(auth,route){const response=await fetch(origin+'/api/boss/ui/'+route,{headers:{Authorization:'Bearer '+auth.token}});assert.equal(response.status,200);return response.json();}
    await access.login(page,accounts,'MAINTAINER');await navigate('A03');
    const panel=page.getByRole('region',{name:'采购与品质模拟资料维护',exact:true});
    await panel.getByLabel('输入种类',{exact:true}).selectOption('initial_request');await panel.getByRole('button',{name:'载入待检查输入',exact:true}).click();
    await panel.getByRole('checkbox',{name:'确认当前输入及模拟状态，仅保存当前资料操作',exact:true}).check();
    await panel.getByRole('button',{name:'确认保存模拟资料操作',exact:true}).click();await panel.getByText('已保存的原请求状态：SUCCESS',{exact:true}).waitFor();
    const maint=await rpc('MAINTAINER');const state=await read(maint,'admin/runtime-configuration');
    const tools=['query_metrics','read_evidence','create_assignment','send_assignment','read_assignment','bossSupplyQualityRead','bossSupplyQualityQuery','bossSupplyQualityPrepare','bossEvidenceRead'];
    assert(tools.every(name=>state.available_tools.includes(name)));
    const saved=await maint.command('boss.runtime.save',{client_request_id:'fc01-runtime-save',expected_version:'0',values:{max_tool_rounds:6,max_output_tokens:700,tool_scope:tools}});assert(saved.ok,JSON.stringify(saved));
    const checked=await maint.command('boss.runtime.validate',{client_request_id:'fc01-runtime-validate',expected_version:saved.result.version,expected_content_sha256:saved.result.content_sha256});assert(checked.ok,JSON.stringify(checked));
    const activated=await maint.command('boss.runtime.activate',{client_request_id:'fc01-runtime-activate',expected_version:checked.result.version,expected_content_sha256:checked.result.content_sha256,expected_active_version:state.current.version});assert(activated.ok,JSON.stringify(activated));
    await access.logout(page);await access.login(page,accounts,'BOSS');await navigate('F21');
    await page.getByLabel('协调依据',{exact:true}).selectOption('production_event:sim-production-event-1');
    await page.getByLabel('协调目的',{exact:true}).fill('汇总当前SIMULATED品质核查资料');
    await page.getByLabel('截止时间（Asia/Shanghai）',{exact:true}).fill('2026-10-25T17:00');
    await page.getByLabel('证据要求（每行一项，最多八项）',{exact:true}).fill('当前专业核查材料');
    await page.getByRole('button',{name:'通过模拟助手准备当前协调材料',exact:true}).click();
    await page.getByText('当前模拟助手已读取实际来源并准备材料，请本人核查当前内容后决定。',{exact:true}).waitFor({timeout:120000});
    await expect(page.getByRole('button',{name:'本人确认创建协调任务',exact:true})).toBeDisabled();
    const boss=await rpc('BOSS');const runs=await read(boss,'runtime-records');
    const run=runs.runs.find(row=>row.feature_id==='FC01');assert(run);assert.equal(run.status,'SUCCEEDED');
    assert.equal(run.source_type,'SIMULATED');assert.equal(run.external_model_invoked,false);assert.equal(run.usage,null);assert.equal(run.cost_total,null);
    assert.deepEqual(run.tool_results.map(row=>row.tool_id),['bossSupplyQualityRead','bossSupplyQualityQuery','bossEvidenceRead','bossSupplyQualityPrepare']);
    assert.equal(run.simulated_model_events.length,5);assert(!JSON.stringify(run).includes('汇总当前SIMULATED品质核查资料'));
    checks.push({check:'runtime_actual_tools_and_private_records',run_id:run.run_id,configuration_version:run.configuration_version,tools:run.tool_results.map(row=>row.tool_id)});save('IN_PROGRESS');
    await navigate('F14');await page.getByRole('button',{name:'返回继续编辑',exact:true}).click();await expect(page.getByLabel('协调目的',{exact:true})).toHaveValue('汇总当前SIMULATED品质核查资料');
    await page.getByRole('checkbox',{name:'本人确认当前依据、负责人、期限与证据要求',exact:true}).check();
    await page.getByRole('button',{name:'本人确认创建协调任务',exact:true}).click();
    await page.getByText('协调任务已经保存，请打开交办查看发送与后续状态。',{exact:true}).waitFor();
    const adopted=await read(boss,'runtime-records?run_id='+encodeURIComponent(run.run_id));
    const link=adopted.runs[0].owner_task_links[0];assert(link.task_id);assert.equal(link.action,'boss.supply_quality.coordinate');
    const quality=await read(boss,'supply-quality?interface_id=SI10');assert(quality.coordination_links.some(row=>row.task_id===link.task_id));
    const maintDenied=await rpc('MAINTAINER');
    const denied=await maintDenied.command('boss.fc01.prepare',{client_request_id:'fc01-maintainer-denied',coordinate_input:{}});assert.equal(denied.ok,false);assert.equal(denied.error.status,403);
    const styles=await page.locator('.boss-v6').evaluate(element=>({font:getComputedStyle(element).fontSize,line:getComputedStyle(element).lineHeight,field:getComputedStyle(document.querySelector('.boss-field')).fontSize}));
    assert.equal(styles.font,'16px');assert.equal(styles.line,'24px');assert.equal(styles.field,'14px');assert.deepEqual(errors,[]);
    checks.push({check:'owner_adoption_same_task_d06_tokens',run_id:run.run_id,task_id:link.task_id,styles,renderer_errors:0});save('PASS');
  }finally{for(const socket of sockets)socket.close();if(desktop)await desktop.close();}
}
main().then(()=>console.log(JSON.stringify({status:'PASS',report})),error=>{checks.push({check:'failure',name:error.name,message:String(error.message).slice(0,1500)});save('FAIL');console.error(JSON.stringify({status:'FAIL',report}));process.exitCode=1;});
