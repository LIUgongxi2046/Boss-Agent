const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {spawn}=require('node:child_process');
const {once}=require('node:events');
const {randomUUID,createHash}=require('node:crypto');
const {_electron:electron}=require('playwright');
const {expect:baseExpect}=require('@playwright/test');
const expect=baseExpect.configure({timeout:20000});
const access=require('./account-access.cjs');
const root=path.resolve(__dirname,'../..'),validation=path.join(root,'validation'),frontend=process.env.BOSS_PRODUCT_FRONTEND_DIR;
assert(frontend&&path.isAbsolute(frontend));
const runId='fc03-order-'+randomUUID(),directory=path.join(validation,'.work',runId),accounts=access.provision(directory);
const ports={business:9941,webui:9942,gateway:19941},proxyPort=9943,origin='http://127.0.0.1:'+proxyPort,records=[];
const output=path.join(root,'evidence/feature-delivery/FC03',runId+'.json');
function save(status){fs.writeFileSync(output,JSON.stringify({status,run_id:runId,ports,proxy_port:proxyPort,application_directory:directory,frontend_directory:frontend,
  manifest_sha256:createHash('sha256').update(fs.readFileSync(path.join(frontend,'asset-manifest.json'))).digest('hex'),external_api_mode:'SIMULATED_FIRST',visual:'NOT_RUN',records},null,2));}
async function main(){let desktop,proxy;
  try{
    proxy=spawn(path.join(validation,'.venv/bin/python'),[path.join(__dirname,'fc03_order_proxy.py'),String(ports.webui),String(proxyPort)],
      {cwd:root,env:{...process.env,TMPDIR:path.join(validation,'.work/tmp')},stdio:['ignore',fs.openSync(path.join(directory,'proxy.stdout.log'),'w'),fs.openSync(path.join(directory,'proxy.stderr.log'),'w')]});
    desktop=await electron.launch({args:[__dirname],cwd:validation,timeout:60000,env:{...process.env,BOSS_VALIDATION_ROOT:validation,BOSS_PRODUCT_UI:'1',BOSS_APPLICATION_WORK_DIR:directory,
      BOSS_APPLICATION_PORTS:JSON.stringify(ports),BOSS_DESKTOP_TEST_WINDOW_HIDDEN:'1',TMPDIR:path.join(validation,'.work/tmp')}});
    const page=await desktop.firstWindow({timeout:120000});await page.waitForURL('http://127.0.0.1:'+ports.webui+'/');
    await desktop.evaluate(async({BrowserWindow},url)=>BrowserWindow.getAllWindows()[0].loadURL(url),origin+'/');await page.waitForURL(origin+'/');
    await access.login(page,accounts,'BOSS');
    const auth=await access.bootstrap(origin,accounts,'BOSS');
    async function get(route){const response=await fetch(origin+route,{headers:{Authorization:'Bearer '+auth.api_token}});assert.equal(response.status,200);return response.json();}
    async function state(){const response=await fetch(origin+'/_order/state');assert.equal(response.status,200);return response.json();}
    const view=await get('/api/boss/ui/today');assert(view.items.length>=2);
    await page.getByRole('button',{name:'降低事项次序：'+view.items[0].title,exact:true}).click();
    await page.getByRole('button',{name:'本人确认保存当前次序',exact:true}).click();
    await expect.poll(async()=>(await state()).dropped).toBe(true);await expect.poll(async()=>(await state()).connections).toBeGreaterThanOrEqual(2);
    const trace=await state();records.push({check:'actual_order_result_interrupted',...trace});save('IN_PROGRESS');
    await expect(page.getByRole('button',{name:'读取排序原请求结果',exact:true})).toBeEnabled();
    const key=new URL(page.url()).searchParams.get('todayOrderRequest');assert(key);assert.equal(key,trace.events.find(row=>row.event==='actual_order_forwarded').client_request_id);
    await page.getByRole('button',{name:'读取排序原请求结果',exact:true}).click();
    await expect(page.getByText('排序回执 RECORDED',{exact:true})).toBeVisible();await expect(page.getByText('当前排序版本 1',{exact:true})).toBeVisible();
    const saved=await get('/api/boss/ui/operation-status?action=boss.today.reorder&client_request_id='+key);
    assert.equal(saved.outcome,'RECORDED');assert.equal(saved.result.version,'1');assert.equal(saved.write_performed_by_lookup,false);
    const expected=view.items.map(item=>item.item_id);[expected[0],expected[1]]=[expected[1],expected[0]];
    assert.deepEqual((await get('/api/boss/ui/today')).items.map(item=>item.item_id),expected);
    await page.reload();await expect(page.getByText('排序回执 RECORDED',{exact:true})).toBeVisible();await expect(page.getByText('当前排序版本 1',{exact:true})).toBeVisible();
    assert.equal(new URL(page.url()).searchParams.get('todayOrderRequest'),key);
    const final=await state();assert.equal(final.events.filter(row=>row.event==='actual_order_forwarded').length,1);
    const unknownKey='today-unknown-'+randomUUID();await page.goto(origin+'/?bossPage=F01&todayOrderRequest='+unknownKey);
    await expect(page.getByText('排序回执 NOT_FOUND_IN_CURRENT_STORE',{exact:true})).toBeVisible();
    await expect(page.getByRole('button',{name:'本人确认保存当前次序',exact:true})).toBeDisabled();
    await page.getByRole('button',{name:'读取排序原请求结果',exact:true}).click();
    await expect(page.getByText('排序回执 NOT_FOUND_IN_CURRENT_STORE',{exact:true})).toBeVisible();
    assert.equal((await state()).events.filter(row=>row.event==='actual_order_forwarded').length,1);
    const maint=await access.bootstrap(origin,accounts,'MAINTAINER');
    const statusRoute=origin+'/api/boss/ui/operation-status?action=boss.today.reorder&client_request_id='+key;
    assert.equal((await fetch(statusRoute,{headers:{Authorization:'Bearer '+maint.api_token}})).status,403);
    assert.equal((await fetch(statusRoute)).status,401);
    records.push({check:'original_order_receipt_read_only_and_refresh',client_request_id:key,order_version:saved.result.version,item_ids:expected,
      write_performed_by_lookup:false,request_replayed:false,transport_events:final.events,unknown_request_remains_unknown:true,maintainer_status:403,anonymous_status:401});save('PASS');
  }finally{if(desktop)await desktop.close();if(proxy&&proxy.exitCode===null){const ended=once(proxy,'exit');proxy.kill('SIGTERM');await ended;}}
}
main().then(()=>console.log(JSON.stringify({status:'PASS',report:output})),failure=>{records.push({check:'failure',name:failure.name,message:String(failure.message).slice(0,1200)});save('FAIL');console.error(JSON.stringify({status:'FAIL',report:output}));process.exitCode=1;});
