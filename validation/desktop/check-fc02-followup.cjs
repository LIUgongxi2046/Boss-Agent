const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {execFileSync}=require('node:child_process');
const {once}=require('node:events');
const {randomUUID,createHash}=require('node:crypto');
const {_electron:electron}=require('playwright');
const {expect:baseExpect}=require('@playwright/test');
const expect=baseExpect.configure({timeout:20000});
const access=require('./account-access.cjs');
const root=path.resolve(__dirname,'../..'),validation=path.join(root,'validation'),frontend=process.env.BOSS_PRODUCT_FRONTEND_DIR;
assert(frontend&&path.isAbsolute(frontend));
const runId='fc02-followup-'+randomUUID(),directory=path.join(validation,'.work',runId),accounts=access.provision(directory);
const ports={business:9921,webui:9922,gateway:19921},origin='http://127.0.0.1:'+ports.webui;
const output=path.join(root,'evidence/feature-delivery/FC02',runId+'.json'),records=[];
const hash=file=>createHash('sha256').update(fs.readFileSync(file)).digest('hex');
const prior=JSON.parse(fs.readFileSync(path.join(root,'docs/feature-delivery/FC02/candidate.json')));
assert.equal(hash(path.join(frontend,'asset-manifest.json')),prior.manifest_sha256);
assert.equal(hash(path.join(frontend,'index.html')),prior.index_sha256);
for(const [file,digest] of Object.entries(prior.source_sha256))assert.equal(hash(path.join(root,file)),digest);
assert.equal(hash(path.join(root,prior.native_client.path)),prior.native_client.sha256);
function save(status){fs.writeFileSync(output,JSON.stringify({status,run_id:runId,defect_id:'FC02-N4-DOMAIN-FOLLOWUP-01',ports,application_directory:directory,
  frontend_directory:frontend,manifest_sha256:prior.manifest_sha256,index_sha256:prior.index_sha256,native_client_sha256:prior.native_client.sha256,
  external_api_mode:'SIMULATED_FIRST',visual:'NOT_RUN',rebuild_required:false,records},null,2));}
function inspect(action='inspect'){return JSON.parse(execFileSync(path.join(validation,'.venv/bin/python'),[path.join(validation,'fc02_followup_check.py'),directory,action],
  {cwd:root,env:{...process.env,PYTHONDONTWRITEBYTECODE:'1',TMPDIR:path.join(validation,'.work/tmp')},encoding:'utf8',timeout:30000}));}
async function launch(){const desktop=await electron.launch({args:[__dirname],cwd:validation,timeout:60000,env:{...process.env,PYTHONDONTWRITEBYTECODE:'1',
  BOSS_VALIDATION_ROOT:validation,BOSS_PRODUCT_UI:'1',BOSS_APPLICATION_WORK_DIR:directory,BOSS_APPLICATION_PORTS:JSON.stringify(ports),BOSS_DESKTOP_TEST_WINDOW_HIDDEN:'1',TMPDIR:path.join(validation,'.work/tmp')}});
  let ready=false;
  try{const page=await desktop.firstWindow({timeout:120000});await page.waitForURL(origin+'/');ready=true;return {desktop,page};}
  finally{if(!ready)await desktop.close();}}
async function main(){let desktop,page,socket;const errors=[];
  try{
    ({desktop,page}=await launch());page.on('pageerror',failure=>errors.push(failure.name));
    await access.login(page,accounts,'MAINTAINER');await page.goto(origin+'/?bossPage=A04');
    const panel=page.getByRole('region',{name:'经营场景维护',exact:true});
    await panel.getByLabel('经营验证场景',{exact:true}).selectOption('weighted-ratios');await panel.getByRole('button',{name:'载入经营场景',exact:true}).click();
    await expect(panel).toContainText('weighted-ratios · 版本 1');
    await access.logout(page);await access.login(page,accounts,'BOSS');await page.goto(origin+'/?bossPage=F03');
    await expect(page.getByRole('button',{name:'提交查询',exact:true})).toBeEnabled();await page.getByRole('button',{name:'提交查询',exact:true}).click();
    await expect(page.locator('.boss-bi-table')).toBeVisible();
    let auth=await access.bootstrap(origin,accounts,'BOSS'),maint=await access.bootstrap(origin,accounts,'MAINTAINER');
    async function read(route,expected=200,identity=auth){const response=await fetch(origin+route,{headers:{Authorization:'Bearer '+identity.api_token}});assert.equal(response.status,expected);return response.json();}
    const receipt=key=>read('/api/boss/ui/bi/receipt?client_request_id='+key);
    const parentKey=new URL(page.url()).searchParams.get('biRequest'),parentReceipt=await receipt(parentKey),parent=parentReceipt.receipt.query.result;
    assert.equal(parentReceipt.request_state,'SUCCEEDED');assert.equal(parent.detail_refs.length,8);
    const initial=inspect();assert(initial.initial_matches_generator);
    let responses;
    async function connect(){responses=new Map();socket=new WebSocket(auth.ws_url+'?token='+encodeURIComponent(auth.token));
      socket.addEventListener('message',event=>{const body=JSON.parse(event.data);if(body.event==='webui_response')responses.set(body.request_id,body);});
      await once(socket,'open');}
    function send(action,payload){const id=randomUUID();socket.send(JSON.stringify({type:'webui_request',request_id:id,action,payload}));return id;}
    async function response(id){await expect.poll(()=>responses.has(id)).toBe(true);return responses.get(id);}
    await connect();
    const childKey='n3-cross-scene-'+randomUUID(),overrides={scenario_id:'weighted-ratios',source_ids:['sim-bi:weighted-ratios:SIMULATED_BOUNDARY'],business_basis:'SIMULATED_BOUNDARY'};
    const payload={client_request_id:childKey,parent_query_id:parent.query_id,question:'按明确正式场景继续查询',overrides};
    const envelope=await response(send('boss.bi.follow_up',payload));assert.equal(envelope.ok,true);assert.equal(envelope.result.request_state,'SUCCEEDED');
    const childReceipt=envelope.result,child=childReceipt.receipt.query.result;
    assert.notEqual(child.query_id,parent.query_id);assert.equal(child.parent_query_id,parent.query_id);
    assert.deepEqual(child.overridden_fields,['business_basis','scenario_id','source_ids']);
    for(const field of ['period_start','period_end','comparison_start','comparison_end','product_ids','metric_ids','region_id','legal_entity_id'])assert.deepEqual(child.context_snapshot[field],parent.context_snapshot[field]);
    assert.equal(Number(child.values.find(row=>row.metric_id==='gross_margin'&&row.period_scope==='CURRENT').value),14);
    assert.equal(child.detail_refs.length,4);assert.deepEqual(child.context_snapshot.source_ids,overrides.source_ids);
    const parentRead=await read('/api/boss/ui/bi/query?query_id='+parent.query_id);assert.equal(parentRead.adoption_state,'CURRENT');assert.deepEqual(parentRead.result,parent);
    const evidence=await read('/api/boss/ui/metrics-evidence?query_id='+child.query_id);
    assert.equal(evidence.query_id,child.query_id);
    const documents=evidence.result.original_records.filter(row=>overrides.source_ids.includes(row.record_id));assert.equal(documents.length,1);
    assert.equal(documents[0].content.author_kind,'SIMULATED_GENERATOR');assert.equal(documents[0].content.business_basis,'SIMULATED_BOUNDARY');
    for(const row of evidence.result.original_records.filter(row=>child.detail_refs.includes(row.record_id)))assert.equal(row.content.source_id,overrides.source_ids[0]);
    const runtime=(await read('/api/boss/ui/runtime-records?run_id='+childReceipt.run_id,200,maint)).runs[0];
    assert.equal(runtime.status,'SUCCEEDED');assert.deepEqual(runtime.tool_configuration.map(item=>item.tool_id).sort(),['query_metrics','read_evidence']);
    assert.deepEqual(runtime.tool_results.map(item=>item.query_id),[child.query_id,child.query_id]);assert.equal(runtime.usage,null);assert.equal(runtime.cost_total,null);
    assert(!JSON.stringify(runtime).includes(payload.question));
    const childAddress=origin+'/?bossPage=F03&biScenario=weighted-ratios&biRequest='+childKey;
    await page.goto(childAddress);await expect(page.locator('.boss-bi-table')).toBeVisible();
    await expect(page.getByLabel('经营资料场景',{exact:true})).toHaveValue('weighted-ratios');await expect(page.getByLabel('资料来源',{exact:true})).toHaveValues(overrides.source_ids);
    const resultPanel=page.locator('section.boss-panel').filter({has:page.getByRole('heading',{name:'经营对比',exact:true})});
    await expect(resultPanel).toContainText(child.query_id);
    await page.getByRole('button',{name:'读取本次查询原始依据',exact:true}).click();
    const evidencePanel=page.locator('section.boss-panel').filter({has:page.getByRole('heading',{name:'本次查询原始依据',exact:true})});
    await expect(evidencePanel.locator('details')).toHaveCount(5);await expect(evidencePanel).toContainText(overrides.source_ids[0]);
    const history=await read('/api/boss/ui/bi/history');assert.equal(history.requests.length,2);
    await page.reload();await expect(resultPanel).toContainText(child.query_id);assert.deepEqual(await read('/api/boss/ui/bi/history'),history);
    records.push({check:'actual_public_default_parent_to_formal_scenario',parent_client_request_id:parentKey,parent_query_id:parent.query_id,client_request_id:childKey,query_id:child.query_id,
      explicit_overrides:overrides,overridden_fields:child.overridden_fields,inherited_periods:Object.fromEntries(['period_start','period_end','comparison_start','comparison_end'].map(field=>[field,child.context_snapshot[field]])),
      gross_margin:'14',source_ids:child.context_snapshot.source_ids,detail_count:child.detail_refs.length,run_id:childReceipt.run_id,parent_adoption_state:parentRead.adoption_state});save('IN_PROGRESS');
    socket.close();socket=null;await desktop.close();desktop=null;
    ({desktop,page}=await launch());page.on('pageerror',failure=>errors.push(failure.name));await access.login(page,accounts,'BOSS');
    auth=await access.bootstrap(origin,accounts,'BOSS');maint=await access.bootstrap(origin,accounts,'MAINTAINER');
    await page.goto(childAddress);await expect(page.locator('.boss-bi-table')).toBeVisible();
    assert.deepEqual((await receipt(childKey)).receipt.query.result,child);assert.deepEqual((await receipt(parentKey)).receipt.query.result,parent);
    assert.deepEqual(await read('/api/boss/ui/bi/history'),history);assert.equal(inspect().counts.query,2);
    await connect();
    const repeated=await response(send('boss.bi.follow_up',payload));assert.equal(repeated.ok,true);assert.equal(repeated.result.receipt.query.result.query_id,child.query_id);
    const conflict=await response(send('boss.bi.follow_up',{...payload,question:'同编号不同内容'}));assert.equal(conflict.ok,false);assert.equal(conflict.error.status,409);
    assert.equal(inspect().counts.query,2);assert.equal(inspect().counts.runtime_run,2);
    records.push({check:'same_store_restart_original_receipt_history_and_idempotence',query_id:child.query_id,parent_query_id:parent.query_id,original_client_request_id:childKey,conflicting_payload_status:409,counts:inspect().counts});save('IN_PROGRESS');
    inspect('withdraw-child');
    const failedKey='n3-withdrawn-child-'+randomUUID(),failedTransport=send('boss.bi.follow_up',{...payload,client_request_id:failedKey});
    await expect.poll(async()=>(await receipt(failedKey)).request_state).toBe('FAILED');
    const failed=await receipt(failedKey),failedRun=(await read('/api/boss/ui/runtime-records?run_id='+failed.run_id,200,maint)).runs[0];
    assert.equal(failed.receipt.query,null);assert.equal(failedRun.status,'FAILED');assert.equal(failedRun.tool_errors[0].error_type,'HTTPGone');
    assert.equal(failedRun.tool_errors[0].tool_id,'query_metrics');assert.equal(failedRun.usage,null);assert.equal(failedRun.cost_total,null);
    const observation=inspect();assert.equal(observation.counts.query,2);assert.equal(observation.counts.runtime_run,3);
    assert.equal((await read('/api/boss/ui/bi/query?query_id='+parent.query_id)).adoption_state,'CURRENT');
    const historical=await read('/api/boss/ui/bi/query?historical=true&query_id='+child.query_id);assert.equal(historical.adoption_state,'HISTORICAL_REQUIRES_REQUERY');assert.deepEqual(historical.result,child);
    assert.equal((await receipt(childKey)).receipt.query.adoption_state,'HISTORICAL_REQUIRES_REQUERY');
    await page.goto(origin+'/?bossPage=F03&biScenario=weighted-ratios&biRequest='+failedKey);
    const recoveryPanel=page.locator('section.boss-panel').filter({has:page.getByRole('heading',{name:'原请求与查询恢复',exact:true})});
    await expect(recoveryPanel).toContainText('运行状态 FAILED · 查询回执 NOT_FOUND_IN_CURRENT_STORE');
    assert.deepEqual(inspect().counts,observation.counts);
    records.push({check:'actual_withdrawn_child_failure_and_read_only_receipt',client_request_id:failedKey,request_state:failed.request_state,run_id:failed.run_id,
      tool_errors:failedRun.tool_errors,observed_websocket_response:responses.get(failedTransport)??null,request_replayed:false,counts:observation.counts});save('IN_PROGRESS');
    inspect('withdraw-parent');
    const parentFailedKey='n3-withdrawn-parent-'+randomUUID(),parentFailure=await response(send('boss.bi.follow_up',{...payload,client_request_id:parentFailedKey}));
    assert.equal(parentFailure.ok,false);assert.equal(parentFailure.error.status,410);
    await read('/api/boss/ui/bi/receipt?client_request_id='+parentFailedKey,404);
    const final=inspect();assert.deepEqual(final.counts,observation.counts);assert.equal(final.initial_sha256,initial.initial_sha256);assert(final.initial_matches_generator);
    for(const kind of ['task','authorization','outbox'])assert.equal(final.counts[kind],0);
    assert.deepEqual(errors,[]);
    records.push({check:'actual_withdrawn_parent_rejection_and_unchanged_initial',status:410,client_request_id:parentFailedKey,receipt_status:404,initial_sha256:final.initial_sha256,
      counts:final.counts,runs:final.runs,renderer_errors:errors.length});save('PASS');
  }finally{if(socket)socket.close();if(desktop)await desktop.close();}
}
main().then(()=>console.log(JSON.stringify({status:'PASS',report:output})),failure=>{records.push({check:'failure',name:failure.name,message:String(failure.message).slice(0,1400)});save('FAIL');console.error(JSON.stringify({status:'FAIL',report:output}));process.exitCode=1;});
