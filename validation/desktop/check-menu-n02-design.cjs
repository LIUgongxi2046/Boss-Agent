const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {createHash}=require('node:crypto');
const {_electron:electron}=require('playwright');
const root=path.resolve(__dirname,'../..'),source=path.join(root,'Boss-Agent-Desktop-Complete-v6/pages/N02-聊天交办.html');
async function main(){
  const app=await electron.launch({args:[path.join(__dirname,'menu-n02-design-main.cjs')],env:{...process.env,MENU_N02_DESIGN_FILE:source,TMPDIR:path.join(root,'validation/.work/tmp')}});
  try{
    const page=await app.firstWindow();await page.waitForLoadState('load');
    const result=await page.evaluate(()=>({title:document.title,page_id:window.V6_PAGE.id,has_builder:Boolean(window.V6PageBuilders?.N02),headings:[...document.querySelectorAll('.stage-body h2')].map(node=>node.textContent),fields:[...document.querySelectorAll('.stage-body [data-persist]')].map(node=>({name:node.getAttribute('data-persist'),tag:node.tagName})),actions:[...document.querySelectorAll('.stage-body [data-act],.stage-body [data-go]')].map(node=>({title:node.textContent,action:node.getAttribute('data-act'),page:node.getAttribute('data-go')}))}));
    assert.equal(result.page_id,'N02');assert.equal(result.has_builder,true);assert(result.headings.includes('对话与任务运行'));assert(result.fields.some(field=>field.name==='本次消息'));
    result.source_sha256=createHash('sha256').update(fs.readFileSync(source)).digest('hex');result.layouts=[];
    const samples=[...[[1440,1024],[1280,800],[1024,768]].flatMap(([width,height])=>[1,2].map(zoom=>({width,height,zoom}))),...[1251,1250,1249,1051,1050,1049,701,700,699,691,690,689].map(width=>({width,height:800,zoom:1}))];
    for(const {width,height,zoom} of samples){
      await app.evaluate(({BrowserWindow},{width,height,zoom})=>{const window=BrowserWindow.getAllWindows()[0];window.setContentSize(width,height);window.webContents.setZoomFactor(zoom);},{width,height,zoom});
      await page.waitForFunction(({width,zoom})=>Math.abs(innerWidth-width/zoom)<=1,{width,zoom});
      result.layouts.push({width,height,zoom,...await page.evaluate(()=>{
        const grid=document.querySelector('.v6-grid'),panel=document.querySelector('.v6-panel'),style=getComputedStyle(grid),rect=node=>({x:node.getBoundingClientRect().x,y:node.getBoundingClientRect().y,width:node.getBoundingClientRect().width,height:node.getBoundingClientRect().height});
        const selectors={screen:'.screen',shell:'.shell',sidebar:'.sidebar',topbar:'.topbar',stage:'.stage',hero:'.hero',title:'.hero h1',description:'.hero p',body:'.stage-body',selected_navigation:'.navitem.on',brand:'.brand',panel:'.v6-panel',primary_action:'.v6-btn.primary',message_input:'[data-persist="本次消息"]'};
        const framework={};for(const [name,selector] of Object.entries(selectors)){
          const element=document.querySelector(selector);if(!element)throw new Error('设计缺少必要区域：'+name);const computed=getComputedStyle(element);
          framework[name]={selector,rect:rect(element),client_width:element.clientWidth,offset_width:element.offsetWidth,scroll_width:element.scrollWidth,client_height:element.clientHeight,scroll_height:element.scrollHeight,scroll_top:element.scrollTop,display:computed.display,columns:computed.gridTemplateColumns,padding:computed.padding,margin:computed.margin,gap:computed.gap,border:computed.border,border_radius:computed.borderRadius,shadow:computed.boxShadow,background:computed.backgroundColor,color:computed.color,font_family:computed.fontFamily,font_size:computed.fontSize,line_height:computed.lineHeight,font_weight:computed.fontWeight,max_width:computed.maxWidth,overflow_x:computed.overflowX,overflow_y:computed.overflowY};
        }
        return {viewport:{inner_width:innerWidth,inner_height:innerHeight,device_pixel_ratio:devicePixelRatio,scroll_x:scrollX,scroll_y:scrollY},content_state:{persisted_fields:document.querySelectorAll('.stage-body [data-persist]').length,panels:document.querySelectorAll('.stage-body .v6-panel').length,expanded:[...document.querySelectorAll('.stage-body [aria-expanded="true"]')].map(node=>node.getAttribute('aria-label')||node.textContent)},columns:style.gridTemplateColumns,gap:style.gap,main:rect(grid.children[0]),aside:rect(grid.children[1]),main_gap:getComputedStyle(grid.children[0]).gap,panel_padding:getComputedStyle(panel).padding,panel_radius:getComputedStyle(panel).borderRadius,framework};
      })});
    }
    const target=path.join(root,'evidence/menu-delivery/N02/reference-dom.json');fs.mkdirSync(path.dirname(target),{recursive:true});fs.writeFileSync(target,JSON.stringify(result,null,2)+'\n');console.log(JSON.stringify({status:'PASS',report:target,layouts:result.layouts.length,headings:result.headings}));
  }finally{await app.close();}
}
main().catch(failure=>{console.error(failure.message);process.exitCode=1;});
