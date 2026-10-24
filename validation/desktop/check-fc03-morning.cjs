const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {once}=require('node:events');
const {spawn}=require('node:child_process');
const {randomUUID,createHash}=require('node:crypto');
const {_electron:electron}=require('playwright');
const {expect:baseExpect}=require('@playwright/test');
const access=require('./account-access.cjs');
const expect=baseExpect.configure({timeout:12000});
const root=path.resolve(__dirname,'../..'),validation=path.join(root,'validation'),frontend=process.env.BOSS_PRODUCT_FRONTEND_DIR;
assert(frontend&&path.isAbsolute(frontend));
const runId='fc03-morning-'+randomUUID(),directory=path.join(validation,'.work',runId),accounts=access.provision(directory);
const ports={business:9951,webui:9952,gateway:19951},proxyPort=9953,origin='http://127.0.0.1:'+proxyPort;
const records=[],output=path.join(root,'evidence/feature-delivery/FC03',runId+'.json');
const hash=file=>createHash('sha256').update(fs.readFileSync(file)).digest('hex');
function save(status){fs.writeFileSync(output,JSON.stringify({status,run_id:runId,ports,application_directory:directory,frontend_directory:frontend,
  manifest_sha256:hash(path.join(frontend,'asset-manifest.json')),index_sha256:hash(path.join(frontend,'index.html')),
  external_api_mode:'SIMULATED_FIRST',visual:'NOT_RUN',records},null,2));}
async function launch(){const desktop=await electron.launch({args:[__dirname],cwd:validation,timeout:60000,env:{...process.env,BOSS_VALIDATION_ROOT:validation,
  BOSS_PRODUCT_UI:'1',BOSS_APPLICATION_WORK_DIR:directory,BOSS_APPLICATION_PORTS:JSON.stringify(ports),BOSS_DESKTOP_TEST_WINDOW_HIDDEN:'1',TMPDIR:path.join(validation,'.work/tmp')}});
  const page=await desktop.firstWindow({timeout:120000});await page.waitForURL('http://127.0.0.1:'+ports.webui+'/');
  await desktop.evaluate(async({BrowserWindow},url)=>BrowserWindow.getAllWindows()[0].loadURL(url),origin+'/');await page.waitForURL(origin+'/');return {desktop,page};}
async function state(){const response=await fetch(origin+'/_morning/state');assert.equal(response.status,200);return response.json();}
async function arm(action){const response=await fetch(origin+'/_morning/arm',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action})});assert.equal(response.status,200);}
async function interrupted(action){await expect.poll(async()=>(await state()).dropped_actions.includes(action)).toBe(true);}
async function main(){let desktop,socket,proxy;
  try{
    proxy=spawn(path.join(validation,'.venv/bin/python'),[path.join(__dirname,'fc03_morning_proxy.py'),String(ports.webui),String(proxyPort)],{cwd:root,env:{...process.env,TMPDIR:path.join(validation,'.work/tmp')},
      stdio:['ignore',fs.openSync(path.join(directory,'proxy.stdout.log'),'w'),fs.openSync(path.join(directory,'proxy.stderr.log'),'w')]});
    let page;({desktop,page}=await launch());
    const rendererErrors=[];page.on('pageerror',error=>rendererErrors.push(error.name));
    await access.login(page,accounts,'MAINTAINER');await page.goto(origin+'/?bossPage=A04');
    const coverage=page.getByRole('region',{name:'晨间覆盖维护',exact:true});
    await expect(coverage.getByRole('button',{name:'载入晨间覆盖资料',exact:true})).toBeEnabled();
    const defaultDate=await coverage.getByLabel('覆盖业务日期',{exact:true}).inputValue();assert(defaultDate);
    const initialBoss=await access.bootstrap(origin,accounts,'BOSS');
    const meetingResponse=await fetch(origin+'/api/boss/ui/meetings',{headers:{Authorization:'Bearer '+initialBoss.api_token}});assert.equal(meetingResponse.status,200);
    const selectedDate=(await meetingResponse.json()).meeting.starts_at.slice(0,10);
    await coverage.getByLabel('覆盖业务日期',{exact:true}).fill(selectedDate);
    await arm('boss.simulation.morning_coverage.load');await coverage.getByRole('button',{name:'载入晨间覆盖资料',exact:true}).click();await interrupted('boss.simulation.morning_coverage.load');
    await expect(coverage.getByRole('button',{name:'读取原覆盖载入回执',exact:true})).toBeEnabled();await coverage.getByRole('button',{name:'读取原覆盖载入回执',exact:true}).click();await expect(coverage).toContainText('回执 RECORDED');
    const coverageKey=new URL(page.url()).searchParams.get('morningCoverageRequest');assert(coverageKey);
    await coverage.getByRole('button',{name:'读取原覆盖载入回执',exact:true}).click();await expect(coverage).toContainText('覆盖版本 1');
    let maint=await access.bootstrap(origin,accounts,'MAINTAINER');
    async function read(route,identity=maint,expected=200){const response=await fetch(origin+route,{headers:{Authorization:'Bearer '+identity.api_token}});assert.equal(response.status,expected,route);return response.json();}
    socket=new WebSocket(maint.ws_url+'?token='+encodeURIComponent(maint.token));
    const responses=new Map();socket.addEventListener('message',event=>{const value=JSON.parse(event.data);if(value.event==='webui_response')responses.set(value.request_id,value);});await once(socket,'open');
    async function command(action,payload){const request_id=randomUUID();socket.send(JSON.stringify({type:'webui_request',request_id,action,payload}));await expect.poll(()=>responses.has(request_id)).toBe(true);const response=responses.get(request_id);assert.equal(response.ok,true,JSON.stringify(response.error));return response.result;}
    const configuration=await read('/api/boss/ui/admin/runtime-configuration');
    const values={max_tool_rounds:6,max_output_tokens:700,tool_scope:['todayRead','morningListRead','morningDetailRead','morningSourceRead']};
    const draft=await command('boss.runtime.save',{client_request_id:'morning-config-save-'+randomUUID(),expected_version:configuration.draft?.version??'0',values});
    const checked=await command('boss.runtime.validate',{client_request_id:'morning-config-check-'+randomUUID(),expected_version:draft.version,expected_content_sha256:draft.content_sha256});
    await command('boss.runtime.activate',{client_request_id:'morning-config-activate-'+randomUUID(),expected_version:checked.version,expected_content_sha256:checked.content_sha256,expected_active_version:configuration.current.version});
    socket.close();await once(socket,'close');socket=null;
    await access.logout(page);await access.login(page,accounts,'BOSS');await page.goto(origin+'/?bossPage=F01');
    let auth=await access.bootstrap(origin,accounts,'BOSS');
    maint=await access.bootstrap(origin,accounts,'MAINTAINER');
    await expect(page.getByLabel('业务日期',{exact:true})).toHaveValue(defaultDate);
    await page.getByLabel('业务日期',{exact:true}).fill(selectedDate);
    await expect(page.getByLabel('晨间问题',{exact:true})).toBeEnabled();
    const current=await read('/api/boss/ui/morning/preview?'+new URLSearchParams({date:selectedDate,timezone:'Asia/Shanghai'}),auth);
    assert(current.items.length>=2);assert(current.source_coverage.some(region=>region.state==='NOT_UPDATED'));assert(current.source_coverage.some(region=>region.state==='UNSYNCHRONIZED'));
    const otherDate='2026-10-24';assert.notEqual(otherDate,selectedDate);
    const otherResponse=page.waitForResponse(response=>new URL(response.url()).pathname==='/api/boss/ui/morning/preview'&&new URL(response.url()).searchParams.get('date')===otherDate);
    await page.getByLabel('业务日期',{exact:true}).fill(otherDate);const other=await (await otherResponse).json();assert.equal(other.date,otherDate);assert.notDeepEqual(other.items.map(item=>item.item_id),current.items.map(item=>item.item_id));
    await page.getByLabel('业务日期',{exact:true}).fill(selectedDate);await expect(page.getByRole('button',{name:'整理晨间事项',exact:true})).toBeEnabled();
    await arm('boss.morning.query');await page.getByRole('button',{name:'整理晨间事项',exact:true}).focus();await page.keyboard.press('Enter');await interrupted('boss.morning.query');
    await expect(page.getByRole('button',{name:'读取原晨间请求结果',exact:true})).toBeEnabled();await page.getByRole('button',{name:'读取原晨间请求结果',exact:true}).click();
    await expect(page.getByText('晨间运行状态 SUCCEEDED · 回执 RECORDED',{exact:true})).toBeVisible();
    const key=new URL(page.url()).searchParams.get('morningRequest');assert(key);
    const original=await read('/api/boss/ui/morning/request?client_request_id='+key,auth);assert.equal(original.request_state,'SUCCEEDED');assert.equal(original.write_performed_by_lookup,false);
    const listId=original.receipt.result.list_id,listRoute='/api/boss/ui/morning/list?list_id='+listId;
    const list=await read(listRoute,auth);assert.equal(list.adoption_state,'CURRENT');assert.equal(list.result.date,selectedDate);
    const runtime=(await read('/api/boss/ui/runtime-records?run_id='+original.run_id,maint)).runs[0];
    assert.equal(runtime.feature_id,'FC03');assert.equal(runtime.status,'SUCCEEDED');assert.equal(runtime.usage,null);assert.equal(runtime.cost_total,null);
    assert.deepEqual(runtime.tool_configuration.map(tool=>tool.tool_id).sort(),values.tool_scope.sort());assert(runtime.tool_results.some(result=>result.list_id===listId));assert(!JSON.stringify(runtime).includes('今天有哪些事情需要本人处理'));
    const meeting=list.result.items.find(item=>item.kind==='meeting');assert(meeting);
    const article=page.locator('.boss-workspace-item').filter({has:page.getByRole('heading',{name:meeting.title,exact:true})}).filter({has:page.getByRole('button',{name:'查看事项详情',exact:true})});
    await article.getByRole('button',{name:'查看事项详情',exact:true}).click();
    const detailPanel=page.locator('section.boss-panel').filter({has:page.getByRole('heading',{name:'当前事项详情',exact:true})});
    await expect(detailPanel).toContainText(meeting.object_id);const detail=await read('/api/boss/ui/morning/detail?'+new URLSearchParams({list_id:listId,item_id:meeting.item_id}),auth);assert.equal(detail.item.version,meeting.version);
    assert(detail.documents.length>0);const source=detail.documents[0];
    await detailPanel.getByRole('button',{name:'查看依据：'+source.source_id+' · v'+source.version,exact:true}).click();
    await expect(page.locator('#morning-source')).toContainText(source.content);const referenceAddress=page.url();
    await page.reload();await expect(page.locator('#morning-source')).toContainText(source.content);assert.equal(new URL(page.url()).searchParams.get('morningItem'),meeting.item_id);
    await detailPanel.getByRole('button',{name:'打开关联会议',exact:true}).click();await page.waitForURL(/bossPage=F04/);
    await page.goBack();await expect(page.locator('#morning-source')).toContainText(source.content);assert.equal(new URL(page.url()).searchParams.get('morningRequest'),key);
    const initialOrder=list.current_order.item_ids,first=list.result.items.find(item=>item.item_id===initialOrder[0]);assert(first);
    await page.getByRole('button',{name:'降低事项次序：'+first.title,exact:true}).click();await expect(page.getByLabel('业务日期',{exact:true})).toBeDisabled();
    await arm('boss.today.reorder');await page.getByRole('button',{name:'本人确认保存当前次序',exact:true}).click();await interrupted('boss.today.reorder');
    await expect(page.getByRole('button',{name:'读取排序原请求结果',exact:true})).toBeEnabled();await page.getByRole('button',{name:'读取排序原请求结果',exact:true}).click();await expect(page.getByText('排序回执 RECORDED',{exact:true})).toBeVisible();
    const orderKey=new URL(page.url()).searchParams.get('todayOrderRequest');assert(orderKey);
    const saved=await read(listRoute,auth),expected=[...initialOrder];[expected[0],expected[1]]=[expected[1],expected[0]];
    assert.deepEqual(saved.current_order.item_ids,expected);assert.equal(saved.current_order.version,'1');
    await page.reload();await expect(page.getByText('当前排序版本 1',{exact:true})).toBeVisible();await expect(page.locator('#morning-source')).toContainText(source.content);
    const style=await page.locator('.boss-morning-view').evaluate(element=>({font:getComputedStyle(element).fontSize,line:getComputedStyle(element).lineHeight}));assert.deepEqual(style,{font:'16px',line:'24px'});
    const field=await page.getByLabel('业务日期',{exact:true}).evaluate(element=>({font:getComputedStyle(element.closest('label')).fontSize,line:getComputedStyle(element.closest('label')).lineHeight,input:getComputedStyle(element).fontSize}));assert.deepEqual(field,{font:'14px',line:'22px',input:'16px'});
    const sourceStyle=await page.locator('#morning-source blockquote').evaluate(element=>({font:getComputedStyle(element).fontSize,line:getComputedStyle(element).lineHeight}));assert.deepEqual(sourceStyle,{font:'16px',line:'24px'});
    for(const [width,height] of [[1440,1024],[1280,800],[1024,768]])for(const zoom of [1,2]){
      await desktop.evaluate(({BrowserWindow},{width,height,zoom})=>{const window=BrowserWindow.getAllWindows()[0];window.setContentSize(width,height);window.webContents.setZoomFactor(zoom);},{width,height,zoom});
      await page.waitForFunction(({width,zoom})=>Math.abs(window.innerWidth-width/zoom)<=1,{width,zoom});
      const bounds=await page.evaluate(()=>({width:document.documentElement.clientWidth,scroll:document.documentElement.scrollWidth,inner_width:window.innerWidth}));assert(bounds.scroll<=bounds.width+1);records.push({check:'dom_bounds',native_width:width,native_height:height,zoom,...bounds});
    }
    assert.equal((await fetch(origin+listRoute)).status,401);await read(listRoute,maint,403);
    const unknownKey='today-unknown-'+randomUUID();await page.goto(referenceAddress+'&todayOrderRequest='+unknownKey);
    await expect(page.getByText('排序回执 NOT_FOUND_IN_CURRENT_STORE',{exact:true})).toBeVisible();
    await expect(page.getByRole('button',{name:'本人确认保存当前次序',exact:true})).toBeDisabled();await expect(page.getByLabel('业务日期',{exact:true})).toBeDisabled();
    await page.getByRole('button',{name:'读取排序原请求结果',exact:true}).click();await expect(page.getByText('排序回执 NOT_FOUND_IN_CURRENT_STORE',{exact:true})).toBeVisible();
    assert.equal((await state()).events.filter(value=>value.event==='actual_request_forwarded'&&value.action==='boss.today.reorder').length,1);
    records.push({check:'public_morning_sdk_detail_source_sort',date:selectedDate,other_date:otherDate,request_id:key,run_id:original.run_id,list_id:listId,list_version:list.result.list_version,
      item_id:meeting.item_id,source_id:source.source_id,source_version:source.version,order_request_id:orderKey,order_version:saved.current_order.version,unknown_order_key:unknownKey,unknown_order_replayed:false,coverage_request_id:coverageKey,style,field,source_style:sourceStyle,renderer_errors:rendererErrors});save('IN_PROGRESS');
    assert.deepEqual(rendererErrors,[]);
    await desktop.close();desktop=null;
    ({desktop,page}=await launch());await access.login(page,accounts,'BOSS');await page.goto(referenceAddress+'&todayOrderRequest='+orderKey);
    auth=await access.bootstrap(origin,accounts,'BOSS');
    await expect(page.getByText('当前排序版本 1',{exact:true})).toBeVisible();await expect(page.locator('#morning-source')).toContainText(source.content);
    const reopened=await read('/api/boss/ui/morning/request?client_request_id='+key,auth);assert.deepEqual(reopened,original);
    assert.deepEqual((await read(listRoute,auth)).current_order,saved.current_order);
    await page.getByRole('button',{name:'继续讨论当前清单',exact:true}).click();await expect(page.getByText('晨间运行状态 SUCCEEDED · 回执 RECORDED',{exact:true})).toBeVisible();
    const discussionKey=new URL(page.url()).searchParams.get('morningRequest');assert.notEqual(discussionKey,key);
    const discussion=await read('/api/boss/ui/morning/request?client_request_id='+discussionKey,auth);assert.equal(discussion.receipt.result.list_id,listId);
    const trace=await state();for(const originalKey of [key,orderKey,coverageKey])assert.equal(trace.events.filter(value=>value.event==='actual_request_forwarded'&&value.client_request_id===originalKey).length,1);
    const tasksBefore=await read('/api/boss/ui/tasks',auth);
    const discussionArticle=page.locator('.boss-workspace-item').filter({has:page.getByRole('heading',{name:meeting.title,exact:true})}).filter({has:page.getByRole('button',{name:'查看事项详情',exact:true})});
    const discussionDetail=page.locator('section.boss-panel').filter({has:page.getByRole('heading',{name:'当前事项详情',exact:true})});
    await discussionArticle.getByRole('button',{name:'查看事项详情',exact:true}).click();await expect(discussionDetail).toContainText(meeting.object_id);
    await discussionDetail.getByRole('button',{name:'准备交办',exact:true}).click();await page.waitForURL(/bossPage=F06/);
    const preparation=page.locator('section.boss-panel').filter({has:page.getByRole('heading',{name:'晨间事项交办准备',exact:true})});
    await expect(preparation).toContainText(listId);await expect(preparation).toContainText(meeting.title);
    assert.deepEqual((await read('/api/boss/ui/tasks',auth)).tasks,tasksBefore.tasks);
    records.push({check:'actual_interrupted_success_without_replay',actions:trace.dropped_actions,events:trace.events,preparation_list_id:listId,preparation_item_id:meeting.item_id,business_task_created_by_preparation:false});
    records.push({check:'same_database_service_restart_and_discussion',request_id:key,reopened_identical:true,order_version:'1',source_id:source.source_id,discussion_request_id:discussionKey,discussion_run_id:discussion.run_id,same_list_id:listId});save('PASS');
  }finally{if(socket)socket.close();if(desktop)await desktop.close();if(proxy&&proxy.exitCode===null){const ended=once(proxy,'exit');proxy.kill('SIGTERM');await ended;}}
}
main().then(()=>console.log(JSON.stringify({status:'PASS',report:output})),failure=>{records.push({check:'failure',name:failure.name,message:String(failure.message).slice(0,1600)});save('FAIL');console.error(JSON.stringify({status:'FAIL',report:output}));process.exitCode=1;});
