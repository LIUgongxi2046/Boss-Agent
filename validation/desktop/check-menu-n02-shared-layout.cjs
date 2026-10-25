const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {once}=require('node:events');
const {randomUUID,createHash}=require('node:crypto');
const {_electron:electron}=require('playwright');
const {expect:baseExpect}=require('@playwright/test');
const access=require('./account-access.cjs');
const expect=baseExpect.configure({timeout:20000});
const root=path.resolve(__dirname,'../..'),validation=path.join(root,'validation'),frontend=path.join(root,'menu-n02-n3-dist');
const directory=path.join(validation,'.work','menu-n02-shared-layout-'+randomUUID()),accounts=access.provision(directory);
const ports={business:10821,webui:10822,gateway:20821},origin='http://127.0.0.1:'+ports.webui;
const output=path.join(root,'evidence/menu-delivery/N02/shared-layout.json'),records=[];
let stage='START';
function save(status){fs.mkdirSync(path.dirname(output),{recursive:true});fs.writeFileSync(output,JSON.stringify({status,scope:'N02_BOUND_TASK_AND_SHARED_F08_D06_DOM',application_directory:directory,ports,manifest_sha256:createHash('sha256').update(fs.readFileSync(path.join(frontend,'asset-manifest.json'))).digest('hex'),external_api_mode:'SIMULATED_FIRST',visual:'NOT_RUN',user_acceptance:'NOT_RUN',records},null,2)+'\n');}
async function main(){let desktop,socket;
  try{
    desktop=await electron.launch({args:[__dirname],cwd:validation,timeout:60000,env:{...process.env,BOSS_VALIDATION_ROOT:validation,BOSS_PRODUCT_UI:'1',BOSS_EXECUTION_SCOPE:'BOSS-PRIORITY-ITERATION',BOSS_PRODUCT_FRONTEND_DIR:frontend,BOSS_APPLICATION_WORK_DIR:directory,BOSS_APPLICATION_PORTS:JSON.stringify(ports),BOSS_DESKTOP_TEST_WINDOW_HIDDEN:'1',TMPDIR:path.join(directory,'tmp')}});
    const page=await desktop.firstWindow({timeout:120000});await page.waitForURL(origin+'/');const identity=await access.bootstrap(origin,accounts,'BOSS'),events=[];
    socket=new WebSocket(identity.ws_url+'?token='+encodeURIComponent(identity.token));socket.addEventListener('message',event=>events.push(JSON.parse(event.data)));await once(socket,'open');await expect.poll(()=>events.some(event=>event.event==='ready')).toBe(true);
    async function read(route){const response=await fetch(origin+route,{headers:{Authorization:'Bearer '+identity.api_token}});assert.equal(response.status,200);return response.json();}
    const source=await read('/api/boss/ui/evidence?source=finance-note'),request_id=randomUUID();socket.send(JSON.stringify({type:'webui_request',request_id,action:'boss.assignment.create',payload:{client_request_id:randomUUID(),purpose:source.content,coordinator_id:'coordinator-1',due_at:'2026-10-25T17:00:00+08:00',timezone:'Asia/Shanghai',evidence_requirements:[source.source_id],related_meeting_id:'meeting-1',related_event_ids:['event-1'],source_refs:[source.source_id],content_version:'1'}}));await expect.poll(()=>events.some(event=>event.request_id===request_id)).toBe(true);const created=events.find(event=>event.request_id===request_id);assert.equal(created.ok,true);const task=created.result;
    await access.login(page,accounts,'BOSS');await page.getByRole('button',{name:'聊天交办',exact:true}).click();await page.getByRole('button',{name:'准备交办',exact:true}).click();await page.waitForURL(/bossPage=F06/);await page.locator('.boss-task-row').filter({hasText:source.content}).click();await page.getByRole('button',{name:'新建当前任务会话',exact:true}).click();await page.waitForURL(/bossPage=N02/);await expect(page.getByLabel('固定任务上下文',{exact:true})).toContainText(task.task_id);
    const sizes=[{width:1440,height:1000},{width:1280,height:800},{width:1024,height:768}];
    async function configure(size,zoom){await desktop.evaluate(({BrowserWindow},{size,zoom})=>{const window=BrowserWindow.getAllWindows()[0];window.setContentSize(size.width,size.height);window.webContents.setZoomFactor(zoom);},{size,zoom});await page.waitForFunction(({size,zoom})=>innerWidth===size.width/zoom&&innerHeight===size.height/zoom,{size,zoom});}
    async function measure(name,controls){
      const bounds=[];
      for(const control of controls){await control.scrollIntoViewIfNeeded();const value=await control.evaluate(element=>{const box=element.getBoundingClientRect(),style=getComputedStyle(element);return {label:element.getAttribute('aria-label')??element.textContent,x:box.x,y:box.y,width:box.width,height:box.height,right:box.right,bottom:box.bottom,fontSize:style.fontSize,lineHeight:style.lineHeight,outlineStyle:style.outlineStyle,outlineWidth:style.outlineWidth,outlineColor:style.outlineColor,outlineOffset:style.outlineOffset,boxShadow:style.boxShadow,innerWidth:innerWidth,innerHeight:innerHeight};});assert(value.width>=44&&value.height>=44,JSON.stringify(value));assert(value.x>=-1&&value.right<=value.innerWidth+1,JSON.stringify(value));assert(value.y>=-1&&value.bottom<=value.innerHeight+1,JSON.stringify(value));bounds.push(value);}
      const layout=await page.evaluate(()=>({innerWidth,innerHeight,documentWidth:document.documentElement.scrollWidth,bodyWidth:document.body.scrollWidth}));assert(layout.documentWidth<=layout.innerWidth+1,JSON.stringify(layout));return {name,layout,bounds};
    }
    stage='BOUND_TASK_LAYOUT';const bound=[];
    for(const size of sizes)for(const zoom of [1,2]){await configure(size,zoom);bound.push({size,zoom,...await measure('BOUND_TASK',[page.getByLabel('固定任务上下文',{exact:true}).getByRole('button',{name:'返回关联任务',exact:true}),page.locator('[data-task-entry-source="'+source.source_id+'"]').getByRole('button',{name:'核查任务来源原文',exact:true}),page.getByRole('button',{name:'查看最新进展',exact:true})])});}
    records.push({check:'actual_bound_task_six_viewports',task_id:task.task_id,task_version:task.version,measurements:bound});save('IN_PROGRESS');
    await configure(sizes[0],1);await page.getByRole('button',{name:'查看消息草稿与回复',exact:true}).click();await page.waitForURL(/bossPage=F08/);const outbox=await read('/api/boss/ui/workspace/outbox'),contact=outbox.contacts.find(item=>item.contact_id==='coordinator-1');assert(contact);
    await page.getByRole('combobox',{name:/^选择唯一联系人/}).selectOption(contact.contact_id);await page.getByLabel('消息正文',{exact:true}).fill(source.content);await page.getByLabel('有权附件来源标识',{exact:true}).fill(source.source_id);await page.getByLabel('附件当前版本',{exact:true}).fill(source.version);
    stage='SHARED_F08_LAYOUT';const messages=[];
    for(const size of sizes)for(const zoom of [1,2]){await configure(size,zoom);messages.push({size,zoom,...await measure('SHARED_F08',[page.getByRole('button',{name:'返回原会话',exact:true}),page.getByRole('button',{name:'保存当前草稿',exact:true}),page.getByRole('button',{name:'重新读取',exact:true})])});await expect(page.getByLabel('消息正文',{exact:true})).toHaveValue(source.content);}
    records.push({check:'actual_shared_f08_six_viewports',source_id:source.source_id,source_version:source.version,measurements:messages});save('IN_PROGRESS');
    stage='D06_VISIBLE_KEYBOARD_FOCUS';const focus=[];
    for(const size of sizes)for(const zoom of [1,2]){
      await configure(size,zoom);await page.getByRole('button',{name:'返回原会话',exact:true}).click();const dialog=page.getByRole('dialog').filter({hasText:'未保存修改（D06）'});await expect(dialog).toBeVisible();
      const keep=dialog.getByRole('button',{name:'返回继续编辑',exact:true}),discard=dialog.getByRole('button',{name:'放弃草稿并离开',exact:true});
      const measured=await measure('D06',[keep,discard]);await page.keyboard.press('Tab');await page.keyboard.press('Shift+Tab');
      const active=await dialog.evaluate(element=>{const active=document.activeElement;if(!active||!element.contains(active))throw new Error('焦点没有保持在D06');const style=getComputedStyle(active);return {label:active.textContent,outlineStyle:style.outlineStyle,outlineWidth:style.outlineWidth,outlineColor:style.outlineColor,outlineOffset:style.outlineOffset,boxShadow:style.boxShadow};});
      assert((active.outlineStyle!=='none'&&parseFloat(active.outlineWidth)>0)||active.boxShadow!=='none',JSON.stringify(active));focus.push({size,zoom,...measured,keyboard_focus:active});await keep.click();await expect(page.getByLabel('消息正文',{exact:true})).toHaveValue(source.content);
    }
    records.push({check:'actual_shared_d06_six_viewports_visible_focus',measurements:focus});assert.equal((await read('/api/boss/ui/workspace/outbox')).sent_messages.length,outbox.sent_messages.length);save('PASS');
  }finally{
    if(socket)socket.close();if(desktop){await desktop.evaluate(({BrowserWindow})=>{for(const window of BrowserWindow.getAllWindows())window.destroy();});await desktop.close();}
  }
}
main().then(()=>console.log(JSON.stringify({status:'PASS',report:output})),failure=>{records.push({check:'failure',stage,error_type:failure.name,message:failure.message});save('FAIL');console.error(JSON.stringify({status:'FAIL',stage,error_type:failure.name,message:failure.message}));process.exitCode=1;});
