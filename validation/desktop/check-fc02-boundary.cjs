const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {spawn,execFileSync}=require('node:child_process');
const {once}=require('node:events');
const {randomUUID,createHash}=require('node:crypto');
const {_electron:electron}=require('playwright');
const {expect:baseExpect}=require('@playwright/test');
const expect=baseExpect.configure({timeout:20000});
const access=require('./account-access.cjs');
const root=path.resolve(__dirname,'../..'),validation=path.join(root,'validation'),frontend=process.env.BOSS_PRODUCT_FRONTEND_DIR;
assert(frontend&&path.isAbsolute(frontend));
const runId='fc02-boundary-'+randomUUID(),directory=path.join(validation,'.work',runId),accounts=access.provision(directory);
const ports={business:9841,webui:9842,gateway:19841},proxyPort=9843,origin='http://127.0.0.1:'+proxyPort;
const records=[],output=path.join(root,'evidence/feature-delivery/FC02',runId+'.json');
const hash=file=>createHash('sha256').update(fs.readFileSync(file)).digest('hex');
function save(status){fs.writeFileSync(output,JSON.stringify({status,run_id:runId,application_directory:directory,ports,proxy_port:proxyPort,frontend_directory:frontend,
  manifest_sha256:hash(path.join(frontend,'asset-manifest.json')),external_api_mode:'SIMULATED_FIRST',visual:'NOT_RUN',records},null,2));}
async function main(){let desktop,proxy;
  try{
    proxy=spawn(path.join(validation,'.venv/bin/python'),[path.join(__dirname,'fc02_load_proxy.py'),String(ports.webui),String(proxyPort)],
      {cwd:root,env:{...process.env,TMPDIR:path.join(validation,'.work/tmp')},stdio:['ignore',fs.openSync(path.join(directory,'proxy.stdout.log'),'w'),fs.openSync(path.join(directory,'proxy.stderr.log'),'w')]});
    desktop=await electron.launch({args:[__dirname],cwd:validation,timeout:60000,env:{...process.env,BOSS_VALIDATION_ROOT:validation,BOSS_PRODUCT_UI:'1',
      BOSS_APPLICATION_WORK_DIR:directory,BOSS_APPLICATION_PORTS:JSON.stringify(ports),BOSS_DESKTOP_TEST_WINDOW_HIDDEN:'1',TMPDIR:path.join(validation,'.work/tmp')}});
    const page=await desktop.firstWindow({timeout:120000});await page.waitForURL('http://127.0.0.1:'+ports.webui+'/');
    await desktop.evaluate(async({BrowserWindow},address)=>BrowserWindow.getAllWindows()[0].loadURL(address),origin+'/');await page.waitForURL(origin+'/');
    const errors=[];page.on('pageerror',failure=>errors.push(failure.name));
    async function navigate(id){await page.locator('button.boss-search').click();const dialog=page.getByRole('dialog',{name:'全部页面导航',exact:true});
      await dialog.getByPlaceholder('搜索页面编号或名称',{exact:true}).fill(id);await dialog.getByRole('button',{name:new RegExp('^'+id+' · ')}).click();}
    async function get(route,auth){const response=await fetch(origin+route,{headers:{Authorization:'Bearer '+auth.api_token}});assert.equal(response.status,200);return response.json();}
    const proxyState=async()=>{const response=await fetch(origin+'/_bi_load/state');assert.equal(response.status,200);return response.json();};
    await access.login(page,accounts,'MAINTAINER');await navigate('A04');
    const maint=await access.bootstrap(origin,accounts,'MAINTAINER'),catalog=await get('/api/boss/ui/admin/bi-scenarios',maint);
    assert.equal(catalog.generator_version,'FC02-BI-1');assert.equal(Object.keys(catalog.scenarios).length,6);
    const panel=page.getByRole('region',{name:'经营场景维护',exact:true});
    await panel.getByLabel('经营验证场景',{exact:true}).selectOption('weighted-ratios');await panel.getByRole('button',{name:'载入经营场景',exact:true}).click();
    await expect.poll(async()=>(await proxyState()).dropped).toBe(true);await expect.poll(async()=>(await proxyState()).connections).toBeGreaterThanOrEqual(2);
    const originalKey=new URL(page.url()).searchParams.get('biLoadRequest');assert(originalKey);
    await expect(panel.getByRole('button',{name:'读取原载入回执',exact:true})).toBeEnabled();await panel.getByRole('button',{name:'读取原载入回执',exact:true}).click();
    await expect(panel).toContainText('weighted-ratios · 版本 1');
    const receipt=await get('/api/boss/ui/admin/bi-scenario-receipt?client_request_id='+originalKey,maint);assert.equal(receipt.outcome,'RECORDED');assert.equal(receipt.result.version,'1');
    for(const identifier of Object.keys(catalog.scenarios).filter(value=>value!=='weighted-ratios')){
      await panel.getByLabel('经营验证场景',{exact:true}).selectOption(identifier);await panel.getByRole('button',{name:'载入经营场景',exact:true}).click();
      await expect(panel).toContainText(identifier+' · 版本 1');
    }
    const trace=await proxyState();assert.equal(trace.events.filter(event=>event.event==='actual_load_forwarded'&&event.scenario_id==='weighted-ratios').length,1);
    const loaded=await get('/api/boss/ui/admin/bi-scenarios',maint);assert.equal(loaded.loaded_scenarios.length,6);assert(loaded.loaded_scenarios.every(row=>row.version==='1'));
    records.push({check:'authenticated_scenario_load_and_unknown_receipt',scenario_ids:loaded.loaded_scenarios.map(row=>row.scenario_id),original_client_request_id:originalKey,
      recorded_version:receipt.result.version,load_replayed:false,transport_events:trace.events});save('IN_PROGRESS');
    await access.logout(page);await access.login(page,accounts,'BOSS');await navigate('F03');const boss=await access.bootstrap(origin,accounts,'BOSS');
    assert.equal((await fetch(origin+'/api/boss/ui/admin/bi-scenarios',{headers:{Authorization:'Bearer '+boss.api_token}})).status,403);
    const compare=page.getByRole('region',{name:'不同口径并列',exact:true});
    const mainPanel=page.locator('section.boss-panel').filter({has:page.getByRole('heading',{name:'经营对比',exact:true})});
    async function query(identifier,basis){
      await page.getByLabel('经营资料场景',{exact:true}).selectOption(identifier);
      await expect(page.getByRole('button',{name:'提交查询',exact:true})).toBeEnabled();
      if(basis){await page.getByLabel('业务口径',{exact:true}).fill(basis);await page.getByLabel('资料来源',{exact:true}).selectOption(['sim-bi:'+identifier+':'+basis]);await expect(page.getByRole('button',{name:'提交查询',exact:true})).toBeEnabled();}
      await page.getByRole('button',{name:'提交查询',exact:true}).click();await expect(mainPanel.locator('table')).toBeVisible();
      const key=new URL(page.url()).searchParams.get('biRequest'),value=await get('/api/boss/ui/bi/receipt?client_request_id='+key,boss);
      assert.equal(value.request_state,'SUCCEEDED');assert.equal(value.receipt.query.result.context_snapshot.scenario_id,identifier);return value.receipt.query.result;
    }
    const weighted=await query('weighted-ratios');assert.equal(Number(weighted.values.find(row=>row.metric_id==='gross_margin'&&row.period_scope==='CURRENT').value),14);
    const zero=await query('zero-denominators');assert.equal(zero.values.find(row=>row.metric_id==='gross_margin'&&row.period_scope==='CURRENT').value,null);
    const missing=await query('missing-numbers');assert.equal(missing.values.find(row=>row.metric_id==='revenue'&&row.period_scope==='CURRENT').value,'100');assert.equal(missing.values.find(row=>row.metric_id==='gross_profit'&&row.period_scope==='CURRENT').value,null);
    const delayed=await query('delayed-records');assert.deepEqual(delayed.coverage.delayed_regions,['region-1']);assert(delayed.values.filter(row=>row.period_scope==='CHANGE').every(row=>row.value===null));
    const unsynchronized=await query('unsynchronized-records');assert.deepEqual(unsynchronized.coverage.unsynchronized_regions,['region-1']);assert(unsynchronized.values.every(row=>row.value===null));
    const financial=await query('basis-conflict','FINANCIAL_REPORTED');await compare.getByRole('button',{name:'保留本次口径',exact:true}).click();
    await expect(compare.getByRole('article',{name:'口径 FINANCIAL_REPORTED',exact:true})).toBeVisible();
    await page.getByLabel('业务口径',{exact:true}).fill('BUSINESS_REPORTED');await page.getByLabel('资料来源',{exact:true}).selectOption(['sim-bi:basis-conflict:BUSINESS_REPORTED']);
    await expect(page.getByRole('button',{name:'提交查询',exact:true})).toBeEnabled();await page.getByRole('button',{name:'提交查询',exact:true}).click();await expect(mainPanel.locator('table')).toBeVisible();
    const business=(await get('/api/boss/ui/bi/receipt?client_request_id='+new URL(page.url()).searchParams.get('biRequest'),boss)).receipt.query.result;
    assert.equal(business.parent_query_id,financial.query_id);assert.equal(business.context_snapshot.business_basis,'BUSINESS_REPORTED');
    await compare.getByRole('button',{name:'保留本次口径',exact:true}).click();
    const financialColumn=compare.getByRole('article',{name:'口径 FINANCIAL_REPORTED',exact:true}),businessColumn=compare.getByRole('article',{name:'口径 BUSINESS_REPORTED',exact:true});
    await expect(financialColumn.getByRole('row').filter({has:page.getByRole('rowheader',{name:'营业收入',exact:true})}).getByRole('cell').first()).toHaveText('100');
    await expect(businessColumn.getByRole('row').filter({has:page.getByRole('rowheader',{name:'营业收入',exact:true})}).getByRole('cell').first()).toHaveText('120');
    await financialColumn.locator('summary').click();await businessColumn.locator('summary').click();await expect(financialColumn).toContainText('SIMULATED_GENERATOR');await expect(businessColumn).toContainText('FC02_BEHAVIOR_VALIDATION');
    await page.reload();await expect(compare.getByRole('article',{name:'口径 BUSINESS_REPORTED',exact:true})).toContainText('120');
    await compare.getByRole('article',{name:'口径 FINANCIAL_REPORTED',exact:true}).getByRole('button',{name:'打开该口径当前原文',exact:true}).focus();await page.keyboard.press('Enter');await page.waitForURL(/bossPage=D01/);
    await expect(page.locator('.boss-document-source')).toBeVisible();await expect(page.getByText('SIMULATED_GENERATOR',{exact:true})).toBeVisible();await navigate('F03');
    await expect(compare.getByRole('article',{name:'口径 BUSINESS_REPORTED',exact:true})).toBeVisible();
    records.push({check:'all_formal_boundary_queries_and_both_bases',query_ids:[weighted,zero,missing,delayed,unsynchronized,financial,business].map(row=>row.query_id),
      weighted_margin:14,zero_denominator:null,missing_profit:null,delayed_regions:['region-1'],unsynchronized_regions:['region-1'],financial_revenue:'100',business_revenue:'120',pinned_queries_persist:true});save('IN_PROGRESS');
    for(const [width,height] of [[1024,768],[1280,800],[1440,1024]])for(const zoom of [1,2]){
      await desktop.evaluate(({BrowserWindow},{width,height,zoom})=>{const window=BrowserWindow.getAllWindows()[0];window.setContentSize(width,height);window.webContents.setZoomFactor(zoom);},{width,height,zoom});
      for(const id of ['F03','N03','D01']){await navigate(id);if(id==='D01')await expect(page.locator('.boss-document-source')).toBeVisible();else await expect(compare.getByRole('article',{name:'口径 BUSINESS_REPORTED',exact:true})).toBeVisible();
        const bounds=await page.evaluate(()=>({width:document.documentElement.clientWidth,scroll:document.documentElement.scrollWidth}));assert(bounds.scroll<=bounds.width+1);records.push({check:'boundary_dom_bounds',page_id:id,native_width:width,native_height:height,zoom,...bounds});}
    }
    const snapshot=JSON.parse(execFileSync(path.join(validation,'.venv/bin/python'),[path.join(validation,'fc02_boundary_snapshot.py'),directory],{cwd:root,encoding:'utf8',env:{...process.env,TMPDIR:path.join(validation,'.work/tmp')}}));
    assert(snapshot.initial_matches_generator);assert.equal(snapshot.counts.query,7);assert.equal(snapshot.counts.bi_scenario,6);assert.equal(snapshot.counts.task,0);assert.equal(snapshot.counts.authorization,0);assert.equal(snapshot.counts.outbox,0);
    assert(snapshot.runs.every(run=>JSON.stringify(run.tools.sort())===JSON.stringify(['query_metrics','read_evidence'])&&run.usage===null&&run.cost_total===null));assert.deepEqual(errors,[]);
    records.push({check:'actual_registry_initial_snapshot_and_business_permissions',...snapshot,renderer_errors:errors.length});save('PASS');
  }finally{
    if(desktop)await desktop.close();if(proxy&&proxy.exitCode===null){const ended=once(proxy,'exit');proxy.kill('SIGTERM');await ended;}
  }
}
main().then(()=>console.log(JSON.stringify({status:'PASS',report:output})),failure=>{records.push({check:'failure',name:failure.name,message:String(failure.message).slice(0,1600)});save('FAIL');console.error(JSON.stringify({status:'FAIL',report:output}));process.exitCode=1;});
