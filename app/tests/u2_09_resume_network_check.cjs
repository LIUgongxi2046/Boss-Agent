const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const Module = require("node:module");
const root = path.resolve(__dirname, "../..");
const dependencies = path.join(root, ".work/upgrade2-u2-07/dependencies/node_modules");
const React = require(path.join(dependencies, "react"));
const {Window} = require(path.join(dependencies, "happy-dom/cjs/index.cjs"));
const {buildSync} = require(path.join(dependencies, "esbuild"));
const snapshot = JSON.parse(fs.readFileSync(0, "utf8"));
const window = new Window({url:"http://127.0.0.1:1/"});
global.window=window;global.document=window.document;global.navigator=window.navigator;
global.fetch=window.fetch.bind(window);global.XMLHttpRequest=window.XMLHttpRequest;global.IS_REACT_ACT_ENVIRONMENT=true;
const {createRoot} = require(path.join(dependencies, "react-dom/client"));
const output = buildSync({entryPoints:[path.join(root,"app/webui/Upgrade2ResumeStatus.tsx"),path.join(root,"app/webui/upgrade2-run-client.ts")],bundle:true,write:false,outdir:path.join(root,"app/tests/resume-network-build"),
  platform:"node",format:"cjs",jsx:"automatic",nodePaths:[dependencies],external:["react","react/jsx-runtime"]});
function load(name){
  const moduleView = new Module(path.join(root,"app/webui/"+name+".cjs"));
  moduleView.filename = path.join(root,"app/webui/"+name+".cjs");
  moduleView.paths = [dependencies];
  moduleView._compile(output.outputFiles.find(item=>item.path.endsWith("/"+name+".js")).text,moduleView.filename);
  return moduleView.exports;
}
const {Upgrade2ResumeStatus}=load("Upgrade2ResumeStatus");
const {Upgrade2RunClient}=load("upgrade2-run-client");
const getToken=()=>"";
const client=new Upgrade2RunClient({getToken});
const container=document.createElement("div");document.body.appendChild(container);
const view=createRoot(container);
React.act(()=>view.render(React.createElement(Upgrade2ResumeStatus,{client,snapshot,token:"",getToken,onAccessDenied:()=>{}})));
setTimeout(()=>{
  const message=container.textContent;
  assert.match(message,/无法连接服务/);
  assert.ok(container.querySelector('[role="alert"]'));
  const retry=[...container.querySelectorAll("button")].find(button=>button.textContent==="重新读取继续运行条件");
  assert.ok(retry);
  React.act(()=>view.unmount());
  process.stdout.write(JSON.stringify({network_error_visible:true,retry_visible:true}));
},600);
