const fs=require('node:fs');
const path=require('node:path');
const assert=require('node:assert/strict');
const {createRequire}=require('node:module');
const {spawn}=require('node:child_process');
const {once}=require('node:events');
const {randomUUID,createHash}=require('node:crypto');
const candidate=path.resolve(__dirname,'../..'),frontend=process.env.BOSS_PRODUCT_FRONTEND_DIR;
assert(frontend&&path.isAbsolute(frontend));
const load=createRequire(path.join(candidate,'validation/desktop/package.json'));
const {_electron:electron}=load('playwright');
const {expect:baseExpect}=load('@playwright/test');
const expect=baseExpect.configure({timeout:20000});
const access=load('./account-access.cjs');
const runId='fc02-n3-timing-'+randomUUID(),directory=path.join(candidate,'validation/.work',runId);
const ports={business:9751,webui:9752,gateway:19751},proxyPort=9753,origin='http://127.0.0.1:'+proxyPort;
const accounts=access.provision(directory),checks=[];
const output=path.join(candidate,'evidence/feature-delivery/FC02',runId+'.json');
let desktop,proxy,page;
async function control(route,body){const response=await fetch(origin+'/_n4/'+route,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  assert.equal(response.status,200);return response.json();}
async function state(){return control('state');}
function save(status,events){fs.writeFileSync(output,JSON.stringify({status,run_id:runId,defect_id:'FC02-N4-UI-ASYNC-01',
  manifest_sha256:createHash('sha256').update(fs.readFileSync(path.join(frontend,'asset-manifest.json'))).digest('hex'),frontend_directory:frontend,
  application_directory:directory,ports,proxy_port:proxyPort,external_api_mode:'SIMULATED_FIRST',visual:'NOT_RUN',
  transport:'真实HTTP/WebSocket双向传递；实际响应字节保持一致，仅延迟指定查询的交付',checks,events},null,2));}
async function main(){
  try{
    proxy=spawn(path.join(candidate,'validation/.venv/bin/python'),[path.join(__dirname,'fc02_timing_proxy.py'),String(ports.webui),String(proxyPort)],
      {cwd:candidate,env:{...process.env,PYTHONDONTWRITEBYTECODE:'1',TMPDIR:path.join(candidate,'validation/.work/tmp')},
        stdio:['ignore',fs.openSync(path.join(directory,'proxy.stdout.log'),'w'),fs.openSync(path.join(directory,'proxy.stderr.log'),'w')]});
    desktop=await electron.launch({args:[path.join(candidate,'validation/desktop')],cwd:path.join(candidate,'validation'),timeout:60000,
      env:{...process.env,PYTHONDONTWRITEBYTECODE:'1',BOSS_VALIDATION_ROOT:path.join(candidate,'validation'),BOSS_PRODUCT_UI:'1',
        BOSS_APPLICATION_WORK_DIR:directory,BOSS_APPLICATION_PORTS:JSON.stringify(ports),BOSS_PRODUCT_FRONTEND_DIR:frontend,
        BOSS_DESKTOP_TEST_WINDOW_HIDDEN:'1',TMPDIR:path.join(candidate,'validation/.work/tmp')}});
    page=await desktop.firstWindow({timeout:120000});await page.waitForURL('http://127.0.0.1:'+ports.webui+'/');
    assert.equal(proxy.exitCode,null);assert.deepEqual(await state(),{gate:null,events:[]});
    await desktop.evaluate(async({BrowserWindow},address)=>{await BrowserWindow.getAllWindows()[0].loadURL(address);},origin+'/');
    await page.waitForURL(origin+'/');await access.login(page,accounts,'BOSS');
    await page.locator('button.boss-search').focus();await page.keyboard.press('Enter');
    const dialog=page.getByRole('dialog',{name:'全部页面导航',exact:true});
    await dialog.getByPlaceholder('搜索页面编号或名称',{exact:true}).fill('F03');await dialog.getByRole('button',{name:/^F03 · /}).click();
    const submit=page.getByRole('button',{name:'提交查询',exact:true});await expect(submit).toBeEnabled();
    await page.getByLabel('产品范围',{exact:true}).selectOption(['product-1']);
    await page.getByLabel('经营问题',{exact:true}).fill('核查较早依据读取的实际时序');await submit.click();await expect(page.locator('.boss-bi-table')).toBeVisible();
    const auth=await access.bootstrap(origin,accounts,'BOSS');
    async function receipt(key){const response=await fetch(origin+'/api/boss/ui/bi/receipt?client_request_id='+key,{headers:{Authorization:'Bearer '+auth.api_token}});
      assert.equal(response.status,200);return response.json();}
    const firstKey=new URL(page.url()).searchParams.get('biRequest');assert(firstKey);
    const first=await receipt(firstKey),firstQuery=first.receipt.query.result;
    assert.deepEqual(firstQuery.context_snapshot.product_ids,['product-1']);
    await control('arm',{path:'/api/boss/ui/metrics-evidence',parameter:'query_id',value:firstQuery.query_id});
    await page.getByRole('button',{name:'读取本次查询原始依据',exact:true}).click();
    await expect.poll(async()=>(await state()).gate.held).toBe(true);
    await page.getByLabel('产品范围',{exact:true}).selectOption(['product-2']);
    await submit.click();await expect(page.locator('.boss-bi-table')).toBeVisible();
    const secondKey=new URL(page.url()).searchParams.get('biRequest');assert(secondKey&&secondKey!==firstKey);
    const second=await receipt(secondKey),secondQuery=second.receipt.query.result;
    assert.notEqual(firstQuery.query_id,secondQuery.query_id);assert.deepEqual(secondQuery.context_snapshot.product_ids,['product-2']);
    assert.equal(secondQuery.parent_query_id,firstQuery.query_id);
    const evidencePanel=page.locator('section.boss-panel').filter({has:page.getByRole('heading',{name:'本次查询原始依据',exact:true})});
    const oldEvidence=page.waitForResponse(response=>{const address=new URL(response.url());return address.pathname==='/api/boss/ui/metrics-evidence'&&address.searchParams.get('query_id')===firstQuery.query_id;});
    await control('release',{});await(await oldEvidence).finished();
    await expect(page.getByRole('button',{name:'读取本次查询原始依据',exact:true})).toBeEnabled();
    await expect(evidencePanel.locator('details')).toHaveCount(0);await expect(page.getByLabel('产品范围',{exact:true})).toHaveValues(['product-2']);
    const comparePanel=page.locator('section.boss-panel').filter({has:page.getByRole('heading',{name:'经营对比',exact:true})});
    await expect(comparePanel).toContainText(secondQuery.query_id);
    checks.push({check:'earlier_evidence_after_new_query',status:'PASS',earlier_query_id:firstQuery.query_id,new_query_id:secondQuery.query_id,
      new_product_ids:['product-2'],earlier_evidence_details_visible:0,earlier_result_replaced_new_scope:false});
    await control('arm',{path:'/api/boss/ui/bi/receipt',parameter:'client_request_id',value:secondKey});
    await page.reload();await expect.poll(async()=>(await state()).gate.held).toBe(true);
    await expect(page.getByLabel('产品范围',{exact:true})).toHaveValues(['product-1','product-2']);
    await page.getByLabel('产品范围',{exact:true}).selectOption(['product-1']);
    await expect(page.getByText('条件已经编辑，请提交查询获取对应结果。',{exact:true})).toBeVisible();
    await expect(page.locator('.boss-bi-table')).toHaveCount(0);
    const lateReceipt=page.waitForResponse(response=>{const address=new URL(response.url());return address.pathname==='/api/boss/ui/bi/receipt'&&address.searchParams.get('client_request_id')===secondKey;});
    await control('release',{});await(await lateReceipt).finished();
    await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
    const selected=await page.getByLabel('产品范围',{exact:true}).evaluate(element=>[...element.selectedOptions].map(option=>option.value));
    const tableCount=await page.locator('.boss-bi-table').count(),dirtyCount=await page.getByText('条件已经编辑，请提交查询获取对应结果。',{exact:true}).count();
    const preserved=JSON.stringify(selected)===JSON.stringify(['product-1'])&&tableCount===0&&dirtyCount===1;
    checks.push({check:'earlier_initial_receipt_after_scope_edit',status:preserved?'PASS':'FAIL',defect_id:preserved?null:'FC02-N4-UI-ASYNC-01',owner:'N3',
      earlier_client_request_id:secondKey,earlier_query_id:secondQuery.query_id,user_edited_product_ids:['product-1'],
      actual_product_ids:selected,actual_table_count:tableCount,dirty_marker_count:dirtyCount,
      expected:'较早恢复响应不得替换用户已经编辑的范围，也不得显示旧范围答案'});
    const trace=(await state()).events;
    const held=trace.filter(event=>event.event==='real_upstream_response_held'),delivered=trace.filter(event=>event.event==='identical_body_delivered');
    assert.equal(held.length,2);assert.equal(delivered.length,2);
    for(let index=0;index<2;index++){assert.equal(held[index].sha256,delivered[index].sha256);assert.equal(held[index].query_id,delivered[index].query_id);assert(held[index].at_monotonic<delivered[index].at_monotonic);}
    save(checks.every(check=>check.status==='PASS')?'PASS':'FAIL',trace);
    console.log(JSON.stringify({status:checks.every(check=>check.status==='PASS')?'PASS':'FAIL',output}));
  }catch(error){
    const current=page&&!page.isClosed()?{url_path:new URL(page.url()).pathname,alerts:await page.getByRole('alert').allTextContents(),login_inputs:await page.getByLabel('账号',{exact:true}).count()}:null;
    checks.push({check:'harness_error',status:'CHECK_ERROR',name:error.name,message:error.message,current});save('CHECK_ERROR',[]);throw error;
  }finally{
    if(desktop)await desktop.close();
    if(proxy&&proxy.exitCode===null){const ended=once(proxy,'exit');proxy.kill('SIGTERM');await ended;}
  }
}
main().catch(error=>{console.error(JSON.stringify({status:'CHECK_ERROR',name:error.name,output}));process.exitCode=1;});
