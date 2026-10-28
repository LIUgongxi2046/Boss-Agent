const assert=require('node:assert/strict');
const {test}=require('node:test');
const fs=require('node:fs');
const path=require('node:path');
const Module=require('node:module');
const root=path.resolve(__dirname,'../..');
const dependencies=path.join(root,'.work/product/nanobot/webui/node_modules');
const {buildSync}=require(path.join(dependencies,'esbuild'));
const design=JSON.parse(fs.readFileSync(path.join(root,'Boss-Agent-Desktop-Complete-v7/meta/页面配置.json'),'utf8'));
const architecture=JSON.parse(fs.readFileSync(path.join(root,'specs/hld-72-page-map.json'),'utf8'));
const compiled=buildSync({entryPoints:[path.join(root,'app/webui/delivered-navigation.ts')],bundle:true,write:false,platform:'node',format:'cjs'});
const actual=new Module(path.join(root,'app/webui/delivered-navigation.cjs'));
actual.filename=path.join(root,'app/webui/delivered-navigation.cjs');
actual._compile(compiled.outputFiles[0].text,actual.filename);
const navigation=actual.exports;
const roles=['BOSS','MAINTAINER'];
const permitted=(gate,role)=>gate===role||gate==='AUTHENTICATED_BOSS_OR_MAINTAINER'||gate==='ANONYMOUS';

test('全部72项设计页面按真实角色保留路由，未知或跨角色入口拒绝',()=>{
  assert.equal(Object.keys(design).length,72);
  for(const page of architecture.pages){
    for(const role of roles){
      const entry=navigation.deliveredPage(page.page_id,role);
      assert.equal(Boolean(entry),permitted(page.role_gate,role),page.page_id+' / '+role);
      if(entry)assert.equal(entry.title,page.page_id==='N06'?'任务通知':design[page.page_id].title);
    }
  }
  for(const role of roles)for(const id of ['UNKNOWN','__proto__','constructor','toString'])assert.equal(navigation.deliveredPage(id,role),undefined);
  assert.equal(navigation.deliveredPage('F01','ANONYMOUS'),undefined);
});

test('本人五组与维护四组保持当前目录，每个可见页面出现一次',()=>{
  assert.equal(typeof navigation.navigationGroups,'function');
  assert.deepEqual(navigation.primaryNavigation('BOSS').map(row=>row.title),['今日工作','聊天交办','经营关注','会议与资料','任务与承诺']);
  assert.deepEqual(navigation.primaryNavigation('MAINTAINER').map(row=>row.title),['档案与访问','模拟中心','Agent配置','运行与评测']);
  for(const role of roles){
    const pages=navigation.navigationGroups(role).flatMap(group=>group.pages);
    assert.equal(pages.length,role==='BOSS'?5:20);
    const hidden=new Set(['N01','D08','D06','D07','F30','F31']);
    const bossVisible=new Set(['F01','N02','N03','N04','N05']);
    const expected=architecture.pages.filter(page=>permitted(page.role_gate,role)&&(role==='BOSS'?bossVisible.has(page.page_id):!hidden.has(page.page_id))).map(page=>page.page_id).sort();
    const actual=pages.filter(page=>Object.hasOwn(design,page.id)).map(page=>page.id).sort();
    assert.deepEqual(actual,expected);assert.equal(new Set(actual).size,actual.length);
    for(const page of pages)assert.equal(navigation.deliveredPage(page.id,role).stateLabel,page.stateLabel);
  }
});

test('F19原变体、既有入口、未完整验收与STT暂停状态保留',()=>{
  for(const id of ['F19','V19-EGG','V19-MILK','V19-BEEF','MVP01'])assert.ok(navigation.deliveredPage(id,'BOSS'));
  assert.ok(navigation.deliveredPage('NATIVE','MAINTAINER'));
  assert.equal(navigation.deliveredPage('F27','BOSS').state,'PAUSED');
  assert.equal(navigation.deliveredPage('N03','BOSS').state,'IN_PROGRESS');
  assert.equal(navigation.deliveredPage('N04','BOSS').state,'PARTIAL');
  for(const role of roles)for(const page of navigation.navigationGroups(role).flatMap(group=>group.pages)){
    assert.equal(typeof page.stateLabel,'string');assert.ok(page.stateLabel.length>0);
    assert.equal(page.accepted,false);
  }
  assert.ok(navigation.deliveredPage('N04','BOSS',true));
});

test('搜索仅覆盖当前目录，关联专题与认证状态保留角色权限',()=>{
  assert.equal(typeof navigation.navigationGroups,'function');
  const matches=navigation.navigationGroups('BOSS','V19-EGG').flatMap(group=>group.pages);
  assert.deepEqual(matches,[]);assert.equal(navigation.deliveredPage('V19-EGG','BOSS').variantLabel,'蛋禽');
  assert.equal(navigation.navigationGroups('BOSS','A01').flatMap(group=>group.pages).length,0);
  for(const role of roles)for(const id of ['N01','D08'])assert.equal(navigation.deliveredPage(id,role).state,'AUTHENTICATION');
  assert.equal(navigation.deliveredPage('F01','MAINTAINER'),undefined);
  assert.equal(navigation.deliveredPage('A01','BOSS'),undefined);
});

test('实际React菜单输出完整角色目录、状态与独立专题，一级入口全部启用',()=>{
  const React=require(path.join(dependencies,'react'));
  const {renderToStaticMarkup}=require(path.join(dependencies,'react-dom/server'));
  const {Window}=require(path.join(dependencies,'happy-dom/cjs/index.cjs'));
  const output=buildSync({entryPoints:[path.join(root,'app/webui/BossMenuNavigation.tsx')],bundle:true,write:false,platform:'node',format:'cjs',jsx:'automatic',nodePaths:[dependencies],external:['react','react/jsx-runtime','lucide-react']});
  const component=new Module(path.join(root,'app/webui/BossMenuNavigation.cjs'));
  component.filename=path.join(root,'app/webui/BossMenuNavigation.cjs');
  component.paths=[dependencies];component._compile(output.outputFiles[0].text,component.filename);
  const {BossPrimaryNavigation,BossMenuDirectory}=component.exports;
  const window=new Window();
  const documentFor=(node)=>new window.DOMParser().parseFromString(renderToStaticMarkup(node),'text/html');
  for(const role of roles){
    const page=role==='BOSS'?'F01':'A16',onNavigate=id=>navigation.deliveredPage(id,role);
    const primary=documentFor(React.createElement(BossPrimaryNavigation,{role,page,expanded:true,onNavigate}));
    const buttons=[...primary.querySelectorAll('button[data-menu-group]')];
    assert.deepEqual(buttons.map(button=>button.dataset.menuGroup),navigation.primaryNavigation(role).map(group=>group.id));
    assert.ok(buttons.every(button=>!button.disabled));assert.equal(primary.querySelectorAll('[aria-current="page"]').length,1);
    assert.deepEqual([...primary.querySelectorAll('button[data-menu-page]')].map(button=>button.dataset.menuPage),navigation.navigationGroups(role).filter(group=>group.pages.length>1).flatMap(group=>group.pages.map(entry=>entry.id)));
    const catalogue=documentFor(React.createElement(BossMenuDirectory,{role,page,search:'',onNavigate}));
    const entries=[...catalogue.querySelectorAll('button[data-menu-page]')];
    assert.deepEqual(entries.map(button=>button.dataset.menuPage),navigation.navigationGroups(role).flatMap(group=>group.pages.map(entry=>entry.id)));
    assert.equal(catalogue.querySelectorAll('button.selected').length,1);
    for(const button of entries){
      const entry=navigation.deliveredPage(button.dataset.menuPage,role);
      assert.equal(button.dataset.menuState,entry.state);assert.ok(button.textContent.includes(entry.title));assert.equal(button.disabled,false);
    }
    if(role==='BOSS')for(const id of ['V19-EGG','V19-MILK','V19-BEEF'])assert.equal(catalogue.querySelector('[data-menu-page="'+id+'"]'),null);
    const searched=documentFor(React.createElement(BossMenuDirectory,{role,page,search:page,onNavigate}));
    assert.deepEqual([...searched.querySelectorAll('button[data-menu-page]')].map(button=>button.dataset.menuPage),[page]);
    const empty=documentFor(React.createElement(BossMenuDirectory,{role,page,search:role==='BOSS'?'A01':'F01',onNavigate}));
    assert.equal(empty.querySelectorAll('button[data-menu-page]').length,0);assert.equal(empty.querySelector('[role="status"]').textContent,'当前身份下无匹配页面。');
  }
});
