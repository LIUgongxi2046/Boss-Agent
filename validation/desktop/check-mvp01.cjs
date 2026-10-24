const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {execFileSync,spawn}=require('node:child_process');
const {once}=require('node:events');
const {randomUUID,createHash}=require('node:crypto');
const {_electron:electron}=require('playwright');
const {expect:baseExpect}=require('@playwright/test');
const access=require('./account-access.cjs');
const expect=baseExpect.configure({timeout:15000});
const root=path.resolve(__dirname,'../..'),validation=path.join(root,'validation'),frontend=process.env.BOSS_PRODUCT_FRONTEND_DIR;
assert(frontend&&path.isAbsolute(frontend));
const runId='mvp01-'+randomUUID(),directory=path.join(validation,'.work',runId),ports={business:10071,webui:10072,gateway:20071},proxyPort=10073;
const origin='http://127.0.0.1:'+proxyPort,records=[],output=path.join(root,'evidence/feature-delivery/MVP01',runId+'.json');
const hash=file=>createHash('sha256').update(fs.readFileSync(file)).digest('hex');
function save(status){fs.writeFileSync(output,JSON.stringify({status,scope:'MVP01_DEVELOPER_CHECKS_PENDING_USER_ACCEPTANCE',run_id:runId,ports,proxy_port:proxyPort,application_directory:directory,
  frontend_directory:frontend,manifest_sha256:hash(path.join(frontend,'asset-manifest.json')),index_sha256:hash(path.join(frontend,'index.html')),external_api_mode:'SIMULATED_FIRST',visual:'NOT_RUN',user_acceptance:'NOT_RUN',records},null,2));}
async function launch(){const desktop=await electron.launch({args:[__dirname],cwd:validation,timeout:60000,env:{...process.env,BOSS_VALIDATION_ROOT:validation,BOSS_PRODUCT_UI:'1',BOSS_EXECUTION_SCOPE:'BOSS-MVP-1',
  BOSS_APPLICATION_WORK_DIR:directory,BOSS_APPLICATION_PORTS:JSON.stringify(ports),BOSS_DESKTOP_TEST_WINDOW_HIDDEN:'1',TMPDIR:path.join(validation,'.work/tmp')}});
  const page=await desktop.firstWindow({timeout:120000});await page.waitForURL('http://127.0.0.1:'+ports.webui+'/');
  await desktop.evaluate(async({BrowserWindow},url)=>BrowserWindow.getAllWindows()[0].loadURL(url),origin+'/');await page.waitForURL(origin+'/');return {desktop,page};}
async function main(){let desktop,proxy;
  try{
    execFileSync(path.join(validation,'.venv/bin/python'),[path.join(root,'scripts/prepare_mvp01.py'),'--directory',directory,'--frontend',frontend,'--ports',JSON.stringify(ports)],{cwd:root,env:{...process.env,TMPDIR:path.join(validation,'.work/tmp')},timeout:120000});
    const accounts=Object.fromEntries(JSON.parse(fs.readFileSync(path.join(directory,'accounts/credentials.json'))).map(account=>[account.role,account]));
    proxy=spawn(path.join(validation,'.venv/bin/python'),[path.join(__dirname,'fc03_morning_proxy.py'),String(ports.webui),String(proxyPort)],{cwd:root,env:{...process.env,TMPDIR:path.join(validation,'.work/tmp')},stdio:['ignore',fs.openSync(path.join(directory,'proxy.stdout.log'),'w'),fs.openSync(path.join(directory,'proxy.stderr.log'),'w')]});
    let page;({desktop,page}=await launch());const errors=[];page.on('pageerror',error=>errors.push(error.name));
    await access.login(page,accounts,'BOSS');
    const panel=page.getByRole('region',{name:'采购成本连续体验',exact:true});await expect(panel).toBeVisible();
    await expect(page.getByRole('heading',{name:'今日采购成本事项',exact:true})).toBeVisible();
    assert.equal(await page.locator('.boss-sidebar-nav button').count(),1);
    const assets=[];
    for(const filename of ['01-待机悬浮.webp','03-思考分析.webp']){const response=await fetch(origin+'/boss-brand/'+encodeURIComponent(filename));assert.equal(response.status,200);assert.equal(response.headers.get('content-type'),'image/webp');const bytes=Buffer.from(await response.arrayBuffer());assert.equal(createHash('sha256').update(bytes).digest('hex'),hash(path.join(frontend,'boss-brand',filename)));assets.push({filename,sha256:createHash('sha256').update(bytes).digest('hex'),content_type:'image/webp'});}
    await expect.poll(()=>panel.locator('.boss-mascot-work img').evaluate(image=>image.complete&&image.naturalWidth>0)).toBe(true);
    assert.equal((await fetch(origin+'/boss-brand/missing.webp')).status,404);
    assert.equal((await fetch(origin+'/boss-brand/%2e%2e%2findex.html')).status,404);
    records.push({check:'matched_brand_resources',assets,decoded_within_brand_directory:true,missing_and_outside_rejected:true});
    let auth=await access.bootstrap(origin,accounts,'BOSS');const maint=await access.bootstrap(origin,accounts,'MAINTAINER');
    async function read(route,identity=auth,expected=200){const response=await fetch(origin+route,{headers:{Authorization:'Bearer '+identity.api_token}});assert.equal(response.status,expected,route);return response.json();}
    async function state(){const response=await fetch(origin+'/_morning/state');assert.equal(response.status,200);return response.json();}
    async function arm(action){const response=await fetch(origin+'/_morning/arm',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action})});assert.equal(response.status,200);}
    assert.equal((await read('/api/boss/identity')).execution_scope,'BOSS-MVP-1');
    assert.equal((await read('/api/boss/ui/tasks')).tasks.length,0);
    await panel.getByRole('button',{name:'入库报告成本 · sim-material-1',exact:true}).click();
    await panel.getByRole('button',{name:'查询成本并准备协调材料',exact:true}).click();assert.equal((await state()).events.length,0);assert.equal(await panel.getByLabel('协调目的',{exact:true}).evaluate(field=>field.validity.valueMissing),true);
    await panel.getByLabel('协调目的',{exact:true}).fill('核查当前采购成本报告变化并协调后续反馈');
    await panel.getByLabel('截止时间（Asia/Shanghai）',{exact:true}).fill('2026-10-25T17:00');
    await panel.getByLabel('证据要求（每行一项）',{exact:true}).fill('本期与基期成本原文、负责人核查结果');
    const create=panel.getByRole('button',{name:'本人确认创建协调任务',exact:true});await expect(create).toBeDisabled();
    await arm('boss.mvp.query');await panel.getByRole('button',{name:'查询成本并准备协调材料',exact:true}).focus();await page.keyboard.press('Enter');
    await expect.poll(async()=>(await state()).dropped_actions.includes('boss.mvp.query')).toBe(true);
    await expect(panel.getByRole('button',{name:'读取原采购查询结果',exact:true})).toBeEnabled();await panel.getByRole('button',{name:'读取原采购查询结果',exact:true}).click();
    await expect(panel.getByText('单位成本变化 100 CNY/tonne · 报告总成本变化 1000 CNY',{exact:true})).toBeVisible();
    const key=new URL(page.url()).searchParams.get('mvpQuery');assert(key);
    const query=await read('/api/boss/ui/mvp/query?client_request_id='+key);assert.equal(query.request_state,'SUCCEEDED');assert.equal(query.write_performed_by_lookup,false);
    assert.equal(query.query.cost_report.current.unit_cost,'2100');assert.equal(query.query.cost_report.baseline.unit_cost,'2000');assert.equal(query.query.cost_report.unit_cost_change,'100');
    assert.equal((await read('/api/boss/ui/tasks')).tasks.length,0);
    await panel.getByRole('button',{name:'查看本期原文依据',exact:true}).click();
    const source=await read('/api/boss/ui/mvp/source?'+new URLSearchParams({client_request_id:key,source_id:query.query.cost_report.current.source_id}));
    await expect(panel.locator('.boss-document-source')).toContainText(source.content);await expect(panel.locator('.boss-document-source')).toContainText(source.source_id);
    const originalAddress=page.url();await page.reload();await expect(panel.locator('.boss-document-source')).toContainText(source.content);
    await expect(create).toBeDisabled();await panel.getByRole('checkbox',{name:'本人确认当前依据、负责人、内容、期限与证据要求',exact:true}).check();await expect(create).toBeEnabled();
    await arm('boss.fc01.coordinate');await create.click();await expect.poll(async()=>(await state()).dropped_actions.includes('boss.fc01.coordinate')).toBe(true);
    await expect(panel.getByRole('button',{name:'读取原协调请求回执',exact:true})).toBeEnabled();await panel.getByRole('button',{name:'读取原协调请求回执',exact:true}).click();
    const coordinateKey=new URL(page.url()).searchParams.get('mvpCoordinate');assert(coordinateKey);
    await expect(panel.getByText(new RegExp('原协调请求 '+coordinateKey+' · 回执 RECORDED'))).toBeVisible();
    const receipt=await read('/api/boss/ui/supply-quality-receipt?'+new URLSearchParams({action:'boss.supply_quality.coordinate',client_request_id:coordinateKey}));assert.equal(receipt.outcome,'RECORDED');
    const tasks=await read('/api/boss/ui/tasks');assert.equal(tasks.tasks.length,1);assert.equal(tasks.tasks[0].task_id,receipt.result.task_id);assert.equal(tasks.tasks[0].status,'OPEN');
    await expect(panel.getByText('交办 '+receipt.result.task_id+' · 版本 1 · 状态 OPEN',{exact:true})).toBeVisible();
    const finalAddress=page.url();await page.reload();await expect(panel.getByText('交办 '+receipt.result.task_id+' · 版本 1 · 状态 OPEN',{exact:true})).toBeVisible();
    const trace=await state();for(const original of [key,coordinateKey])assert.equal(trace.events.filter(row=>row.event==='actual_request_forwarded'&&row.client_request_id===original).length,1);
    const runtime=(await read('/api/boss/ui/runtime-records?run_id='+query.run_id,maint)).runs[0];
    assert.deepEqual(runtime.tool_configuration.map(row=>row.tool_id).sort(),['bossEvidenceRead','bossSupplyQualityPrepare','bossSupplyQualityQuery','bossSupplyQualityRead']);assert.equal(runtime.usage,null);assert.equal(runtime.cost_total,null);assert(!JSON.stringify(runtime).includes('核查当前采购成本报告变化并协调后续反馈'));
    await read('/api/boss/ui/mvp/query?client_request_id='+key,maint,403);assert.equal((await fetch(origin+'/api/boss/ui/mvp/query?client_request_id='+key)).status,401);
    const body=await panel.locator('.boss-document-source blockquote').evaluate(element=>({font:getComputedStyle(element).fontSize,line:getComputedStyle(element).lineHeight}));assert.deepEqual(body,{font:'16px',line:'24px'});
    for(const [width,height] of [[1440,1024],[1280,800],[1024,768]])for(const zoom of [1,2]){await desktop.evaluate(({BrowserWindow},{width,height,zoom})=>{const window=BrowserWindow.getAllWindows()[0];window.setContentSize(width,height);window.webContents.setZoomFactor(zoom);},{width,height,zoom});await page.waitForFunction(({width,zoom})=>Math.abs(window.innerWidth-width/zoom)<=1,{width,zoom});const bounds=await page.evaluate(()=>({width:document.documentElement.clientWidth,scroll:document.documentElement.scrollWidth}));assert(bounds.scroll<=bounds.width+1);records.push({check:'mvp_dom_bounds',native_width:width,native_height:height,zoom,...bounds});}
    records.push({check:'continuous_procurement_journey',query_key:key,coordinate_key:coordinateKey,task_id:receipt.result.task_id,origin_record_id:query.query.coordinate_input.origin_record_id,current_source_id:source.source_id,current_source_version:source.version,
      baseline_unit_cost:'2000',current_unit_cost:'2100',unit_cost_change:'100',currency:'CNY',quantity_unit:'tonne',source_matches:true,task_created_before_confirmation:false,body,transport:trace.events});save('IN_PROGRESS');
    await access.logout(page);await access.login(page,accounts,'BOSS');await page.goto(finalAddress);await expect(panel.getByText('交办 '+receipt.result.task_id+' · 版本 1 · 状态 OPEN',{exact:true})).toBeVisible();
    await desktop.close();desktop=null;({desktop,page}=await launch());await access.login(page,accounts,'BOSS');await page.goto(finalAddress);
    const reopenedPanel=page.getByRole('region',{name:'采购成本连续体验',exact:true});await expect(reopenedPanel.getByText('交办 '+receipt.result.task_id+' · 版本 1 · 状态 OPEN',{exact:true})).toBeVisible();
    await expect(reopenedPanel.locator('.boss-document-source')).toContainText(source.content);auth=await access.bootstrap(origin,accounts,'BOSS');
    assert.deepEqual(await read('/api/boss/ui/mvp/query?client_request_id='+key),query);assert.equal((await read('/api/boss/ui/tasks')).tasks.length,1);
    assert.deepEqual(errors,[]);records.push({check:'same_query_task_and_receipt_after_relogin_and_restart',query_key:key,task_id:receipt.result.task_id,coordinate_key:coordinateKey,reopened_identical:true,source_restored:true,renderer_errors:errors});save('PASS');
  }finally{if(desktop)await desktop.close();if(proxy&&proxy.exitCode===null){const ended=once(proxy,'exit');proxy.kill('SIGTERM');await ended;}}
}
main().then(()=>console.log(JSON.stringify({status:'PASS',report:output})),failure=>{records.push({check:'failure',name:failure.name,message:String(failure.message).slice(0,1600)});save('FAIL');console.error(JSON.stringify({status:'FAIL',report:output}));process.exitCode=1;});
