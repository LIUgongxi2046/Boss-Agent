const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {randomUUID,createHash}=require('node:crypto');
const {_electron:electron}=require('playwright');
const {expect:baseExpect}=require('@playwright/test');
const access=require('./account-access.cjs');
const expect=baseExpect.configure({timeout:15000});
const root=path.resolve(__dirname,'../..'),validation=path.join(root,'validation'),frontend=path.join(root,'menu-n02-n3-dist');
const directory=path.join(validation,'.work','menu-n02-framework-'+randomUUID()),accounts=access.provision(directory),ports={business:10751,webui:10752,gateway:20751};
async function main(){let desktop;
  try{
    desktop=await electron.launch({args:[__dirname],cwd:validation,timeout:60000,env:{...process.env,BOSS_VALIDATION_ROOT:validation,BOSS_PRODUCT_UI:'1',BOSS_EXECUTION_SCOPE:'BOSS-PRIORITY-ITERATION',BOSS_PRODUCT_FRONTEND_DIR:frontend,BOSS_APPLICATION_WORK_DIR:directory,BOSS_APPLICATION_PORTS:JSON.stringify(ports),BOSS_DESKTOP_TEST_WINDOW_HIDDEN:'1',TMPDIR:path.join(directory,'tmp')}});
    const page=await desktop.firstWindow({timeout:120000});await page.waitForURL('http://127.0.0.1:'+ports.webui+'/');await access.login(page,accounts,'BOSS');await page.getByRole('button',{name:'大鹏会话',exact:true}).click();await expect(page.getByRole('region',{name:'大鹏会话内容',exact:true})).toBeVisible();await page.getByRole('button',{name:'新建会话',exact:true}).click();await expect(page.locator('.boss-native-surface textarea')).toBeVisible();
    const result={status:'MEASURED',scope:'N02_EXISTING_NATIVE_FRAMEWORK_BEFORE_DESIGN_REPAIR',application_directory:directory,ports,manifest_sha256:createHash('sha256').update(fs.readFileSync(path.join(frontend,'asset-manifest.json'))).digest('hex'),visual:'NOT_RUN',user_acceptance:'NOT_RUN',layouts:[]};
    const samples=[...[[1440,1024],[1280,800],[1024,768]].flatMap(([width,height])=>[1,2].map(zoom=>({width,height,zoom}))),...[1251,1250,1249,1051,1050,1049,701,700,699,691,690,689].map(width=>({width,height:800,zoom:1}))];
    for(const {width,height,zoom} of samples){
      await desktop.evaluate(({BrowserWindow},sample)=>{const window=BrowserWindow.getAllWindows()[0];window.setContentSize(sample.width,sample.height);window.webContents.setZoomFactor(sample.zoom);},{width,height,zoom});await page.waitForFunction(({width,zoom})=>Math.abs(innerWidth-width/zoom)<=1,{width,zoom});
      result.layouts.push({width,height,zoom,...await page.evaluate(()=>{
        const selectors={screen:'.boss-frame',shell:'.boss-layout',sidebar:'.boss-sidebar',topbar:'.boss-topbar',stage:'.boss-stage',hero:'.boss-hero',title:'.boss-hero h1',description:'.boss-hero p',body:'.boss-native-surface',brand:'.boss-brand',message_input:'.boss-native-surface textarea'};
        const framework={};for(const [name,selector] of Object.entries(selectors)){const element=document.querySelector(selector);if(!element)throw new Error('当前界面缺少必要区域：'+name);const rect=element.getBoundingClientRect(),computed=getComputedStyle(element);framework[name]={selector,rect:{x:rect.x,y:rect.y,width:rect.width,height:rect.height},client_width:element.clientWidth,offset_width:element.offsetWidth,scroll_width:element.scrollWidth,client_height:element.clientHeight,scroll_height:element.scrollHeight,scroll_top:element.scrollTop,display:computed.display,columns:computed.gridTemplateColumns,padding:computed.padding,margin:computed.margin,gap:computed.gap,border:computed.border,border_radius:computed.borderRadius,shadow:computed.boxShadow,background:computed.backgroundColor,color:computed.color,font_family:computed.fontFamily,font_size:computed.fontSize,line_height:computed.lineHeight,font_weight:computed.fontWeight,max_width:computed.maxWidth,overflow_x:computed.overflowX,overflow_y:computed.overflowY};}
        return {page_id:new URL(location.href).searchParams.get('bossPage'),viewport:{inner_width:innerWidth,inner_height:innerHeight,device_pixel_ratio:devicePixelRatio,scroll_x:scrollX,scroll_y:scrollY},content_state:{native_messages:document.querySelectorAll('[data-message-id]').length,expanded:[...document.querySelectorAll('.boss-native-surface [aria-expanded="true"]')].map(node=>node.getAttribute('aria-label')||node.textContent),new_conversation:!location.hash.includes('websocket')},framework};
      })});
    }
    assert.equal(result.layouts.length,18);const target=path.join(root,'evidence/menu-delivery/N02/framework-before.json');fs.writeFileSync(target,JSON.stringify(result,null,2)+'\n');console.log(JSON.stringify({status:'MEASURED',report:target,layouts:result.layouts.length}));
  }finally{if(desktop)await desktop.close();}
}
main().catch(failure=>{let message=failure.message;for(const account of Object.values(accounts))for(const key of ['username','password'])message=message.replaceAll(account[key],'[已隐藏]');console.error(message);process.exitCode=1;});
