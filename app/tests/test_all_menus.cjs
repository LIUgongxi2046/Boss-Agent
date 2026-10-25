const assert=require('node:assert/strict');
const {test}=require('node:test');
const fs=require('node:fs');
const path=require('node:path');
const Module=require('node:module');
const root=path.resolve(__dirname,'../..');
const dependencies=path.join(root,'.work/product/nanobot/webui/node_modules');
const {buildSync}=require(path.join(dependencies,'esbuild'));
const design=JSON.parse(fs.readFileSync(path.join(root,'Boss-Agent-Desktop-Complete-v6/meta/页面配置.json'),'utf8'));
const architecture=JSON.parse(fs.readFileSync(path.join(root,'specs/hld-72-page-map.json'),'utf8'));
const compiled=buildSync({entryPoints:[path.join(root,'app/webui/delivered-navigation.ts')],bundle:true,write:false,platform:'node',format:'cjs'});
const actual=new Module(path.join(root,'app/webui/delivered-navigation.cjs'));
actual.filename=path.join(root,'app/webui/delivered-navigation.cjs');
actual._compile(compiled.outputFiles[0].text,actual.filename);
const navigation=actual.exports;
const roles=['BOSS','MAINTAINER'];
const permitted=(gate,role)=>gate===role||gate==='AUTHENTICATED_BOSS_OR_MAINTAINER'||gate==='ANONYMOUS';

test('全部72项设计页面按真实角色映射可见，未知或跨角色入口拒绝',()=>{
  assert.equal(Object.keys(design).length,72);
  for(const page of architecture.pages){
    for(const role of roles){
      const entry=navigation.deliveredPage(page.page_id,role);
      assert.equal(Boolean(entry),permitted(page.role_gate,role),page.page_id+' / '+role);
      if(entry){assert.equal(entry.title,design[page.page_id].title);assert.equal(entry.directory,true);}
    }
  }
  for(const role of roles)for(const id of ['UNKNOWN','__proto__','constructor','toString'])assert.equal(navigation.deliveredPage(id,role),undefined);
  assert.equal(navigation.deliveredPage('F01','ANONYMOUS'),undefined);
});

test('本人六组与维护四组完整，每个设计页面在目录中出现一次',()=>{
  assert.equal(typeof navigation.navigationGroups,'function');
  assert.deepEqual(navigation.primaryNavigation('BOSS').map(row=>row.title),['今日工作','聊天交办','经营关注','会议与资料','任务与承诺','通知与设置']);
  assert.deepEqual(navigation.primaryNavigation('MAINTAINER').map(row=>row.title),['档案与访问','模拟中心','Agent配置','运行与评测']);
  for(const role of roles){
    const pages=navigation.navigationGroups(role).flatMap(group=>group.pages);
    assert.equal(pages.length,role==='BOSS'?52:26);
    const expected=architecture.pages.filter(page=>permitted(page.role_gate,role)).map(page=>page.page_id).sort();
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

test('搜索覆盖分组与页面编号，F19用途可辨，认证状态不伪造业务权限',()=>{
  assert.equal(typeof navigation.navigationGroups,'function');
  const matches=navigation.navigationGroups('BOSS','V19-EGG').flatMap(group=>group.pages);
  assert.deepEqual(matches.map(page=>page.id),['V19-EGG']);assert.equal(matches[0].variantLabel,'蛋禽');
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
    const page=role==='BOSS'?'V19-EGG':'A16',onNavigate=id=>navigation.deliveredPage(id,role);
    const primary=documentFor(React.createElement(BossPrimaryNavigation,{role,page,expanded:true,onNavigate}));
    const buttons=[...primary.querySelectorAll('button[data-menu-group]')];
    assert.deepEqual(buttons.map(button=>button.dataset.menuGroup),navigation.primaryNavigation(role).map(group=>group.id));
    assert.ok(buttons.every(button=>!button.disabled));assert.equal(primary.querySelectorAll('[aria-current="page"]').length,1);
    const catalogue=documentFor(React.createElement(BossMenuDirectory,{role,page,search:'',onNavigate}));
    const entries=[...catalogue.querySelectorAll('button[data-menu-page]')];
    assert.deepEqual(entries.map(button=>button.dataset.menuPage),navigation.navigationGroups(role).flatMap(group=>group.pages.map(entry=>entry.id)));
    assert.equal(catalogue.querySelectorAll('button.selected').length,1);
    for(const button of entries){
      const entry=navigation.deliveredPage(button.dataset.menuPage,role);
      assert.equal(button.dataset.menuState,entry.state);assert.ok(button.textContent.includes(entry.stateLabel));assert.equal(button.disabled,false);
    }
    if(role==='BOSS')for(const [id,label] of [['V19-EGG','蛋禽'],['V19-MILK','奶畜'],['V19-BEEF','肉用牛羊']])assert.ok(catalogue.querySelector('[data-menu-page="'+id+'"]').textContent.includes(label));
    const searched=documentFor(React.createElement(BossMenuDirectory,{role,page,search:page,onNavigate}));
    assert.deepEqual([...searched.querySelectorAll('button[data-menu-page]')].map(button=>button.dataset.menuPage),[page]);
    const empty=documentFor(React.createElement(BossMenuDirectory,{role,page,search:role==='BOSS'?'A01':'F01',onNavigate}));
    assert.equal(empty.querySelectorAll('button[data-menu-page]').length,0);assert.equal(empty.querySelector('[role="status"]').textContent,'当前身份下无匹配页面。');
  }
});
