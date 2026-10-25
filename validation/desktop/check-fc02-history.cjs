const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {execFileSync}=require('node:child_process');
const {randomUUID,createHash}=require('node:crypto');
const {_electron:electron}=require('playwright');
const {expect:baseExpect}=require('@playwright/test');
const expect=baseExpect.configure({timeout:20000});
const access=require('./account-access.cjs');
const root=path.resolve(__dirname,'../..'),validation=path.join(root,'validation');
const runId='fc02-history-'+randomUUID(),directory=path.join(validation,'.work',runId),ports={business:9761,webui:9762,gateway:19761};
const origin='http://127.0.0.1:'+ports.webui,frontend=process.env.BOSS_PRODUCT_FRONTEND_DIR;
assert(frontend&&path.isAbsolute(frontend));
const accounts=access.provision(directory),records=[],output=path.join(root,'evidence/feature-delivery/FC02',runId+'.json');
function inspect(action='inspect'){return JSON.parse(execFileSync(path.join(validation,'.venv/bin/python'),[path.join(validation,'fc02_history_check.py'),directory,action],
  {cwd:root,env:{...process.env,TMPDIR:path.join(validation,'.work/tmp')},timeout:30000,encoding:'utf8'}));}
function save(status){fs.writeFileSync(output,JSON.stringify({status,defect_id:'FC02-N4-UI-HISTORY-01',run_id:runId,ports,application_directory:directory,
  frontend_directory:frontend,manifest_sha256:createHash('sha256').update(fs.readFileSync(path.join(frontend,'asset-manifest.json'))).digest('hex'),
  external_api_mode:'SIMULATED_FIRST',visual:'NOT_RUN',records},null,2));}
async function launch(){const desktop=await electron.launch({args:[__dirname],cwd:validation,timeout:60000,env:{...process.env,
  BOSS_VALIDATION_ROOT:validation,BOSS_PRODUCT_UI:'1',BOSS_APPLICATION_WORK_DIR:directory,BOSS_APPLICATION_PORTS:JSON.stringify(ports),
  BOSS_DESKTOP_TEST_WINDOW_HIDDEN:'1',TMPDIR:path.join(validation,'.work/tmp')}});
  const page=await desktop.firstWindow({timeout:120000});await page.waitForURL(origin+'/');return {desktop,page};}
async function main(){let desktop,page;
  try{
    ({desktop,page}=await launch());await access.login(page,accounts,'BOSS');await page.goto(origin+'/?bossPage=F03');
    await expect(page.getByRole('button',{name:'提交查询',exact:true})).toBeEnabled();
    await page.getByRole('button',{name:'提交查询',exact:true}).focus();await page.keyboard.press('Enter');await expect(page.locator('.boss-bi-table')).toBeVisible();
    let key=new URL(page.url()).searchParams.get('biRequest');assert(key);
    const auth=await access.bootstrap(origin,accounts,'BOSS');
    async function get(route,token=auth.api_token){const response=await fetch(origin+'/api/boss/ui/'+route,{headers:{Authorization:'Bearer '+token}});return {status:response.status,body:response.status===401?null:await response.json()};}
    const original=await get('bi/receipt?client_request_id='+key);assert.equal(original.status,200);let query=original.body.receipt.query.result;
    await page.getByRole('button',{name:'读取本次查询原始依据',exact:true}).click();
    const evidencePanel=()=>page.locator('section.boss-panel').filter({has:page.getByRole('heading',{name:'本次查询原始依据',exact:true})});
    await expect(evidencePanel().locator('details')).toHaveCount(query.detail_refs.length+1);
    const parent=query.query_id;
    await page.getByLabel('产品范围',{exact:true}).selectOption(['product-1']);await page.getByLabel('经营问题',{exact:true}).fill('继续查询product-1');
    await page.getByRole('button',{name:'提交查询',exact:true}).click();await expect(page.locator('.boss-bi-table')).toBeVisible();
    key=new URL(page.url()).searchParams.get('biRequest');query=(await get('bi/receipt?client_request_id='+key)).body.receipt.query.result;
    assert.equal(query.parent_query_id,parent);assert.equal(query.detail_refs.length,4);
    const before=inspect();assert.equal(before.counts.query,2);assert.equal(before.counts.runtime_run,2);
    records.push({check:'valid_query_and_evidence',client_request_id:key,query_id:query.query_id,counts:before.counts});save('IN_PROGRESS');
    await desktop.close();desktop=null;const withdrawn=inspect('withdraw');assert.equal(withdrawn.source_withdrawn,true);
    ({desktop,page}=await launch());await access.login(page,accounts,'BOSS');
    const fresh=await access.bootstrap(origin,accounts,'BOSS');
    const dimensions=await get('bi/dimensions',fresh.api_token),history=await get('bi/history',fresh.api_token),receipt=await get('bi/receipt?client_request_id='+key,fresh.api_token);
    assert.equal(dimensions.status,410);assert.equal(history.status,200);assert.equal(receipt.status,200);assert.equal(receipt.body.receipt.query.adoption_state,'HISTORICAL_REQUIRES_REQUERY');
    assert.equal(receipt.body.receipt.query.result.query_id,query.query_id);
    await page.goto(origin+'/?bossPage=F03&biRequest='+key);
    const actual={api:{dimensions:dimensions.status,history:history.status,receipt:receipt.status},history_count:history.body.requests.length};
    await page.getByRole('alert').filter({hasText:'WITHDRAWN'}).waitFor();
    actual.history_buttons=await page.locator('.boss-bi-history button').count();actual.restore_disabled=await page.getByRole('button',{name:'读取原请求结果',exact:true}).isDisabled();
    records.push({check:'withdrawn_initial_state',...actual});save('IN_PROGRESS');
    await expect(page.locator('.boss-bi-history button')).toHaveCount(history.body.requests.length);
    await expect(page.getByText(/HISTORICAL_REQUIRES_REQUERY/)).toBeVisible();await expect(page.locator('.boss-bi-table')).toBeVisible();
    await expect(page.getByRole('button',{name:'读取原请求结果',exact:true})).toBeEnabled();
    await expect(page.getByRole('button',{name:'提交查询',exact:true})).toBeDisabled();
    await expect(page.getByRole('button',{name:'读取本次查询原始依据',exact:true})).toBeDisabled();
    await expect(page.getByRole('button',{name:'打开当前来源原文',exact:true})).toBeDisabled();
    await expect(page.locator('.boss-document-source')).toHaveCount(0);await expect(evidencePanel().locator('details')).toHaveCount(0);
    await expect(page.getByLabel('法人',{exact:true})).toHaveValue(query.context_snapshot.legal_entity_id);
    await expect(page.getByLabel('产品范围',{exact:true})).toHaveValues(query.context_snapshot.product_ids);
    await expect(page.getByLabel('指标范围',{exact:true})).toHaveValues(query.context_snapshot.metric_ids);
    const response=page.waitForResponse(value=>new URL(value.url()).pathname==='/api/boss/ui/bi/receipt');
    await page.getByRole('button',{name:'读取原请求结果',exact:true}).focus();await page.keyboard.press('Enter');assert.equal((await response).status(),200);
    await expect(page.getByText(/HISTORICAL_REQUIRES_REQUERY/)).toBeVisible();
    await page.locator('.boss-bi-history button').filter({hasText:key}).focus();await page.keyboard.press('Enter');await expect(page.locator('.boss-bi-table')).toBeVisible();
    await page.reload();await expect(page.getByText(/HISTORICAL_REQUIRES_REQUERY/)).toBeVisible();
    await page.goto(origin+'/?bossPage=N03');await expect(page.getByText(/HISTORICAL_REQUIRES_REQUERY/)).toContainText(query.query_id);
    assert.equal((await get('metrics-evidence?query_id='+query.query_id,fresh.api_token)).status,410);
    assert.equal((await get('bi/query?query_id='+query.query_id,fresh.api_token)).status,410);
    assert.deepEqual(inspect().counts,before.counts);
    records.push({check:'withdrawn_history_receipt_refresh_restart',client_request_id:key,query_id:query.query_id,current_source_status:410,historical_state:'HISTORICAL_REQUIRES_REQUERY',counts:inspect().counts});save('IN_PROGRESS');
    for(const [width,height] of [[1024,768],[1280,800],[1440,1024]])for(const zoom of [1,2]){
      await desktop.evaluate(({BrowserWindow},{width,height,zoom})=>{const window=BrowserWindow.getAllWindows()[0];window.setContentSize(width,height);window.webContents.setZoomFactor(zoom);},{width,height,zoom});
      for(const id of ['F03','N03']){await page.goto(origin+'/?bossPage='+id+'&biRequest='+key);await expect(page.getByText(/HISTORICAL_REQUIRES_REQUERY/)).toBeVisible();
        const bounds=await page.evaluate(()=>({width:document.documentElement.clientWidth,scroll:document.documentElement.scrollWidth}));assert(bounds.scroll<=bounds.width+1);
        records.push({check:'historical_dom_bounds',page_id:id,native_width:width,native_height:height,zoom,...bounds});}
    }
    await expect.poll(async()=>(await get('bi/history',fresh.api_token)).status,{timeout:45000,intervals:[500,1000]}).toBe(401);
    await expect(page.getByLabel('账号',{exact:true})).toBeEnabled();await expect(page.locator('.boss-bi-table')).toHaveCount(0);await expect(page.locator('.boss-bi-history button')).toHaveCount(0);
    await access.login(page,accounts,'BOSS');await page.goto(origin+'/?bossPage=F03&biRequest='+key);await expect(page.getByText(/HISTORICAL_REQUIRES_REQUERY/)).toBeVisible();
    await access.logout(page);await expect(page.locator('.boss-bi-history button')).toHaveCount(0);await expect(page.locator('.boss-bi-table')).toHaveCount(0);
    await access.login(page,accounts,'MAINTAINER');await page.goto(origin+'/?bossPage=F03&biRequest='+key);await expect(page.locator('.boss-bi-view')).toHaveCount(0);
    const maint=await access.bootstrap(origin,accounts,'MAINTAINER');for(const route of ['bi/dimensions','bi/history','bi/receipt?client_request_id='+key,'bi/query?query_id='+query.query_id])assert.equal((await get(route,maint.api_token)).status,403);
    assert.deepEqual(inspect().counts,before.counts);records.push({check:'expired_logout_maintainer',expired_status:401,maintainer_status:403,protected_history_cleared:true,reauthentication_restored:true,counts:inspect().counts});save('PASS');
  }finally{if(desktop)await desktop.close();}
}
main().then(()=>console.log(JSON.stringify({status:'PASS',report:output})),error=>{records.push({check:'failure',name:error.name,message:String(error.message).slice(0,1600)});save('FAIL');console.error(JSON.stringify({status:'FAIL',report:output}));process.exitCode=1;});
