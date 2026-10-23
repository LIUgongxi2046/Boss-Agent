const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {randomUUID,createHash}=require('node:crypto');
const {_electron:electron}=require('playwright');
const {expect:baseExpect}=require('@playwright/test');
const expect=baseExpect.configure({timeout:20000});
const access=require('./account-access.cjs');
const root=path.resolve(__dirname,'../..'),validation=path.join(root,'validation');
const runId='fc02-scoped-'+randomUUID(),directory=path.join(validation,'.work',runId),ports={business:9681,webui:9682,gateway:19681};
const origin='http://127.0.0.1:'+ports.webui,frontend=process.env.BOSS_PRODUCT_FRONTEND_DIR;
assert(frontend&&path.isAbsolute(frontend));
const accounts=access.provision(directory),records=[],output=path.join(root,'evidence/feature-delivery/FC02',runId+'.json');
const hash=file=>createHash('sha256').update(fs.readFileSync(file)).digest('hex');
function save(status){fs.writeFileSync(output,JSON.stringify({status,run_id:runId,ports,application_directory:directory,frontend_directory:frontend,
  manifest_sha256:hash(path.join(frontend,'asset-manifest.json')),external_api_mode:'SIMULATED_FIRST',visual:'NOT_RUN',records},null,2));}
async function main(){let desktop;
  try{
    desktop=await electron.launch({args:[__dirname],cwd:validation,timeout:60000,env:{...process.env,BOSS_VALIDATION_ROOT:validation,BOSS_PRODUCT_UI:'1',
      BOSS_APPLICATION_WORK_DIR:directory,BOSS_APPLICATION_PORTS:JSON.stringify(ports),BOSS_DESKTOP_TEST_WINDOW_HIDDEN:'1',TMPDIR:path.join(validation,'.work/tmp')}});
    const page=await desktop.firstWindow({timeout:120000});await page.waitForURL(origin+'/');const errors=[];page.on('pageerror',error=>errors.push(error.name));
    async function navigate(id){await page.locator('button.boss-search').click();const dialog=page.getByRole('dialog',{name:'全部页面导航',exact:true});
      await dialog.getByPlaceholder('搜索页面编号或名称',{exact:true}).fill(id);await dialog.getByRole('button',{name:new RegExp('^'+id+' · ')}).click();}
    await access.login(page,accounts,'BOSS');await navigate('F03');
    await expect(page.getByLabel('法人',{exact:true})).toHaveValue('entity-1');
    await expect(page.getByLabel('目标版本',{exact:true})).toHaveValue('');
    await page.getByLabel('查询方式',{exact:true}).focus();await page.keyboard.press('Tab');await expect(page.getByLabel('经营问题',{exact:true})).toBeFocused();
    const auth=await access.bootstrap(origin,accounts,'BOSS'),maint=await access.bootstrap(origin,accounts,'MAINTAINER');
    let headers={Authorization:'Bearer '+auth.api_token};
    async function get(route,tokenHeaders=headers){const response=await fetch(origin+route,{headers:tokenHeaders});assert.equal(response.status,200);return response.json();}
    async function current(){const key=new URL(page.url()).searchParams.get('biRequest');assert(key);return get('/api/boss/ui/bi/receipt?client_request_id='+key);}
    await page.getByRole('button',{name:'提交查询',exact:true}).focus();await page.keyboard.press('Enter');
    const table=page.locator('.boss-bi-table');await expect(table).toBeVisible();const first=await current();
    assert.equal(first.request_state,'SUCCEEDED');const parent=first.receipt.query.result;
    assert.equal(parent.source_type,'SIMULATED');
    const expected={sales_quantity:'20',revenue:'20',gross_profit:'-4',gross_margin:'-2',gross_profit_per_tonne:'-20'};
    for(const [metric,value] of Object.entries(expected)){const change=parent.values.find(item=>item.metric_id===metric&&item.period_scope==='CHANGE');assert.equal(Number(change.value),Number(value));}
    await page.getByLabel('产品范围',{exact:true}).selectOption(['product-1']);await expect(table).toHaveCount(0);
    await expect(page.getByText('明确覆盖：产品范围',{exact:true})).toBeVisible();
    await page.getByLabel('经营问题',{exact:true}).fill('继续查询product-1');await page.getByRole('button',{name:'提交查询',exact:true}).click();await expect(table).toBeVisible();
    const second=await current(),child=second.receipt.query.result;assert.notEqual(child.query_id,parent.query_id);assert.equal(child.parent_query_id,parent.query_id);
    assert.equal(child.detail_refs.length,4);assert.deepEqual(child.context_snapshot.product_ids,['product-1']);assert.deepEqual(child.overridden_fields,['product_ids']);
    await page.getByRole('button',{name:'读取本次查询原始依据',exact:true}).click();
    const evidencePanel=page.locator('section.boss-panel').filter({has:page.getByRole('heading',{name:'本次查询原始依据',exact:true})});
    await expect(evidencePanel.locator('details')).toHaveCount(5);
    const run=(await get('/api/boss/ui/runtime-records?run_id='+second.run_id,{Authorization:'Bearer '+maint.api_token})).runs[0];
    assert.equal(run.feature_id,'FC02');assert.deepEqual(run.tool_configuration.map(item=>item.tool_id).sort(),['query_metrics','read_evidence']);
    assert.deepEqual(run.tool_results.map(item=>item.query_id),[child.query_id,child.query_id]);assert.equal(run.usage,null);assert.equal(run.cost_total,null);
    assert(!JSON.stringify(run).includes('继续查询product-1'));
    records.push({check:'public_scoped_query_followup_runtime',parent_query_id:parent.query_id,query_id:child.query_id,run_id:second.run_id,detail_count:4,usage:null,cost:null});save('IN_PROGRESS');
    const beforeHistory=await get('/api/boss/ui/bi/history');await page.reload();await expect(table).toBeVisible();assert.equal((await current()).receipt.query.result.query_id,child.query_id);
    assert.deepEqual(await get('/api/boss/ui/bi/history'),beforeHistory);
    await page.getByText('比较期间的业务条件',{exact:true}).click();
    await page.getByRole('checkbox',{name:'单独指定币种',exact:true}).check();await page.getByLabel('比较条件币种',{exact:true}).fill('USD');
    await page.getByRole('button',{name:'提交查询',exact:true}).click();await expect(table).toBeVisible();const incomparable=await current();
    assert.equal(incomparable.receipt.query.result.comparison.state,'INCOMPARABLE');assert(incomparable.receipt.query.result.values.filter(item=>item.period_scope==='CHANGE').every(item=>item.value===null));
    await access.logout(page);await access.login(page,accounts,'BOSS');await navigate('N03');await expect(table).toBeVisible();
    headers={Authorization:'Bearer '+(await access.bootstrap(origin,accounts,'BOSS')).api_token};
    assert.equal((await current()).receipt.query.result.query_id,incomparable.receipt.query.result.query_id);
    for(const route of ['/api/boss/ui/bi/dimensions','/api/boss/ui/bi/receipt?client_request_id='+first.client_request_id,'/api/boss/ui/bi/query?query_id='+parent.query_id]){
      assert.equal((await fetch(origin+route)).status,401);
      const currentMaint=await access.bootstrap(origin,accounts,'MAINTAINER');assert.equal((await fetch(origin+route,{headers:{Authorization:'Bearer '+currentMaint.api_token}})).status,403);
    }
    const style=await table.evaluate(element=>({font:getComputedStyle(element).fontSize,line:getComputedStyle(element).lineHeight}));assert.deepEqual(style,{font:'16px',line:'24px'});
    const field=await page.getByLabel('法人',{exact:true}).evaluate(element=>({font:getComputedStyle(element.closest('label')).fontSize,line:getComputedStyle(element.closest('label')).lineHeight,input:getComputedStyle(element).fontSize}));assert.deepEqual(field,{font:'14px',line:'22px',input:'16px'});
    await page.getByRole('button',{name:'打开当前来源原文',exact:true}).click();await page.waitForURL(/bossPage=D01/);await expect(page.locator('.boss-document-source')).toBeVisible();
    for(const [width,height] of [[1024,768],[1280,800],[1440,1024]])for(const zoom of [1,2]){
      await desktop.evaluate(({BrowserWindow},{width,height,zoom})=>{const window=BrowserWindow.getAllWindows()[0];window.setContentSize(width,height);window.webContents.setZoomFactor(zoom);},{width,height,zoom});
      for(const pageId of ['F03','N03','D01']){await navigate(pageId);await page.locator('.boss-hero .boss-eyebrow').filter({hasText:'· '+pageId}).waitFor();
        if(pageId==='D01')await expect(page.locator('.boss-document-source')).toBeVisible();else await expect(table).toBeVisible();
        const bounds=await page.evaluate(()=>({width:document.documentElement.clientWidth,scroll:document.documentElement.scrollWidth}));assert(bounds.scroll<=bounds.width+1,pageId);records.push({check:'dom_bounds',page_id:pageId,native_width:width,native_height:height,zoom,...bounds});}
    }
    assert.deepEqual(errors,[]);records.push({check:'persistence_comparison_roles_tokens_keyboard',reload:true,relogin:true,incomparable:true,anonymous:401,maintainer:403,style,field,renderer_errors:0});save('PASS');
  }finally{if(desktop)await desktop.close();}
}
main().then(()=>console.log(JSON.stringify({status:'PASS',report:output})),error=>{records.push({check:'failure',name:error.name,message:String(error.message).slice(0,1600)});save('FAIL');console.error(JSON.stringify({status:'FAIL',report:output}));process.exitCode=1;});
