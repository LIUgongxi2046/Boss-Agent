const assert = require("node:assert/strict");
const path = require("node:path");
const Module = require("node:module");
const root = path.resolve(__dirname, "../..");
const dependencies = path.join(root, ".work/upgrade2-u2-07/dependencies/node_modules");
const React = require(path.join(dependencies, "react"));
const {Window} = require(path.join(dependencies, "happy-dom/cjs/index.cjs"));
const {buildSync} = require(path.join(dependencies, "esbuild"));
const output = buildSync({entryPoints:[path.join(root,"app/webui/BossExecutionRecovery.tsx")],bundle:true,write:false,platform:"node",format:"cjs",jsx:"automatic",nodePaths:[dependencies],alias:{"@":path.join(root,".work/product/nanobot/webui/src")},external:["react","react/jsx-runtime","react-dom","react-dom/*"],loader:{".css":"empty"}});
const bundle = new Module(path.join(root,"app/tests/u2_04_recovery_bundle.cjs"));
bundle.filename=path.join(root,"app/tests/u2_04_recovery_bundle.cjs");bundle.paths=[dependencies];bundle._compile(output.outputFiles[0].text,bundle.filename);
const {BossExecutionRecoveryContent}=bundle.exports;
const window=new Window({url:"http://127.0.0.1:0/?bossRecoveryRequest=technical-request&bossRecoveryAction=technical-action"});
global.window=window;global.document=window.document;global.navigator=window.navigator;global.fetch=window.fetch.bind(window);global.IS_REACT_ACT_ENVIRONMENT=true;
const {createRoot}=require(path.join(dependencies,"react-dom/client"));
const container=document.createElement("div");document.body.appendChild(container);
const view=createRoot(container), getToken=()=>"", onOpenTask=()=>{}, onNavigate=()=>{};
function render(taskId){view.render(React.createElement(BossExecutionRecoveryContent,{taskId,getToken,onOpenTask,onNavigate}));}
async function main(){
  await React.act(async()=>render("technical-a"));
  const read=()=>[...container.querySelectorAll("button")].find(button=>button.textContent==="查询原请求结果");
  await React.act(async()=>{read().click();render("technical-b");});
  await React.act(async()=>{await new Promise(resolve=>setTimeout(resolve,100));});
  assert.doesNotMatch(container.textContent,/执行结果查询失败|ECONNREFUSED|fetch failed/i);
  await React.act(async()=>read().click());
  for(let index=0;index<50&&!container.querySelector('[role="alert"]');index++)await React.act(async()=>{await new Promise(resolve=>setTimeout(resolve,20));});
  assert.ok(container.querySelector('[role="alert"]'));
  const input=container.querySelector('input[placeholder="client_request_id"]');
  await React.act(async()=>{
    Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,"value").set.call(input,"technical-next");
    input.dispatchEvent(new window.Event("input",{bubbles:true}));
  });
  assert.equal(container.querySelector('[role="alert"]'),null);
  await React.act(async()=>{
    read().click();
    Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,"value").set.call(input,"technical-final");
    input.dispatchEvent(new window.Event("input",{bubbles:true}));
  });
  await React.act(async()=>{await new Promise(resolve=>setTimeout(resolve,100));});
  assert.equal(container.querySelector('[role="alert"]'),null);
  await React.act(async()=>{read().click();view.unmount();});
  await React.act(async()=>{await new Promise(resolve=>setTimeout(resolve,100));});
  assert.equal(container.textContent,"");
  await window.happyDOM.close();
  process.stdout.write("实际组件切换与读取失败检查通过\n");
}
void main();
