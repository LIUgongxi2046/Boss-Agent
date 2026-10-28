const assert=require('node:assert/strict');
const {test}=require('node:test');
const fs=require('node:fs');
const path=require('node:path');
const Module=require('node:module');
const root=path.resolve(__dirname,'../..');
const dependencies=path.join(root,'.work/product/nanobot/webui/node_modules');
const {buildSync}=require(path.join(dependencies,'esbuild'));
const compiled=buildSync({entryPoints:[path.join(root,'app/webui/delivered-navigation.ts')],bundle:true,write:false,platform:'node',format:'cjs'});
const actual=new Module(path.join(root,'app/webui/admin-navigation-check.cjs'));
actual.filename=path.join(root,'app/webui/admin-navigation-check.cjs');
actual._compile(compiled.outputFiles[0].text,actual.filename);
const navigation=actual.exports;
const hidden=['N01','D08','D06','D07','F30','F31'];

test('管理员提示状态及重复入口从菜单与检索隐藏，关联页面保持可访问',()=>{
  const visible=navigation.navigationGroups('MAINTAINER').flatMap(group=>group.pages.map(page=>page.id));
  for(const id of hidden){
    assert.ok(navigation.deliveredPage(id,'MAINTAINER'),id+' 关联页面应当保留');
    assert.equal(visible.includes(id),false,id+' 不应当出现在菜单');
    assert.deepEqual(navigation.navigationGroups('MAINTAINER',id),[]);
    assert.deepEqual(navigation.navigationGroups('MAINTAINER',navigation.deliveredPage(id,'MAINTAINER').title),[]);
  }
  for(const id of ['A01','A12','A14','A16','A03','A04','A05','A08','A13','A15','N12','F32'])assert.ok(visible.includes(id),id+' 维护入口应当可见');
  const plan=JSON.parse(fs.readFileSync(path.join(root,'specs/menu-plan.json'),'utf8'));
  assert.deepEqual(plan.administrator_hidden_pages.map(page=>page.id),hidden);
});

test('Boss端五项主菜单、目录及全部原有页面权限保持一致',()=>{
  const expected=['F01','N02','N03','N04','N05'];
  assert.deepEqual(navigation.primaryNavigation('BOSS').map(page=>page.id),expected);
  assert.deepEqual(navigation.navigationGroups('BOSS').flatMap(group=>group.pages.map(page=>page.id)),expected);
  for(const id of ['D06','D07','N01','D08','F30','F31']){
    const entry=navigation.deliveredPage(id,'BOSS');
    assert.equal(Boolean(entry),!['F30','F31'].includes(id));
  }
  assert.equal(navigation.deliveredPage('A01','BOSS'),undefined);
  assert.equal(navigation.deliveredPage('F01','MAINTAINER'),undefined);
});
