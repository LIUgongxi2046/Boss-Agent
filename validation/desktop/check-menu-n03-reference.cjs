const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {randomUUID,createHash}=require('node:crypto');
const {_electron:electron}=require('playwright');
const root=path.resolve(__dirname,'../..');
const space=fs.statfsSync(root);
assert(space.bavail*space.bsize>=200*1024*1024,'参考测量需要至少200MiB可用空间');
const directory=path.join(root,'validation/.work/menu-n03-reference-'+randomUUID());
fs.mkdirSync(path.join(directory,'tmp'),{recursive:true,mode:0o700});
const sourceRoot=path.join(root,'Boss-Agent-Desktop-Complete-v6');
const selectors={frame:'.screen',shell:'.shell',sidebar:'.sidebar',topbar:'.topbar',stage:'.stage',scroll:'.stage-body',hero:'.hero',title:'.hero h1',logo:'.brand img',mascot:'.hero .mascot',grid:'.v6-body>.v6-grid',main:'.v6-body>.v6-grid>.v6-stack:first-child',aside:'.v6-body>.v6-grid>.v6-stack:last-child',panel:'.v6-panel',heading:'.v6-panel h2',form:'.v6-formgrid',label:'.v6-field>span',input:'.v6-field input',primary:'.v6-btn.primary',topic_grid:'.v6-grid.split',topic:'.v6-grid.split>.v6-item',topic_title:'.v6-grid.split>.v6-item b',topic_copy:'.v6-grid.split>.v6-item p',topic_icon:'.v6-grid.split>.v6-item>.v6-icon',note:'.v6-note',kv:'.v6-kv',actions:'.v6-actions'};
const expected=['原料与饲料','水产季节','苗种批次','动保与技服','生猪合作','禽类与反刍','公司水产养殖','食品与品质','海外业务','研发应用'];
async function main(){
  let application;
  try{
    application=await electron.launch({args:[path.join(__dirname,'menu-n03-reference-main.cjs')],env:{...process.env,MENU_N03_REFERENCE_DIRECTORY:path.join(directory,'profile'),MENU_N03_REFERENCE_FILE:path.join(sourceRoot,'pages/N03-经营关注.html'),TMPDIR:path.join(directory,'tmp')}});
    const page=await application.firstWindow();
    await page.waitForLoadState('load');
    await page.locator('.v6-grid.split>.v6-item').last().waitFor();
    const layouts=[];
    const samples=[...[[1440,1024],[1280,800],[1024,768]].flatMap(([width,height])=>[1,2].map(zoom=>({width,height,zoom}))),...[1251,1250,1249,1051,1050,1049,701,700,699,691,690,689].map(width=>({width,height:800,zoom:1}))];
    for(const sample of samples){
      await application.evaluate(({BrowserWindow},value)=>{const window=BrowserWindow.getAllWindows()[0];window.setContentSize(value.width,value.height);window.webContents.setZoomFactor(value.zoom);},sample);
      await page.waitForFunction(value=>Math.abs(innerWidth-value.width/value.zoom)<.1&&Math.abs(innerHeight-value.height/value.zoom)<.1,sample);
      await page.waitForFunction(()=>document.getAnimations().every(animation=>animation.effect.getTiming().iterations===Infinity||['finished','idle'].includes(animation.playState)),undefined,{timeout:15000});
      const source=await page.evaluate(selectors=>{
        const regions={};
        for(const [name,selector]of Object.entries(selectors)){
          const element=document.querySelector(selector);
          if(!element)throw new Error('原始经营关注缺少区域：'+name);
          const style=getComputedStyle(element),rectangle=element.getBoundingClientRect();
          regions[name]={x:rectangle.x,y:rectangle.y,width:rectangle.width,height:rectangle.height,client_width:element.clientWidth,offset_width:element.offsetWidth,scroll_width:element.scrollWidth,scroll_top:element.scrollTop};
          for(const field of ['display','gridTemplateColumns','padding','gap','border','borderRadius','boxShadow','backgroundColor','backgroundImage','fontFamily','fontSize','fontWeight','lineHeight','color','minHeight','outlineWidth','outlineOffset'])regions[name][field]=style[field];
        }
        return {regions,headings:[...document.querySelectorAll('.stage-body h2')].map(element=>element.textContent),labels:[...document.querySelectorAll('.v6-field>span')].map(element=>element.textContent),topics:[...document.querySelectorAll('.v6-grid.split>.v6-item')].map(element=>({title:element.querySelector('b').textContent,target:element.dataset.go})),document_width:document.documentElement.clientWidth,document_scroll:document.documentElement.scrollWidth};
      },selectors);
      assert.deepEqual(source.topics.map(item=>item.title),expected);
      assert.deepEqual(source.topics.map(item=>item.target),Array.from({length:10},(_,index)=>'F'+(index+14)));
      assert.deepEqual(source.headings,['经营关注范围','十个经营专题','经营提醒与来源']);
      layouts.push({...sample,source});
    }
    const inputs={};
    for(const name of ['pages/N03-经营关注.html','design-v6-panels.js','design-v6.js','design-v6.css','style.css','design-tokens.json'])inputs[name]=createHash('sha256').update(fs.readFileSync(path.join(sourceRoot,name))).digest('hex');
    const output=path.join(root,'evidence/menu-delivery/N03/reference-dom.json');
    fs.mkdirSync(path.dirname(output),{recursive:true});
    fs.writeFileSync(output,JSON.stringify({status:'REFERENCE_MEASURED',scope:'MENU_N03_REFERENCE_ONLY',visual:'NOT_RUN',user_acceptance:'NOT_RUN',application_directory:directory,inputs,layouts},null,2)+'\n');
    console.log(JSON.stringify({status:'REFERENCE_MEASURED',samples:layouts.length,report:output}));
  }finally{if(application)await application.close();}
}
void main();
