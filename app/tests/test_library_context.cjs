const assert=require('node:assert/strict');
const {test}=require('node:test');
const path=require('node:path');
const Module=require('node:module');
const root=path.resolve(__dirname,'../..');
const dependencies=path.join(root,'.work/product/nanobot/webui/node_modules');
const {buildSync}=require(path.join(dependencies,'esbuild'));

function source(file){
  const result=buildSync({entryPoints:[path.join(root,'app/webui',file)],bundle:true,write:false,platform:'node',format:'cjs',jsx:'automatic',nodePaths:[dependencies]});
  const module=new Module(path.join(root,'app/webui',file+'.cjs'));module.filename=path.join(root,'app/webui',file+'.cjs');module.paths=[dependencies];module._compile(result.outputFiles[0].text,module.filename);return module.exports;
}

const context=source('library-context.ts');

function withSearch(search){global.window={location:{search}};}

test('有效目录上下文与动作被解析',()=>{
  withSearch('?bossPage=F07&bossLibraryContext='+encodeURIComponent(JSON.stringify({id:'application-1',kind:'approval',version:'1',namespace:'ui-check'}))+'&bossLibraryAction=open');
  assert.deepEqual(context.readLibraryContext(),{id:'application-1',kind:'approval',version:'1',namespace:'ui-check'});
  assert.equal(context.readLibraryAction(),'open');
});

test('缺少字段、未知类别与损坏内容被拒绝',()=>{
  withSearch('?bossLibraryContext='+encodeURIComponent(JSON.stringify({id:'x',kind:'unknown',version:'1',namespace:'ns'})));
  assert.equal(context.readLibraryContext(),null);
  withSearch('?bossLibraryContext='+encodeURIComponent(JSON.stringify({id:'x',kind:'people',version:'1'})));
  assert.equal(context.readLibraryContext(),null);
  withSearch('?bossLibraryContext=%7Bnot-json');
  assert.equal(context.readLibraryContext(),null);
  withSearch('');
  assert.equal(context.readLibraryContext(),null);
  assert.equal(context.readLibraryAction(),'');
});
