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
const directory=path.join(validation,'.work','menu-f01-behavior-'+randomUUID()),accounts=access.provision(directory);
const ports={business:10521,webui:10522,gateway:20521},proxyPort=10523,origin='http://127.0.0.1:'+proxyPort;
const records=[],output=path.join(root,'evidence/menu-delivery/F01/behavior.json');
fs.mkdirSync(path.dirname(output),{recursive:true});
const hash=file=>createHash('sha256').update(fs.readFileSync(file)).digest('hex');
function save(status){fs.writeFileSync(output,JSON.stringify({status,application_directory:directory,ports,frontend_directory:frontend,
  manifest_sha256:hash(path.join(frontend,'asset-manifest.json')),external_api_mode:'SIMULATED_FIRST',visual:'NOT_RUN',user_acceptance:'NOT_RUN',records},null,2)+'\n');}
async function main(){let desktop,proxy;const sockets=[];
  try{
    proxy=spawn(path.join(validation,'.venv/bin/python'),[path.join(__dirname,'fc03_morning_proxy.py'),String(ports.webui),String(proxyPort)],{cwd:root,env:{...process.env,TMPDIR:path.join(directory,'tmp')},
      stdio:['ignore',fs.openSync(path.join(directory,'proxy.stdout.log'),'w'),fs.openSync(path.join(directory,'proxy.stderr.log'),'w')]});
    async function launch(){desktop=await electron.launch({args:[__dirname],cwd:validation,timeout:60000,env:{...process.env,BOSS_VALIDATION_ROOT:validation,
      BOSS_PRODUCT_UI:'1',BOSS_EXECUTION_SCOPE:'BOSS-PRIORITY-ITERATION',BOSS_PRODUCT_FRONTEND_DIR:frontend,BOSS_APPLICATION_WORK_DIR:directory,
      BOSS_APPLICATION_PORTS:JSON.stringify(ports),BOSS_DESKTOP_TEST_WINDOW_HIDDEN:'1',TMPDIR:path.join(directory,'tmp')}});
      const page=await desktop.firstWindow({timeout:120000});await page.waitForURL('http://127.0.0.1:'+ports.webui+'/');
      await desktop.evaluate(async({BrowserWindow},url)=>BrowserWindow.getAllWindows()[0].loadURL(url),origin+'/');await page.waitForURL(origin+'/');return page;}
    let page=await launch();const rendererErrors=[];page.on('pageerror',failure=>rendererErrors.push(failure.name));
    const identities={};for(const role of ['BOSS','MAINTAINER'])identities[role]=await access.bootstrap(origin,accounts,role);
    async function read(route,role='BOSS',status=200){const response=await fetch(origin+route,{headers:{Authorization:'Bearer '+identities[role].api_token}});assert.equal(response.status,status,route);return response.json();}
    async function channel(role){const socket=new WebSocket(identities[role].ws_url+'?token='+encodeURIComponent(identities[role].token));sockets.push(socket);const responses=new Map();socket.addEventListener('message',event=>{const body=JSON.parse(event.data);if(body.event==='webui_response')responses.set(body.request_id,body);});await once(socket,'open');
      return async(action,payload,status=200)=>{const id=randomUUID();socket.send(JSON.stringify({type:'webui_request',request_id:id,action,payload}));await expect.poll(()=>responses.has(id),{message:action}).toBe(true);const response=responses.get(id);assert.equal(response.ok,status===200,JSON.stringify(response.error));if(status!==200)assert.equal(response.error.status,status);return response.result;};}
    let maint=await channel('MAINTAINER'),boss=await channel('BOSS');
    const meeting=(await read('/api/boss/ui/meetings')).meeting,day={date:meeting.starts_at.slice(0,10),timezone:meeting.timezone};
    const coverage=await read('/api/boss/ui/admin/morning-coverage','MAINTAINER');
    await maint('boss.simulation.morning_coverage.load',{...day,mode:'SIMULATED',generator_version:coverage.definition.generator_version,seed:coverage.definition.seed,client_request_id:'menu-f01-coverage-'+randomUUID(),expected_version:'0'});
    const config=await read('/api/boss/ui/admin/runtime-configuration','MAINTAINER');
    const values={max_tool_rounds:6,max_output_tokens:700,tool_scope:['todayRead','morningListRead','morningDetailRead','morningSourceRead']};
    const draft=await maint('boss.runtime.save',{client_request_id:'menu-config-'+randomUUID(),expected_version:config.draft?.version??'0',values});
    const checked=await maint('boss.runtime.validate',{client_request_id:'menu-validate-'+randomUUID(),expected_version:draft.version,expected_content_sha256:draft.content_sha256});
    await maint('boss.runtime.activate',{client_request_id:'menu-activate-'+randomUUID(),expected_version:checked.version,expected_content_sha256:checked.content_sha256,expected_active_version:config.current.version});
    const requestId='menu-f01-query-'+randomUUID(),query={client_request_id:requestId,...day,question:'请整理当前日期需要本人决定、协调和知晓的事项'};
    const result=await boss('boss.morning.query',query);assert.equal(result.request_state,'SUCCEEDED');assert.deepEqual(await boss('boss.morning.query',query),result);
    const listId=result.receipt.result.list_id,list=await read('/api/boss/ui/morning/list?list_id='+listId),view=list.result;
    assert.equal(view.input_coverage.length,8);assert(view.source_coverage.some(region=>region.state==='NOT_UPDATED'));assert(view.source_coverage.some(region=>region.state==='UNSYNCHRONIZED'));
    await access.login(page,accounts,'BOSS');
    const address=origin+'/?bossPage=F01&'+new URLSearchParams({morningRequest:requestId,morningDate:day.date,morningTimezone:day.timezone});await page.goto(address);
    let surface=page.locator('.boss-f01'),table=surface.getByRole('region',{name:'我的当前事项',exact:true});
    await expect(table.locator('tbody tr')).toHaveCount(view.items.length);
    await expect(surface.locator('.boss-f01-input-coverage')).toHaveCount(8);
    for(const [category,title] of [['DECIDE','待决定'],['COORDINATE','待协调'],['INFORM','需要知晓']]){
      const button=surface.getByRole('group',{name:'事项分类'}).getByRole('button',{name:new RegExp('^'+title)});
      await expect(button).toContainText(view.category_counts[category]+' 项');await button.click();await expect(table.locator('tbody tr')).toHaveCount(view.category_counts[category]);await button.click();
    }
    const selected=view.items.find(item=>item.kind==='meeting');assert(selected);
    await table.locator('tr').filter({has:page.getByRole('button',{name:selected.title,exact:true})}).getByRole('button',{name:selected.title,exact:true}).click();
    let detail=surface.locator('aside section').filter({has:page.getByRole('heading',{name:'当前事项详情',exact:true})});await expect(detail).toContainText(selected.object_id);
    const currentDetail=await read('/api/boss/ui/morning/detail?'+new URLSearchParams({list_id:listId,item_id:selected.item_id}));assert(currentDetail.documents.length>0);
    const other=view.items.find(item=>item.item_id!==selected.item_id);assert(other);
    const selectRow=async item=>table.locator('tbody tr').filter({has:page.getByRole('button',{name:item.title,exact:true})}).getByRole('button',{name:item.title,exact:true}).click();
    await selectRow(other);await expect(detail).toContainText(other.object_id);
    const heldDetail={path:'/api/boss/ui/morning/detail',field:'item_id',value:selected.item_id};
    assert.equal((await fetch(origin+'/_morning/delay',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(heldDetail)})).status,200);
    await selectRow(selected);await expect.poll(async()=>(await (await fetch(origin+'/_morning/state')).json()).delayed_read?.value).toBe(selected.item_id);
    await selectRow(other);await expect(detail).toContainText(other.object_id);await fetch(origin+'/_morning/release',{method:'POST'});await expect.poll(async()=>(await (await fetch(origin+'/_morning/state')).json()).delayed_read).toBe(null);await expect(detail).toContainText(other.object_id);
    await selectRow(selected);await expect(detail).toContainText(selected.object_id);
    const source=currentDetail.documents[0],sourceButton=detail.getByRole('button',{name:'查看依据：'+source.source_id+' · v'+source.version,exact:true});
    await sourceButton.click();await expect(page.locator('#morning-source')).toContainText(source.content);await page.keyboard.press('Escape');await expect(sourceButton).toBeFocused();
    const secondSource=currentDetail.documents.find(document=>document.source_id!==source.source_id);assert(secondSource);
    assert.equal((await fetch(origin+'/_morning/delay',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({path:'/api/boss/ui/morning/source',field:'source_id',value:source.source_id})})).status,200);
    await sourceButton.click();await expect.poll(async()=>(await (await fetch(origin+'/_morning/state')).json()).delayed_read?.value).toBe(source.source_id);await page.keyboard.press('Escape');
    await detail.getByRole('button',{name:'查看依据：'+secondSource.source_id+' · v'+secondSource.version,exact:true}).click();await expect(page.locator('#morning-source')).toContainText(secondSource.content);
    await fetch(origin+'/_morning/release',{method:'POST'});await expect.poll(async()=>(await (await fetch(origin+'/_morning/state')).json()).delayed_read).toBe(null);await expect(page.locator('#morning-source h3')).toHaveText(secondSource.source_id+' · v'+secondSource.version);await page.keyboard.press('Escape');
    const meetingButton=detail.getByRole('button',{name:'打开关联会议',exact:true});await meetingButton.click();await expect(page.getByRole('dialog')).toContainText(meeting.meeting_id);await page.keyboard.press('Escape');await expect(meetingButton).toBeFocused();
    const originalOrder=list.current_order.item_ids,first=view.items.find(item=>item.item_id===originalOrder[0]);assert(first);
    await table.getByRole('button',{name:'降低事项次序：'+first.title,exact:true}).focus();await page.keyboard.press('Enter');
    await expect(page.getByLabel('业务日期',{exact:true})).toBeDisabled();
    await fetch(origin+'/_morning/arm',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'boss.today.reorder'})});
    await table.getByRole('button',{name:'本人确认保存当前次序',exact:true}).click();
    await expect.poll(async()=>(await (await fetch(origin+'/_morning/state')).json()).dropped_actions.includes('boss.today.reorder')).toBe(true);
    await table.getByRole('button',{name:'读取排序原请求结果',exact:true}).click();await expect(table).toContainText('排序回执 RECORDED');
    const saved=await read('/api/boss/ui/morning/list?list_id='+listId),expected=[...originalOrder];[expected[0],expected[1]]=[expected[1],expected[0]];assert.deepEqual(saved.current_order.item_ids,expected);
    const sortedAddress=page.url();await page.reload();await expect(table).toContainText('当前排序版本 1');await expect(detail).toContainText(selected.object_id);
    const layouts=[];
    records.push({check:'current_scope_sources_meeting_and_actual_sort_recovery',status:'PASS'});save('IN_PROGRESS');
    const referenceDom=JSON.parse(fs.readFileSync(path.join(root,'evidence/menu-delivery/F01/reference-dom.json')));assert.equal(referenceDom.has_grid,true);
    for(const [width,height] of [[1440,1024],[1280,800],[1024,768]])for(const zoom of [1,2]){
      await desktop.evaluate(({BrowserWindow},{width,height,zoom})=>{for(const window of BrowserWindow.getAllWindows()){window.setContentSize(width,height);window.webContents.setZoomFactor(zoom);}},{width,height,zoom});
      await page.waitForFunction(({width,zoom})=>Math.abs(innerWidth-width/zoom)<=1,{width,zoom});
      const actual=await surface.evaluate(element=>{const grid=element.querySelector('.boss-f01-grid'),main=element.querySelector('.boss-f01-main'),aside=element.querySelector('.boss-f01-aside'),panel=main.querySelector('.boss-panel'),style=getComputedStyle(grid),rect=node=>({x:node.getBoundingClientRect().x,y:node.getBoundingClientRect().y,width:node.getBoundingClientRect().width,height:node.getBoundingClientRect().height});return {grid:rect(grid),main:rect(main),aside:rect(aside),columns:style.gridTemplateColumns,gap:style.gap,main_gap:getComputedStyle(main).gap,panel_padding:getComputedStyle(panel).padding,panel_radius:getComputedStyle(panel).borderRadius,document_width:document.documentElement.clientWidth,document_scroll:document.documentElement.scrollWidth};});
      const reference=referenceDom.layouts.find(row=>row.width===width&&row.height===height&&row.zoom===zoom);assert(reference);
      assert(actual.document_scroll<=actual.document_width+1);assert.equal(actual.gap,'14px');assert.equal(actual.main_gap,'13px');
      if(width/zoom>1050)assert.equal(actual.aside.width,width/zoom>1250?310:260);else assert(Math.abs(actual.aside.width-actual.main.width)<1);
      assert.equal(reference.gap,'14px');assert.equal(actual.panel_padding,reference.panel_padding);assert.equal(actual.panel_radius,'14px');layouts.push({width,height,zoom,actual,reference});
      await table.getByRole('button',{name:'重新读取今日资料',exact:true}).scrollIntoViewIfNeeded();await expect(table.getByRole('button',{name:'重新读取今日资料',exact:true})).toBeVisible();
    }
    await desktop.evaluate(({BrowserWindow})=>{const window=BrowserWindow.getAllWindows()[0];window.setContentSize(1440,1024);window.webContents.setZoomFactor(1);});
    const currentFirst=view.items.find(item=>item.item_id===saved.current_order.item_ids[0]);assert(currentFirst);
    await table.getByRole('button',{name:'降低事项次序：'+currentFirst.title,exact:true}).click();
    const externalOrder=[...saved.current_order.item_ids].reverse();
    await boss('boss.today.reorder',{...day,list_id:listId,client_request_id:'menu-concurrent-'+randomUUID(),expected_version:saved.current_order.version,snapshot_sha256:view.snapshot_sha256,item_ids:externalOrder});
    await table.getByRole('button',{name:'本人确认保存当前次序',exact:true}).click();await expect(table.getByRole('alert')).toContainText('事项版本或本人次序已经变化');await expect(table).toContainText('当前次序尚未保存');await expect(page.getByLabel('业务日期',{exact:true})).toBeDisabled();
    await table.getByRole('button',{name:'放弃未保存次序',exact:true}).click();await expect(table).toContainText('当前排序版本 2');
    assert.deepEqual((await read('/api/boss/ui/morning/list?list_id='+listId)).current_order.item_ids,externalOrder);
    await page.getByLabel('IANA 时区',{exact:true}).fill('Invalid/Zone');await page.getByRole('button',{name:'更新当前事项',exact:true}).click();await expect(surface.getByRole('alert')).toContainText('IANA');await expect(surface.locator('.boss-f01-categories')).toContainText('数量待读取');
    await page.goto(sortedAddress);await expect(table).toContainText('当前排序版本 2');await expect(detail).toContainText(selected.object_id);
    assert.equal((await fetch(origin+'/api/boss/ui/morning/list?list_id='+listId)).status,401);await read('/api/boss/ui/morning/list?list_id='+listId,'MAINTAINER',403);
    await boss('boss.morning.query',{...query,owner_id:'boss-1'},400);
    records.push({check:'formal_scope_categories_same_version_sources_meeting_sort_recovery',request_id:requestId,run_id:result.run_id,list_id:listId,item_id:selected.item_id,source_id:source.source_id,source_version:source.version,order_version:saved.current_order.version,input_kinds:view.input_coverage.map(row=>row.kind),layouts});save('IN_PROGRESS');
    await page.evaluate(()=>{window.menuFocusTrail=[];document.addEventListener('focusin',event=>{window.menuFocusTrail.push({id:event.target.id,tag:event.target.tagName,role:event.target.getAttribute('role')});});});
    const tasksBefore=await read('/api/boss/ui/tasks');await detail.getByRole('button',{name:'准备交办',exact:true}).click();await page.waitForURL(/bossPage=F06/);
    await expect(page.getByRole('heading',{name:'晨间事项交办准备',exact:true})).toBeVisible();assert.deepEqual((await read('/api/boss/ui/tasks')).tasks,tasksBefore.tasks);
    await page.getByRole('button',{name:'返回晨间清单',exact:true}).click();await expect(page.getByRole('dialog')).toContainText('未保存修改（D06）');
    await page.getByRole('dialog').getByRole('button',{name:'放弃草稿并离开',exact:true}).click();await page.waitForURL(/bossPage=F01/);
    await expect(detail.getByRole('button',{name:'准备交办',exact:true})).toBeFocused();assert.equal(new URL(page.url()).searchParams.get('morningItem'),selected.item_id);
    records.push({check:'return_focus_observation',...await page.evaluate(()=>({focus_events:window.menuFocusTrail,active_id:document.activeElement.id,active_tag:document.activeElement.tagName}))});save('IN_PROGRESS');
    const orderKey=new URL(sortedAddress).searchParams.get('todayOrderRequest');const trace=await (await fetch(origin+'/_morning/state')).json();assert.equal(trace.events.filter(row=>row.event==='actual_request_forwarded'&&row.action==='boss.today.reorder'&&row.client_request_id===orderKey).length,1);
    records.push({check:'actual_delayed_read_rejection_and_cas_edit_preservation',released_reads:trace.events.filter(row=>row.event==='actual_read_released'),concurrent_order_version:'2',invalid_timezone_not_counted_as_empty:true});
    assert.deepEqual(rendererErrors,[]);records.push({check:'preparation_return_and_no_automatic_business_write',task_count:tasksBefore.tasks.length,renderer_errors:rendererErrors,sort_replayed:false});save('IN_PROGRESS');
    const reopenAddress=page.url(),reopenState=await read('/api/boss/ui/morning/list?list_id='+listId);
    for(const socket of sockets)socket.close();await desktop.close();desktop=null;page=await launch();
    for(const role of ['BOSS','MAINTAINER'])identities[role]=await access.bootstrap(origin,accounts,role);
    maint=await channel('MAINTAINER');boss=await channel('BOSS');void maint;void boss;
    await access.login(page,accounts,'BOSS');await page.goto(reopenAddress);surface=page.locator('.boss-f01');table=surface.getByRole('region',{name:'我的当前事项',exact:true});detail=surface.locator('aside section').filter({has:page.getByRole('heading',{name:'当前事项详情',exact:true})});
    await expect(table).toContainText('当前排序版本 2');await expect(detail).toContainText(selected.object_id);assert.deepEqual((await read('/api/boss/ui/morning/list?list_id='+listId)),reopenState);
    records.push({check:'same_database_independent_service_reopen',list_id:listId,current_order_version:'2',same_saved_view:true});save('IN_PROGRESS');
    await detail.getByRole('button',{name:'准备交办',exact:true}).click();await page.waitForURL(/bossPage=F06/);
    const createPanel=page.locator('.boss-assignment-scope section').filter({has:page.getByRole('heading',{name:'创建交办',exact:true})});
    await expect(createPanel.getByLabel('交办目的',{exact:true})).toHaveValue(selected.title);
    await createPanel.getByLabel('唯一负责人',{exact:true}).selectOption('coordinator-1');await createPanel.getByLabel('期限（Asia/Shanghai）',{exact:true}).fill(day.date+'T17:00');await createPanel.getByLabel('证据要求',{exact:true}).fill('提交当前事项的来源引用与处理进展');
    await createPanel.getByRole('button',{name:'核对并创建',exact:true}).click();const confirmation=page.getByRole('dialog',{name:'核对并创建交办',exact:true});await expect(confirmation).toBeVisible();
    assert.deepEqual((await read('/api/boss/ui/tasks')).tasks,tasksBefore.tasks);await expect(confirmation.getByRole('button',{name:'确认并提交',exact:true})).toBeDisabled();
    await confirmation.getByLabel('本人确认以上具体对象、内容、期限和动作。',{exact:true}).check();await confirmation.getByRole('button',{name:'确认并提交',exact:true}).click();
    let createdTask;await expect.poll(async()=>{const tasks=await read('/api/boss/ui/tasks');createdTask=tasks.tasks.find(task=>task.purpose===selected.title);return createdTask?.status;}).toBe('OPEN');
    assert.equal(createdTask.related_meeting_id,meeting.meeting_id);assert(createdTask.source_refs.includes('finance-note'));assert.equal(createdTask.message_ids.length,0);
    const finalTrace=await (await fetch(origin+'/_morning/state')).json(),creation=finalTrace.events.filter(row=>row.event==='actual_request_forwarded'&&row.action==='boss.assignment.create');assert.equal(creation.length,1);assert.equal(creation[0].morning_reference.item_id,selected.item_id);assert.equal(creation[0].morning_reference.list_id,listId);
    await page.getByRole('button',{name:'返回晨间清单',exact:true}).click();await page.waitForURL(/bossPage=F01/);await expect(surface).toContainText('历史内容需要重新查询');await expect(detail.getByRole('button',{name:'准备交办',exact:true})).toHaveCount(0);
    records.push({check:'explicit_owner_confirmation_persists_current_morning_assignment',task_id:createdTask.task_id,task_version:createdTask.version,state:createdTask.status,morning_reference:creation[0].morning_reference,automatic_send:false,current_list_after_business_change:'HISTORICAL_REQUIRES_REQUERY'});save('IN_PROGRESS');
    const unknown='today-unknown-'+randomUUID(),unknownAddress=new URL(page.url());unknownAddress.searchParams.set('todayOrderRequest',unknown);await page.goto(unknownAddress.href);await expect(table).toContainText('排序回执 NOT_FOUND_IN_CURRENT_STORE');await expect(table.getByRole('button',{name:'本人确认保存当前次序',exact:true})).toBeDisabled();await expect(page.getByLabel('业务日期',{exact:true})).toBeDisabled();
    assert(!((await (await fetch(origin+'/_morning/state')).json()).events.some(row=>row.client_request_id===unknown)));
    await page.locator('.boss-sidebar-nav').getByRole('button',{name:'采购成本协调',exact:true}).click();await page.getByRole('dialog').getByRole('button',{name:'放弃草稿并离开',exact:true}).click();await page.waitForURL(/bossPage=MVP01/);
    assert.equal(new URL(page.url()).searchParams.get('todayOrderRequest'),unknown);records.push({check:'unknown_order_read_only_and_explicit_leave',unknown_original_replayed:false,original_id_retained_after_explicit_leave:true});save('PASS');
  }finally{for(const socket of sockets)socket.close();if(desktop)await desktop.close();if(proxy&&proxy.exitCode===null){const ended=once(proxy,'exit');proxy.kill('SIGTERM');await ended;}}
}
main().then(()=>console.log(JSON.stringify({status:'PASS',report:output})),failure=>{let message=failure.stack;for(const account of Object.values(accounts))for(const key of ['username','password'])message=message.replaceAll(account[key],'[已隐藏]');records.push({check:'failure',message});save('FAIL');console.error(JSON.stringify({status:'FAIL',report:output}));process.exitCode=1;});
