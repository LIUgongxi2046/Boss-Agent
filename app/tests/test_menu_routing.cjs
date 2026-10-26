const assert=require('node:assert/strict');
const {test,before,after}=require('node:test');
const http=require('node:http');
const os=require('node:os');
const path=require('node:path');
const Module=require('node:module');
const root=path.resolve(__dirname,'../..');
const dependencies=path.join(root,'.work/product/nanobot/webui/node_modules');
const {buildSync}=require(path.join(dependencies,'esbuild'));
const {chromium}=require(path.join(root,'validation/desktop/node_modules/playwright'));
function source(file){
  const result=buildSync({entryPoints:[path.join(root,'app/webui',file)],bundle:true,write:false,platform:'node',format:'cjs',jsx:'automatic',nodePaths:[dependencies],external:['react','react/jsx-runtime','lucide-react']});
  const module=new Module(path.join(root,'app/webui',file+'.cjs'));module.filename=path.join(root,'app/webui',file+'.cjs');module.paths=[dependencies];module._compile(result.outputFiles[0].text,module.filename);return module.exports;
}
const routes=source('boss-route.ts'),history=source('boss-history.ts'),navigation=source('delivered-navigation.ts');
const compiled=buildSync({entryPoints:[path.join(root,'app/tests/menu-routing-browser.tsx')],bundle:true,write:false,platform:'browser',format:'iife',globalName:'MenuChecks',jsx:'automatic',nodePaths:[dependencies]});
let server,browser,origin;
before(async()=>{
  server=http.createServer((request,response)=>{const url=new URL(request.url,'http://127.0.0.1');if(url.pathname==='/modules.js'){response.setHeader('Content-Type','text/javascript');response.end(compiled.outputFiles[0].text);}else if(url.pathname==='/'){response.setHeader('Content-Type','text/html');response.end('<!doctype html><html><head><meta charset="utf-8"></head><body><script src="/modules.js"></script></body></html>');}else{response.writeHead(404);response.end();}});
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));origin='http://127.0.0.1:'+server.address().port;
  browser=await chromium.launch({headless:true,executablePath:process.env.BOSS_MENU_TEST_CHROMIUM||path.join(os.homedir(),'Library/Caches/ms-playwright/chromium_headless_shell-1228/chrome-headless-shell-mac-x64/chrome-headless-shell')});
});
after(async()=>{if(browser)await browser.close();if(server)await new Promise(resolve=>server.close(resolve));});

test('完整角色目录逐项生成实际目的URL，直接读取与刷新保持页面、原生别名及权限',()=>{
  for(const role of ['BOSS','MAINTAINER'])for(const entry of navigation.navigationGroups(role).flatMap(group=>group.pages)){
    const url=routes.menuPageUrl('http://127.0.0.1:10822/?overviewReturn=N03&bossConversationReturn=N02&bossTask=previous&bossSource=previous&bossOwnerRecord=previous-authorization&bossHistoryRecord=previous-notification&bossSimulationSection=reset&bossLibraryContext=previous&bossLibraryAction=prepare&libraryTab=meeting&libraryQuery=previous&libraryDate=2026-10-26&libraryState=READY&librarySelected=previous&taskTab=previous&taskCoordinator=previous&taskBefore=2026-10-26&taskState=ACTIVE&taskMeeting=previous&bossCommitment=previous&bossRun=previous&bossIssue=previous&bossRecoveryRequest=previous&bossRecoveryAction=previous#/',entry.id,role);
    assert.equal(routes.readBossLocation(url,role).page,entry.id);
    for(const key of ['overviewReturn','bossConversationReturn','bossTask','bossSource','bossOwnerRecord','bossHistoryRecord','bossSimulationSection','bossLibraryContext','bossLibraryAction','libraryTab','libraryQuery','libraryDate','libraryState','librarySelected','taskTab','taskCoordinator','taskBefore','taskState','taskMeeting','bossCommitment','bossRun','bossIssue','bossRecoveryRequest','bossRecoveryAction'])assert.equal(url.searchParams.has(key),false);
    assert.equal(navigation.deliveredPage(routes.readBossLocation(new URL(url.href),role).page,role).title,entry.title);
  }
  assert.equal(routes.readBossLocation(new URL('http://127.0.0.1/?bossPage=NATIVE'),'BOSS').page,'N02');
  assert.equal(routes.readBossLocation(new URL('http://127.0.0.1/?bossPage=NATIVE'),'MAINTAINER').page,'NATIVE');
  assert.equal(routes.readBossLocation(new URL('http://127.0.0.1/?bossPage=A01'),'BOSS').page,'UNAVAILABLE');
  assert.equal(routes.readBossLocation(new URL('http://127.0.0.1/?bossPage=F01'),'MAINTAINER').page,'UNAVAILABLE');
  assert.throws(()=>routes.menuPageUrl('http://127.0.0.1/','A01','BOSS'));
});

test('共享任务与来源读取原返回页面，普通菜单进入独立页面',()=>{
  const shared=new URL('http://127.0.0.1/?bossPage=D01&bossReturn=F19&bossSource=finance-note&bossTask=retained&bossSourceReferenceVersion=1');
  const actual=routes.readBossLocation(shared,'BOSS');
  assert.deepEqual(actual,{page:'D01',returnPage:'F19',sourceId:'finance-note',taskId:'retained',sopId:''});
  assert.equal(routes.readBossLocation(routes.menuPageUrl(shared.href,'F03','BOSS'),'BOSS').taskId,'');
  assert.equal(routes.menuPageUrl(shared.href,'F03','BOSS').searchParams.has('bossReturn'),false);
  assert.equal(new URL(shared.href).searchParams.get('bossSourceReferenceVersion'),'1');
  assert.equal(routes.menuPageUrl(shared.href,'F03','BOSS').searchParams.has('bossSourceReferenceVersion'),false);
});

test('实际Chromium History后退与前进不增加条目，刷新与F19变体保持目的页面',async()=>{
  const page=await browser.newPage();await page.goto(origin+'/?bossPage=F01');
  const length=await page.evaluate(()=>{MenuChecks.bindBossHistory(window,(_url,proceed)=>proceed(),url=>{window.currentPage=MenuChecks.readBossLocation(url,'BOSS').page;});for(const id of ['N02','N04','V19-MILK'])MenuChecks.pushBossHistory(MenuChecks.menuPageUrl(location.href,id,'BOSS'));return history.length;});
  for(const [method,id] of [['back','N04'],['back','N02'],['forward','N04'],['forward','V19-MILK']]){
    await page.evaluate(method=>history[method](),method);await page.waitForFunction(id=>window.currentPage===id,id);assert.equal(await page.evaluate(()=>history.length),length);
  }
  await page.reload();assert.equal(await page.evaluate(()=>MenuChecks.readBossLocation(new URL(location.href),'BOSS').page),'V19-MILK');await page.close();
});

test('历史移动等待当前离开确认，取消保持来源及前进条目，批准后沿原历史继续',async()=>{
  const page=await browser.newPage();await page.goto(origin+'/?bossPage=F01');
  const length=await page.evaluate(()=>{window.currentPage='N02';window.guarded=true;MenuChecks.bindBossHistory(window,(_url,proceed)=>{if(window.guarded)window.approveHistory=proceed;else proceed();},url=>{window.currentPage=MenuChecks.readBossLocation(url,'BOSS').page;});MenuChecks.pushBossHistory(MenuChecks.menuPageUrl(location.href,'N02','BOSS'));history.back();return history.length;});
  await page.waitForFunction(()=>window.approveHistory&&location.search==='?bossPage=N02');
  assert.equal(await page.evaluate(()=>window.currentPage),'N02');assert.equal(await page.evaluate(()=>MenuChecks.bossHistorySuppressed()),true);assert.equal(await page.evaluate(()=>history.length),length);
  await page.evaluate(()=>window.approveHistory());await page.waitForFunction(()=>window.currentPage==='F01');
  await page.evaluate(()=>{window.guarded=false;history.forward();});await page.waitForFunction(()=>window.currentPage==='N02');assert.equal(await page.evaluate(()=>history.length),length);await page.close();
});

test('实际React侧栏和目录按钮点击后采用同一页面读取与History函数',async()=>{
  const page=await browser.newPage();await page.goto(origin+'/?bossPage=F01');
  for(const role of ['BOSS','MAINTAINER']){
    for(const directory of [false,true]){
      const primary=navigation.primaryNavigation(role);
      const expected=navigation.navigationGroups(role).filter(group=>directory||primary.some(item=>item.title===group.title)).flatMap(group=>group.pages);
      await page.evaluate(({role,directory})=>{window.unmountMenu?.();window.unmountMenu=MenuChecks.mountMenu(role,directory);},{role,directory});
      await page.waitForFunction(count=>document.querySelectorAll('button[data-menu-page]').length===count,expected.length);
      if(!directory){
        assert.deepEqual(await page.locator('button[data-menu-group]').evaluateAll(buttons=>buttons.map(button=>button.dataset.menuGroup)),role==='BOSS'?['F01','N02','N03','N04','N05','N06']:['A01','F25','A08','A15']);
        for(const disclosure of await page.locator('button.boss-nav-disclosure').all())await disclosure.click();
      }
      for(const entry of expected){
        const button=page.locator('button[data-menu-page="'+entry.id+'"]');assert.ok((await button.textContent()).includes(entry.title));await button.click();
        assert.equal(await page.evaluate(role=>MenuChecks.readBossLocation(new URL(location.href),role).page,role),entry.id);
      }
    }
  }
  await page.evaluate(()=>window.unmountMenu());await page.close();
});
