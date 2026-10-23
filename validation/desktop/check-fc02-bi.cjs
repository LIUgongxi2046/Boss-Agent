const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {randomUUID,createHash}=require('node:crypto');
const {_electron:electron}=require('playwright');
const {expect}=require('@playwright/test');
const access=require('./account-access.cjs');
const root=path.resolve(__dirname,'../..'),validation=path.join(root,'validation');
const runId='fc02-bi-'+randomUUID(),directory=path.join(validation,'.work',runId);
const accounts=access.provision(directory),ports={business:9671,webui:9672,gateway:19671};
const origin='http://127.0.0.1:'+ports.webui,frontend=process.env.BOSS_PRODUCT_FRONTEND_DIR;
assert(frontend&&path.isAbsolute(frontend));
const output=path.join(root,'evidence/feature-delivery/FC02',runId+'.json'),records=[];
const hash=file=>createHash('sha256').update(fs.readFileSync(file)).digest('hex');
function save(status){fs.writeFileSync(output,JSON.stringify({status,run_id:runId,ports,application_directory:directory,
  frontend_directory:frontend,manifest_sha256:hash(path.join(frontend,'asset-manifest.json')),
  inputs:['app/webui/BossDesktop.tsx','app/webui/boss-v6.css','validation/boss_page_api.py','specs/product-bi.openapi.yaml'].map(file=>({path:file,sha256:hash(path.join(root,file))})),
  scope:'当前公开产品范围、变化、精度、公式和原查询依据；完整FC02二十项尚未验收',external_api_mode:'SIMULATED_FIRST',model_requests:0,visual:'NOT_RUN',records},null,2));}
async function main(){let desktop;
  try{
    desktop=await electron.launch({args:[__dirname],cwd:validation,timeout:60000,env:{...process.env,
      BOSS_VALIDATION_ROOT:validation,BOSS_PRODUCT_UI:'1',BOSS_APPLICATION_WORK_DIR:directory,
      BOSS_APPLICATION_PORTS:JSON.stringify(ports),BOSS_DESKTOP_TEST_WINDOW_HIDDEN:'1',TMPDIR:path.join(validation,'.work/tmp')}});
    const page=await desktop.firstWindow({timeout:120000});await page.waitForURL(origin+'/');
    const errors=[];page.on('pageerror',error=>errors.push(error.name));
    async function navigate(id){await page.locator('button.boss-search').click();const dialog=page.getByRole('dialog',{name:'全部页面导航',exact:true});
      await dialog.getByPlaceholder('搜索页面编号或名称',{exact:true}).fill(id);await dialog.getByRole('button',{name:new RegExp('^'+id+' · ')}).click();}
    await access.login(page,accounts,'BOSS');await navigate('F03');
    await expect(page.getByRole('button',{name:'读取本次查询原始依据',exact:true})).toBeDisabled();
    const firstResponse=page.waitForResponse(response=>new URL(response.url()).pathname==='/api/boss/ui/metrics');
    await page.getByRole('button',{name:'提交查询',exact:true}).focus();await page.keyboard.press('Enter');
    const first=await (await firstResponse).json();
    const table=page.locator('.boss-bi-table');await expect(table).toBeVisible();
    const margin=table.getByRole('row').filter({has:page.getByRole('rowheader',{name:'毛利率',exact:true})});
    await expect(margin.getByRole('cell').last()).toHaveText(/-2(?:\.0+)?\s+百分点/);
    const profit=table.getByRole('row').filter({has:page.getByRole('rowheader',{name:'毛利',exact:true})});
    await expect(profit.getByRole('cell').last()).toHaveText(/-4(?:\.0+)?\s+%/);
    await expect(page.getByRole('heading',{name:'原始精度与计算公式',exact:true})).toBeVisible();
    await page.getByLabel('产品范围',{exact:true}).selectOption('product-1');await expect(table).toHaveCount(0);
    const secondResponse=page.waitForResponse(response=>new URL(response.url()).pathname==='/api/boss/ui/metrics'&&new URL(response.url()).searchParams.get('products')==='product-1');
    await page.getByRole('button',{name:'提交查询',exact:true}).click();const second=await (await secondResponse).json();
    assert.notEqual(first.result.query_id,second.result.query_id);
    const revenue=table.getByRole('row').filter({has:page.getByRole('rowheader',{name:'营业收入',exact:true})});
    await expect(revenue.getByRole('cell').nth(1)).toHaveText('24000000');
    const evidenceResponse=page.waitForResponse(response=>new URL(response.url()).pathname==='/api/boss/ui/metrics-evidence');
    await page.getByRole('button',{name:'读取本次查询原始依据',exact:true}).click();const evidence=await (await evidenceResponse).json();
    assert.equal(evidence.query_id,second.result.query_id);
    const details=evidence.result.original_records.filter(record=>record.content.product_id!==undefined);
    assert.equal(details.length,4);assert(details.every(record=>record.content.product_id==='product-1'));
    const evidencePanel=page.locator('section.boss-panel').filter({has:page.getByRole('heading',{name:'本次查询原始依据',exact:true})});
    await expect(evidencePanel.locator('details')).toHaveCount(evidence.result.original_records.length);
    const auth=await access.bootstrap(origin,accounts,'BOSS'),maint=await access.bootstrap(origin,accounts,'MAINTAINER');
    const route=origin+'/api/boss/ui/metrics-evidence?query_id='+encodeURIComponent(second.result.query_id);
    assert.equal((await fetch(route)).status,401);
    assert.equal((await fetch(route,{headers:{Authorization:'Bearer '+maint.api_token}})).status,403);
    assert.equal((await fetch(route+'&owner_id=other',{headers:{Authorization:'Bearer '+auth.api_token}})).status,400);
    records.push({check:'query_change_precision_and_scoped_evidence',query_ids:[first.result.query_id,second.result.query_id],matching_detail_count:details.length,unauthenticated:401,maintainer:403,extra_scope:400});save('IN_PROGRESS');
    const style=await table.evaluate(element=>({font:getComputedStyle(element).fontSize,line:getComputedStyle(element).lineHeight}));
    assert.deepEqual(style,{font:'16px',line:'24px'});
    const product=page.getByLabel('产品范围',{exact:true});const field=await product.evaluate(element=>({font:getComputedStyle(element.closest('label')).fontSize,line:getComputedStyle(element.closest('label')).lineHeight,input:getComputedStyle(element).fontSize}));
    assert.deepEqual(field,{font:'14px',line:'22px',input:'16px'});
    await product.focus();await page.keyboard.press('Tab');await expect(page.getByLabel('指标口径',{exact:true})).toBeFocused();
    await page.getByRole('button',{name:'打开当前来源原文',exact:true}).click();await page.waitForURL(/bossPage=D01/);
    await expect(page.locator('.boss-document-source')).toBeVisible();
    const sourceStyle=await page.locator('.boss-document-source').evaluate(element=>({font:getComputedStyle(element).fontSize,line:getComputedStyle(element).lineHeight}));assert.deepEqual(sourceStyle,{font:'16px',line:'24px'});
    for(const [width,height] of [[1024,768],[1280,800],[1440,1024]])for(const zoom of [1,2]){
      await desktop.evaluate(({BrowserWindow},{width,height,zoom})=>{const window=BrowserWindow.getAllWindows()[0];window.setContentSize(width,height);window.webContents.setZoomFactor(zoom);},{width,height,zoom});
      for(const pageId of ['F03','N03','D01']){await navigate(pageId);await page.locator('.boss-hero .boss-eyebrow').filter({hasText:'· '+pageId}).waitFor();
        if(pageId==='F03'||pageId==='N03')await expect(page.locator('.boss-bi-table')).toBeVisible();
        else await expect(page.locator('.boss-document-source')).toBeVisible();
        const size=await page.evaluate(()=>({width:document.documentElement.clientWidth,scroll:document.documentElement.scrollWidth}));assert(size.scroll<=size.width+1,pageId);
        records.push({check:'dom_bounds',page_id:pageId,native_width:width,native_height:height,zoom,...size});}
    }
    assert.deepEqual(errors,[]);records.push({check:'tokens_keyboard_renderer',table:style,source:sourceStyle,field,enter:true,tab:true,renderer_errors:0});save('PASS');
  }finally{if(desktop)await desktop.close();}
}
main().then(()=>console.log(JSON.stringify({status:'PASS',report:output})),error=>{records.push({check:'failure',name:error.name,message:String(error.message).slice(0,1400)});save('FAIL');console.error(JSON.stringify({status:'FAIL',report:output}));process.exitCode=1;});
