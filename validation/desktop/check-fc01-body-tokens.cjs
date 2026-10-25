const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {execFileSync}=require('node:child_process');
const {randomUUID,createHash}=require('node:crypto');
const {_electron:electron}=require('playwright');
const {expect}=require('@playwright/test');
const access=require('./account-access.cjs');
const root=path.resolve(__dirname,'../..');
const validation=path.join(root,'validation');
const runId='fc01-c15-'+randomUUID();
const directory=path.join(validation,'.work',runId);
const accounts=access.provision(directory);
const ports={business:9571,webui:9572,gateway:19571};
const frontend=process.env.BOSS_PRODUCT_FRONTEND_DIR;
assert(frontend&&path.isAbsolute(frontend));
const records=[];
const outputDirectory=path.join(root,'evidence/feature-delivery/FC01');
fs.mkdirSync(outputDirectory,{recursive:true});
const output=path.join(outputDirectory,runId+'.json');
const digest=file=>createHash('sha256').update(fs.readFileSync(file)).digest('hex');
function save(status){fs.writeFileSync(output,JSON.stringify({status,run_id:runId,ports,application_directory:directory,
  frontend_directory:frontend,css_sha256:digest(path.join(root,'app/webui/boss-v6.css')),
  manifest_sha256:digest(path.join(frontend,'asset-manifest.json')),index_sha256:digest(path.join(frontend,'index.html')),
  expected:{body:{font_size:'16px',line_height:'24px'},field:{font_size:'14px',line_height:'22px'}},records,
  external_api_mode:'SIMULATED_FIRST',model_requests:0,visual:'NOT_RUN'},null,2));}
async function main(){
  let desktop;
  try{
    desktop=await electron.launch({args:[__dirname],cwd:validation,timeout:60000,env:{...process.env,
      BOSS_VALIDATION_ROOT:validation,BOSS_PRODUCT_UI:'1',BOSS_APPLICATION_WORK_DIR:directory,
      BOSS_APPLICATION_PORTS:JSON.stringify(ports),BOSS_DESKTOP_TEST_WINDOW_HIDDEN:'1',TMPDIR:path.join(validation,'.work/tmp')}});
    const page=await desktop.firstWindow({timeout:120000});await page.waitForURL('http://127.0.0.1:'+ports.webui+'/');
    const errors=[];page.on('pageerror',error=>errors.push(error.name));
    async function navigate(id){await page.locator('button.boss-search').click();const dialog=page.getByRole('dialog',{name:'全部页面导航',exact:true});
      await dialog.getByPlaceholder('搜索页面编号或名称',{exact:true}).fill(id);await dialog.getByRole('button',{name:new RegExp('^'+id+' · ')}).click();}
    async function paragraphs(label,locator,required=false){
      const values=await locator.evaluateAll(elements=>elements.map(element=>({font_size:getComputedStyle(element).fontSize,
        line_height:getComputedStyle(element).lineHeight,text_length:element.textContent.length})));
      if(required)assert(values.length>=6,label+': 缺少实际报告正文');
      for(const value of values){assert.equal(value.font_size,'16px',label);assert.equal(value.line_height,'24px',label);}
      records.push({check:'actual_body',label,paragraphs:values});save('IN_PROGRESS');
    }
    await access.login(page,accounts,'MAINTAINER');await navigate('A03');
    const panel=page.getByRole('region',{name:'采购与品质模拟资料维护',exact:true});
    await panel.getByLabel('输入种类',{exact:true}).selectOption('initial_request');await panel.getByRole('button',{name:'载入待检查输入',exact:true}).click();
    await panel.getByRole('checkbox',{name:'确认当前输入及模拟状态，仅保存当前资料操作',exact:true}).check();
    await panel.getByRole('button',{name:'确认保存模拟资料操作',exact:true}).click();await panel.getByText('已保存的原请求状态：SUCCESS',{exact:true}).waitFor();
    const payload=JSON.parse(execFileSync(path.join(validation,'.venv/bin/python'),['validation/fc01_cost_token_input.py'],{cwd:root,encoding:'utf8',env:{...process.env,PYTHONDONTWRITEBYTECODE:'1'}}));
    payload.client_request_id=runId;
    await panel.getByLabel('完整输入JSON',{exact:true}).fill(JSON.stringify(payload));
    await panel.getByRole('checkbox',{name:'确认当前输入及模拟状态，仅保存当前资料操作',exact:true}).check();
    await panel.getByRole('button',{name:'确认保存模拟资料操作',exact:true}).click();await panel.getByText('已保存的原请求状态：SUCCESS',{exact:true}).waitFor();
    await access.logout(page);await access.login(page,accounts,'BOSS');await navigate('F14');
    for(const name of ['已报告入库成本','已报告实际领用成本']){
      const region=page.getByRole('region',{name,exact:true});await expect(region).toContainText('CNY/tonne');
      await paragraphs(name,region.locator('p'),true);
    }
    for(const pageId of ['F14','F21','F06','N05','F01','F04','F08','F09','F10','F11','F13','F28','N06','N09','N10','N11']){
      await navigate(pageId);await page.locator('.boss-hero .boss-eyebrow').filter({hasText:'· '+pageId}).waitFor();
      if(pageId==='N05')await page.getByRole('tab',{name:/^本人承诺/}).click();
      await paragraphs(pageId,page.locator('.boss-workspace-item p'));
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>document.documentElement.clientWidth+1),false,pageId);
    }
    for(const [width,height] of [[1024,768],[1280,800],[1440,1024]])for(const zoom of [1,2]){
      await desktop.evaluate(({BrowserWindow},{width,height,zoom})=>{const window=BrowserWindow.getAllWindows()[0];window.setContentSize(width,height);window.webContents.setZoomFactor(zoom);},{width,height,zoom});
      for(const pageId of ['F14','F21','F06']){
        await navigate(pageId);await page.locator('.boss-hero .boss-eyebrow').filter({hasText:'· '+pageId}).waitFor();
        const size=await page.evaluate(()=>({width:document.documentElement.clientWidth,scroll:document.documentElement.scrollWidth}));
        assert(size.scroll<=size.width+1,pageId+': 整页横向溢出');
        records.push({check:'page_bounds',page_id:pageId,native_width:width,native_height:height,zoom,...size});
      }
    }
    await desktop.evaluate(({BrowserWindow})=>{const window=BrowserWindow.getAllWindows()[0];window.setContentSize(1280,800);window.webContents.setZoomFactor(1);});
    await navigate('F14');const material=page.getByLabel('原料编号',{exact:true});await material.focus();await page.keyboard.press('Tab');
    await expect(page.getByLabel('产品编号',{exact:true})).toBeFocused();
    const field=await material.evaluate(element=>({font:getComputedStyle(element.closest('label')).fontSize,line:getComputedStyle(element.closest('label')).lineHeight,input:getComputedStyle(element).fontSize}));
    assert.deepEqual(field,{font:'14px',line:'22px',input:'16px'});
    await material.fill('sim-material-1');await material.press('Enter');
    await expect(page.getByRole('region',{name:'当前筛选结果',exact:true})).toBeVisible();
    await page.getByLabel('协调目的',{exact:true}).fill('核查当前资料');await navigate('F21');
    await expect(page.getByRole('dialog',{name:'未保存修改（D06）',exact:true})).toBeVisible();
    await page.keyboard.press('Escape');await expect(page.locator('button.boss-search')).toBeFocused();
    await expect(page.getByLabel('协调目的',{exact:true})).toHaveValue('核查当前资料');
    await page.getByLabel('协调目的',{exact:true}).fill('');
    records.push({check:'keyboard_and_field_tokens',tab:true,enter_query:true,escape_d06:true,field});
    await access.logout(page);await access.login(page,accounts,'MAINTAINER');
    for(const pageId of ['A05','A07','A15']){await navigate(pageId);await page.locator('.boss-hero .boss-eyebrow').filter({hasText:'· '+pageId}).waitFor();await paragraphs(pageId,page.locator('.boss-workspace-item p'));}
    assert.deepEqual(errors,[]);records.push({check:'renderer_errors',count:0});save('PASS');
  }finally{if(desktop)await desktop.close();}
}
main().then(()=>console.log(JSON.stringify({status:'PASS',report:output})),error=>{records.push({check:'failure',name:error.name,message:String(error.message).slice(0,1500)});save('FAIL');console.error(JSON.stringify({status:'FAIL',report:output}));process.exitCode=1;});
