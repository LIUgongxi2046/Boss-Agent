const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const Module = require("node:module");
const {spawn} = require("node:child_process");
const {once} = require("node:events");
const root = path.resolve(__dirname,"../..");
const dependencies = path.join(root,".work/upgrade2-u2-07/dependencies/node_modules");
const React = require(path.join(dependencies,"react"));
const {renderToStaticMarkup} = require(path.join(dependencies,"react-dom/server"));
const {Window} = require(path.join(dependencies,"happy-dom/cjs/index.cjs"));
const {buildSync} = require(path.join(dependencies,"esbuild"));
const {catalog,snapshot,receipt} = JSON.parse(fs.readFileSync(0,"utf8"));
const output = buildSync({entryPoints:[path.join(root,"app/webui/Upgrade2ObjectSelection.tsx")],bundle:true,write:false,platform:"node",format:"cjs",jsx:"automatic",nodePaths:[dependencies],external:["react","react/jsx-runtime"]});
const component = new Module(path.join(root,"app/tests/meeting-scope-bundle.cjs"));
component.filename = path.join(root,"app/tests/meeting-scope-bundle.cjs");
component.paths = [dependencies];
component._compile(output.outputFiles[0].text,component.filename);
const {MeetingScopeDetails,ObjectChoices,Upgrade2ObjectSelection} = component.exports;
const clientOutput = buildSync({entryPoints:[path.join(root,"app/webui/upgrade2-run-client.ts")],bundle:true,write:false,platform:"node",format:"cjs",nodePaths:[dependencies]});
const clientModule = new Module(path.join(root,"app/tests/meeting-scope-client.cjs"));
clientModule.filename = path.join(root,"app/tests/meeting-scope-client.cjs");
clientModule._compile(clientOutput.outputFiles[0].text,clientModule.filename);
const client = new clientModule.exports.Upgrade2RunClient({getToken:()=>""});
const candidate = catalog.objects[0];
const text = renderToStaticMarkup(React.createElement(MeetingScopeDetails,{candidate}));
assert.ok(text.includes(candidate.object_id));
assert.ok(text.includes("参会人员") && text.includes("关联对象"));
for(const member of candidate.data.members)assert.ok(text.includes(member.object_id));
const window = new Window();
global.window=window;global.document=window.document;global.navigator=window.navigator;global.sessionStorage=window.sessionStorage;global.IS_REACT_ACT_ENVIRONMENT=true;
const initial=new window.DOMParser().parseFromString(renderToStaticMarkup(React.createElement(Upgrade2ObjectSelection,{client,snapshot,connected:true,enabled:true,token:"",getToken:()=>"",pendingScopeKey:"scope",onBlockChange:()=>{}})),"text/html");
assert.equal(initial.querySelector("form button").disabled,true);
assert.ok(!initial.body.textContent.includes("会议资料"));
const {createRoot} = require(path.join(dependencies,"react-dom/client"));
const container = window.document.createElement("div");
window.document.body.appendChild(container);
const view = createRoot(container), selections=[];
function Selection(){
  const [selected,setSelected]=React.useState([]);
  return React.createElement(ObjectChoices,{catalog,selected,canSelect:true,onChange:setSelected,onSubmit:event=>{event.preventDefault();selections.push(selected);}});
}
React.act(()=>view.render(React.createElement(Selection)));
assert.equal(container.querySelector("button").disabled,true);
React.act(()=>container.querySelector("input").click());
React.act(()=>container.querySelector("button").click());
assert.deepEqual(selections,[[JSON.stringify(["meeting_context",candidate.object_id])]]);
React.act(()=>view.unmount());

async function verifyReceiptRejection(){
  const server=spawn(path.join(root,".work/upgrade2-u2-04/locked-env/bin/python"),[path.join(root,"app/tests/upgrade2-run-client-server.py")],{cwd:root,env:{...process.env,PYTHONDONTWRITEBYTECODE:"1"},stdio:["ignore","pipe","pipe"]});
  let errors="";server.stderr.on("data",value=>{errors+=value;});
  try {
    const data=await Promise.race([once(server.stdout,"data").then(([value])=>value),once(server,"exit").then(([code])=>{throw new Error("服务启动失败 "+code+"："+errors);})]);
    const browser=new Window({url:"http://127.0.0.1:"+Number(String(data).trim())+"/"});
    global.window=browser;global.document=browser.document;global.navigator=browser.navigator;global.sessionStorage=browser.sessionStorage;global.fetch=browser.fetch.bind(browser);
    const scope="meeting-scope-test";
    const key="boss:upgrade2:object-scope:"+JSON.stringify([scope,snapshot.run_id]);
    const objects=receipt.objects.map(({entity_type,object_id,version,sha256})=>({entity_type,object_id,version,sha256}));
    browser.sessionStorage.setItem(key,JSON.stringify({request_key:receipt.request_key,goal_revision:receipt.goal_revision,objects,sources:receipt.objects.map(item=>item.source_refs)}));
    const element=browser.document.createElement("div");browser.document.body.appendChild(element);
    const mounted=createRoot(element);
    await React.act(async()=>{mounted.render(React.createElement(Upgrade2ObjectSelection,{client,snapshot,connected:true,enabled:true,token:"",getToken:()=>"",pendingScopeKey:scope,onBlockChange:()=>{}}));await browser.happyDOM.waitUntilComplete();});
    assert.ok(element.textContent.includes(receipt.request_key));
    await React.act(async()=>{Array.from(element.querySelectorAll("button")).find(item=>item.textContent.includes("查询对象选择原回执")).click();await browser.happyDOM.waitUntilComplete();});
    assert.ok(element.textContent.includes("HTTP 401"));
    assert.ok(!element.textContent.includes(candidate.sha256));
    assert.equal(JSON.parse(browser.sessionStorage.getItem(key)).request_key,receipt.request_key);
    React.act(()=>mounted.unmount());
  } finally {
    server.kill();
  }
}
verifyReceiptRejection().then(()=>process.stdout.write(JSON.stringify({members:candidate.data.members.length})));
