const fs=require('node:fs');
const path=require('node:path');
const {_electron:electron}=require('playwright');
const root=path.resolve(__dirname,'../..');
async function main(){const app=await electron.launch({args:[path.join(__dirname,'menu-f01-design-main.cjs')],env:{...process.env,MENU_F01_DESIGN_FILE:path.join(root,'Boss-Agent-Desktop-Complete-v6/pages/F01-今日工作.html'),TMPDIR:path.join(root,'validation/.work/tmp')}});
  try{const page=await app.firstWindow();await page.waitForLoadState('load');
    const result=await page.evaluate(()=>({title:document.title,loaded:document.readyState,has_grid:Boolean(document.querySelector('.v6-grid')),has_builder:Boolean(window.V6PageBuilders?.F01),has_page:Boolean(window.V6_PAGE),scripts:[...document.scripts].map(node=>({src:node.getAttribute('src'),type:node.type})),headings:[...document.querySelectorAll('h2')].map(node=>node.textContent),body_class:document.querySelector('.stage-body')?.firstElementChild?.className}));
    result.layouts=[];
    for(const [width,height] of [[1440,1024],[1280,800],[1024,768]])for(const zoom of [1,2]){
      await app.evaluate(({BrowserWindow},{width,height,zoom})=>{const window=BrowserWindow.getAllWindows()[0];window.setContentSize(width,height);window.webContents.setZoomFactor(zoom);},{width,height,zoom});
      await page.waitForFunction(({width,zoom})=>Math.abs(innerWidth-width/zoom)<=1,{width,zoom});
      result.layouts.push({width,height,zoom,...await page.evaluate(()=>{const grid=document.querySelector('.v6-grid'),panel=document.querySelector('.v6-panel'),style=getComputedStyle(grid),rect=node=>({x:node.getBoundingClientRect().x,y:node.getBoundingClientRect().y,width:node.getBoundingClientRect().width,height:node.getBoundingClientRect().height});return {columns:style.gridTemplateColumns,gap:style.gap,main:rect(grid.children[0]),aside:rect(grid.children[1]),main_gap:getComputedStyle(grid.children[0]).gap,panel_padding:getComputedStyle(panel).padding,panel_radius:getComputedStyle(panel).borderRadius};})});
    }
    fs.writeFileSync(path.join(root,'evidence/menu-delivery/F01/reference-dom.json'),JSON.stringify(result,null,2)+'\n');console.log(JSON.stringify(result));
  }finally{await app.close();}}
main().catch(error=>{console.error(error.message);process.exitCode=1;});
